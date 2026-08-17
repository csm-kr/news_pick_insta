# 뉴스픽 자동화 스킬 구현 계획

## 1. 목표

한국의 20~60대 독자를 대상으로 정치·부동산을 포함한 종합 이슈를 골라, 중립적이지만 시선을 끄는 3~4장 인스타그램 카드뉴스로 제작하고 `@newspick_studio`에 게시한다.

- 기본 게시량: 하루 3건
- 기본 회차: 07:00, 12:00, 17:00 KST
- 선정 비율: 관심도가 큰 현안 2건 : 공공 영향도가 큰 현안 1건
- MVP: cron 없이 한 회차를 수동 실행해 캐러셀 1건의 실게시까지 확인
- 이후: MVP가 안정화된 뒤 회차별 완전 자동 실행을 별도 단계로 추가

## 2. 아키텍처 결정

전체 흐름을 하나의 거대한 스킬로 구현하지 않는다. 오케스트레이터 하나와 단계별 전문 스킬 네 개를 둔다.

```text
upload-news-pick                  전체 실행·체크포인트·실패 복구
  ├─ 1. search-news              뉴스 발견·영향도 평가·교차검증
  ├─ 2. plan-news-pick           후킹·논조·3~4장 스토리보드
  ├─ 3. create-news-cards        이미지 생성·한글 편집·시각 QA
  └─ 4. publish-news-pick        캐러셀 준비·승인·게시·사후 확인
```

각 전문 스킬은 단독 실행할 수 있어야 하며, 다른 단계의 내부 구현을 알지 못한다. 단계 간 연결은 버전이 명시된 JSON 산출물과 파일 경로로만 한다.

### 이름과 역할

| 스킬 | 단일 책임 | 하지 않는 일 |
|---|---|---|
| `upload-news-pick` | 네 단계 순서 제어, 실행 ID, 재개, 최종 요약 | 직접 검색·카피 작성·이미지 생성·Instagram API 호출 |
| `search-news` | 현재 회차 후보 수집, 사건 묶기, 국내 영향도 점수, 사실 검증 | 후킹 문구·디자인·게시 |
| `plan-news-pick` | 하나의 검증된 사건을 카드뉴스 메시지와 슬라이드별 카피로 변환 | 새 사실 추가·이미지 렌더링·게시 |
| `create-news-cards` | 무문자 비주얼 생성, 결정적 한글 합성, 3~4장 시각 QA | 뉴스 선정·사실 변경·게시 |
| `publish-news-pick` | 불변 payload, 캐러셀 업로드, 중복 방지, 공개 결과 확인 | 콘텐츠 내용 수정·계정 로그인 자동화 |

## 3. 공통 실행 단위

한 번의 오케스트레이터 실행은 하나의 `run_id`를 가진다. 한 게시물은 하나의 핵심 사건만 다룬다.

```text
output/runs/<run_id>/
  run.json
  01-search/news-candidates.json
  01-search/selected-story.json
  02-plan/editorial-plan.json
  02-plan/storyboard.json
  03-create/assets/
  03-create/directions/direction-01.json ...
  03-create/candidates/direction-01/01.png ...
  03-create/contact-sheets/direction-01.png ...
  03-create/slides/01.png ... 04.png
  03-create/visual-manifest.json
  03-create/selection.json
  03-create/qa-report.json
  04-publish/publish-job.json
  04-publish/attempts.jsonl
  04-publish/result.json
```

모든 단계는 입력 파일의 SHA-256을 기록한다. 앞 단계의 산출물이 바뀌면 뒤 단계의 기존 승인과 게시 준비 상태는 자동으로 무효화한다.

## 4. 1단계: `search-news`

### 발견 경로

기본 검색 경로는 실측 결과에 따라 다음으로 고정한다.

