#!/usr/bin/env python3
"""뉴스픽 일일 보고: 회차별 게시 결과·ego 프로필·계정·팔로워 증감·팔로우 활동·예약 이상을 짧은 목록으로 모은다.

Instagram API는 부르지 않는다(11-12 진단 중 429). 게시 시각은 게시 대기열의 공유 기록을 쓰고, 팔로워 수는
newspick-growth 공간의 백그라운드 탭에서 프로필 페이지를 한 번 열어 og:description만 읽는다.
결과는 output/reports/daily/<날짜>.json·.txt, 팔로워 기록은 output/growth/followers.jsonl(날짜별 한 줄)에 남긴다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[3]
SLOTS = ("07:00", "12:00", "17:00")
INSTAGRAM_SPACE = "newspick-instagram"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STATUS_LABEL = {"published": "게시", "needs_review": "검토 필요", "skipped": "건너뜀", "failed": "실패", "in_progress": "진행 중",
                "cancelled": "취소", "duplicate_suppressed": "중복 실행 막음"}
STATUS_ICON = {"published": "✅", "needs_review": "❌", "failed": "❌", "cancelled": "❌", "skipped": "⏭",
               "in_progress": "⏳", "duplicate_suppressed": "⏭"}
# 예약 실행기가 남기는 사유 코드(접두어)를 짧은 한국어로 바꾼다
REASON_TEXT = {
    "image_generation_incomplete": "이미지 생성 결과 누락",
    "visual_qa_failed": "카드 QA 실패",
    "no_publishable_story": "올릴 만한 새 사건 없음",
    "composer_busy": "다른 게시가 작성 중",
    "outside_start_window": "시작 가능 시간 밖",
    "duplicate_suppressed": "이미 처리한 회차",
}

GROWTH_SPACE = "newspick-growth"
# 결과 코드 4는 언팔이 다음 예약 run 전에 스스로 멈춘 것이다. 267009/267011은 실행 중·아직 안 돎.
BENIGN_RESULTS = {"NewsPickUnfollow-Weekly": {0, 4}}
DEFAULT_BENIGN = {0, 267009, 267011}
META_PATTERNS = {
    "followers": (r"팔로워\s*([\d.,]+[KMk만천]?)", r"([\d.,]+[KMk]?)\s*Followers"),
    "following": (r"팔로잉\s*([\d.,]+[KMk만천]?)", r"([\d.,]+[KMk]?)\s*Following"),
    "posts": (r"게시물\s*([\d.,]+[KMk만천]?)", r"([\d.,]+[KMk]?)\s*Posts"),
}


# --- 순수 계산 ------------------------------------------------------------------
def _kst(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _number(text: str) -> int:
    scale = {"K": 1_000, "k": 1_000, "M": 1_000_000, "천": 1_000, "만": 10_000}.get(text[-1], 1)
    return round(float(text.rstrip("KMk만천").replace(",", "")) * scale)


def parse_profile_meta(meta: str) -> dict[str, int]:
    counts = {}
    for key, patterns in META_PATTERNS.items():
        match = next((m for m in (re.search(p, meta) for p in patterns) if m), None)
        if match is None:
            raise ValueError(f"프로필 설명에서 {key} 수를 찾지 못함: {meta[:80]}")
        counts[key] = _number(match.group(1))
    return counts


def share_times(jobs_dir: Path) -> dict[str, dict[str, Any]]:
    """게시 대기열 job에서 게시물 코드별 공유 기록 시각과 게시 계정을 모은다."""
    times = {}
    for job_path in jobs_dir.glob("*/job.json"):
        job = _read(job_path) or {}
        shortcode = (job.get("public_result") or {}).get("shortcode")
        recorded = (job.get("submission_result") or {}).get("recorded_at")
        if shortcode and recorded:
            times[shortcode] = {"at": recorded, "account": job.get("account")}
    return times


def load_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def upsert_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    rows = [row for row in load_snapshots(path) if row["date"] != snapshot["date"]] + [snapshot]
    rows.sort(key=lambda row: row["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def growth(rows: list[dict[str, Any]], day: date) -> dict[str, Any]:
    by_date = {row["date"]: row for row in rows}
    today = by_date.get(day.isoformat())

    def base_on_or_before(limit: date) -> dict[str, Any] | None:
        earlier = [row for row in rows if row["date"] <= limit.isoformat()]
        return earlier[-1] if earlier else None

    result: dict[str, Any] = {}
    for key in ("followers", "following"):
        result[key] = {}
        for label, days in (("day", 1), ("week", 7)):
            base = base_on_or_before(day - timedelta(days=days))
            if today is None or base is None:
                result[key][label] = None
                continue
            delta = today[key] - base[key]
            result[key][label] = {"base": base[key], "delta": delta, "rate": round(delta / base[key] * 100, 2) if base[key] else None}
    return result


def todays_posts(output_root: Path, day: date, shares: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """07·12·17시 회차와 그날 수동 run을 한 줄씩. 같은 회차를 다시 돌렸으면 마지막 run을 쓴다."""
    editions = output_root / "scheduler" / "editions"
    # 정규 회차를 대신한 수동 run(사용자 지시로 기록한 replacement 파일): run 이름 → 회차
    replacement_of = {str(r.get("run_id")): slot for slot in SLOTS
                      if (r := _read(editions / f"{day.isoformat()}-{slot.replace(':', '')}.replacement.json")) and r.get("run_id")}
    latest: dict[str, Path] = {}
    for run_json in sorted((output_root / "runs").glob("*/run.json")):
        state = _read(run_json) or {}
        try:
            edition = _kst(str(state.get("edition_at") or ""))
        except ValueError:
            continue
        if edition.date() != day:
            continue
        hhmm = edition.strftime("%H:%M")
        if run_json.parent.name in replacement_of:
            latest[replacement_of[run_json.parent.name]] = run_json.parent
            continue
        latest[hhmm if hhmm in SLOTS else f"수동 {hhmm}"] = run_json.parent
    posts = []
    for slot in list(SLOTS) + sorted(key for key in latest if key not in SLOTS):
        run = latest.get(slot)
        edition_state = _read(output_root / "scheduler" / "editions" / f"{day.isoformat()}-{slot.replace(':', '')}.json") if slot in SLOTS else None
        result = _read(run / "04-publish" / "result.json") if run else None
        story = _read(run / "01-search" / "selected-story.json") if run else None
        if result and result.get("status") == "published":
            status = "published"
        elif edition_state:
            status = str(edition_state.get("status") or "unknown")
        elif run:
            status = str((_read(run / "run.json") or {}).get("status") or "unknown")
        else:
            status = "없음"
        # 사유 코드는 run 결과 파일에, 예약 기록에는 설명 문장만 남는 경우가 있어 결과 파일을 먼저 본다
        note = None if status == "published" else ((result or {}).get("reason")
                                                   or ((edition_state or {}).get("final_result") or {}).get("reason"))
        posted_at, share = None, shares.get((result or {}).get("shortcode"))
        if share:
            posted_at = _kst(share["at"]).strftime("%H:%M")
        elif result and result.get("verified_at"):
            posted_at = _kst(result["verified_at"]).strftime("%H:%M") + "*"
        replaced = run is not None and run.name in replacement_of
        # 대체한 회차는 건너뛴 예약 기록이 아니라 수동 run의 시작 시각을 쓴다
        started = None if replaced else (edition_state or {}).get("started_at")
        started_at = _kst(started).strftime("%H:%M") if started else (f"{run.name[9:11]}:{run.name[11:13]}" if run else None)
        ended = None if replaced else (edition_state or {}).get("completed_at")
        posts.append({"slot": slot, "status": status, "posted_at": posted_at, "account": (share or {}).get("account"),
                      "shared_at": (share or {}).get("at"),
                      "started_at": started_at, "ended_at": _kst(ended).strftime("%H:%M") if ended else None,
                      "replaced": replaced,
                      "headline": (story or {}).get("verified_headline"),
                      "url": (result or {}).get("url"), "note": note})
    return posts


def _count(path: Path, step: str, day: date) -> int:
    total = 0
    for row in load_snapshots(path):
        if row.get("step") == step and row.get("status") == 200 and _kst(row["at"]).date() == day:
            total += 1
    return total


def activity(output_root: Path, day: date) -> dict[str, int]:
    return {
        "follow": _count(output_root / "follow" / "follow_log.jsonl", "follow", day),
        "unfollow": sum(_count(path, "unfollow", day) for path in (output_root / "unfollow").glob("*/unfollow_log.jsonl")),
    }


def _ego_label(row: dict[str, Any]) -> str:
    return f"{row.get('profile_name') or '?'} ({row.get('profile_id') or '?'})"


def ego_used(sessions: list[dict[str, Any]], space: str, at: datetime, window_hours: int = 3) -> str | None:
    """그 시각 직전(기본 3시간 안) 그 공간의 마지막 연결이 붙은 ego 프로필. ego_harness가 연결마다 남긴 기록이다."""
    earlier = [row for row in sessions if row.get("space") == space and at - timedelta(hours=window_hours) <= _kst(row["at"]) <= at]
    return _ego_label(earlier[-1]) if earlier else None


def ego_used_on(sessions: list[dict[str, Any]], space: str, day: date) -> str | None:
    labels = sorted({_ego_label(row) for row in sessions if row.get("space") == space and _kst(row["at"]).date() == day})
    return ", ".join(labels) or None


def last_ego(sessions: list[dict[str, Any]], space: str) -> dict[str, str] | None:
    rows = [row for row in sessions if row.get("space") == space]
    return {"label": _ego_label(rows[-1]), "at": _kst(rows[-1]["at"]).strftime("%H:%M")} if rows else None


def ego_profile(config: dict[str, Any], spaces: list[dict[str, Any]]) -> dict[str, Any]:
    browser = config.get("browser") or {}
    configured_id = browser.get("ego_profile_id")
    configured = f"{browser.get('ego_profile_name') or '?'} ({configured_id})" if configured_id else "지정 없음(기본 프로필)"
    space = next((item for item in spaces if item.get("name") == INSTAGRAM_SPACE), None)
    if space is None:
        return {"configured": configured, "space": "공간 없음", "match": None}
    return {"configured": configured, "space": f"{space.get('profileName')} ({space.get('profileId')})",
            "match": configured_id is None or space.get("profileId") == configured_id}


def parse_spaces(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """ego-browser nodejs는 console.log를 stderr로 낼 때가 있다. JSON 배열이 있는 쪽을 쓴다."""
    for text in (stdout, stderr):
        lines = [line for line in (text or "").splitlines() if line.strip().startswith("[")]
        if lines:
            return json.loads(lines[-1])
    raise ValueError("ego 공간 목록 출력이 없다")


def schedule_warnings(schedule: list[dict[str, Any]]) -> list[str]:
    failed = [f"{s['name']} 최근 결과 코드 {s['last_result']}" for s in schedule
              if s["state"] != "Disabled" and s.get("last_result") not in BENIGN_RESULTS.get(s["name"], DEFAULT_BENIGN)]
    return failed + [f"{s['name']} 꺼져 있음" for s in schedule if s["state"] == "Disabled"]


def short_reason(text: str | None) -> str | None:
    if not text:
        return None
    code = text.split(":", 1)[0].strip()
    for prefix, label in REASON_TEXT.items():
        if code.startswith(prefix):
            return label
    return clip(text, 40)


def story_status(output_root: Path, day: date) -> dict[str, Any] | None:
    """19시 스토리 예약 결과. 정규 3건이 공개 검증되지 않으면 실행기가 게시 전에 멈춘다(failed_pre_submit)."""
    editions = output_root / "scheduler" / "daily-story" / "editions"
    state = next((s for s in (_read(editions / f"{day.isoformat()}-{hhmm}.json") for hhmm in ("1900", "2100")) if s), None)
    if state is None:
        return None
    status = str(state.get("status") or "unknown")
    if status == "published":
        done = state.get("completed_at") or state.get("started_at")
        return {"status": "published", "reason": None, "at": _kst(done).strftime("%H:%M") if done else None}
    error = ""
    log = Path(state["stderr_log"]) if state.get("stderr_log") else None
    if log and log.is_file():
        lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        error = lines[-1] if lines else ""
        try:
            error = str(json.loads(error).get("error") or error)
        except (ValueError, AttributeError):
            pass
    found = re.search(r"requires exactly (\d+) publicly verified posts; found (\d+)", error)
    started = state.get("started_at")
    at = _kst(started).strftime("%H:%M") if started else None
    if status == "failed_pre_submit":
        return {"status": "not_posted", "reason": f"정규 게시 {found.group(2)}/{found.group(1)}건" if found else short_reason(error), "at": at}
    return {"status": "failed", "reason": short_reason(error) or status, "at": at}


WEEKDAYS = "월화수목금토일"
TASK_LABELS = {
    "NewsPickInstagram-DailyStory-1900": "스토리 (정규 3건 공개 검증 시)",
    "NewsPickDailyReport-1930": "일일 보고",
    "NewsPickFollow-Morning": "팔로우 (오전)",
    "NewsPickFollow-Afternoon": "팔로우 (오후)",
    "NewsPickFollow-Evening": "팔로우 (저녁)",
    "NewsPickUnfollow-Weekly": "언팔 (맞팔 아닌 계정, 7일 유예)",
}


def _task_label(name: str) -> str:
    slot = re.fullmatch(r"NewsPickInstagram-(\d\d)00", name)
    if slot:
        hour = slot.group(1)
        # 공유는 회차 시각 뒤 1~15분 사이 무작위(scheduled_runner.PUBLISH_OFFSET_RANGE_SECONDS)
        return f"{hour}시 회차 준비 → {hour}:01~{hour}:15 사이 게시"
    return TASK_LABELS.get(name, name)


def _when(at: datetime, now: datetime) -> str:
    days = (at.date() - now.date()).days
    if days == 0:
        return at.strftime("%H:%M")
    if days == 1:
        return "내일 " + at.strftime("%H:%M")
    return f"{at.month}/{at.day}({WEEKDAYS[at.weekday()]}) {at.strftime('%H:%M')}"


def upcoming_lines(schedule: list[dict[str, Any]], now: datetime) -> list[str]:
    active = []
    for task in schedule:
        if task["state"] == "Disabled" or not task.get("next_run"):
            continue
        at = datetime.fromisoformat(task["next_run"][:19]).replace(tzinfo=KST)
        active.append((at, f"- {_when(at, now)} {_task_label(task['name'])}"))
    disabled = [f"- (꺼짐) {_task_label(t['name'])}" for t in schedule if t["state"] == "Disabled"]
    return [line for _, line in sorted(active)] + disabled


def _minutes(start: str, end: str) -> int:
    (h1, m1), (h2, m2) = (map(int, t.rstrip("*").split(":")) for t in (start, end))
    return (h2 * 60 + m2 - h1 * 60 - m1) % (24 * 60)


def duration_line(posts: list[dict[str, Any]]) -> str | None:
    parts = [f"{'수동' if p['slot'].startswith('수동') else p['slot']} {_minutes(p['started_at'], p['posted_at'])}분"
             + (" (수동 대체)" if p.get("replaced") else "")
             for p in posts if p["status"] == "published" and p.get("started_at") and p.get("posted_at")]
    return "걸린 시간: " + " · ".join(parts) if parts else None


# --- 출력 -----------------------------------------------------------------------
def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def clip(text: str | None, width: int) -> str | None:
    if text is None or display_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if display_width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def _delta(item: dict[str, Any] | None, with_rate: bool) -> str | None:
    if not item:
        return None
    text = f"{item['delta']:+,}"
    if with_rate and item["rate"] is not None:
        text += f" · {item['rate']:+.2f}%"
    return text


def _num(value: Any) -> str:
    return "-" if value is None else f"{value:,}"


def _count_line(label: str, value: Any, growth_item: dict[str, Any], with_rate: bool, empty: str) -> str:
    head = f"{label} {_num(value)}"
    parts = [f"{name} {d}" for name, d in (("전일", _delta(growth_item["day"], with_rate)), ("7일", _delta(growth_item["week"], with_rate))) if d]
    if parts:
        return f"{head} ({', '.join(parts)})"
    return f"{head}{empty}"


def _slot_lines(p: dict[str, Any], report: dict[str, Any], now: datetime) -> list[str]:
    status = p["status"]
    slot = "수동" if p["slot"].startswith("수동") else p["slot"]  # 수동 run의 시각은 '시작'에 이미 나온다
    if status == "없음":
        due = datetime.combine(now.date(), datetime.strptime(slot, "%H:%M").time(), tzinfo=KST)
        if now < due:
            return [f"- {slot} ⏰ 예정 ({(due - timedelta(minutes=30)).strftime('%H:%M')} 준비 시작)"]
        return [f"- {slot} ⚠️ 실행 기록 없음"]
    icon, label = STATUS_ICON.get(status, "❔"), STATUS_LABEL.get(status, status)
    if status == "published":
        span = f"{p['started_at']} 시작 → {p['posted_at']} 게시" if p.get("started_at") else f"{p['posted_at']} 게시"
        lines = [f"- {slot} {icon} {label}{' · 수동 대체' if p.get('replaced') else ''} ({span})",
                 f"  - ego: {p.get('ego') or '기록 없음'} · 계정 @{p.get('account') or report['account']}"]
    else:
        times = " → ".join(t for t in (f"{p['started_at']} 시작" if p.get("started_at") else None,
                                         f"{p['ended_at']} 종료" if p.get("ended_at") else None) if t)
        reason = short_reason(p.get("note"))
        lines = [f"- {slot} {icon} {label}" + (f" ({times})" if times else "") + (f": {reason}" if reason else "")]
    if p.get("headline"):
        lines.append(f"  - {p['headline']}" + (f" · {p['url']}" if p.get("url") else ""))
    return lines


def render(report: dict[str, Any]) -> str:
    now = datetime.fromisoformat(report["generated_at"])
    day = date.fromisoformat(report["date"])
    title = "지금 보고" if report.get("mode") == "status" else "뉴스픽 보고"
    lines = [f"{title} ({day.month}/{day.day}) · {report['generated_at'][11:16]} 기준"]
    for p in report["posts"]:
        lines += _slot_lines(p, report, now)
    story = report.get("story")
    if story is None:
        lines.append("- 19:00 스토리 ⏰ 예정" if now.hour < 19 else "- 19:00 스토리 ⚠️ 실행 기록 없음")
    elif story["status"] == "published":
        lines.append(f"- 19:00 스토리 ✅ 게시 ({story['at']})")
    elif story["status"] == "not_posted":
        lines.append(f"- 19:00 스토리 ⏭ 안 올림: {story['reason']}")
    else:
        lines.append(f"- 19:00 스토리 ❌ 실패: {story['reason']}")
    profile, g = report.get("profile") or {}, report["growth"]
    as_of = profile.get("as_of")
    if as_of and as_of != report["date"]:  # 오늘 기록이 아직 없어 마지막 기록을 쓴 경우
        stale = date.fromisoformat(as_of)
        lines.append(f"- 팔로워 {_num(profile.get('followers'))} ({stale.month}/{stale.day} 기준) · 팔로잉 {_num(profile.get('following'))}")
    else:
        lines.append("- " + _count_line("팔로워", profile.get("followers"), g["followers"], True, " (비교 기록 없음)")
                     + " · " + _count_line("팔로잉", profile.get("following"), g["following"], False, ""))
    lines.append(f"- 팔로우 {report['activity']['follow']} · 언팔 {report['activity']['unfollow']}"
                 f" (ego: {report.get('growth_ego') or '기록 없음'})")
    ego = report["ego"]
    if ego["match"] is True:
        lines.append(f"- ego 게시 공간: {ego['space']} ✓ 설정과 일치")
    elif ego["match"] is False:
        lines.append(f"- ego 게시 공간: {ego['space']} ✗ 설정({ego['configured']})과 다름")
    elif ego["space"] == "공간 없음" and report.get("last_ego"):
        # 게시가 끝나면 게시용 공간이 닫히므로, 마지막으로 실제 연결된 프로필을 보여 준다
        last = report["last_ego"]
        lines.append(f"- ego 게시 공간: 지금 열린 공간 없음 · 마지막 연결 {last['label']} {last['at']} (설정 {ego['configured']})")
    else:
        lines.append(f"- ego 게시 공간: {ego['space']} (설정 {ego['configured']})")
    warnings = report.get("warnings") or []
    schedule_issues = [w for w in warnings if "결과 코드" in w or w.endswith("꺼져 있음")]
    lines.append("- 예약 이상: " + (", ".join(schedule_issues) if schedule_issues else "없음"))
    lines += [f"- 확인 필요: {w}" for w in warnings if w not in schedule_issues and "회차:" not in w]
    durations = duration_line(report["posts"])
    if durations:
        lines += ["", durations]
    upcoming = upcoming_lines(report.get("schedule") or [], now)
    if upcoming:
        lines += ["", "다음 일정 (예약 등록 완료)", *upcoming]
    return "\n".join(lines)


# --- 수집(부수효과) -------------------------------------------------------------
def fetch_profile(account: str) -> dict[str, int]:
    """newspick-growth 공간에 백그라운드 탭을 하나 열어 프로필 페이지 설명만 읽고 닫는다."""
    sys.path.insert(0, str(ROOT / "skills" / "publish-news-pick" / "scripts"))
    import ego_harness  # noqa: PLC0415

    ego_harness.ensure_ego_running()
    transport = ego_harness.BridgeTransport(space=GROWTH_SPACE, call_timeout=90)
    try:
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/")

        def send(method: str, params: dict, sid: str | None = None) -> dict:
            return session.send({"method": method, "params": params, "session_id": sid}).get("result", {})

        tab = send("Target.createTarget", {"url": f"https://www.instagram.com/{account}/", "background": True})["targetId"]
        try:
            expression = "(document.querySelector('meta[property=\"og:description\"]')||{}).content||''"
            for _ in range(30):
                meta = send("Runtime.evaluate", {"expression": expression, "returnByValue": True}, tab).get("result", {}).get("value") or ""
                if meta:
                    return parse_profile_meta(meta)
                time.sleep(1)
            raise ValueError("프로필 페이지 설명(og:description)이 나타나지 않음")
        finally:
            send("Target.closeTarget", {"targetId": tab})
    finally:
        transport.close()


def ego_spaces() -> list[dict[str, Any]]:
    completed = subprocess.run(["ego-browser", "nodejs", "-e", "console.log(JSON.stringify(await listTaskSpaces()))"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
    return parse_spaces(completed.stdout, completed.stderr)


def schedule_status() -> list[dict[str, Any]]:
    script = ("Get-ScheduledTask | Where-Object { $_.TaskName -like 'NewsPick*' } | ForEach-Object { $i = Get-ScheduledTaskInfo -TaskName $_.TaskName; "
              "[pscustomobject]@{ name = $_.TaskName; state = [string]$_.State; next_run = $i.NextRunTime.ToString('s'); last_result = $i.LastTaskResult } } "
              "| ConvertTo-Json -Compress")
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
    data = json.loads(completed.stdout or "[]")
    return sorted(data if isinstance(data, list) else [data], key=lambda item: item["name"])


def build_report(day: date, live: bool = True, read_profile: bool = True) -> dict[str, Any]:
    output_root = ROOT / "output"
    config = _read(output_root / "workspace.json") or {}
    account = config.get("account", "newspick_studio")
    warnings: list[str] = []
    profile, spaces = None, []
    if live and read_profile:
        try:
            profile = fetch_profile(account)
        except (Exception, SystemExit) as exc:  # 보고는 계속 낸다
            warnings.append(f"Instagram 프로필을 읽지 못함: {str(exc)[:120]}")
    if live:
        try:
            spaces = ego_spaces()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ego 공간 목록을 읽지 못함: {str(exc)[:120]}")
    snapshots_path = output_root / "growth" / "followers.jsonl"
    if profile:
        upsert_snapshot(snapshots_path, {"date": day.isoformat(), "at": datetime.now(KST).isoformat(timespec="seconds"),
                                         "followers": profile["followers"], "following": profile["following"], "posts": profile["posts"]})
    rows = load_snapshots(snapshots_path)
    if profile is None:  # 오늘 기록이 없으면 그날 이전의 마지막 기록을 날짜와 함께 쓴다
        last = next((row for row in reversed(rows) if row["date"] <= day.isoformat()), None)
        profile = {**last, "as_of": last["date"]} if last else None
    report = {
        "date": day.isoformat(), "generated_at": datetime.now(KST).isoformat(timespec="seconds"), "account": account,
        "ego": ego_profile(config, spaces) if spaces else {"configured": ego_profile(config, [])["configured"], "space": "확인 안 함", "match": None},
        "posts": todays_posts(output_root, day, share_times(output_root / "publish-news-pick" / "jobs")),
        "profile": {k: profile.get(k) for k in ("followers", "following", "posts", "as_of")} if profile else None,
        "story": story_status(output_root, day),
        "growth": growth(rows, day),
        "activity": activity(output_root, day),
        "schedule": schedule_status(),
        "warnings": warnings,
    }
    sessions = load_snapshots(output_root / "logs" / "ego-sessions.jsonl")  # 한 줄에 JSON 하나
    for p in report["posts"]:
        p["ego"] = ego_used(sessions, INSTAGRAM_SPACE, _kst(p["shared_at"])) if p.get("shared_at") else None
    report["growth_ego"] = ego_used_on(sessions, GROWTH_SPACE, day)
    report["last_ego"] = last_ego(sessions, INSTAGRAM_SPACE)
    if report["ego"]["match"] is False:
        warnings.append("게시 공간이 설정과 다른 ego 프로필에 붙어 있다")
    warnings += [f"{p['slot']} 회차: {STATUS_LABEL.get(p['status'], p['status'])}" for p in report["posts"]
                 if p["slot"] in SLOTS and p["status"] not in ("published", "없음")]
    warnings += schedule_warnings(report["schedule"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(KST).date())
    parser.add_argument("--offline", action="store_true", help="Instagram·ego를 읽지 않고 로컬 기록만으로 만든다")
    parser.add_argument("--status", action="store_true",
                        help="지금 보고: Instagram은 읽지 않고(마지막 팔로워 기록 사용) ego·예약만 확인해 화면에만 출력한다")
    args = parser.parse_args()
    if args.status:
        report = build_report(args.date, live=not args.offline, read_profile=False)
        print(render({**report, "mode": "status"}))
        return 0
    out_dir = ROOT / "output" / "reports" / "daily"
    if sys.stdout is None:  # pythonw 예약 실행
        out_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = (out_dir / "run.log").open("a", encoding="utf-8")
    report = build_report(args.date, live=not args.offline)
    text = render(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.date.isoformat()}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{args.date.isoformat()}.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
