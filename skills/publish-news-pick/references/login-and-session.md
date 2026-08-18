# 로그인과 세션 준비

## 필요한 것

- Windows·macOS·Linux의 표시형 Chrome
- `NEWS_PICK_CHROME_PROFILE`로 지정한 전용 profile
- 그 profile에 사용자가 직접 로그인한 `IG_ACCOUNT`
- 같은 profile에 열린 `https://www.instagram.com/<IG_ACCOUNT>/` 탭 하나
- 동작하는 Browser Harness 기본 연결
- 안정적인 네트워크
- 게시할 1024×1024 PNG 3~4장, caption, 승인된 payload hash

전용 profile 창이 없으면 portable launcher로 표시형 Chrome을 연다.

```powershell
$env:IG_ACCOUNT = 'newspick_studio'
$env:NEWS_PICK_CHROME_PROFILE = 'Profile 3'
python scripts/launch_chrome_profile.py --profile $env:NEWS_PICK_CHROME_PROFILE --account $env:IG_ACCOUNT
```

사용자가 그 창에서 로그인·MFA·challenge를 직접 끝낸다. 에이전트는 password, 인증 코드, CAPTCHA를 입력하거나 요청하지 않는다.

## 웹 UI 경로의 쿠키 정책

웹 UI 게시에는 cookie 문자열을 따로 준비할 필요가 없다. 설정된 Chrome profile에 저장된 로그인 세션을 Chrome이 요청마다 자동 전송한다. Browser Harness는 로그인된 탭을 제어할 뿐 cookie를 추출·복사·출력·파일 저장하지 않는다.

다음 값은 웹 UI 경로에 필요하지 않다.

- Instagram password 또는 앱 비밀번호
- `sessionid`, `csrftoken`, `mid`, `ig_did`의 수동 복사
- cookie export 확장 프로그램
- Authorization header 또는 private client settings

시크릿 창이나 다른 Chrome profile에 로그인해도 설정된 전용 profile 세션에는 적용되지 않는다. Chrome 재시작 뒤에도 같은 `NEWS_PICK_CHROME_PROFILE`로 연다.

## 로그인 준비 완료 판정

`scripts/browser_web_preflight.py`를 Browser Harness에 전달한다.

```powershell
browser-harness < scripts/browser_web_preflight.py
```

다음이 모두 참이어야 한다.

- Instagram page target이 정확히 하나
- URL이 `IG_ACCOUNT` 프로필
- 프로필에 설정 계정이 보이고, 소유자 전용 control인 `프로필 편집`·`보관함 보기`·`프로페셔널 대시보드` 중 하나 이상이 보임
- `새로운 게시물` control이 보임
- `/accounts/login`, `/challenge`, `/checkpoint`가 아님

로그인 화면·challenge·계정 전환 화면이면 멈추고 사용자에게 설정된 profile에서 직접 완료해 달라고 요청한다. 로그인했다고 말한 것만으로 준비 완료로 간주하지 말고 위 화면 상태로 확인한다.

Instagram은 background target에서 `프로필 편집`과 `보관함 보기`를 생략하거나 본인 프로필 control을 늦게 렌더링할 수 있다. preflight는 최대 15초 동안 재확인하며, 일반 로그인 사용자에게도 보이는 `새로운 게시물`만으로 계정 소유권을 판정하지 않는다. 위 소유자 전용 control 중 하나와 설정 계정명이 함께 확인되어야 통과한다.

## 선택적 private API의 cookie

private API 경로만 Instagram 도메인의 `sessionid`가 필요하다. 구현은 Browser Harness 프로세스 메모리에서 기존 탭의 cookie를 읽어 `Client.login_by_sessionid()`에 한 번 전달하고 즉시 참조를 버린다.

- 값을 로그·JSON·환경변수·파일·클립보드에 남기지 않는다.
- 사용자의 browser session과 private client account가 모두 `IG_ACCOUNT`인지 다시 확인한다.
- visible browser login이 성공해도 private API session은 `login_required`로 거부될 수 있다.
- private API 실패는 browser cookie가 없다는 뜻이 아니다. 웹 UI 로그인을 별도로 검사한다.
- 비공식 API는 계정 위험이 있으므로 사용자가 별도 승인하지 않으면 실행하지 않는다.

cookie가 만료됐으면 에이전트가 우회하거나 갱신하지 않는다. 사용자가 설정된 profile에서 다시 로그인한 뒤 preflight부터 다시 시작한다.
