# news_pick_insta

국내 종합 이슈를 검증해 3~4장 정방형 Instagram 카드뉴스로 만들고 `@newspick_studio`에 게시하는 Codex 스킬 묶음입니다.

## 스킬 구성

1. `search-news` — 언론 원문·공식 발표 기반 이슈 발견, 국내 영향도 평가, 교차검증
2. `plan-news-pick` — 중립적 강후킹, 카드별 사실·카피·차트·고유 시각 역할 기획
3. `create-news-cards` — 실제 기사·공식 이미지 reference 기반 1024×1024 완성 카드 생성과 QA
4. `publish-news-pick` — Browser Harness와 전용 Chrome Profile 3을 이용한 Instagram 캐러셀 게시·공개 검증
5. `upload-news-pick` — 위 네 단계를 hash·승인 게이트로 연결하는 전체 오케스트레이터

## 핵심 운영 원칙

- 국내 영향도 우선, 정치·부동산·경제·사회 종합 편성
- 공식 발표와 독립 언론 원문으로 검증된 사실만 사용
- 첫 카드는 중립적이되 강한 숫자·결정·생활 영향으로 후킹
- 이미지 생성은 카드별 서로 다른 `visual_role`과 대표 reference를 사용
- 생성 뒤 SHA-256, 전체/상단 영역 dHash·MAE로 exact/near duplicate를 차단
- 같은 인물·사건 사진의 유사 crop 반복은 확대 육안 QA 후 겹친 장만 재생성
- 출처명·날짜·도메인은 마지막 장에 모으고 전체 URL은 caption·manifest에 보존
- Instagram 게시 직전 불변 payload hash를 승인하고 게시 후 공개 프로필에서 재검증
- 로그인 비밀번호·MFA·cookie·`sessionid`는 저장소나 로그에 저장하지 않음

## 구조

```text
skills/
  search-news/
  plan-news-pick/
  create-news-cards/
  publish-news-pick/
  upload-news-pick/
plan.md
repo-analysis.md
news-search-benchmark.md
card-news-research.md
youtube-cardnews-analysis.md
```

각 스킬을 실행하기 전에 해당 폴더의 `SKILL.md`를 완전히 읽어야 합니다. 전체 실행의 시작점은 `skills/upload-news-pick/SKILL.md`입니다.

## 검증

```powershell
$skillDirs = @('search-news','plan-news-pick','create-news-cards','publish-news-pick','upload-news-pick')
foreach ($name in $skillDirs) {
  python -m unittest discover -s "skills/$name/scripts" -p 'test_*.py'
}
```

이미지 QA 스크립트는 Pillow가 필요합니다. 선택적 Instagram private API 보조 경로의 의존성은 `skills/publish-news-pick/requirements.txt`에 있습니다. 기본 게시 경로는 Browser Harness가 제어하는 Instagram 웹 UI입니다.

## 로컬 전용 데이터

`runs/`, `assets/`, 모든 `.local/`, Python 가상환경, Chrome 프로필, cookie·session·credential 파일은 커밋하지 않습니다. 생성 이미지와 실제 게시 기록은 로컬 run 디렉터리에서만 관리합니다.

