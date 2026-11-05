---
name: upload-news-pick
description: 공개 반응이 큰 한국 종합 이슈를 최근 48시간에서 우선 탐색·검증하고, 하단 그라데이션 사진 표지·줄글+이미지+표 본문 3장·출처 카드의 1080×1350 다섯 장으로 제작해 게시하는 portable 전체 오케스트레이터. 뉴스픽 제작, 네 단계 일괄 실행, 중단된 run 재개, 07·12·17시 예약 게시에 사용한다.
---

# Upload News Pick

하나의 `run_id` 아래 네 전문 스킬을 순서대로 연결한다. 이 스킬은 각 단계의 일을 직접 대신하지 않고 입력·출력 계약, hash, 중단·재개와 게시 승인 경계만 관리한다.

실행 전 [references/portable-layout.md](references/portable-layout.md)와 [../publish-news-pick/references/edge-browser-contract.md](../publish-news-pick/references/edge-browser-contract.md)를 읽고 다섯 스킬이 같은 부모 폴더에 설치됐는지 확인한다. skill 폴더는 읽기 전용으로 유지하고 모든 실행물은 별도 `NEWS_PICK_OUTPUT_ROOT` 아래에 쓴다. 뉴스픽의 모든 웹 상호작용은 `invoke_edge_browser_harness.py`로만 실행한다. 기본은 Microsoft Edge `edge9333`이고, 예약 게시(07·12·17시)는 실행기가 `NEWS_PICK_BROWSER=ego`를 주입해 ego lite로 간다. Chrome/default/다른 CDP로 대체하지 않는다.

## 고정 구성

1. `../search-news/SKILL.md`: 뉴스 발견·영향도 평가·교차검증
2. `../plan-news-pick/SKILL.md`: 후킹 후보·5장 스토리보드·편집 QA
3. `../create-news-cards/SKILL.md`: 실제 기사·공식 화면 reference 수집, 10개 디렉터 풀의 Tibo 후보 15장, 세트 선택·시각 QA
4. `../publish-news-pick/SKILL.md`: 불변 캐러셀 payload·승인·실게시·공개 확인

단계를 실행하기 직전에 해당 전문 스킬의 `SKILL.md`를 완전히 읽고 따른다. 한 단계의 출력 검증이 끝나기 전에 다음 스킬을 호출하지 않는다.

## 시작과 재개