1. 상태 검사를 통과한 국내 언론 RSS와 정부·공공기관 발표 목록을 직접 병렬 조회한다.
2. 회차 후보가 부족할 때만 Google News RSS와 네이버 뉴스 검색·섹션·랭킹으로 회수를 넓힌다.
3. 검색 결과의 제목·스니펫·중계 URL은 사실 근거로 쓰지 않는다. 반드시 언론사 또는 기관의 canonical 원문으로 복귀한다.
4. 본문은 `원문 직접 GET → Jina Reader → 준비된 경우의 insane-search → Browser Harness background` 순으로 복구한다.
5. `agent-reach`/Exa는 현재 환경에서 실행되지 않고 이 규모에 불필요하므로 기본 의존성에서 제외한다.

Browser Harness는 모든 기사 수집기가 아니라 JS 렌더링이 꼭 필요한 최상위 후보의 마지막 복구 수단이다. Instagram 게시에는 별도로 필수 사용한다.

### 회차 시간창

- 07:00: 전일 17:00 이후부터 당일 07:00까지
- 12:00: 당일 07:00 이후부터 12:00까지
- 17:00: 당일 12:00 이후부터 17:00까지

마지막 성공 체크포인트를 함께 사용해 누락과 중복을 방지한다.

### 사건 묶기와 선정

동일 사건의 여러 기사는 제목 유사도만으로 합치지 않는다. 인물, 기관, 정책, 수치, 장소, 발생 시각을 정규화해 안정적인 `event_id`를 만든다.

최종 점수는 다음 신호로 구성한다.

- 국내 영향 범위와 직접성
- 새 정보량과 시급성
- 공공성
- 독립 언론사의 보도 수
- 공식 발표의 존재와 적합성
- 원문과 locator의 검증 완성도
- 당일 다른 게시물과의 주제 다양성

포털 랭킹은 관심도 보조 신호로만 사용하고 사실성이나 중요도의 증거로 쓰지 않는다. 정치·부동산은 상시 탐색하되 낮은 영향도의 기사를 할당량 때문에 강제로 채택하지 않는다.

### 게시 가능 증거 기준

- 최소 두 개의 서로 독립적인 언론사 원문이 같은 핵심 사실을 지지해야 한다.
- 정책·정치·부동산·재난 통계처럼 공식 발표가 존재해야 하는 사안은 공식 원문도 포함한다.
- 각 atomic claim에 canonical URL, 발행 시각, locator, 지지 또는 반박 관계를 남긴다.
- 보도가 서로 충돌하거나 근거가 충분하지 않으면 `developing` 또는 `blocked`로 두고 자동 게시하지 않는다.
- X, 소셜, 커뮤니티, 동영상 요약은 후보와 근거에서 모두 제외한다.

### 주요 출력

`selected-story.json`에는 적어도 다음이 있어야 한다.

```json
{
  "schema_version": "1.0",
  "story_id": "stable-event-id",
  "edition_at": "2026-08-17T17:00:00+09:00",
  "topic": "politics | real_estate | economy | society",
  "verified_headline": "검증된 사실 문장",
  "why_it_matters": "국내 독자 영향 한 문장",
  "claims": [],
  "sources": [],
  "limitations": [],
  "verification_status": "verified"
}
```

## 5. 2단계: `plan-news-pick`

### 편집 원칙

- 강한 후킹은 허용하지만 사실의 강도를 키우지 않는다.
- 첫 장은 가장 중요한 변화와 독자 영향을 짧게 제시한다.
- 제목에 없는 공포, 분노, 단정, 승패, 책임 소재를 새로 만들지 않는다.
- 정치 뉴스는 행위자별 표현 강도와 맥락의 양을 대칭적으로 점검한다.
- 부동산 뉴스는 지역·대상·시행일·예외 조건을 생략해 보편적 변화처럼 보이게 하지 않는다.
- 클릭을 위해 질문형을 쓰더라도 본문에서 즉시 답할 수 있는 질문만 허용한다.

