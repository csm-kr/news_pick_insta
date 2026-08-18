#!/usr/bin/env python3
"""Run one policy-scoped news-pick edition through Codex non-interactively."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
VALID_SLOTS = ("07:00", "12:00", "17:00")
MAX_START_LATENESS = timedelta(minutes=30)
STALE_LOCK_AGE = timedelta(hours=4)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_account(value: str) -> str:
    account = value.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    return account


def validate_profile(value: str) -> str:
    profile = value.strip()
    if not profile or any(marker in profile for marker in ("/", "\\")):
        raise ValueError("Chrome profile에는 폴더명만 사용한다.")
    return profile


def edition_at(slot: str, edition_date: date) -> datetime:
    if slot not in VALID_SLOTS:
        raise ValueError(f"지원하지 않는 회차다: {slot}")
    hour, minute = (int(part) for part in slot.split(":"))
    return datetime.combine(edition_date, time(hour, minute), tzinfo=KST)


def workspace_settings(
    root: Path,
    output_override: Path | None = None,
    account_override: str | None = None,
    profile_override: str | None = None,
) -> dict[str, Any]:
    config_path = root / "output" / "workspace.json"
    config = load_json(config_path) if config_path.is_file() else {}
    output_root = (output_override or Path(config.get("output_root", root / "output"))).expanduser().resolve()
    skills_root = (root / "skills").resolve()
    try:
        output_root.relative_to(skills_root)
    except ValueError:
        pass
    else:
        raise ValueError("NEWS_PICK_OUTPUT_ROOT는 skills 폴더 밖이어야 한다.")
    return {
        "output_root": output_root,
        "account": validate_account(account_override or config.get("account", "newspick_studio")),
        "chrome_profile": validate_profile(profile_override or config.get("chrome_profile", "Profile 3")),
    }


def build_prompt(root: Path, scheduled_at: datetime, settings: dict[str, Any]) -> str:
    skill_path = root / "skills" / "upload-news-pick" / "SKILL.md"
    return f"""$upload-news-pick 예약 무인 실행이다.

먼저 `{skill_path}`를 완전히 읽고 그 파일이 연결하는 네 전문 스킬을 단계 직전에 읽어 그대로 수행하라.

이번 회차:
- edition_at: {scheduled_at.isoformat()}
- timezone: Asia/Seoul
- account: {settings['account']}
- Chrome profile: {settings['chrome_profile']}
- output root: {settings['output_root']}

사용자는 이 예약 정책 범위의 실게시를 사전 승인했다. 모든 검증을 통과한 정확한 payload hash를 잠근 뒤 예약 승인으로 한 번만 승인하고, Instagram 웹 UI에서 실제 캐러셀 게시와 공개 검증까지 끝내라. 게시 직전 사용자 입력을 요구하지 마라.

고정 편집 정책:
- 그 시각 국내 영향도가 가장 큰 새 종합 이슈 1건. 직전 예약 게시물과 같은 사건·핵심 주장은 제외한다.
- 언론 기사와 공식 발표만 사실 근거로 사용하고, 독립 언론 2곳 이상으로 교차검증한다.
- 중립적이고 강한 사실형 후킹, 1024×1024 정방형 4장, 기본 direction-01 다크 스타일을 사용한다.
- 제목 다음 장부터 설명·핵심 수치·비교표나 차트를 포함한다. 기사·공식 이미지를 reference로 사용하고 카드마다 장면과 visual role을 다르게 한다.
- caption은 장별 설명을 나열하지 말고 자연스러운 뉴스 문단 하나로 쓴다.
- 출처는 마지막 카드에만 모으고 caption에는 `AI로 재구성한 인포그래픽` 계열 문구를 넣지 않는다.
- 사실적 AI 재구성 게시물은 Instagram의 `AI 콘텐츠` 라벨을 켠다.

실행 안전 규칙:
- 로그인된 Instagram 탭이 없을 때만 Profile 3 창을 한 번 연다. Instagram 탭이 여러 개거나 계정·로그인 상태가 다르면 게시하지 않는다.
- 적합한 새 이슈가 없거나 검색·기획·이미지·중복·계정·캐러셀·AI 라벨 QA가 하나라도 실패하면 filler를 만들지 말고 skipped 또는 needs_review로 끝낸다.
- 공유하기는 한 번만 누른다. 제출 시작 뒤 오류·timeout이면 자동 재시도하지 않고 공개 프로필을 읽기 전용으로 확인한다.
- 기존 게시물을 삭제하거나 수정하지 않는다. 단, 이번 게시물의 AI 라벨 공개 검증 복구는 publish-news-pick 계약이 허용한 한 번만 수행한다.
- repository의 소스·스킬·Git 상태를 수정하거나 commit/push하지 않는다. 실행물은 output root에만 저장한다.
- published는 shortcode, 4장 전체, 첫 카드, caption, AI 라벨을 공개 페이지에서 확인하고 result.public_verified=true일 때만 보고한다.

