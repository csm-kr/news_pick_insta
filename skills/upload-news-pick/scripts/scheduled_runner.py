#!/usr/bin/env python3
"""Run one policy-scoped news-pick edition through Claude Code non-interactively (`claude -p`)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
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
# 예약 작업은 pythonw로 창 없이 돈다. 콘솔 자식은 숨은 콘솔로 띄워 창이 번쩍이거나 닫혀 run이 죽지 않게 한다.
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
VALID_SLOTS = ("07:00", "12:00", "17:00")
ENTERTAINMENT_WATCHLIST = ("리센느",)
ASIAN_GAMES_FIRST_DAY = date(2026, 9, 27)
ASIAN_GAMES_LAST_DAY = date(2026, 10, 2)
PREPARATION_LEAD = timedelta(minutes=30)
MAX_START_LATENESS = timedelta(minutes=30)
STALE_LOCK_AGE = timedelta(hours=4)
EXECUTOR = "claude-code"
# 모델은 지정하지 않으면 Claude Code에 저장된 기본 모델(/model)을 따른다.
DEFAULT_CLAUDE_EFFORT = "high"
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# 매일 같은 초에 공유하면 자동화로 보이므로 회차 시각 뒤 1~15분 사이에서 무작위로 공유한다
PUBLISH_OFFSET_RANGE_SECONDS = (60, 900)


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


def edition_at(slot: str, edition_date: date) -> datetime:
    if slot not in VALID_SLOTS:
        raise ValueError(f"지원하지 않는 회차다: {slot}")
    hour, minute = (int(part) for part in slot.split(":"))
    return datetime.combine(edition_date, time(hour, minute), tzinfo=KST)


def workspace_settings(
    root: Path,
    output_override: Path | None = None,
    account_override: str | None = None,
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
        "imagegen": validate_imagegen(config.get("imagegen")),
    }


def validate_imagegen(value: dict[str, Any] | None) -> dict[str, str]:
    """workspace.json의 선택적 `imagegen` 블록(auth_file, model)을 검증한다. 값 자체는 출력하지 않는다."""
    block = value or {}
    if not isinstance(block, dict):
        raise ValueError("workspace imagegen은 객체여야 한다.")
    result: dict[str, str] = {}
    auth_file = str(block.get("auth_file") or "").strip()
    if auth_file:
        path = Path(auth_file).expanduser()
        if not path.is_absolute():
            raise ValueError("workspace imagegen.auth_file은 절대경로여야 한다.")
        result["auth_file"] = str(path.resolve())
    model = str(block.get("model") or "").strip()
    if model:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", model):
            raise ValueError("workspace imagegen.model 형식이 올바르지 않다.")
        result["model"] = model
    return result


def editorial_lane_for(scheduled_at: datetime) -> str:
    if scheduled_at.strftime("%H:%M") == "07:00" and ASIAN_GAMES_FIRST_DAY <= scheduled_at.date() <= ASIAN_GAMES_LAST_DAY:
        return "asian_games"
    return {
        "07:00": "entertainment",
        "12:00": "hot_news_week",
        "17:00": "hot_news_3day",
    }[scheduled_at.strftime("%H:%M")]


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
        if (
            result.get("status") != "published"
            or result.get("public_verified") is not True
            or result.get("portrait_4x5") is not True
            or result.get("card_count") != 5
        ):
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


def earlier_editions_in_progress(output_root: Path, scheduled_at: datetime) -> list[dict[str, str]]:
    """Reserve verified stories while an earlier edition is being produced."""
    stories = []
    for run_path in sorted((output_root / "runs").glob("*/run.json")):
        try:
            state = load_json(run_path)
            when = datetime.fromisoformat(str(state.get("edition_at") or "").replace("Z", "+00:00"))
            if state.get("status") != "in_progress" or when.tzinfo is None:
                continue
            if when.astimezone(KST).date() != scheduled_at.astimezone(KST).date() or when >= scheduled_at:
                continue
            story = load_json(run_path.parent / "01-search" / "selected-story.json")
            if story.get("verification_status") != "verified":
                continue
        except (OSError, ValueError, TypeError):
            continue
        stories.append({
            "edition_at": when.isoformat(),
            "story_id": str(story.get("story_id") or ""),
            "headline": str(story.get("verified_headline") or ""),
            "run_directory": str(run_path.parent),
        })
    return stories


def build_prompt(root: Path, scheduled_at: datetime, settings: dict[str, Any]) -> str:
    skill_path = root / "skills" / "upload-news-pick" / "SKILL.md"
    publish_gate_path = root / "skills" / "upload-news-pick" / "scripts" / "wait_for_publish_time.py"
    publish_scripts = root / "skills" / "publish-news-pick" / "scripts"
    edge_invoker_path = publish_scripts / "invoke_edge_browser_harness.py"
    instagram_preflight_path = publish_scripts / "browser_web_preflight.py"
    editorial_lane = editorial_lane_for(scheduled_at)
    watchlist = ", ".join(ENTERTAINMENT_WATCHLIST)
    asian_games_rule = (
        "- 07:00 `asian_games`(2026-10-02까지)는 위 07:00 `entertainment` 기준 대신 2026 아이치·나고야 아시안게임의 한국 선수단 소식을 다룬다. 금메달·신기록·대회 최초·연패·종합순위 변화처럼 결과와 의미가 확정된 사건만 고르고, 대회 공식 결과·대한체육회 발표 또는 독립 언론 2곳으로 검증한다. 이 lane에서는 '단순 경기 결과' 제외 규칙 대신 이 기준을 적용하되, 점수만 나열하지 말고 기록·배경·다음 일정으로 5장을 채운다. 직전 48시간 안에서 공개 반응·국내 화제성이 가장 큰 사건을 고르고 최근 게시물과 같은 경기·선수의 후속은 제외한다. 적격 사건이 없으면 07:00 `entertainment` 기준으로 대체하고 그 근거를 selected-story.json의 limitations에 기록한다.\n"
        if editorial_lane == "asian_games"
        else ""
    )
    recent_history = recent_published_stories(settings["output_root"])
    recent_history_json = json.dumps(recent_history, ensure_ascii=False, indent=2)
    reserved_stories_json = json.dumps(earlier_editions_in_progress(settings["output_root"], scheduled_at), ensure_ascii=False, indent=2)
    imagegen = settings.get("imagegen") or {}
    imagegen_flags = " ".join(
        part
        for part in (
            f"--imagegen-auth-file {imagegen['auth_file']}" if imagegen.get("auth_file") else "",
            f"--imagegen-model {imagegen['model']}" if imagegen.get("model") else "",
        )
        if part
    )
    imagegen_rule = (
        f"- 이미지 생성 명령(`generate_candidates.py`)에는 이 워크스페이스에 설정된 `{imagegen_flags}`를 그대로 명시한다. 같은 값이 환경변수 `CODEX_IMAGEGEN_AUTH_FILE`/`CODEX_IMAGEGEN_MODEL`로도 주입돼 있다. 다른 인증 홈·계정으로 바꾸지 않는다."
        if imagegen_flags
        else "- 이미지 생성 인증·모델은 `create-news-cards` 스킬의 image-backend-recovery 절차대로 확인하고, 다른 인증 홈·계정으로 자동 전환하지 않는다."
    )
    return f"""뉴스픽 `upload-news-pick` 예약 무인 실행이다.