### 3~4장 기본 구조

```text
1장: HOOK       무엇이 바뀌었고 왜 지금 봐야 하는가
2장: FACT       검증된 핵심 사실·수치·발표 내용
3장: IMPACT     누구에게 어떤 영향이 있는가
4장: CONTEXT    예외·남은 변수·출처·업데이트 시각
```

세 장일 때는 2장과 3장을 합친다. 한 장에는 하나의 메시지만 둔다.

### 후킹 생성 계약

한 사건마다 서로 다른 각도의 후킹 후보를 5개 만든 뒤 다음 기준으로 채점한다.

- 사실 충실도
- 현재성
- 독자 영향의 명확성
- 구체성
- 첫눈 가독성
- 선정성·편향 위험

후보별 점수는 사실 구체성 0~2, 생활 영향 0~2, 즉시 이해 0~2, 과장 위험 0~-2로 계산한다. 최고점이 같으면 더 짧은 제목을 선택한다. 선정성 위험이 기준을 넘는 후보는 총점과 무관하게 폐기한다. 최종 후킹의 모든 명사·동사·숫자·최상급은 `selected-story.json`의 claim으로 역추적할 수 있어야 한다.

### 주요 출력

- `editorial-plan.json`: 독자, 핵심 메시지, 선택한 후킹, 톤, caption, 출처 표기
- `storyboard.json`: 슬라이드 순서, 역할, 잠긴 `required_text`, `chart_spec`, 근거 claim ID, 기사·공식 화면 `reference_requirements`

## 6. 3단계: `create-news-cards`

### 실제 reference 기반 완성 이미지 생성

`god-tibo-image-lab`은 실제 기사 대표 사진과 공식 발표·공시 화면을 reference로 받아 한글 카피·핵심 수치·차트까지 포함한 완성 카드를 장당 하나의 `controllable` job으로 생성한다. 여러 슬라이드를 한 batch로 묶지 않아 한 장의 실패가 전체를 무효화하지 않게 한다. 코드는 이미지 렌더링이 아니라 크기·해시·장수·매니페스트 QA에만 사용한다.

한 번에 한 세트만 생성해 그대로 채택하지 않는다. **총 12장의 후보를 완결된 비주얼 방향별 세트로 만든 뒤 한 세트를 선택**한다.

```text
기본 4장 카드뉴스: 비주얼 방향 3개 × 방향별 4장 = 총 12장
```

각 방향은 공통 `direction_bible`을 먼저 고정한다. 여기에는 팔레트, 포토에디토리얼 처리, 타이포 계층, 차트 언어, reference에 없는 인물·사건·문서 생성 금지, 카드별 구도 변화 규칙을 둔다. 같은 방향 안의 모든 장은 동일한 bible을 공유하되, 각 장의 역할에 맞춰 구도만 달라져야 한다.

선택은 낱장 인기투표가 아니라 **완성 세트 단위**가 기본이다. 서로 다른 방향의 낱장을 섞으면 캐러셀의 색감·공간·상징이 끊기기 때문이다. 한 장만 실패한 경우에는 선택된 방향의 bible을 유지해 그 장만 재생성한다.

세트 선택 점수는 카드 간 일관성, 사진-reference 적합성, 구도 다양성, 한글·숫자 가독성, 차트 정확성, 생성 왜곡 부재로 구성한다. contact sheet로 방향을 비교한 뒤 각 카드를 원본 크기로 확대 검수한다. 한글·수치·차트 오류가 있는 장은 코드로 덮지 않고 해당 job만 재생성한다.

현재 전역 Tibo wrapper는 한 job의 `items/prompts/workers`를 최대 8개로 검증하지만, 프로젝트 어댑터는 단일 이미지 job 12개를 만들어 하나의 상위 명령에서 동시에 실행한다. 따라서 전역 스킬을 수정하지 않고도 12개 backend 생성을 동시에 요청하며, 각 이미지의 실패는 다른 11장과 격리한다.