최종 응답은 지정된 JSON schema에 맞춰 status, summary, story_headline, run_directory, instagram_url, reason만 반환하라.
"""


def find_codex() -> Path:
    configured = os.environ.get("CODEX_EXECUTABLE")
    candidates = [Path(configured).expanduser()] if configured else []
    discovered = shutil.which("codex.exe") or shutil.which("codex")
    if discovered:
        candidates.append(Path(discovered))
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin" / "codex.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("codex executable을 찾을 수 없다. CODEX_EXECUTABLE을 설정한다.")


def within_start_window(scheduled_at: datetime, now: datetime) -> bool:
    return scheduled_at <= now <= scheduled_at + MAX_START_LATENESS


@contextmanager
def exclusive_lock(path: Path, now: datetime) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        age = now - datetime.fromtimestamp(path.stat().st_mtime, tz=KST)
        if age > STALE_LOCK_AGE:
            stale = path.with_name(f"{path.name}.stale-{now.strftime('%Y%m%d-%H%M%S')}")
            os.replace(path, stale)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("다른 뉴스픽 예약 회차가 실행 중이다.") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\nstarted_at={now.isoformat()}\n".encode())
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)


def run_job(
    root: Path,
    scheduled_at: datetime,
    settings: dict[str, Any],
    now: datetime,
    dry_run: bool = False,
) -> tuple[int, dict[str, Any]]:
    output_root: Path = settings["output_root"]
    slot_id = scheduled_at.strftime("%Y-%m-%d-%H%M")
    scheduler_root = output_root / "scheduler"
    state_path = scheduler_root / "editions" / f"{slot_id}.json"
    prompt = build_prompt(root, scheduled_at, settings)
    schema_path = root / "skills" / "upload-news-pick" / "references" / "scheduled-result.schema.json"
    result_path = scheduler_root / "results" / f"{slot_id}.json"
    command = [
        str(find_codex()),
        "exec",
        "--model",
        "gpt-5.5",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--ephemeral",
        "--json",
        "--sandbox",
        "workspace-write",
        "--approve-for-me",
        "--cd",
        str(root),
        "--output-schema",
        str(schema_path),
        "-o",
        str(result_path),
        "-",
    ]
    if dry_run:
        return 0, {
            "status": "dry_run",
            "slot_id": slot_id,
            "scheduled_at": scheduled_at.isoformat(),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "command": command,
            "settings": {**settings, "output_root": str(output_root)},
        }
    if state_path.exists():
        previous = load_json(state_path)
        return 0, {
            "status": "duplicate_suppressed",
            "slot_id": slot_id,
            "previous_status": previous.get("status"),
            "state_path": str(state_path),
        }
    if not within_start_window(scheduled_at, now):
        skipped = {
            "schema_version": "1.0",
            "slot_id": slot_id,
            "scheduled_at": scheduled_at.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "status": "skipped",
            "reason": "outside_start_window",
        }
        atomic_json(state_path, skipped)
        return 0, skipped

    log_root = output_root / "logs" / "scheduler"
    event_path = log_root / f"{slot_id}.jsonl"
    error_path = log_root / f"{slot_id}.stderr.log"
    for path in (result_path, event_path, error_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    started = {
        "schema_version": "1.0",
        "slot_id": slot_id,
        "scheduled_at": scheduled_at.isoformat(),
        "started_at": now.isoformat(),
        "status": "running",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "event_log": str(event_path),
        "error_log": str(error_path),
        "result_path": str(result_path),
    }
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "NEWS_PICK_OUTPUT_ROOT": str(output_root),
            "IG_ACCOUNT": settings["account"],
            "NEWS_PICK_CHROME_PROFILE": settings["chrome_profile"],
            "NEWS_PICK_SCHEDULED_MODE": "1",
            "NEWS_PICK_EDITION_AT": scheduled_at.isoformat(),
        }
    )
    with exclusive_lock(scheduler_root / "scheduled-run.lock", now):
        atomic_json(state_path, started)
        with event_path.open("w", encoding="utf-8") as events, error_path.open("w", encoding="utf-8") as errors:
            completed = subprocess.run(
                command,
                input=prompt,
                stdout=events,
                stderr=errors,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
    finished_at = datetime.now(KST)
    final: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            final = load_json(result_path)
        except (OSError, json.JSONDecodeError):
            final = None
    status = str((final or {}).get("status") or "failed")
    if completed.returncode != 0:
        status = "failed"
    if status == "published" and final and (not final.get("instagram_url") or not final.get("run_directory")):
        status = "failed"
    ended = {
        **started,
        "completed_at": finished_at.isoformat(),
        "status": status,
        "codex_exit_code": completed.returncode,
        "final_result": final,
    }
    atomic_json(state_path, ended)
    exit_code = 0 if status in {"published", "skipped"} else 2
    return exit_code, ended


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True, choices=VALID_SLOTS)
    parser.add_argument("--edition-date", type=date.fromisoformat)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--account")
    parser.add_argument("--chrome-profile")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        root = project_root()
        now = datetime.now(KST)
        scheduled_at = edition_at(args.slot, args.edition_date or now.date())
        settings = workspace_settings(root, args.output_root, args.account, args.chrome_profile)
        exit_code, result = run_job(root, scheduled_at, settings, now, args.dry_run)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": exit_code == 0, "result": result}, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