이 실행은 Claude Code 비대화형(`claude -p`) 무인 실행이며 사용자가 지켜보지 않는다. 사용자에게 질문하거나 확인을 기다리지 말고 아래 지시와 전문 스킬에 따라 정상적인 수집·제작 오류를 수정해 완료하라. 참조 이미지 누락·원문 불일치는 검증된 대체 자료를 확보해 재검수한 뒤에만 진행하며, 실패한 QA를 통과로 바꾸지 않는다. 사실·계정·권한·정책 경계가 막히거나 정상 복구 뒤에도 필수 QA가 실패하면 게시 없이 skipped 또는 needs_review로 끝낸다. 브레인스토밍·계획 모드·별도 승인 요청 없이 수행한다.

먼저 `{skill_path}`를 완전히 읽고 그 파일이 연결하는 네 전문 스킬을 단계 직전에 읽어 그대로 수행하라.

파일은 사용 가능한 읽기 도구로 읽는다. Windows PowerShell에서 한글 UTF-8 텍스트 파일을 읽어야 할 때는 반드시 `Get-Content -Raw -Encoding UTF8`을 사용한다. `-Encoding UTF8` 없이 스킬·JSON·Markdown을 읽지 말고, 글자가 깨져 보이면 즉시 중단해 UTF-8로 다시 읽는다. Python 하위 프로세스에는 `PYTHONUTF8=1`이 이미 설정돼 있다.