AI 모델에는 잠긴 `required_text`와 `chart_spec`을 주고 최종 이미지 안에서 직접 생성하게 한다. reference에 없는 인물·현장·건물·은행 표지·정당 로고·정부 문서를 새로 만들게 하지 않는다. 실제 기사 사진은 그대로 복제하지 않고 독창적인 포토에디토리얼 인포그래픽으로 재구성하며, 캡션에 `AI로 재구성한 인포그래픽`임을 밝힌다. 한국경제·한경·한경BUSINESS는 source와 reference에서 제외한다.

### 캔버스와 안전영역

- 기본 산출물: 1080×1350 PNG, sRGB
- 슬라이드 수: 기본 4장
- 첫 장은 작은 화면에서도 제목과 핵심 숫자가 먼저 읽혀야 한다.
- Instagram UI와 크롭에 걸리지 않도록 공통 안전영역을 둔다.
- 카드 간 그리드, 색상, 타이포 계층, 출처 위치를 고정한다.

첫 구현의 내부 운영 기준은 다음으로 잠근다. Instagram 공식 제한값이 아니라 조사 표본과 모바일 축소 화면을 바탕으로 한 뉴스픽 기준이다.

- 첫 장 제목: 한글 12~26자, 2~3행, 72~96px
- 첫 장 부제: 20~45자, 최대 2행, 38~48px
- 본문 카드: 55~110자, 2~4문장, 34~42px
- 출처·AI 라벨: 26~30px
- 안전 여백: 좌우 80~96px, 상하 72~96px
- 의미 있는 모든 글자와 배경의 대비: 최소 4.5:1
- 한 카드의 위계: 결론 1개 → 근거 2~3개 → 출처·기준시각

### 자동 QA와 시각 QA

- 정확히 3~4장의 PNG가 존재한다.
- 모든 파일이 1080×1350이고 열리며 손상되지 않았다.
- 본문·제목 overflow나 잘림이 없다.
- 각 수치·인용·고유명사가 storyboard claim과 일치한다.
- 출처와 업데이트 시각이 읽을 수 있는 크기로 존재한다.
- AI 이미지 라벨이 필요한 장에 누락되지 않았다.
- 360px 축소 미리보기에서 첫 장 후킹과 각 장의 핵심 메시지가 읽힌다.
- 장면이 실제 보도사진으로 오인될 위험을 육안으로 점검한다.
- 편집 품질 8개 항목을 각 0~2점으로 평가해 16점 중 13점 미만이면 재작성한다.

## 7. 4단계: `publish-news-pick`

### 게시 방식

기본 산출물은 Reel이 아니라 사진 캐러셀이다. 기존 `instagram-upload-skill`의 `private_reel` 구현을 그대로 쓰지 않고, 상태 머신과 보안 원칙만 재사용해 별도의 `private_carousel` backend를 만든다.

- 대상 계정: `@newspick_studio`
- 로그인 세션: 전용 Chrome `Profile 3`의 현재 로그인 상태 재사용
- Browser Harness: 사용자 포커스를 가져오지 않는 background target만 사용
- 비밀번호, MFA, CAPTCHA, 동의 처리는 자동화하지 않는다.
- 세션 쿠키는 메모리에서만 전달하고 로그·파일에 저장하지 않는다.

### 상태 머신

```text
draft → approved → submitting → submitted → published
                         ├─ failed_pre_submit
                         └─ needs_review
```

`submitted`는 private API가 식별자를 반환했지만 공개 프로필 검증 전인 상태다.

`prepare` 시 순서가 고정된 이미지 목록, 각 파일 SHA-256, caption, 계정, 예약 시각을 하나의 `payload_sha256`으로 잠근다. payload가 바뀌면 승인을 무효화한다.

