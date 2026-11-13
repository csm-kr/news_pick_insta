# DOM 오류 점검과 스킬 갱신

`multiple file input was not found`, exact control 누락, 작성 단계 전환 실패 때만 읽는다. 뉴스픽은 ego lite만 쓴다. Chrome, default Harness, ego-browser 직접 스크립트로 원인을 우회하지 않는다.

## 먼저 증거를 보존한다

1. 실패한 run·queue job·`attempts.jsonl`의 시각, 단계, `submission_started`를 확인한다. 다른 run이 작성기를 소유하면 클릭·탐색·draft 폐기를 하지 않는다.
2. `공유하기`를 눌렀거나 제출 여부가 불명확하면 `needs_review`로 두고 공개 프로필만 확인한다. 업로드 helper를 재실행하지 않는다.
3. 제출 전 오류는 기존 전용 Instagram target을 그대로 둔 채 아래 읽기 전용 진단을 실행한다. 진단은 탭 활성화·탐색·클릭·쿠키 접근을 하지 않으며, Instagram target이 하나가 아니면 중단한다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = (Resolve-Path ./output).Path
$env:IG_DOM_DIAGNOSTIC_PATH = '<run-directory>/04-publish/dom-diagnostic.json'
python skills/publish-news-pick/scripts/invoke_edge_browser_harness.py skills/publish-news-pick/scripts/browser_web_dom_probe.py --timeout 60
```

설치본을 실행하는 환경에서는 두 script 경로를 설치본의 절대 경로로 바꾼다. 증거에는 브라우저 product(`ego-lite/`), target ID, 허용된 control의 exact 이름·role·가시 영역·hit-test, dialog 상태, file input의 `multiple/accept/disabled`만 남긴다. 전체 DOM/AX dump, 쿠키, 입력값, DM, 계정 목록을 수집하지 않는다. 추가 판독이 꼭 필요하면 해당 dialog/해당 control만 좁혀 확인하고, 시각 증거는 JPEG quality 72를 우선한다.

## 결과를 구분한다

- **작성창 없음:** `새로운 게시물` control이 존재해도 클릭 성공 증거는 아니다. `dialog_count=0`이면 렌더링·클릭·가림 여부를 확인한다. 반복 클릭, JavaScript `.click()`, 임의 `/create/select/` 이동으로 우회하지 않는다.
- **작성창 로딩:** exact `새 게시물 만들기` dialog가 나타났으나 다중 input이 아직 없으면 같은 클릭 뒤 최대 총 20초까지만 상태를 기다린다. 기존 helper의 8초를 무조건 늘리거나 새로 클릭하지 않는다.
- **구조 변경 후보:** 로딩 한도 후에도 dialog 안 input이 없거나 `multiple=false`뿐이면 DOM 증거와 현재 helper를 대조한다. selector를 `input[type=file]`로 넓히지 않는다. 실제 관찰한 새 구조에만 좁은 수정과 회귀 테스트를 추가한다.
- **이미 crop 단계:** `자르기`·`다음`·갤러리/5개 dot이 확인되면 React의 input 제거는 정상일 수 있다. 재업로드하지 않고 기존 crop 상태를 검수한다.
- **인증 경계:** login/challenge/checkpoint이면 대기·우회를 멈추고 사용자가 ego lite 창에서 직접 처리하게 한다.
- **공개 프로필의 로그인 안내:** 프로필 URL과 게시물은 읽혀도 화면에 보이는 dialog 안에 exact `로그인`과 `가입하기` action이 함께 있으면 인증 경계다. 비밀번호 input이나 `/accounts/login` 이동이 없어도 preflight는 `login_wall=true`, `authentication_reason=instagram_login_required`로 반환한다. 숨은 dialog나 게시물 본문 속 로그인 단어는 이 판정에 포함하지 않는다. 인증을 대신 처리하거나 ready 조건을 낮추지 않는다.
- **caption은 맞고 AI switch만 꺼짐:** 이미 일치하는 caption을 재입력하거나 업로드를 반복하지 않는다. [web-ui-carousel.md](web-ui-carousel.md)의 공유 전 AI switch 복구에 따라 해당 dialog의 label·단일 switch·checked·가시 영역·hit-test만 추가 판독한다. 첫 클릭의 내부 실패 원인을 추측하지 않으며 최대 한 번 복구 뒤에도 켜짐이 확인되지 않으면 공유하지 않는다.

2026-09-05 12시 실행은 `create_dialog_unavailable`로 제출 전 취소되었다. 같은 날 17:48 KST Edge `Edg/152.0.4191.62` 실측에서는 create를 한 번 누른 뒤 dialog가 먼저 보이고, 후속 판독에서 dialog 내부 `input[type=file][multiple]`과 `컴퓨터에서 선택`이 확인됐다. 따라서 당시 실패를 DOM selector 변경으로 단정하지 않는다. 17시 실행의 이미지 backend HTTP 400은 별개 오류이며 DOM 수정으로 해결됐다고 보고하지 않는다.

## 소스 수정 → 테스트 → 설치본 갱신

1. 현재 실행 파일 경로와 저장소/설치본 SHA-256을 비교한다. run-local 우회 helper를 정식 해결책으로 남기지 않는다.
2. 저장소 `skills/publish-news-pick/`의 해당 helper·회귀 테스트·이 참조를 수정한다. 무관한 사용자 변경, 승인 hash, 제출 이력은 보존한다.
3. 지연 렌더링, dialog 부재, 인증 경계, 이미 열린 crop의 무재업로드를 테스트한다.

```powershell
python -m unittest discover -s skills/publish-news-pick/scripts -p 'test_*.py'
python scripts/bootstrap.py install --update-existing --skills-dir "$HOME/.codex/skills"
Get-FileHash skills/publish-news-pick/scripts/browser_web_upload_prepare.py
Get-FileHash "$HOME/.codex/skills/publish-news-pick/scripts/browser_web_upload_prepare.py"
```

bootstrap은 기존 뉴스픽 pack을 백업한 뒤 함께 갱신한다. 실제 설치 경로가 다르면 `--skills-dir`에 그 경로를 명시한다. 활성 게시 executor와 겹치는 동안에는 설치하지 않는다. 테스트 통과, 설치본 hash 일치, 설치본 읽기 전용 진단까지 확인해야 갱신 완료다. 코드 테스트와 실제 게시 성공은 별개로 보고한다. exact payload 승인을 새로 받기 전에는 공유하지 않는다.

## 클릭이 화면에 닿지 않을 때 (2026-09-12 실측)

2026-09-11 밤 수동 run에서 `create_dialog_unavailable`가 세 번 연속 났다. 라이브 관찰에서 두 가지가 확인됐다.

- 스토리 뷰어 탭에서 프로필로 막 이동한 직후에는 `새로운 게시물` 라벨이 계정 프로필 링크(`href=/<account>/`)에 붙어 후보 목록 앞에 나온다. 그 후보를 누르면 프로필로 이동만 하고 작성 dialog는 열리지 않는다. `click_named_control`은 이제 계정 프로필 href를 가진 후보를 항상 뒤로 민다.
- 좌표 클릭 자체는 브라우저 줌이 올라가 있어도 정확히 도달한다. 빈 탭과 Instagram 탭에서 보낸 좌표와 페이지가 받은 `clientX/clientY`가 일치했다. 반면 `Emulation.setDeviceMetricsOverride`로 레이아웃 폭을 넓힌 상태에서는 같은 좌표 클릭이 도달하지 않았다. 폭을 넓히려고 override를 걸지 않는다.

그래서 `browser_web_upload_prepare.py`와 `browser_web_share_once.py`는 좌표 클릭 뒤 상태를 한 번 확인하고, 아무 변화가 없을 때만 같은 좌표로 합성 포인터 시퀀스를 한 번 더 보낸다. 공유는 `공유하기` control이 같은 자리에 그대로 남아 있을 때만 보강하고, control이 사라졌으면 다른 주체가 이미 제출했을 수 있으므로 다시 누르지 않고 성공 표지만 확인한다(`submission_already_started`). 두 보강 모두 한 번뿐이며 결과 JSON의 `reinforced_with_pointer_sequence`로 남는다.

사이드바가 좁아지는 레이아웃(실측 855~933px)에서도 `새로운 게시물` 컨트롤 자체는 `href="#"`로 존재한다. 좁다는 이유만으로 줌 조정을 요구하기 전에 후보 목록과 href를 먼저 읽는다.

## AI 라벨 switch의 hit-test (2026-09-12)

2026-09-12 07:00 회차는 `ensure_ai_label`이 `hit_matches=false`로 클릭을 한 번도 시도하지 못한 채 멈췄다. switch는 `visible=true`, `disabled=false`인데 `elementFromPoint(중심좌표)`가 그 요소도 자식도 아닌 형제를 돌려줬다. Instagram의 toggle이 숨은 `input` 위에 렌더 요소를 덮는 구조이기 때문이며, 그 형제는 같은 toggle 래퍼 안에 있으므로 좌표 클릭은 toggle에 도달한다.

그래서 `hit_matches`는 `element.parentElement.contains(hit)`까지 인정한다. 래퍼 밖의 다른 오버레이가 찍히면 여전히 `false`이고 클릭하지 않는다. 회귀 테스트는 Node DOM fixture의 `sibling` 케이스다. 이 판정을 더 넓히지 않는다.
