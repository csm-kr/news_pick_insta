# Edge DOM 오류 점검과 스킬 갱신

`multiple file input was not found`, exact control 누락, 작성 단계 전환 실패 때만 읽는다. 뉴스픽은 Microsoft Edge `edge9333` / `http://127.0.0.1:9333`을 유지한다. Chrome, default Harness, 다른 포트로 원인을 우회하지 않는다.

## 먼저 증거를 보존한다

1. 실패한 run·queue job·`attempts.jsonl`의 시각, 단계, `submission_started`를 확인한다. 다른 run이 작성기를 소유하면 클릭·탐색·draft 폐기를 하지 않는다.
2. `공유하기`를 눌렀거나 제출 여부가 불명확하면 `needs_review`로 두고 공개 프로필만 확인한다. 업로드 helper를 재실행하지 않는다.
3. 제출 전 오류는 기존 전용 Instagram target을 그대로 둔 채 아래 읽기 전용 진단을 실행한다. 진단은 탭 활성화·탐색·클릭·쿠키 접근을 하지 않으며, Instagram target이 하나가 아니면 중단한다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = (Resolve-Path ./output).Path
$env:IG_DOM_DIAGNOSTIC_PATH = '<run-directory>/04-publish/dom-diagnostic.json'
python skills/publish-news-pick/scripts/invoke_edge_browser_harness.py skills/publish-news-pick/scripts/browser_web_dom_probe.py --timeout 60
```

설치본을 실행하는 환경에서는 두 script 경로를 설치본의 절대 경로로 바꾼다. 증거에는 Edge product, target ID, 허용된 control의 exact 이름·role·가시 영역·hit-test, dialog 상태, file input의 `multiple/accept/disabled`만 남긴다. 전체 DOM/AX dump, 쿠키, 입력값, DM, 계정 목록을 수집하지 않는다. 추가 판독이 꼭 필요하면 해당 dialog/해당 control만 좁혀 확인하고, 시각 증거는 JPEG quality 72를 우선한다.

## 결과를 구분한다

- **작성창 없음:** `새로운 게시물` control이 존재해도 클릭 성공 증거는 아니다. `dialog_count=0`이면 렌더링·클릭·가림 여부를 확인한다. 반복 클릭, JavaScript `.click()`, 임의 `/create/select/` 이동으로 우회하지 않는다.
- **작성창 로딩:** exact `새 게시물 만들기` dialog가 나타났으나 다중 input이 아직 없으면 같은 클릭 뒤 최대 총 20초까지만 상태를 기다린다. 기존 helper의 8초를 무조건 늘리거나 새로 클릭하지 않는다.
- **구조 변경 후보:** 로딩 한도 후에도 dialog 안 input이 없거나 `multiple=false`뿐이면 DOM 증거와 현재 helper를 대조한다. selector를 `input[type=file]`로 넓히지 않는다. 실제 관찰한 새 구조에만 좁은 수정과 회귀 테스트를 추가한다.
- **이미 crop 단계:** `자르기`·`다음`·갤러리/5개 dot이 확인되면 React의 input 제거는 정상일 수 있다. 재업로드하지 않고 기존 crop 상태를 검수한다.
- **인증 경계:** login/challenge/checkpoint이면 대기·우회를 멈추고 사용자가 Edge에서 직접 처리하게 한다.
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
