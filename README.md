# news_pick_insta

국내 종합 이슈를 검증해 3~4장 정방형 Instagram 카드뉴스로 만들고, 설정된 계정의 피드와 일일 요약 Story에 게시하는 portable Codex skill pack입니다.

## 폴더 경계

```text
news_pick_insta/
├── skills/                 # 설치·배포하는 불변 skill 소스
│   ├── search-news/
│   ├── plan-news-pick/
│   ├── create-news-cards/
│   ├── publish-news-pick/
│   ├── publish-daily-news-story/
│   └── upload-news-pick/
├── scripts/                # pack 설치·workspace 초기화·검증
├── docs/                   # 설계와 조사 기록
└── output/                 # 실제 run·이미지·게시 상태, Git 제외
    ├── runs/
    ├── publish-news-pick/
    ├── profile-candidates/
    ├── cache/
    └── logs/
```

`skills/` 아래에는 생성 이미지, 기사 reference, 게시 job, screenshot, 가상환경을 쓰지 않습니다. 모든 runtime 파일은 `NEWS_PICK_OUTPUT_ROOT` 하나에 모읍니다.

## 새 환경에서 시작

```powershell
git clone https://github.com/csm-kr/news_pick_insta.git
cd news_pick_insta

python scripts/bootstrap.py check
python scripts/bootstrap.py install
python scripts/bootstrap.py init `
  --workspace . `
  --account newspick_studio `
  --chrome-profile "Profile 3"

$env:NEWS_PICK_OUTPUT_ROOT = (Resolve-Path ./output)
$env:IG_ACCOUNT = 'newspick_studio'
$env:NEWS_PICK_CHROME_PROFILE = 'Profile 3'
```

`install`은 여섯 스킬을 `$CODEX_HOME/skills` 또는 `~/.codex/skills`에 함께 설치하며 기존 폴더를 덮어쓰지 않습니다. 다른 설치 위치는 `--skills-dir`로 지정합니다.

전체 실행의 시작점은 `skills/upload-news-pick/SKILL.md`입니다.

```powershell
python skills/upload-news-pick/scripts/orchestrate.py init `
  --output-root $env:NEWS_PICK_OUTPUT_ROOT `
  --edition-at <ISO-8601> `
  --account $env:IG_ACCOUNT
```

## 예약 무인 게시

Windows에서는 cron 대신 Task Scheduler로 `07:00`, `12:00`, `17:00` KST 회차를 등록합니다. 로그인된 사용자 세션, Codex CLI 로그인, Profile 3의 Instagram 로그인이 필요합니다.

```powershell
python skills/upload-news-pick/scripts/scheduled_runner.py --slot 17:00 --dry-run
powershell -ExecutionPolicy Bypass -File skills/upload-news-pick/scripts/manage_windows_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File skills/upload-news-pick/scripts/manage_windows_schedule.ps1 status
```

동일 회차 중복 실행, 30분을 넘긴 missed run, QA 실패, 모호한 제출은 자동 게시하지 않습니다. 상태와 로그는 Git에서 제외된 `output/scheduler`와 `output/logs/scheduler`에 저장됩니다.

매일 `21:00`에는 그날 공개 검증된 뉴스 캐러셀 전부의 첫 카드만 모아 6초 Story로 게시합니다. 게시물이 3개면 대문 3장, 4개면 대문 4장처럼 당일 게시 완료 목록 전체를 사용합니다.

```powershell
python skills/publish-daily-news-story/scripts/scheduled_story_runner.py --dry-run
powershell -ExecutionPolicy Bypass -File skills/publish-daily-news-story/scripts/manage_windows_story_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File skills/publish-daily-news-story/scripts/manage_windows_story_schedule.ps1 status
```

## 스킬 구성

1. `search-news` — 언론 원문·공식 발표 기반 이슈 발견, 국내 영향도 평가, 교차검증
2. `plan-news-pick` — 중립적 강후킹, 사실·카피·차트·고유 시각 역할 기획
3. `create-news-cards` — 기사·공식 이미지 reference 기반 1024×1024 카드 생성과 중복 QA
4. `publish-news-pick` — 설정된 Chrome profile의 Instagram 웹 UI 게시·공개 검증
5. `publish-daily-news-story` — 오늘 검증된 모든 표지를 FFmpeg 6초 영상으로 만들어 Story 게시·검증
6. `upload-news-pick` — 네 단계를 hash·승인 게이트로 연결하는 오케스트레이터

## 외부 의존성

- Python 3.10 이상과 Pillow
- Node.js
- FFmpeg와 ffprobe
- Browser Harness CLI
- `god-tibo-gpt-image2-skill`; 자동 검색되지 않으면 `GOD_TIBO_SKILL_ROOT` 지정
- 사용자가 직접 로그인한 표시형 Chrome profile

비밀번호·MFA·cookie·`sessionid`는 저장소나 workspace 설정에 기록하지 않습니다. 선택적 Instagram private API 의존성은 `skills/publish-news-pick/requirements.txt`에 있으며, 기본 게시 경로는 Browser Harness 웹 UI입니다.

## 검증

```powershell
python -m unittest discover -s scripts -p 'test_*.py'

$skillDirs = @('search-news','plan-news-pick','create-news-cards','publish-news-pick','publish-daily-news-story','upload-news-pick')
foreach ($name in $skillDirs) {
  python -m unittest discover -s "skills/$name/scripts" -p 'test_*.py'
}
```

`output/`, 과거 호환용 `runs/`·`assets/`, 모든 `.local/`, Chrome profile과 인증 관련 파일은 Git에서 제외합니다.
