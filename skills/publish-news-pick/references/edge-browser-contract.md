# 뉴스픽 Edge Browser Harness 계약

뉴스픽의 모든 웹 상호작용은 다음 하나의 로컬 브라우저 연결만 사용한다.

- 브라우저: Microsoft Edge
- Browser Harness named connection: `edge9333`
- CDP URL: `http://127.0.0.1:9333`
- user data dir: `%LOCALAPPDATA%\NewsPick\EdgeProfile`
- Edge profile directory: `Default`

Chrome, Chromium, Browser Harness `default`, 다른 named connection, 원격 CDP, 확장 프로그램 제어, `computer-use`는 이 스킬의 대체 경로가 아니다. `scripts/edge_browser.py`는 `/json/version`의 product가 `Edg/` 또는 `MicrosoftEdge/`인지 확인한다. 다른 브라우저가 9333 포트를 점유하거나 환경변수가 고정값과 다르면 변경 동작 전에 실패한다.

최초 실행 또는 Edge가 닫힌 경우에만 다음 launcher를 실행한다.

```powershell
python scripts/launch_edge_profile.py --account $env:IG_ACCOUNT
```

비밀번호, MFA, CAPTCHA, challenge는 사용자가 표시형 Edge에서 직접 완료한다. cookie와 session 문자열은 출력하거나 파일에 저장하지 않는다.

## Excel Collector fast-path 적용

`cafe24-excel-collector`의 빠른 실행 계약과 같은 원칙을 적용한다.

1. `scripts/invoke_edge_browser_harness.py`가 실제 Harness target의 `Browser.getVersion` Edge guard와 browser script의 UTF-8 원본 바이트를 Browser Harness 프로세스 하나에 전달한다.
2. 하나의 bounded phase 안에서 target 선택, targeted DOM 판독, 필요한 UI 조작, 완료 검증을 묶는다.
3. 전체 DOM·전체 AX tree·반복 screenshot 탐색을 기본 경로로 사용하지 않는다. 고정 selector와 작은 allowlist 결과를 우선한다.
4. 고정 sleep 대신 상태가 준비되는 즉시 끝나는 짧은 polling을 사용한다.
5. 독립 조회와 제출 전 preflight는 background target에서 수행하고 `document.hasFocus() is False`를 확인한다.
6. 사용자가 승인한 웹 UI 게시가 성공한 직후의 캐러셀 공개 검증만 예외다. `browser_web_verify_carousel.py`는 같은 승인 거래 안에서 공유에 사용한 전용 Instagram target 하나를 읽기 전용으로 재사용해 정확한 permalink와 `?img_index=1..N`만 탐색할 수 있다. 이 예외에서는 작성·수정·공유 control을 누르지 않으며, 다른 target을 만들거나 닫거나 탐색하지 않는다.
7. 그 밖의 사용자가 열어 둔 기존 target은 닫거나 다른 URL로 탐색하지 않는다. 작업용으로 만든 background target만 닫는다.

Instagram 변경 동작은 속도보다 정확히 한 번 실행되는 계약이 우선이다. 작성 화면의 단계 전환에는 짧은 random jitter를 두되, 장시간 사람 흉내 지연이나 카드별 별도 Harness 호출은 사용하지 않는다. `공유하기`는 최대 한 번이며 결과가 모호하면 재클릭하지 않는다.

웹 작성 단계의 기본 속도는 의미 있는 클릭 사이 `0.22~0.48초`, 준비 상태 polling `0.22~0.42초`, 공유 성공 polling `0.35~0.65초`다. DOM이 이미 준비되면 즉시 다음 상태로 넘어가되 zero-delay 연속 클릭은 만들지 않는다.

변경 helper는 `switch_tab(..., activate=True)` 또는 `Target.activateTarget`으로 writable target을 명시적으로 활성화한다. 현재 Browser Harness의 단순 `switch_tab(target)`은 attach만 하고 전면 활성화하지 않을 수 있다. 작성 화면 증거 screenshot은 활성 target에서 저용량 JPEG(`Page.captureScreenshot`, quality 72)를 우선해 PNG 캡처 timeout을 줄인다.

preflight는 `IG_DUPLICATE_TOKENS`가 있으면 계정·소유자 control·login/challenge와 최근 게시물 중복을 한 background Harness phase에서 함께 판정한다. 모델-브라우저 왕복이나 중복 전용 프로세스를 추가하지 않는다.

각 browser script는 다음처럼 실행한다.

```powershell
python scripts/invoke_edge_browser_harness.py scripts/browser_web_preflight.py
```

예약 실행기는 `BU_NAME`, `BU_CDP_URL`, `NEWS_PICK_BROWSER`를 위 값으로 주입한다. 개별 스킬이나 하위 프로세스가 이를 덮어쓸 수 없다.
