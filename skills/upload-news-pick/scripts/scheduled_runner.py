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
PREPARATION_LEAD = timedelta(minutes=30)
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


def editorial_lane_for(scheduled_at: datetime) -> str:
    return "popular_interest" if scheduled_at.strftime("%H:%M") in {"07:00", "12:00"} else "public_impact"


def recent_published_stories(output_root: Path, limit: int = 6) -> list[dict[str, str]]:
    runs_root = output_root / "runs"
    history: list[dict[str, str]] = []
    if not runs_root.is_dir():
        return history
    for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), reverse=True):
        story_path = run_dir / "01-search" / "selected-story.json"
        result_path = run_dir / "04-publish" / "result.json"
        if not story_path.is_file() or not result_path.is_file():
            continue
        try:
            story = load_json(story_path)
            result = load_json(result_path)
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("status") != "published" or result.get("public_verified") is not True:
            continue
        history.append(
            {
                "edition_at": str(story.get("edition_at") or ""),
                "topic": str(story.get("topic") or ""),
                "headline": str(story.get("verified_headline") or ""),
            }
        )
        if len(history) >= limit:
            break
    return history


def build_prompt(root: Path, scheduled_at: datetime, settings: dict[str, Any]) -> str:
    skill_path = root / "skills" / "upload-news-pick" / "SKILL.md"
    publish_gate_path = root / "skills" / "upload-news-pick" / "scripts" / "wait_for_publish_time.py"
    instagram_target_resolver_path = root / "skills" / "publish-news-pick" / "scripts" / "browser_web_resolve_targets.py"
    editorial_lane = editorial_lane_for(scheduled_at)
    recent_history = recent_published_stories(settings["output_root"])
    recent_history_json = json.dumps(recent_history, ensure_ascii=False, indent=2)
    return f"""$upload-news-pick 예약 무인 실행이다.

먼저 `{skill_path}`를 완전히 읽고 그 파일이 연결하는 네 전문 스킬을 단계 직전에 읽어 그대로 수행하라.

Windows PowerShell에서 한글 UTF-8 텍스트 파일을 읽을 때는 반드시 `Get-Content -Raw -Encoding UTF8`을 사용한다. `-Encoding UTF8` 없이 스킬·JSON·Markdown을 읽지 말고, 글자가 깨져 보이면 즉시 중단해 UTF-8로 다시 읽는다.

이번 회차:
- edition_at: {scheduled_at.isoformat()}
- timezone: Asia/Seoul
- account: {settings['account']}
- Chrome profile: {settings['chrome_profile']}
- output root: {settings['output_root']}
- target editorial lane: {editorial_lane}

최근 공개 검증 게시물 6건 이내의 편성 기록은 다음과 같다. 같은 사건은 제외하고, 같은 대분류의 연속·과다 편성을 판정하는 입력으로 사용하라.

```json
{recent_history_json}
```

사용자는 이 예약 정책 범위의 실게시를 사전 승인했다. 모든 검증을 통과한 정확한 payload hash를 잠근 뒤 예약 승인으로 한 번만 승인하고, Instagram 웹 UI에서 실제 캐러셀 게시와 공개 검증까지 끝내라. 게시 직전 사용자 입력을 요구하지 마라.

사용자는 카드 후보 생성을 위해 이번 run이 공개 웹에서 수집한 기사 대표 이미지, 공식 기관 보도자료·공시 화면, 카드뉴스 스타일 참고 이미지를 Tibo/GPT Image 백엔드로 전송하는 것도 명시적으로 승인했다. 이 승인은 현재 run의 `references/content`와 `references/style` 아래 파일을 정확히 12장 후보 생성에 사용하는 범위로만 제한된다. cookie, session, 인증 파일, 개인정보, 그 밖의 로컬 파일은 절대 전송하지 않는다. 실제 생성 명령에는 `--approve-public-reference-egress`를 반드시 포함한다. 이 플래그가 빠진 생성 명령은 한 번도 시도하지 말고, 범위 검증이 실패하면 즉시 중단하라.

이 실행은 게시 회차 30분 전에 시작한다. 검색·기획·이미지 생성·QA와 Instagram 작성 화면의 게시 직전 검증까지 미리 끝내되, `공유하기`는 edition_at 이전에 절대 누르지 않는다. 게시 직전 아래 시간 게이트를 실행하고 성공 종료된 뒤에만 `browser_web_share_once.py`를 실행하라. 게이트가 실패하면 게시하지 말고 skipped 또는 needs_review로 끝낸다.

```powershell
python "{publish_gate_path}"
```

고정 편집 정책:
- 증거 조건을 먼저 통과한 후보 중 이번 회차의 target editorial lane에 가장 잘 맞는 새 종합 이슈 1건을 고른다. 직전 예약 게시물과 같은 사건·핵심 주장은 제외한다.
- 07:00·12:00 `popular_interest`는 생활경제·소비자·건강·교통·과학기술·사회·문화·스포츠·환경처럼 여러 연령대의 일상과 대화에 가까운 주제를 우선한다. 생활 관련성·대화 가치·4장 설명력·새로움 합계가 8/12 미만이면 선택하지 않는다.
- 17:00 `public_impact`는 제도·안전·경제·국제 현안 중 당일 영향이 큰 확정 사안을 우선하되 최근 주제 반복을 피한다.
- 정치·부동산은 계속 탐색하지만 두 분야 합계 하루 1건을 기본 상한으로 하고 직전 게시물과 연속 편성하지 않는다. 전국적 긴급성 또는 즉시 권리·비용 변화가 명확한 확정 사안만 예외로 하며 근거를 selected-story.json의 limitations에 기록한다.
- 연예인 사생활·확인되지 않은 논란·단순 경기 결과·자극적 범죄 소비는 대중 관심형으로 취급하지 않는다. target lane에 맞는 검증된 사건이 없으면 낮은 대중 적합도의 정치·부동산으로 채우지 않는다.
- 언론 기사와 공식 발표만 사실 근거로 사용하고, 독립 언론 2곳 이상으로 교차검증한다.
- 중립적이고 강한 사실형 후킹, 1024×1024 정방형 4장, 기본 direction-01 다크 스타일을 사용한다.
- 제목 다음 장부터 설명·핵심 수치·비교표나 차트를 포함한다. 기사·공식 이미지를 reference로 사용하고 카드마다 장면과 visual role을 다르게 한다.
- caption은 장별 설명을 나열하지 말고 자연스러운 뉴스 문단 하나로 쓴다.
- 출처는 마지막 카드에만 모으고 caption에는 `AI로 재구성한 인포그래픽` 계열 문구를 넣지 않는다.
- 사실적 AI 재구성 게시물은 Instagram의 `AI 콘텐츠` 라벨을 켠다.

실행 안전 규칙:
- 로그인된 Instagram 탭이 없을 때만 Profile 3 창을 한 번 연다.
- Instagram page target이 여러 개면 아래 resolver를 Browser Harness로 먼저 실행한다. 설정 계정의 정확한 프로필 탭을 우선해 하나만 남기고 중복 Instagram target만 닫는다. Instagram이 아닌 다른 사이트 탭은 절대 닫거나 탐색하지 않는다. resolver 뒤 target이 정확히 하나인지와 계정·로그인 상태를 preflight로 다시 검증하며, 불일치·login wall·challenge가 있으면 게시하지 않는다.

```powershell
$env:IG_ACCOUNT = "{settings['account']}"
browser-harness < "{instagram_target_resolver_path}"
```
- 적합한 새 이슈가 없거나 검색·기획·이미지·중복·계정·캐러셀·AI 라벨 QA가 하나라도 실패하면 filler를 만들지 말고 skipped 또는 needs_review로 끝낸다.
- 공유하기는 한 번만 누른다. 제출 시작 뒤 오류·timeout이면 자동 재시도하지 않고 공개 프로필을 읽기 전용으로 확인한다.
- 기존 게시물을 삭제하거나 수정하지 않는다. 단, 이번 게시물의 AI 라벨 공개 검증 복구는 publish-news-pick 계약이 허용한 한 번만 수행한다.
- repository의 소스·스킬·Git 상태를 수정하거나 commit/push하지 않는다. 실행물은 output root에만 저장한다.
- published는 shortcode, 4장 전체, 첫 카드, caption, AI 라벨을 공개 페이지에서 확인하고 result.public_verified=true일 때만 보고한다.

최종 응답은 지정된 JSON schema에 맞춰 status, summary, story_headline, run_directory, instagram_url, reason만 반환하라.
"""


def codex_candidates() -> list[Path]:
    configured = os.environ.get("CODEX_EXECUTABLE")
    candidates = [Path(configured).expanduser()] if configured else []
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        npm_packages = Path(os.environ["APPDATA"]) / "npm" / "node_modules" / "@openai" / "codex" / "node_modules"
        candidates.extend(sorted(npm_packages.glob("@openai/codex-*/vendor/*/bin/codex.exe"), reverse=True))
    for name in ("codex.exe", "codex"):
        discovered = shutil.which(name)
        if discovered:
            candidates.append(Path(discovered))
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin" / "codex.exe")
    return candidates


def supports_auto_approval(candidate: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(candidate), "exec", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0 and "--approve-for-me" in completed.stdout


def find_codex() -> Path:
    checked: set[Path] = set()
    for candidate in codex_candidates():
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if supports_auto_approval(resolved):
            return resolved
    raise FileNotFoundError("--approve-for-me를 지원하는 Codex executable을 찾을 수 없다. Codex CLI를 업데이트한다.")


def within_start_window(scheduled_at: datetime, now: datetime) -> bool:
    return scheduled_at - PREPARATION_LEAD <= now <= scheduled_at + MAX_START_LATENESS


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
            "PYTHONIOENCODING": "utf-8",
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