새 실행은 다음으로 만든다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = '<workspace>/output'
python scripts/orchestrate.py init --output-root $env:NEWS_PICK_OUTPUT_ROOT --edition-at <ISO-8601> --account <instagram-account>
```

수동 요청은 항상 새 `run_id`로 만든다. 같은 회차의 예약 실행이 이미 있어도 그 run 디렉터리나 산출물을 재사용하지 않는다. Instagram 변경 동작 직전 모든 `run.json`을 다시 확인하고, 다른 run이 `status=in_progress`, `current_stage=publish-news-pick`이면 작성기를 건드리거나 열린 draft를 폐기하지 않는다. 사용자가 수동 즉시 게시를 명시해 예약 실행을 중단해야 하는 경우에도 정확한 예약 executor만 확인해 중단하고 그 run의 파일은 보존한다.

중단된 executor가 종료됐는데 run만 `in_progress`로 남았다면 산출물을 삭제하거나 직접 JSON을 편집하지 말고 `python scripts/orchestrate.py cancel-run --run <run-directory> --reason <reason>`으로 닫는다.

이 명령은 `<output-root>/runs`, `publish-news-pick`, `profile-candidates`, `cache`, `logs`를 만들고 run은 `<output-root>/runs/<run_id>`에 둔다. 기존 실행은 먼저 상태를 읽는다.

```powershell
python scripts/orchestrate.py status --run <run-directory>
```

입력 hash가 기존 완료 기록과 같으면 완료 단계를 다시 실행하지 않는다. 앞 단계 산출물이 바뀌면 그 뒤 단계 기록과 승인은 폐기하고 해당 단계부터 다시 시작한다. 자세한 계약은 [references/workflow-contract.md](references/workflow-contract.md)를 읽는다.

## 1단계 — 뉴스 검색

`search-news`에 `edition_at`, `timezone=Asia/Seoul`, 직전 성공 체크포인트를 전달한다. 출력은 반드시 다음 위치에 둔다.

07:00은 `entertainment`, 12:00은 `hot_news_week`(최근 7일 핫뉴스), 17:00은 `hot_news_3day`(최근 3일 핫뉴스)를 고정 editorial lane으로 전달한다(2026-10-14 사용자 지시). 단 2026-09-27~10-02(사용자 지시로 폐막 전 조기 종료)의 07:00은 `asian_games`로 바꿔 한국 선수단의 확정 결과·기록 사건을 다루고, 적격 사건이 없으면 `entertainment` 기준으로 대체한다(`scheduled_runner.py`의 `ASIAN_GAMES_FIRST_DAY`·`ASIAN_GAMES_LAST_DAY`). 07시는 `edition_at` 직전 48시간, 12시는 7일, 17시는 3일을 기본 탐색창으로 사용한다. 회차 안에 막 발행된 약한 기사보다 하루 전이라도 공개 반응·보도 확산·대화 열기가 큰 검증 사건을 우선한다. 적격 사건 최소 3건의 `reaction_score`와 서로 다른 유형의 `reaction_signals` 2개 이상을 비교하고 최신성은 마지막 동점 해소에만 쓴다. `output/runs`의 최근 공개 검증 게시물 6건을 함께 확인해 같은 사건과 연속 주제를 피한다. 07시 `entertainment`는 검증된 연예·방송·영화·음악 산업 뉴스만 다루고 사생활·루머·자극적 범죄 소비를 제외한다. 연예 watchlist(`scheduled_runner.py`의 `ENTERTAINMENT_WATCHLIST`, 현재 리센느)의 검증된 사건은 최우선 후보로 비교한다. 12시 `hot_news_week`는 분야 제한 없이 직전 7일, 17시 `hot_news_3day`는 분야 제한 없이 직전 3일 안에서 공개 반응·확산·대화 열기가 가장 큰 검증 사건을 다룬다. 정치·정책·재난·공공통계 사안은 공식 원문과 독립 언론 두 곳을 요구한다. 12시는 오늘 07시 사건을, 17시는 오늘 07·12시 사건을 제외한다. 핫뉴스 두 lane은 경찰·검찰·법원 발표 또는 독립 언론 두 곳으로 확인된 강력범죄 사건도 후보로 비교하되 피해자 신상·잔혹한 묘사·확정되지 않은 피의자 실명은 다루지 않는다.

07:00 `entertainment`는 48시간 검색창에서 적격 사건이 없다고 바로 건너뛰지 않는다. 전날, 이틀 전 순서로 하루씩 검색 범위를 넓혀 최대 30일을 역추적한다. 첫 적격 사건을 즉시 선택하지 말고 가능한 경우 서로 다른 검증 사건 3건을 모은 뒤 공개 반응, 대중 파급 범위, 확정 수치·결과의 크기, 여러 연령대의 대화 가치, 5장 설명력을 비교한다. 증거 완성도를 먼저 통과한 후보 중 반응과 임팩트가 가장 큰 사건을 선택하고, 발행일 최신성은 임팩트가 비슷할 때만 우선한다. 최근 공개 게시물과 같은 사건은 날짜가 달라도 제외하며, `selected-story.json.limitations`에 검색한 날짜 범위·반응 신호·후보 비교 근거를 남긴다.

```text
01-search/news-candidates.json
01-search/selected-story.json
```

`selected-story.json`이 `verified`가 아니거나 독립 언론 두 곳 및 필요한 공식 근거를 갖추지 못하면 run을 멈춘다. `entertainment`와 핫뉴스 lane은 `audience_fit` 네 항목 합계 8/12 이상이어야 한다. 연예 회차는 위 역추적·임팩트 비교를 끝내기 전 `no_publishable_story`로 종료하지 않는다. 그래도 target lane에 맞는 적격 사건이 없으면 다른 분야 filler로 채우지 않는다. 통과 후:

```powershell
python scripts/orchestrate.py complete-stage --run <run-directory> --stage search-news
```

## 2단계 — 후킹과 기획

`plan-news-pick`에는 1단계의 `selected-story.json`만 사실 입력으로 준다. 새 사실을 검색하거나 추가하게 하지 않는다. 출력:

```text
02-plan/editorial-plan.json
02-plan/storyboard.json
```

정확히 5장, hook의 근거 연결, 선택 hook 점수 11/14 이상, hard-fail 통과, 편집 점수 16/20 이상을 확인한 뒤 `plan-news-pick` 단계를 완료 처리한다.

1~4장에는 보이는 출처 footer를 반복하지 않는다. 5장의 `source_block`에만 사용한 모든 근거의 출처명·날짜·도메인을 모은다. 전체 URL과 locator는 storyboard, caption과 manifest에도 보존한다.

## 3단계 — 편집과 이미지

`create-news-cards`에는 승인된 storyboard와 사용자가 확인한 `1080x1350` 크기를 전달한다. 이 크기는 같은 계정의 기본 preset으로 재사용한다.

Tibo 작업은 `backend_size=1024x1536`, `resize_fit=cover`, `preserve_backend_raw=true`를 명시한다. 크기 선택은 요청값일 뿐 실제 backend 원본 크기를 잠그지 않으므로 raw와 최종 4:5 결과를 함께 검수한다. 패딩으로 글자와 사진이 작아지는 `contain`은 기본 제작에 쓰지 않는다. 중앙 crop으로 제목·본문·표·로고·핵심 사진이 손실되면 해당 카드만 탈락시키고, 통과한 같은 세트의 4:5 카드를 마지막 레이아웃 reference로 추가해 재생성한다. 그래도 같은 crop 손실만 반복되고 backend raw는 내용 QA를 모두 통과했을 때만 1장에 한해 배경색 매칭 좌우 contain 폴백을 검수할 수 있다. 띠 경계가 보이거나 360px 가독성·세트 리듬이 낮아지면 실패이며, manifest에 raw·최종 sha256, 패딩 색, `fallback_reason=repeated_cover_crop_loss`를 남긴다.

- 원문 기사 대표 사진과 공식 발표·공시 화면을 고정 Edge Browser Harness 연결로 확보하고 URL·로컬 경로·SHA-256을 기록
- 10개 디렉터 풀에서 3개를 시드 기반 무작위 선택: 3개 × 5장 = 완성 후보 15장
- 1장은 실제 사진 전면+하단 그라데이션 표지, 2~4장은 줄글+실제 이미지+표, 5장은 출처 전용
- 프로젝트 어댑터 한 명령에서 단일 이미지 job 15개를 동시에 실행
- 모델이 한글 카피·숫자·표까지 포함한 최종 카드를 생성하고 코드는 QA에만 사용
- 낱장이 아니라 완결된 방향 세트로 선택
- 한글·수치·표 오류가 있는 장만 모델로 재생성
- 카드마다 고유한 `visual_role`과 서로 다른 첫 reference를 사용
- 생성 뒤 exact/near duplicate 자동 검사와 동일 인물·장면·crop 반복 육안 검사

출력:

```text
03-create/candidates/
03-create/contact-sheets/
03-create/selection.json
03-create/slides/01.png ... 05.png
03-create/visual-manifest.json
03-create/duplicate-qa.json
03-create/qa-report.json
```

15장 후보가 모두 존재하고 최종 5장이 1080×1350·360px 가독성·한글·수치·표·출처 QA를 통과하며 `duplicate-qa.json.passed=true`, 의미상 중복 육안 검수 통과, `pixel_modification=false`인 뒤 `create-news-cards` 단계를 완료 처리한다.

## 4단계 — 업로드

`publish-news-pick`에 최종 slides, caption, run의 설정 계정, 게시 시각을 전달한다. run의 `account`, `IG_ACCOUNT`, 실제 로그인 계정이 모두 같아야 한다. caption에 `AI로 재구성한 인포그래픽` 계열 문구가 없어야 하며, AI 공개 표시는 Instagram `AI 콘텐츠` 라벨로 처리한다. 업로드 자르기 단계에서는 입력이 1080×1350이어도 Instagram의 실제 `자르기 선택` control을 열어 exact `4:5`를 직접 선택하고, 첫 카드 상·하단 전체가 보이는 screenshot과 자연·렌더 비율 `0.78~0.82`를 확인해야 한다. 이 증거 없이 정방형 기본 crop 상태에서 `다음`으로 진행하면 hard fail이다. 수동 모드는 payload hash를 사람에게 보여주고 건별 승인받는다. 예약 모드는 아래 standing approval 범위 안에서 모든 QA를 통과한 exact payload hash를 잠근 뒤 회차당 한 번 승인한다.

공개 프로필 preflight에는 첫 카드의 안정적인 고유 토큰 2~3개를 `IG_DUPLICATE_TOKENS`에 `|`로 연결해 전달한다. `browser_web_preflight.py` 한 번에서 Edge 계정·소유자 control·로그인/challenge·최신 게시물 중복을 함께 확인한다. 별도 중복 확인용 Harness 프로세스를 다시 만들지 않는다. 업로드는 설치된 `browser_web_upload_prepare.py`를 사용하며, link wrapper 이름이 비어 있으면 자식 SVG의 exact create label을 쓴다. helper가 이미 열린 crop session을 확인한 뒤에는 React가 file input을 제거했어도 run-local helper를 만들거나 create·파일 선택을 반복하지 않는다.

제출 후 오류나 timeout은 자동 재시도하지 않는다. `needs_review`에서 프로필을 읽기 전용으로 확인한다. 예약 run에서 미게시가 확정되면 [operating-policy.md](references/operating-policy.md)의 미게시 복구 조건으로 회차당 한 번만 다시 공유한다. private API 응답만으로 완료하지 말고 공개 permalink의 `?img_index=1..5`에서 shortcode, 서로 다른 media source 5개, 각 주 이미지의 공개 4:5 자연·렌더 비율, 첫·마지막 장, caption, AI 라벨을 검증한다. 페이지 아래 추천 게시물 thumbnail은 본문 카드로 세지 않는다.

공개 검증 뒤 `publish-news-pick`의 `verify-published`에 `--run-dir <run-directory>`를 전달한다. 이 명령이 queue 결과와 `04-publish/result.json`을 같은 내용으로 기록하므로 수동 복사본을 만들지 않는다.

```text
04-publish/publish-job.json
04-publish/attempts.jsonl
04-publish/result.json
```

`result.status=published`, `public_verified=true`, `portrait_4x5=true`, `card_count=5`일 때만 전체 run을 완료한다.

## 자동 게시 차단

DOM/control 오류나 이전 게시 실패 점검을 요청받으면 `publish-news-pick`의 [DOM 점검·업데이트 절차](../publish-news-pick/references/dom-diagnostics-and-update.md)를 먼저 적용한다. 모든 진단도 Edge `edge9333`에 고정하며, 라이브 관찰 없이 selector 변경으로 단정하거나 run-local 우회 업로더를 만들지 않는다. 저장소와 실제 설치본을 함께 갱신·검증한 다음 정상 단계로 돌아온다.

다음 중 하나면 즉시 멈춘다.

- 검증되지 않은 유출·루머·사생활, 선거 결과 또는 충돌하는 근거
- 미성년자·피해자 식별, 잔혹 이미지, 개인화 투자·의료 조언
- 후킹에 근거 없는 명사·동사·숫자·최상급이 있음
- reference에 없는 실제 인물·사건·문서·통계를 생성물이 새로 묘사함
- 출처·기준시각·정정 경로 누락 또는 caption에 금지된 `AI로 재구성한 인포그래픽` 문구가 남음
- 사실적 AI 재구성 게시물의 Instagram `AI 콘텐츠` 라벨 누락
- Instagram `자르기 선택 → 4:5` 증거 누락, 공개 주 이미지 5장 중 하나라도 자연·렌더 비율이 `0.78~0.82` 밖임
- 마지막 카드의 전체 출처 블록 누락 또는 판독 불가
- 360px 폭에서 표지 제목·본문 줄글·표 셀·출처 행 중 하나라도 판독 불가
- exact/near duplicate 또는 같은 인물·사건 사진·공식 화면의 유사 crop 반복
- 이미지 QA 실패 또는 payload 변경으로 승인 hash 불일치

운영 정책은 [references/operating-policy.md](references/operating-policy.md)를 읽는다.

## 예약 무인 실행

사용자가 `07:00`, `12:00`, `17:00` KST 자동 게시를 승인한 계정에서는 [references/operating-policy.md](references/operating-policy.md)의 standing approval을 적용한다. 다음 명령은 prompt를 생성하고 Claude Code 비대화형 실행(`claude -p --output-format stream-json --dangerously-skip-permissions --json-schema …`)을 한 회차만 시작한다. prompt는 stdin으로 전달하고, 최종 응답은 `references/scheduled-result.schema.json`의 구조화 출력으로 받아 `output/scheduler/results/<slot>.json`에 저장한다.

```powershell
python scripts/scheduled_runner.py --slot 07:00 --dry-run
python scripts/scheduled_runner.py --slot 07:00
```

실행 파일은 `CLAUDE_EXECUTABLE` → PATH의 `claude` → `%USERPROFILE%\.local\bin\claude.exe` 순서로 찾고, `--json-schema`와 `--dangerously-skip-permissions`를 지원하는 버전만 사용한다. 모델과 effort는 기본값(`claude-fable-5-1`, `high`)을 쓰며 `NEWS_PICK_CLAUDE_MODEL`, `NEWS_PICK_CLAUDE_EFFORT`(low·medium·high·xhigh·max)로 바꾼다. `output/workspace.json`에 선택적 `imagegen` 블록(`auth_file`, `model`)을 두면 실행기가 `CODEX_IMAGEGEN_AUTH_FILE`/`CODEX_IMAGEGEN_MODEL`을 주입하고 prompt에 같은 `--imagegen-auth-file`/`--imagegen-model` 값을 명시한다. 이벤트 로그(`output/logs/scheduler/<slot>.jsonl`)는 stream-json이며 `claude_session_id`로 `claude --resume`할 수 있다.

공개 웹 조사는 `aside-browser`와 Aside CLI를 우선한다. 현재 운영 계정은 Aside의 Instagram 로그아웃을 확인하고 사용자에게 알린 뒤, 예약 게시는 ego lite 기본 프로필의 newspick_studio 세션을, 수동 Edge 경로는 뉴스픽 전용 Edge `edge9333` 로그인 세션을 쓴다.

Windows 예약 작업은 다음으로 관리한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_schedule.ps1 remove
```

