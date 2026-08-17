# news_pick_insta

국내 종합 이슈를 검증해 3~4장 정방형 Instagram 카드뉴스로 만들고 설정된 계정에 게시하는 portable Codex skill pack입니다.

## 폴더 경계

```text
news_pick_insta/
├── skills/                 # 설치·배포하는 불변 skill 소스
│   ├── search-news/
│   ├── plan-news-pick/
│   ├── create-news-cards/
│   ├── publish-news-pick/
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

`install`은 다섯 스킬을 `$CODEX_HOME/skills` 또는 `~/.codex/skills`에 함께 설치하며 기존 폴더를 덮어쓰지 않습니다. 다른 설치 위치는 `--skills-dir`로 지정합니다.

전체 실행의 시작점은 `skills/upload-news-pick/SKILL.md`입니다.

```powershell
python skills/upload-news-pick/scripts/orchestrate.py init `
  --output-root $env:NEWS_PICK_OUTPUT_ROOT `
  --edition-at <ISO-8601> `
  --account $env:IG_ACCOUNT
```

## 스킬 구성

1. `search-news` — 언론 원문·공식 발표 기반 이슈 발견, 국내 영향도 평가, 교차검증
2. `plan-news-pick` — 중립적 강후킹, 사실·카피·차트·고유 시각 역할 기획
3. `create-news-cards` — 기사·공식 이미지 reference 기반 1024×1024 카드 생성과 중복 QA
4. `publish-news-pick` — 설정된 Chrome profile의 Instagram 웹 UI 게시·공개 검증
5. `upload-news-pick` — 네 단계를 hash·승인 게이트로 연결하는 오케스트레이터

## 외부 의존성

- Python 3.10 이상과 Pillow
- Node.js
- Browser Harness CLI
- `god-tibo-gpt-image2-skill`; 자동 검색되지 않으면 `GOD_TIBO_SKILL_ROOT` 지정
- 사용자가 직접 로그인한 표시형 Chrome profile

비밀번호·MFA·cookie·`sessionid`는 저장소나 workspace 설정에 기록하지 않습니다. 선택적 Instagram private API 의존성은 `skills/publish-news-pick/requirements.txt`에 있으며, 기본 게시 경로는 Browser Harness 웹 UI입니다.

## 검증

```powershell
python -m unittest discover -s scripts -p 'test_*.py'

$skillDirs = @('search-news','plan-news-pick','create-news-cards','publish-news-pick','upload-news-pick')
foreach ($name in $skillDirs) {
  python -m unittest discover -s "skills/$name/scripts" -p 'test_*.py'
}
```

`output/`, 과거 호환용 `runs/`·`assets/`, 모든 `.local/`, Chrome profile과 인증 관련 파일은 Git에서 제외합니다.
