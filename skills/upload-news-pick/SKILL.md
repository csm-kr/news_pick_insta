---
name: upload-news-pick
description: 한국 종합 이슈 하나를 탐색·검증하고, 중립적 강후킹의 3~4장 Instagram 카드뉴스로 기획·제작한 뒤 설정된 계정에 캐러셀로 안전하게 게시하는 portable 전체 오케스트레이터. 오늘의 뉴스픽 제작, 카드뉴스 자동화, 네 단계 일괄 실행, 새 workspace 설치, 중단된 run 재개, 실게시 전 검증, 07·12·17시 KST 예약 무인 게시를 요청할 때 사용한다.
---

# Upload News Pick

하나의 `run_id` 아래 네 전문 스킬을 순서대로 연결한다. 이 스킬은 각 단계의 일을 직접 대신하지 않고 입력·출력 계약, hash, 중단·재개와 게시 승인 경계만 관리한다.

실행 전 [references/portable-layout.md](references/portable-layout.md)를 읽고 다섯 스킬이 같은 부모 폴더에 설치됐는지 확인한다. skill 폴더는 읽기 전용으로 유지하고 모든 실행물은 별도 `NEWS_PICK_OUTPUT_ROOT` 아래에 쓴다.

## 고정 구성

1. `../search-news/SKILL.md`: 뉴스 발견·영향도 평가·교차검증
2. `../plan-news-pick/SKILL.md`: 후킹 후보·3~4장 스토리보드·편집 QA
3. `../create-news-cards/SKILL.md`: 실제 기사·공식 화면 reference 수집, Tibo 완성 후보 12장, 세트 선택·시각 QA
4. `../publish-news-pick/SKILL.md`: 불변 캐러셀 payload·승인·실게시·공개 확인

단계를 실행하기 직전에 해당 전문 스킬의 `SKILL.md`를 완전히 읽고 따른다. 한 단계의 출력 검증이 끝나기 전에 다음 스킬을 호출하지 않는다.

## 시작과 재개