Windows 작업은 각 회차 30분 전인 `06:30`, `11:30`, `16:30` KST에 준비를 시작한다. 검색·기획·이미지 생성·QA와 게시 직전 검증을 미리 끝내고, `scripts/wait_for_publish_time.py`가 목표 회차 시각까지 대기한 뒤에만 Instagram `공유하기`를 누른다. 매일 같은 초에 올라가 자동화로 보이지 않도록 `scheduled_runner.py`가 회차마다 1~15분 무작위 편차를 골라 `NEWS_PICK_PUBLISH_OFFSET_SECONDS`로 넘기고 게이트는 그만큼 더 기다린다. 카드의 기준시각과 30분 게시 창은 edition_at 기준 그대로다. 웹 UI 공유 스크립트도 목표 시각 전 클릭과 목표 시각 30분 뒤의 보충 게시를 코드로 차단한다.

예약 실행은 `output/scheduler/editions/<date>-<slot>.json`을 idempotency key로 사용한다. state가 한 번 생긴 회차, 목표 시각 30분 전보다 이른 실행, 목표 시각에서 30분 넘게 지난 실행, 다른 회차가 실행 중인 경우에는 새 게시를 시작하지 않는다. `needs_review`와 제출 뒤 오류를 자동 재시도하지 않는다. Windows 사용자가 로그인되어 있고 `%LOCALAPPDATA%\NewsPick\EdgeProfile`의 세션과 `edge9333` 연결을 사용할 수 있을 때만 동작하며, 컴퓨터가 꺼져 있던 회차는 나중에 몰아서 게시하지 않는다. 자세한 고정 prompt와 결과 schema는 `scripts/scheduled_runner.py`와 `references/scheduled-result.schema.json`을 사용한다.

## 완료 보고

최종 보고에는 선택한 사건, 출처 수, 카드 장수, 선택한 비주얼 방향, payload hash 앞 12자리, Instagram URL, 공개 검증 결과, 남은 경고만 포함한다. cookie, sessionid, Authorization, 전체 private client settings는 출력하지 않는다.