제출 호출 이후 timeout이나 불명확한 오류가 나면 자동 재시도하지 않는다. 이미 게시됐을 가능성이 있으므로 `needs_review`로 두고 프로필에서 중복 여부를 먼저 확인한다.

### 게시 전 자동 차단

- 검증되지 않은 유출·루머·사생활
- 미성년자 또는 피해자 식별 정보
- 잔혹한 범죄·사고 이미지
- 검증되지 않은 선거 결과
- 개인화된 투자·의료 조언
- 핵심 근거의 충돌 또는 부족
- `verification_status != verified`
- 이미지 QA 실패 또는 출처 누락

### 게시 성공 판정

private API 응답만으로 성공을 확정하지 않는다. `@newspick_studio` 공개 프로필에서 새 캐러셀의 shortcode/URL, 첫 장, 장수, caption 일부를 다시 읽어 payload와 일치시킨 뒤 `published`로 전환한다.

## 8. 오케스트레이터: `upload-news-pick`

오케스트레이터는 다음 규칙만 가진다.

1. 회차와 `run_id`를 정한다.
2. 각 전문 스킬을 정확히 한 단계씩 호출한다.
3. 스키마와 SHA-256을 검증한 뒤 다음 단계로 넘긴다.
4. 실패한 단계에서 멈추고, 이미 성공한 단계는 입력이 바뀌지 않았다면 재사용한다.
5. 자동 차단 사유를 숨기지 않고 최종 요약에 남긴다.
6. MVP에서는 4단계 직전 최종 payload를 사람이 확인한 뒤 실게시한다.
7. 한 건의 실게시와 사후 확인이 성공한 뒤에만 무인 실행 옵션을 연다.

## 9. `references/` 배치

참고 자료는 `reference/`가 아니라 Codex 스킬 관례에 맞춰 `references/` 복수형을 사용한다. 한 파일에 모두 넣지 않고 실제 사용 단계별로 나눈다.

```text
upload-news-pick/references/
  workflow-contract.md          네 단계 연결·재개·차단 정책
  operating-policy.md           계정·회차·게시량·편집 원칙

search-news/references/
  source-registry.md            상태 검증된 언론 RSS·공식 발표 목록
  search-routing.md             direct/Jina/insane/browser fallback
  evidence-contract.md          claim·locator·독립 출처·반증 규칙
  impact-scoring.md             국내 영향도와 2:1 선정 기준

plan-news-pick/references/
  card-news-formulas.md         검증된 3~4장 구성 공식
  hook-patterns.md              중립적 강후킹 패턴과 금지 패턴
  politics-realestate-guide.md  정치·부동산의 균형·조건 표기
  copy-qa.md                    제목·숫자·맥락·출처 QA

create-news-cards/references/
  visual-system.md              그리드·타이포·색상·안전영역
  image-policy.md               AI 일러스트·실제 사진 오인 방지
  render-qa.md                  크기·overflow·대비·360px 검사

publish-news-pick/references/
  private-carousel.md           캐러셀 backend와 세션 처리
  publish-state-machine.md      hash·승인·중복 방지·needs_review
  post-publish-verification.md  공개 프로필 확인 계약
```

조사 원문은 짧은 사실 데이터베이스처럼 복사하지 않는다. 각 reference는 출처 링크, 관찰 사례, 채택한 규칙, 적용 조건, 피해야 할 패턴을 함께 기록한다.

카드뉴스 reference의 첫 근거 묶음은 2026-08-17에 직접 확인한 8개 게시물·7개 발행주체 표본과 BBC·Reuters 편집 원칙, W3C 접근성 기준, Meta AI 라벨 정책이다. 조사 원본은 `card-news-research.md`에 보존하고, 구현 시 위 표의 `plan-news-pick/references/` 및 `create-news-cards/references/`로 규칙을 분리한다.

## 10. 참조 저장소에서 재사용할 범위

### `research-master`

재사용:

- candidate → verified 상태
- canonical URL, `published_at`/`observed_at`, locator
- 사건·원문 중복 제거
- supports/contradicts/context 관계
- 외부 쓰기 전 승인과 exact payload 고정 원칙

제외:

- AI 트렌드 30~40건과 9개 lane
- YouTube·X·소셜 수집
- 단일 대형 HTML 보고서
- 모든 deep-research 엔진 bundle

### `god-tibo-image-lab`

재사용:

- `controllable` 생성 job과 manifest 검증
- 장당 단일 job, 실패 격리
- target size와 산출물 검증

추가:

- 뉴스 카드 전용 얇은 생성 adapter
- 무문자 비주얼 정책
- 결정적 한글 합성기와 시각 QA

### `instagram-upload-skill`

재사용:

- 전용 Chrome·loopback CDP·background target
- sessionid 메모리 전달과 민감정보 redaction
- payload SHA-256, 승인 무효화, 감사 로그
- 제출 후 자동 재시도 금지

추가 또는 수정:

- Reel이 아닌 `private_carousel` backend
- Windows `Scripts/python.exe` 탐색
- Unix 전용 `fcntl`을 대체할 cross-platform lock
- 공개 프로필 기반 게시 사후 확인

## 11. 구현 순서

1. 스킬 생성 위치와 다섯 스킬 디렉터리 이름을 확정한다.
2. 공식 `init_skill.py`로 다섯 스킬을 초기화한다.
3. 조사 자료를 단계별 `references/`로 분해하고 각 `SKILL.md`에 읽기 조건을 명시한다.
4. 공통 JSON Schema와 fixture를 먼저 만든다.
5. `search-news`의 직접 RSS/공식 목록, event dedupe, evidence 검증부터 구현한다.
6. `plan-news-pick`의 후킹 후보 생성, 선정성 차단, 3~4장 storyboard 검증을 구현한다.
7. `create-news-cards`의 Image Lab adapter, 한글 합성, 360px QA를 구현한다.
8. `publish-news-pick`의 carousel prepare/approve/dry-run과 Windows 호환을 구현한다.
9. 네 단계를 `upload-news-pick`으로 연결하고 중단·재개 테스트를 한다.
10. 현재 회차의 실제 뉴스 1건을 선정해 1~3단계를 실행한다.
11. 최종 payload 확인 후 `@newspick_studio`에 캐러셀 1건을 게시하고 공개 결과를 검증한다.
12. 성공 뒤에만 07:00·12:00·17:00 무인 실행을 별도 승인한다.

## 12. MVP 완료 기준

- 다섯 스킬이 각각 단독 호출 가능하고 오케스트레이터에서도 연결된다.
- 허용 출처만으로 한 사건의 독립 언론 2곳과 필요한 공식 근거가 검증된다.
- 후킹의 모든 표현이 claim ID로 추적되며 선정성 가드레일을 통과한다.
- 1080×1350 카드 3~4장이 생성되고 360px 가독성·출처·AI 라벨 QA를 통과한다.
- 게시 payload가 hash로 잠기며 변경 시 승인이 무효화된다.
- `@newspick_studio`에 캐러셀 한 건이 중복 없이 게시된다.
- 공개 프로필에서 URL, 첫 장, 장수, caption이 준비한 payload와 일치한다.
- 비밀번호·MFA·cookie·Authorization이 파일과 로그에 남지 않는다.
- 제출 결과가 모호할 때 자동 재시도하지 않고 `needs_review`로 멈춘다.

## 13. MVP 이후에만 검토할 것

- cron 또는 Codex scheduled task
- 하루 3건 초과의 탄력 편성
- 성과 데이터 기반 후킹 공식 가중치 조정
- 공식 Meta Graph API backend
- agent-reach/Exa 또는 상시 insane-search
- Reel·쇼츠 동시 배포

현재 단계에서는 위 항목을 구현하지 않는다.