이번 회차:
- edition_at: {scheduled_at.isoformat()}
- timezone: Asia/Seoul
- account: {settings['account']}
- public research and reference capture browser: Aside CLI (read `aside-browser` skill)
- Instagram browser: ego lite (`NEWS_PICK_BROWSER=ego`가 주입돼 있다). `invoke_edge_browser_harness.py`가 helper를 ego TaskSpace `newspick-instagram`의 agent 탭으로 중계한다.
- output root: {settings['output_root']}
- target editorial lane: {editorial_lane}

최근 공개 검증 게시물 6건 이내의 편성 기록은 다음과 같다. 같은 사건은 제외하고, 같은 대분류의 연속·과다 편성을 판정하는 입력으로 사용하라.

```json
{recent_history_json}
```

오늘 앞 회차가 제작 중이며 사실 검증을 통과해 확보한 사건은 다음과 같다. 공개 게시가 아직 끝나지 않았어도 이 사건은 이번 회차 후보에서 제외한다. 공개 프로필의 최근 게시물과 함께 확인하고, 다른 run의 산출물이나 작성기를 수정하지 않는다.

```json
{reserved_stories_json}
```

사용자는 이 예약 정책 범위의 실게시를 사전 승인했다. 모든 검증을 통과한 정확한 payload hash를 잠근 뒤 예약 승인으로 한 번만 승인하고, Instagram 웹 UI에서 실제 캐러셀 게시와 공개 검증까지 끝내라. 게시 직전 사용자 입력을 요구하지 마라.

사용자는 카드 후보 생성을 위해 이번 run이 공개 웹에서 수집한 기사 대표 이미지, 공식 기관 보도자료·공시 화면, 카드뉴스 스타일 참고 이미지를 Tibo/GPT Image 백엔드로 전송하는 것도 명시적으로 승인했다. 이 승인은 현재 run의 `references/content`와 `references/style` 아래 파일을 정확히 15장 후보 생성에 사용하는 범위로만 제한된다. cookie, session, 인증 파일, 개인정보, 그 밖의 로컬 파일은 절대 전송하지 않는다. 실제 생성 명령에는 `--approve-public-reference-egress`를 반드시 포함한다. 이 플래그가 빠진 생성 명령은 한 번도 시도하지 말고, 범위 검증이 실패하면 즉시 중단하라.

이 실행은 게시 회차 30분 전에 시작한다. 검색·기획·이미지 생성·QA와 Instagram 작성 화면의 게시 직전 검증까지 미리 끝내되, `공유하기`는 edition_at 이전에 절대 누르지 않는다. 게시 직전 아래 시간 게이트를 실행하고 성공 종료된 뒤에만 `browser_web_share_once.py`를 실행하라. 게이트가 실패하면 게시하지 말고 skipped 또는 needs_review로 끝낸다. 게이트는 환경변수 `NEWS_PICK_PUBLISH_OFFSET_SECONDS`만큼 edition_at 뒤로 공유를 미루므로 도구 timeout보다 오래 기다릴 수 있다. timeout으로 끊기면 실패로 보지 말고 성공 종료할 때까지 같은 게이트 명령을 다시 실행한다. 이 환경변수를 바꾸거나 지우지 않는다.

```powershell
python "{publish_gate_path}"
```