새 실행은 다음으로 만든다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = '<workspace>/output'
python scripts/orchestrate.py init --output-root $env:NEWS_PICK_OUTPUT_ROOT --edition-at <ISO-8601> --account <instagram-account>
```

이 명령은 `<output-root>/runs`, `publish-news-pick`, `profile-candidates`, `cache`, `logs`를 만들고 run은 `<output-root>/runs/<run_id>`에 둔다. 기존 실행은 먼저 상태를 읽는다.

```powershell
python scripts/orchestrate.py status --run <run-directory>
```

입력 hash가 기존 완료 기록과 같으면 완료 단계를 다시 실행하지 않는다. 앞 단계 산출물이 바뀌면 그 뒤 단계 기록과 승인은 폐기하고 해당 단계부터 다시 시작한다. 자세한 계약은 [references/workflow-contract.md](references/workflow-contract.md)를 읽는다.

## 1단계 — 뉴스 검색

`search-news`에 `edition_at`, `timezone=Asia/Seoul`, 직전 성공 체크포인트를 전달한다. 출력은 반드시 다음 위치에 둔다.

```text
01-search/news-candidates.json
01-search/selected-story.json
```

`selected-story.json`이 `verified`가 아니거나 독립 언론 두 곳 및 필요한 공식 근거를 갖추지 못하면 run을 멈춘다. 통과 후:

```powershell
python scripts/orchestrate.py complete-stage --run <run-directory> --stage search-news
```

## 2단계 — 후킹과 기획

`plan-news-pick`에는 1단계의 `selected-story.json`만 사실 입력으로 준다. 새 사실을 검색하거나 추가하게 하지 않는다. 출력:

```text
02-plan/editorial-plan.json
02-plan/storyboard.json
```

3~4장, hook의 근거 연결, hard-fail 통과, 편집 점수 13/16 이상을 확인한 뒤 `plan-news-pick` 단계를 완료 처리한다.

1~3장에는 보이는 출처 footer를 반복하지 않는다. 마지막 카드의 `source_block`에만 사용한 모든 근거의 출처명·날짜·도메인을 모은다. 전체 URL과 locator는 storyboard, caption과 manifest에도 보존한다.

## 3단계 — 편집과 이미지

`create-news-cards`에는 승인된 storyboard와 명시적으로 확인한 `1024x1024` 크기를 전달한다. 첫 실행에서만 사용자에게 이 크기를 확인하고 이후 같은 계정 preset에서는 재사용한다.

- 원문 기사 대표 사진과 공식 발표·공시 화면을 Browser Harness로 확보하고 URL·로컬 경로·SHA-256을 기록
- 기본 4장: 비주얼 방향 3개 × 4장 = 완성 후보 12장
- 프로젝트 어댑터 한 명령에서 단일 이미지 job 12개를 동시에 실행
- 모델이 한글 카피·숫자·차트까지 포함한 최종 카드를 생성하고 코드는 QA에만 사용
- 낱장이 아니라 완결된 방향 세트로 선택
- 한글·수치·차트 오류가 있는 장만 모델로 재생성
- 카드마다 고유한 `visual_role`과 서로 다른 첫 reference를 사용
- 생성 뒤 exact/near duplicate 자동 검사와 동일 인물·장면·crop 반복 육안 검사

출력:

```text
03-create/candidates/
03-create/contact-sheets/
03-create/selection.json
03-create/slides/01.png ... 04.png
03-create/visual-manifest.json
03-create/duplicate-qa.json
03-create/qa-report.json
```

12장 후보가 모두 존재하고 최종 4장이 크기·가독성·한글·수치·차트·출처 QA를 통과하며 `duplicate-qa.json.passed=true`, 의미상 중복 육안 검수 통과, `pixel_modification=false`인 뒤 `create-news-cards` 단계를 완료 처리한다.

## 4단계 — 업로드

`publish-news-pick`에 최종 slides, caption, run의 설정 계정, 게시 시각을 전달한다. run의 `account`, `IG_ACCOUNT`, 실제 로그인 계정이 모두 같아야 한다. caption에 `AI로 재구성한 인포그래픽` 계열 문구가 없어야 하며, AI 공개 표시는 Instagram `AI 콘텐츠` 라벨로 처리한다. 수동 모드는 payload hash를 사람에게 보여주고 건별 승인받는다. 예약 모드는 아래 standing approval 범위 안에서 모든 QA를 통과한 exact payload hash를 잠근 뒤 회차당 한 번 승인한다.

제출 후 오류나 timeout은 자동 재시도하지 않는다. `needs_review`에서 프로필을 읽기 전용으로 확인한다. private API 응답만으로 완료하지 말고 공개 프로필에서 shortcode, 카드 장수, 첫 장, caption을 검증한다.

```text
04-publish/publish-job.json
04-publish/attempts.jsonl
04-publish/result.json
```

`result.status=published`와 `public_verified=true`일 때만 전체 run을 완료한다.

## 자동 게시 차단

다음 중 하나면 즉시 멈춘다.

- 검증되지 않은 유출·루머·사생활, 선거 결과 또는 충돌하는 근거
- 미성년자·피해자 식별, 잔혹 이미지, 개인화 투자·의료 조언
- 후킹에 근거 없는 명사·동사·숫자·최상급이 있음
- reference에 없는 실제 인물·사건·문서·통계를 생성물이 새로 묘사함
- 출처·기준시각·정정 경로 누락 또는 caption에 금지된 `AI로 재구성한 인포그래픽` 문구가 남음
- 사실적 AI 재구성 게시물의 Instagram `AI 콘텐츠` 라벨 누락
- 마지막 카드의 전체 출처 블록 누락 또는 판독 불가
- exact/near duplicate 또는 같은 인물·사건 사진·공식 화면의 유사 crop 반복
- 이미지 QA 실패 또는 payload 변경으로 승인 hash 불일치

운영 정책은 [references/operating-policy.md](references/operating-policy.md)를 읽는다.

## 예약 무인 실행

사용자가 `07:00`, `12:00`, `17:00` KST 자동 게시를 승인한 계정에서는 [references/operating-policy.md](references/operating-policy.md)의 standing approval을 적용한다. 다음 명령은 prompt를 생성하고 Codex 비대화형 실행을 한 회차만 시작한다.

```powershell
python scripts/scheduled_runner.py --slot 07:00 --dry-run
python scripts/scheduled_runner.py --slot 07:00
```

Windows 예약 작업은 다음으로 관리한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 remove
```

예약 실행은 `output/scheduler/editions/<date>-<slot>.json`을 idempotency key로 사용한다. state가 한 번 생긴 회차, 시작 시각에서 30분 넘게 지난 회차, 다른 회차가 실행 중인 경우에는 새 게시를 시작하지 않는다. `needs_review`와 제출 뒤 오류를 자동 재시도하지 않는다. Windows 사용자가 로그인되어 있고 전용 Chrome profile의 세션을 사용할 수 있을 때만 동작하며, 컴퓨터가 꺼져 있던 회차는 나중에 몰아서 게시하지 않는다. 자세한 고정 prompt와 결과 schema는 `scripts/scheduled_runner.py`와 `references/scheduled-result.schema.json`을 사용한다.

## 완료 보고

최종 보고에는 선택한 사건, 출처 수, 카드 장수, 선택한 비주얼 방향, payload hash 앞 12자리, Instagram URL, 공개 검증 결과, 남은 경고만 포함한다. cookie, sessionid, Authorization, 전체 private client settings는 출력하지 않는다.
