# 뉴스픽 브라우저 계약 (기본 ego lite, 비상용 Edge)

2026-11-06부터 뉴스픽은 Microsoft Edge를 쓰지 않는다. 게시·스토리·팔로우·언팔·reference 캡처 모두 ego lite로 돈다. 파일 이름은 기존 링크 때문에 그대로 둔다.

- 기본 브라우저: ego lite (`NEWS_PICK_BROWSER`를 비우거나 `ego`)
- 실행기: `scripts/invoke_edge_browser_harness.py` → `scripts/ego_harness.py` → `scripts/ego_bridge.mjs`(`ego-browser nodejs`)
- TaskSpace: 게시·스토리 `newspick-instagram`, 팔로우·언팔 `newspick-growth`(작성기와 섞이지 않게 분리)
- 로그인: ego lite 기본 프로필의 newspick_studio Instagram 세션
- 필요한 것: `ego-browser` CLI(사용자 PATH `%USERPROFILE%\.local\share\ego\active_version_dir`), 실행 중인 ego lite

Chrome, Chromium, Browser Harness `default`, 원격 CDP, 확장 프로그램 제어, `computer-use`, ego-browser 직접 스크립트는 이 스킬의 대체 경로가 아니다. `NEWS_PICK_BROWSER`는 `ego`·`edge` 외의 값이면 변경 동작 전에 실패한다.

비밀번호, MFA, CAPTCHA, challenge는 사용자가 ego lite 창에서 직접 완료한다. cookie와 session 문자열은 출력하거나 파일에 저장하지 않는다.

### 비상용 Edge 경로

`NEWS_PICK_BROWSER=edge`를 명시할 때만 예전 Edge 경로(`edge9333`, `http://127.0.0.1:9333`, `%LOCALAPPDATA%\NewsPick\EdgeProfile`)를 쓴다. 이때만 `python scripts/launch_edge_profile.py --account $env:IG_ACCOUNT`로 Edge를 열고, `scripts/edge_browser.py`가 `/json/version`의 product가 `Edg/` 또는 `MicrosoftEdge/`인지 확인한다. 예약 작업은 이 경로를 쓰지 않는다.

## Excel Collector fast-path 적용

`cafe24-excel-collector`의 빠른 실행 계약과 같은 원칙을 적용한다.

1. `scripts/invoke_edge_browser_harness.py`가 브라우저 guard(ego는 `ego-lite/`, 비상용 Edge는 `Edg/`)를 먼저 확인하고 browser script의 UTF-8 원본을 helper 프로세스 하나에서 실행한다.
2. 하나의 bounded phase 안에서 target 선택, targeted DOM 판독, 필요한 UI 조작, 완료 검증을 묶는다.
3. 전체 DOM·전체 AX tree·반복 screenshot 탐색을 기본 경로로 사용하지 않는다. 고정 selector와 작은 allowlist 결과를 우선한다.
4. 고정 sleep 대신 상태가 준비되는 즉시 끝나는 짧은 polling을 사용한다.
5. 독립 조회와 제출 전 preflight는 background target에서 수행하고 `document.hasFocus() is False`를 확인한다.
6. 사용자가 승인한 웹 UI 게시가 성공한 직후의 캐러셀 공개 검증만 예외다. `browser_web_verify_carousel.py`는 같은 승인 거래 안에서 공유에 사용한 전용 Instagram target 하나를 읽기 전용으로 재사용해 정확한 permalink와 `?img_index=1..N`만 탐색할 수 있다. 이 예외에서는 작성·수정·공유 control을 누르지 않으며, 다른 target을 만들거나 닫거나 탐색하지 않는다.
7. 그 밖의 사용자가 열어 둔 기존 target은 닫거나 다른 URL로 탐색하지 않는다. 작업용으로 만든 background target만 닫는다.

Instagram 변경 동작은 속도보다 정확히 한 번 실행되는 계약이 우선이다. 작성 화면의 단계 전환에는 짧은 random jitter를 두되, 장시간 사람 흉내 지연이나 카드별 별도 Harness 호출은 사용하지 않는다. `공유하기`는 최대 한 번이며 결과가 모호하면 재클릭하지 않는다.

웹 작성 단계의 기본 속도는 의미 있는 클릭 사이 `0.22~0.48초`, 준비 상태 polling `0.22~0.42초`, 공유 성공 polling `0.35~0.65초`다. DOM이 이미 준비되면 즉시 다음 상태로 넘어가되 zero-delay 연속 클릭은 만들지 않는다.

변경 helper는 `switch_tab(..., activate=True)` 또는 `Target.activateTarget`으로 writable target을 명시적으로 활성화한다. 현재 Browser Harness의 단순 `switch_tab(target)`은 attach만 하고 전면 활성화하지 않을 수 있다. 작성 화면 증거 screenshot은 활성 target에서 저용량 JPEG(`Page.captureScreenshot`, quality 72)를 우선해 PNG 캡처 timeout을 줄인다.