고정 편집 정책:
- 증거 조건을 먼저 통과한 후보 중 이번 회차의 target editorial lane에 맞고 공개 반응·확산·대화 열기·지속성이 가장 큰 이슈 1건을 고른다. 기본 탐색창은 07:00 `entertainment`가 edition_at 직전 48시간이고 핫뉴스 lane은 아래 기간이며 하루 지난 뉴스도 반응과 임팩트가 더 크면 선택한다. 직전 예약 게시물과 같은 사건·핵심 주장은 제외한다.
- 모든 회차는 후보를 비교할 때 후킹 잠재력을 반응 다음 순위의 선정 기준으로 함께 본다. 반전·격차·손실·최초·역대 기록·마감 시점처럼 검증된 사실만으로 첫 장 제목이 성립하는 사건을 우선하고, 반응이 비슷하면 후킹이 더 강한 사건을 고른다. 후킹 근거가 되는 수치·비교 대상을 selected-story.json의 limitations에 남긴다. 사실을 부풀리거나 결과를 감추는 낚시성 제목이 필요한 사건은 후킹 점수를 주지 않는다.
- 07:00 `entertainment`는 한국 연예·방송·영화·음악 산업의 확정 뉴스를 다룬다. 48시간 검색창에 적격 사건이 없으면 전날부터 하루씩 최대 30일을 역추적하고, 가능한 경우 서로 다른 검증 사건 3건을 모을 때까지 범위를 넓힌다. 첫 적격 사건을 즉시 선택하지 말고 공개 반응, 대중 파급 범위, 확정 결과·수치의 크기, 여러 연령대의 대화 가치, 5장 설명력을 비교해 가장 임팩트가 큰 사건을 선택한다. 최신성은 임팩트가 비슷할 때만 우선한다. 검색 범위·반응 신호·비교 근거를 selected-story.json의 limitations에 기록한다. 공식 발표나 독립 언론 두 곳으로 검증된 계약·흥행·컴백·수상·법원·산업 이슈만 선택하고 사생활·루머·악성 논란은 제외한다.
{asian_games_rule}- 연예 watchlist: {watchlist}. watchlist 아티스트·작품의 검증된 사건(컴백·발매·공연·차트·수상·계약)이 탐색창 안에 있으면 최우선 후보로 비교하되, 증거 조건과 반응 비교는 다른 후보와 똑같이 적용하고 근거가 부족하면 선택하지 않는다.
- 12:00 `hot_news_week`는 분야 제한 없이 edition_at 직전 7일 안에서 공개 반응·확산·대화 열기가 가장 큰 검증 사건 1건을 고른다. 며칠 지난 사건도 반응이 이어지면 후보다.
- 17:00 `hot_news_3day`는 분야 제한 없이 edition_at 직전 3일 안에서 공개 반응·확산·대화 열기가 가장 큰 검증 사건 1건을 고른다.
- 핫뉴스 lane은 정치·경제·사회·문화·국제·스포츠·연예 모두 후보이며 정치·정책·재난·공공통계 사안은 공식 원문과 독립 언론 두 곳을 요구한다. 선거 예측·정파적 단정·확인되지 않은 공방·루머는 제외한다. 12:00 `hot_news_week`는 오늘 07:00 회차와 같은 사건을 제외하고, 17:00 `hot_news_3day`는 오늘 07:00·12:00 회차와 같은 사건은 제외한다. 최근 공개 게시물 6건과 오늘 게시물을 먼저 읽어 사건이 겹치는지 확인한다.
- 핫뉴스 lane(`hot_news_week`·`hot_news_3day`)은 경찰·검찰·법원 발표 또는 독립 언론 두 곳으로 확인된 강력범죄 사건도 후보로 비교한다. 사건 개요·수사·재판 경과·제도적 쟁점을 다루고, 피해자 신상·유족 사생활·잔혹한 수법 묘사·확정되지 않은 피의자 실명과 얼굴은 카드·caption·이미지에 넣지 않는다. 피해 현장·피해자 사진은 reference로 쓰지 않는다.
- 정치·부동산은 계속 탐색하지만 두 분야 합계 하루 1건을 기본 상한으로 하고 직전 게시물과 연속 편성하지 않는다. 전국적 긴급성 또는 즉시 권리·비용 변화가 명확한 확정 사안만 예외로 하며 근거를 selected-story.json의 limitations에 기록한다.
- 연예인 사생활·확인되지 않은 논란·단순 경기 결과는 대중 관심형으로 취급하지 않는다. 07:00 `entertainment`에서는 자극적 범죄 소비도 제외한다. target lane에 맞는 검증된 사건이 없으면 낮은 대중 적합도의 정치·부동산으로 채우지 않는다.
- 언론 기사와 공식 발표만 사실 근거로 사용하고, 독립 언론 2곳 이상으로 교차검증한다.
- 결과·손실·격차·반전을 전면에 두는 고강도 사실형 후킹을 사용한다. 1080×1350 세로형 5장으로 만들고, 1장은 실제 사진 전면+하단 그라데이션+좌측 2행 제목을 고정한다. 10개 디렉터 풀에서 3개를 무작위 선택해 15장 후보를 만든 뒤 가장 읽기 좋은 한 세트를 고른다.
{imagegen_rule}
- 공개 기사 사진·공식 화면·스타일 reference는 Aside CLI로 확보한다. Instagram용 ego TaskSpace에서 언론사·기관·스타일 사이트를 열지 않는다. 원문이 빈 화면이거나 추천 콘텐츠로 이동하면 같은 사건의 검증된 다른 원문·공식 자료 또는 정상 확인된 다른 스타일 자료로 대체하고 URL·locator·SHA-256을 다시 검증한다. 제목 캡처에 연락처가 있으면 제목·날짜 영역만 다시 캡처해 입력에서 제외한다. 이미지 backend로 전송하기 전에 reference QA를 통과해야 한다.
- Tibo 후보 job은 `backend_size=1024x1536`, `resize_fit=cover`, `preserve_backend_raw=true`를 명시한다. `contain` 패딩은 기본 제작에 쓰지 않는다. backend `raw_size`와 최종 1080×1350 결과를 나란히 비교해 제목·본문·표·로고·핵심 사진이 crop으로 손실된 후보를 탈락시키고, 실패 카드만 통과한 4:5 카드의 레이아웃을 마지막 보조 reference로 추가해 재생성한다. 그래도 같은 crop 손실만 반복되고 backend raw의 내용이 모두 정확할 때만 1장에 한해 원본 가장자리 배경색을 맞춘 좌우 contain 폴백을 검수한다. 띠 경계, 360px 가독성, 세트 리듬 중 하나라도 실패하면 쓰지 말고, 통과하면 raw·최종 sha256, 패딩 색, `fallback_reason=repeated_cover_crop_loss`를 manifest에 기록한다.
- Instagram 자르기 단계에서는 입력 PNG가 1080×1350이어도 실제 접근성 이름 `자르기 선택`인 종횡비 control을 열어 exact `4:5`를 직접 선택한다. 첫 카드 상·하단 전체와 세로 프레임 screenshot, 자연·렌더 비율 `0.78~0.82`를 확인하기 전에는 `다음`을 누르지 않는다. 입력 크기·정방형 crop preview·carousel dot만으로 4:5를 추정하면 hard fail이다.
- 업로드 준비는 설치된 `browser_web_upload_prepare.py`를 그대로 사용한다. 좌측 create link wrapper의 이름이 비어 있으면 helper가 자식 SVG의 exact `새로운 게시물`/`만들기` label을 사용한다. helper가 `existing_confirmed_crop_session` 또는 crop dialog 성공을 반환한 뒤 React가 file input을 제거했어도 새 run-local helper를 만들거나 create control·파일 업로드를 반복하지 말고 4:5 단계로 진행한다.
- 편집(필터·조정) 단계에서 `다음`이 무시되고 `게시물을 삭제하시겠어요?` 확인창이 뜨면 절대 `삭제`를 누르지 말고 `취소`만 한 번 눌러 draft를 보존한 뒤, 화면이 여전히 편집 단계임을 확인한 경우에만 `다음`을 한 번 더 누른다. 파일을 다시 올리거나 작성기를 다시 열지 않는다.
- 2~4장은 각각 2~3문장 줄글, 서로 다른 관련 실제 이미지, 2~4행·최대 3열 표를 포함하고 5장은 출처만 정리한다. 360px 폭에서 모든 본문·표 셀·출처 행이 읽혀야 한다.
- caption은 장별 설명을 나열하지 말고 자연스러운 뉴스 문단 하나로 쓴다.
- 출처는 마지막 카드에만 모으고 caption에는 `AI로 재구성한 인포그래픽` 계열 문구를 넣지 않는다.
- 사실적 AI 재구성 게시물은 Instagram의 `AI 콘텐츠` 라벨을 켠다.

실행 안전 규칙:
- Instagram 상호작용만 `invoke_edge_browser_harness.py`로 실행한다(이번 회차는 `NEWS_PICK_BROWSER=ego`라 ego lite로 간다). 공개 조사·기사 사진·공식 화면·스타일 자료는 Aside CLI를 사용한다. 이 환경변수를 바꾸지 말고, Instagram은 ego-browser 직접 스크립트·Chrome·다른 CDP URL로 우회하지 않는다. ego helper는 Instagram과 준비용 about:blank 이외의 탐색을 차단한다.
- Instagram 변경 동작 직전에 `output/runs/*/run.json`을 다시 읽는다. 자신과 다른 run이 `status=in_progress`이면서 `current_stage=publish-news-pick`이면 작성기를 열거나 기존 draft를 폐기하지 말고 `skipped`(`composer_busy`)로 끝낸다. 수동 run과 예약 run의 산출물·run_id를 절대 공유하거나 덮어쓰지 않는다.
- `external_submission_pending=true`인 run은 executor가 종료돼도 stale run으로 취소하지 않는다. 공유 요청의 성공·실패가 공개 근거로 확정되기 전에는 읽기 전용 확인만 하며, 작성기 폐기·재업로드·추가 공유를 하지 않는다.
- ego lite는 따로 띄울 필요가 없다. 기존 사용자 탭은 닫거나 탐색하지 않는다(helper는 `newspick-instagram` agent 탭만 본다). exact-byte invoker로 targeted preflight를 helper 프로세스 하나에서 실행한다. 전체 AX/DOM dump를 사용하지 않는다. `upload_prepare`가 클릭 전에 `visible control not found`로 끝나면 탭이 막 앞으로 온 직후일 수 있으니 같은 명령을 한 번만 다시 실행한다.