이 활성화는 이전 Harness 호출에서 했다는 이유로 생략하지 않는다. 승인된 작성 화면이나 동일 거래 공개 검증을 새 프로세스에서 캡처할 때도 target 하나를 다시 선택·활성화한다. 2026-09-05 갤러리 캡처는 이 단계가 없는 호출에서 timeout이 났고 명시 활성화 후 같은 화면에서 성공했다. 캡처 실패는 파일 선택·AI toggle·공유의 실패 증거가 아니므로 변경 동작을 반복하지 않고 현재 상태부터 읽는다. 독립 읽기 전용 조회의 background 원칙은 유지한다.

preflight는 `IG_DUPLICATE_TOKENS`가 있으면 계정·소유자 control·login/challenge와 최근 게시물 중복을 한 background Harness phase에서 함께 판정한다. 모델-브라우저 왕복이나 중복 전용 프로세스를 추가하지 않는다.

각 browser script는 다음처럼 실행한다.

```powershell
python scripts/invoke_edge_browser_harness.py scripts/browser_web_preflight.py
```

예약 실행기(게시·스토리)는 `NEWS_PICK_BROWSER=ego`를 주입한다. 개별 스킬이나 하위 프로세스가 이를 덮어쓸 수 없다.

## ego lite 구현 메모

ego lite는 원격 디버깅 포트를 열지 않아 Browser Harness가 붙을 수 없다. 그래서 helper가 쓰는 Browser Harness 함수는 그대로 두고 전송만 ego로 바꿨다. helper 스크립트는 수정 없이 돈다.

- `scripts/ego_harness.py`: Browser Harness helper(`cdp`, `js`, `click_at_xy`, `switch_tab`, `_send` 등)를 같은 이름으로 제공하고, 전송만 ego로 바꾼다. 실행 전 `Browser.getVersion`이 `ego-lite/`인지 확인한다.
- `scripts/ego_bridge.mjs`: `ego-browser nodejs` 안에서 TaskSpace `newspick-instagram`을 열고 loopback TCP로 `page.cdp`·`task.cdp`·탭 조작만 중계한다. 10분 동안 요청이 없으면 스스로 종료한다.
- target·session은 ego Page 라벨(`p1`, `p2` …)로 바뀐다. `Target.getTargets`는 이 TaskSpace의 탭만 돌려주므로, 사용자가 ego에서 따로 연 Instagram 탭은 계산에 들어가지 않는다. `Target.createTarget`은 `task.newPage()`, `Target.closeTarget`은 `page.close()`, `Target.activateTarget`은 `Page.bringToFront`로 바뀐다. 그 밖의 `Target.*`·`Browser.*`(창 위치 조회·변경 제외)는 실패한다.
- ego 창이 최소화돼 있으면 `Page.captureScreenshot` 앞뒤로 창을 잠깐 복원했다가 다시 최소화한다. `activate=True` 탭 전환은 창을 앞으로 가져온다.
- `Target.createTarget(newWindow=True)`(스토리 검증)는 새 탭을 만들고 최소화된 창만 복원한다. ego 새 탭은 앞으로 가져오지 않아도 visible·unfocused라 스토리 영상이 재생되고, 포커스 보존 검사도 통과한다(11-06 실측).
- ego `page.cdp`의 기본 제한 시간은 짧아서 모든 page CDP 호출에 timeout을 실어 보낸다(기본 110초, 팔로우·언팔은 `evaluate(timeout)` 값). 팔로잉 목록 수집은 약 3분 걸린다.
- ego 경로의 helper는 `output/publish-news-pick/private-venv`의 python(3.12)으로 돈다(`NEWS_PICK_HELPER_PYTHON`으로 바꿀 수 있다). private API helper가 그 venv의 instagrapi를 불러오기 때문이다.
- 로그인은 ego lite 기본 프로필의 Instagram 세션을 쓴다. 계정 확인은 preflight가 Edge 때와 같은 방식으로 한다.
- 게시 확인: 2026-11-06 수동 run `20261106-081953-d13439eb`에서 preflight → upload_prepare → 갤러리 확인 → advance_to_caption(4:5, 0.8) → fill_caption_ai(AI 라벨) → share_once → verify_carousel까지 helper 수정 없이 ego로 게시·공개 검증했다([DfYNmPskh8b](https://www.instagram.com/p/DfYNmPskh8b/)). 그래서 `scheduled_runner.py`는 예약 회차에 `NEWS_PICK_BROWSER=ego`를 주입한다.
- 첫 `upload_prepare`가 클릭 전에 `visible control not found: 만들기`로 끝난 적이 있다(같은 명령 재실행으로 통과). 클릭 전 실패라 재실행해도 이중 업로드가 아니다.
- `browser_web_dom_probe.py`는 `ego-lite/` product도 허용하고 보고서 `connection`을 `ego-lite`로 적는다.
- 11-06 추가 확인: 어제 스토리 3개 공개 검증(6초), private API 세션 probe(쿠키→instagrapi), 언팔 대상 수집(팔로잉 1535·팔로워 1180), 추천 계정 41개 읽기를 모두 ego로 통과했다.