```powershell
$env:IG_ACCOUNT = "{settings['account']}"
$env:IG_DUPLICATE_TOKENS = '<첫 카드의 안정적인 고유 토큰 2~3개를 | 로 연결>'
python "{edge_invoker_path}" "{instagram_preflight_path}"
```
- preflight 한 번에서 설정 계정·소유자 control·로그인/challenge·공개 프로필 최신 게시물 중복을 함께 확인한다. 중복 점검을 별도 Harness 호출로 반복하지 않는다.
- 같은 Instagram bounded phase 안의 target 탐색·DOM 판독·대기·검증은 한 Browser Harness 호환 helper 프로세스 안에서 묶는다. 공개 자료 수집에는 Aside CLI를 사용한다. 조회는 event-driven targeted probe로 빠르게 처리하고, 게시 UI 변경 사이에만 짧은 random jitter를 둔다.
- 적합한 새 이슈가 없거나 정상적인 재수집·재생성 복구 후에도 필수 QA가 실패하면 filler를 만들지 말고 skipped 또는 needs_review로 끝낸다. 사실·개인정보·권한·중복·계정·캐러셀·AI 라벨의 안전 조건은 완화하지 않는다.
- 공유하기는 한 번만 누른다. 제출 시작 뒤 오류·timeout이면 자동 재시도하지 않고 공개 프로필을 읽기 전용으로 확인한다. 작성기 dialog에 `게시물 공유됨`·`완료`·`게시물` 링크 중 하나가 보이면 공유 성공이므로 정상 검증으로 간다.
- 미게시 복구(사용자 사전 승인, 회차당 한 번): 성공 표지가 없고, 작성기 dialog가 사라졌고, background target에서 프로필을 새로 열어 읽은 최신 게시물 href와 게시물 수가 공유 전 preflight 값과 같을 때만 미게시로 판정한다. 그중 하나라도 다르거나 dialog가 남아 있으면 복구하지 말고 needs_review로 끝낸다. 미게시로 판정하면 실패 시각을 timezone 포함 ISO로 `NEWS_PICK_SHARE_FAILED_AT`에 넣고 `NEWS_PICK_SHARE_RECOVERY=1`, `NEWS_PICK_RUN_DIR=<이번 run 디렉터리>`를 함께 설정해 위 시간 게이트를 다시 실행한다(실패 10분 뒤 해제, 회차 시각+60분이 지나면 거부). 게이트가 끝나면 같은 `IG_DUPLICATE_TOKENS`로 preflight를 다시 실행해 `duplicate_match=false`이고 최신 게시물 href가 그대로일 때만 진행한다. 첫 queue job은 needs_review로 둔 채 같은 slides·caption으로 `carousel_queue.py prepare`를 다시 하고, payload hash가 첫 job과 같을 때만 새 job을 예약 승인한다. `browser_web_upload_prepare.py`부터 4:5·caption·AI 라벨·게시 직전 검증을 처음과 똑같이 다시 통과한 뒤, 위 세 환경변수와 `NEWS_PICK_SCHEDULED_MODE=1`, `NEWS_PICK_EDITION_AT`을 유지한 채 `browser_web_share_once.py`를 한 번 실행한다. 이 helper는 run당 한 번만 복구 클릭을 허용한다. 복구 공유도 실패하면 더 시도하지 말고 needs_review로 끝낸다. 복구로 게시했으면 summary에 첫 실패 원인과 복구 시각을 남긴다.
- 기존 게시물을 삭제하거나 수정하지 않는다. 단, 이번 게시물의 AI 라벨 공개 검증 복구는 publish-news-pick 계약이 허용한 한 번만 수행한다.
- repository의 소스·스킬·Git 상태를 수정하거나 commit/push하지 않는다. 실행물은 output root에만 저장한다.
- published는 shortcode, 서로 다른 media source 5개, 모든 주 이미지의 공개 4:5 자연·렌더 비율, 첫·마지막 카드, caption, AI 라벨을 공개 페이지에서 확인하고 result.public_verified=true, result.portrait_4x5=true, result.card_count=5일 때만 보고한다.
- 공개 캐러셀 검증은 공유 성공 직후 같은 승인 거래에서만 `IG_APPROVED_PUBLISH_VERIFY=1`을 설정해 공유에 사용한 전용 Instagram target을 읽기 전용으로 재사용한다. 독립 조회와 needs_review 조사는 background target에서 수행한다.

최종 응답은 지정된 JSON schema에 맞춰 status, summary, story_headline, run_directory, instagram_url, reason만 반환하라. 다른 설명 문장을 붙이지 않는다.
"""


def claude_candidates() -> list[Path]:
    configured = os.environ.get("CLAUDE_EXECUTABLE")
    candidates = [Path(configured).expanduser()] if configured else []
    for name in ("claude", "claude.exe", "claude.cmd"):
        discovered = shutil.which(name)
        if discovered:
            candidates.append(Path(discovered))
    home = Path.home()
    candidates.append(home / ".local" / "bin" / "claude.exe" if sys.platform == "win32" else home / ".local" / "bin" / "claude")
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "npm" / "claude.cmd")
    return candidates


def supports_print_schema(candidate: Path) -> bool:
    """`claude -p`에 필요한 구조화 출력·무인 권한 플래그를 이 실행 파일이 지원하는지 확인한다."""
    try:
        completed = subprocess.run(
            [str(candidate), "--help"],
            capture_output=True,
            creationflags=NO_WINDOW_FLAGS,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = completed.stdout or ""
    return completed.returncode == 0 and "--json-schema" in output and "--dangerously-skip-permissions" in output


def find_claude() -> Path:
    checked: set[Path] = set()
    for candidate in claude_candidates():
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if supports_print_schema(resolved):
            return resolved
    raise FileNotFoundError(
        "--json-schema와 --dangerously-skip-permissions를 지원하는 Claude Code executable을 찾을 수 없다. "
        "Claude Code CLI를 설치·업데이트하거나 CLAUDE_EXECUTABLE을 지정한다."
    )


def claude_model() -> str | None:
    value = (os.environ.get("NEWS_PICK_CLAUDE_MODEL") or "").strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        raise ValueError("NEWS_PICK_CLAUDE_MODEL 형식이 올바르지 않다.")
    return value


def claude_effort() -> str:
    value = (os.environ.get("NEWS_PICK_CLAUDE_EFFORT") or DEFAULT_CLAUDE_EFFORT).strip().lower()
    if value not in CLAUDE_EFFORT_LEVELS:
        raise ValueError(f"NEWS_PICK_CLAUDE_EFFORT는 {', '.join(CLAUDE_EFFORT_LEVELS)} 중 하나여야 한다.")
    return value


def cli_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """`claude --json-schema` 검증기가 거부하는 `$schema`/`$id` 방언 키를 뺀 사본을 만든다."""
    return {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}


def build_command(claude_path: Path, root: Path, schema: dict[str, Any], output_root: Path) -> list[str]:
    """한 회차를 `claude -p`로 무인 실행하는 명령. prompt는 stdin으로 전달한다."""
    schema = cli_schema(schema)
    command = [
        str(claude_path),
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--effort",
        claude_effort(),
        "--json-schema",
        json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
    ]
    model = claude_model()
    if model:
        command.extend(["--model", model])
    try:
        Path(output_root).resolve().relative_to(Path(root).resolve())
    except ValueError:
        command.extend(["--add-dir", str(output_root)])
    return command


def choose_publish_offset() -> int:
    return random.randint(*PUBLISH_OFFSET_RANGE_SECONDS)


def child_environment(
    settings: dict[str, Any],
    scheduled_at: datetime,
    base: dict[str, str] | None = None,
    publish_offset: int = 0,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "NEWS_PICK_OUTPUT_ROOT": str(settings["output_root"]),
            "IG_ACCOUNT": settings["account"],
            "NEWS_PICK_BROWSER": "ego",
            "NEWS_PICK_SCHEDULED_MODE": "1",
            "NEWS_PICK_EDITION_AT": scheduled_at.isoformat(),
            "NEWS_PICK_PUBLISH_OFFSET_SECONDS": str(publish_offset),
        }
    )
    imagegen = settings.get("imagegen") or {}
    if imagegen.get("auth_file"):
        environment["CODEX_IMAGEGEN_AUTH_FILE"] = imagegen["auth_file"]
    if imagegen.get("model"):
        environment["CODEX_IMAGEGEN_MODEL"] = imagegen["model"]
    return environment


def extract_json_object(text: str) -> dict[str, Any] | None:
    """최종 응답 텍스트에서 JSON 객체 하나를 꺼낸다(코드펜스·앞뒤 설명 허용)."""
    if not text:
        return None
    candidates = [text.strip()]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_stream_result(event_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """stream-json 이벤트 로그에서 마지막 result 이벤트의 구조화 출력과 메타데이터를 읽는다."""
    meta: dict[str, Any] = {"session_id": None, "is_error": None, "subtype": None, "total_cost_usd": None, "num_turns": None}
    result_event: dict[str, Any] | None = None
    if not event_path.is_file():
        return None, meta
    with event_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("session_id") and not meta["session_id"]:
                meta["session_id"] = event["session_id"]
            if event.get("type") == "result":
                result_event = event
    if result_event is None:
        return None, meta
    meta.update(
        {
            "session_id": result_event.get("session_id") or meta["session_id"],
            "is_error": bool(result_event.get("is_error")),
            "subtype": result_event.get("subtype"),
            "total_cost_usd": result_event.get("total_cost_usd"),
            "num_turns": result_event.get("num_turns"),
        }
    )
    if meta["is_error"]:
        return None, meta
    structured = result_event.get("structured_output")
    if isinstance(structured, dict):
        return structured, meta
    text = result_event.get("result")
    return (extract_json_object(text) if isinstance(text, str) else None), meta


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
    schema = load_json(schema_path)
    result_path = scheduler_root / "results" / f"{slot_id}.json"
    if dry_run:
        command = build_command(find_claude(), root, schema, output_root)
        return 0, {
            "status": "dry_run",
            "executor": EXECUTOR,
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

    command = build_command(find_claude(), root, schema, output_root)
    log_root = output_root / "logs" / "scheduler"
    event_path = log_root / f"{slot_id}.jsonl"
    error_path = log_root / f"{slot_id}.stderr.log"
    for path in (result_path, event_path, error_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    publish_offset = choose_publish_offset()
    started = {
        "schema_version": "1.0",
        "executor": EXECUTOR,
        "slot_id": slot_id,
        "scheduled_at": scheduled_at.isoformat(),
        "started_at": now.isoformat(),
        "status": "running",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "publish_offset_seconds": publish_offset,
        "event_log": str(event_path),
        "error_log": str(error_path),
        "result_path": str(result_path),
    }
    environment = child_environment(settings, scheduled_at, publish_offset=publish_offset)
    with exclusive_lock(scheduler_root / "scheduled-run.lock", now):
        atomic_json(state_path, started)
        result_path.unlink(missing_ok=True)
        with event_path.open("w", encoding="utf-8") as events, error_path.open("w", encoding="utf-8") as errors:
            completed = subprocess.run(
                command,
                input=prompt,
                stdout=events,
                stderr=errors,
                creationflags=NO_WINDOW_FLAGS,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                cwd=str(root),
                check=False,
            )
    finished_at = datetime.now(KST)
    final, meta = parse_stream_result(event_path)
    if final is not None:
        atomic_json(result_path, final)
    status = str((final or {}).get("status") or "failed")
    if status not in {"published", "skipped", "needs_review", "failed"}:
        status = "failed"
    if completed.returncode != 0 or meta.get("is_error"):
        status = "failed"
    if status == "published" and final and (not final.get("instagram_url") or not final.get("run_directory")):
        status = "failed"
    ended = {
        **started,
        "completed_at": finished_at.isoformat(),
        "status": status,
        "claude_exit_code": completed.returncode,
        "claude_session_id": meta.get("session_id"),
        "claude_result_subtype": meta.get("subtype"),
        "claude_total_cost_usd": meta.get("total_cost_usd"),
        "claude_num_turns": meta.get("num_turns"),
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        root = project_root()
        now = datetime.now(KST)
        scheduled_at = edition_at(args.slot, args.edition_date or now.date())
        settings = workspace_settings(root, args.output_root, args.account)
        exit_code, result = run_job(root, scheduled_at, settings, now, args.dry_run)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": exit_code == 0, "result": result}, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
