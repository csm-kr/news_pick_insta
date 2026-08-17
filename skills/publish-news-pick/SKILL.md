---
name: publish-news-pick
description: 승인된 3~4장 PNG를 설정된 Instagram 계정의 사진 캐러셀로 게시한다. 사용자가 고른 전용 Chrome profile의 Instagram 웹 UI를 Browser Harness로 제어하고 private API는 선택적 보조 경로로만 사용한다. 불변 payload 승인, AI 라벨, 중복 방지, 모호한 제출의 needs_review, 공개 프로필 검증이 필요한 뉴스픽 업로드에 사용한다.
---

# Publish News Pick

이미 완성·검증된 PNG와 caption만 게시한다. 뉴스 검색, 카피 수정, 이미지 생성을 하지 않는다. 기본 게시 경로는 사용자가 로그인한 Instagram 웹 UI다. 비공식 private API는 사용자가 그 위험을 별도로 승인했을 때만 보조 경로로 사용한다.

실행 전 [references/login-and-session.md](references/login-and-session.md), [references/web-ui-carousel.md](references/web-ui-carousel.md), [references/publish-state-machine.md](references/publish-state-machine.md)를 읽는다. 사용자가 private API를 별도 승인한 경우에만 [references/private-carousel.md](references/private-carousel.md)를 추가로 읽는다.

## 필요한 입력과 환경

- 승인된 1024×1024 PNG 3~4장과 고정된 순서
- 2200자 이하 caption과 게시 시각
- `IG_ACCOUNT`의 계정에 로그인된 `NEWS_PICK_CHROME_PROFILE` 표시형 Chrome
- skill 폴더 밖의 절대 `NEWS_PICK_OUTPUT_ROOT`
- Browser Harness 기본 연결
- exact payload에 대한 사용자 게시 승인

기본값은 `IG_ACCOUNT=newspick_studio`, `NEWS_PICK_CHROME_PROFILE=Profile 3`이지만 다른 workspace에서는 명시적으로 바꿀 수 있다. 웹 UI 경로에는 password, cookie export, `sessionid`, 앱 비밀번호가 필요 없다. 선택한 Chrome profile의 기존 로그인 세션을 그대로 사용한다.

## 불변조건

- 대상 계정은 승인 payload의 계정 및 `IG_ACCOUNT`와 일치해야 한다.
- 사용자가 로그인한 `NEWS_PICK_CHROME_PROFILE` 전용 Chrome과 loopback CDP만 사용한다.
- Browser Harness에서 설정된 profile의 Instagram 탭 하나만 제어한다. 다른 탭을 닫거나 탐색하지 않는다.
- 웹 UI 게시 경로에서는 해당 Instagram 탭의 활성화·탐색·파일 선택을 허용한다. 공개 검증은 background target으로 수행한다.
- password, MFA, CAPTCHA, 동의 화면을 자동 처리하지 않는다.
- cookie·Authorization·client settings를 출력하거나 저장하지 않는다.
- 웹 UI에서는 cookie를 읽지 않는다. 선택적 private API에서만 `sessionid`를 Browser Harness 프로세스 메모리에서 `Client.login_by_sessionid()`로 전달하고 즉시 버린다.
- PNG 3~4장 순서, caption, 계정, 시각, 파일 hash를 승인 payload로 잠근다.
- 1~3장에는 반복 출처 footer가 없어야 하고, 마지막 카드에만 사용한 모든 출처의 출처명·날짜·도메인이 읽을 수 있게 들어 있어야 한다.
- caption에 `AI로 재구성한 인포그래픽`과 그 변형 문구를 넣지 않는다. 공개 표시는 Instagram `AI 콘텐츠` 라벨로 처리한다.
- 웹 UI에서 `여러 항목 선택`, 1:1 crop, `원본` 필터, 정확한 카드 순서와 caption을 확인하고 사실적 AI 재구성에는 `AI 라벨 추가`를 켠다.
- `공유하기`는 한 번만 누르고 `게시물이 공유되었습니다` 성공 표시가 확인되지 않으면 자동 재시도하지 않는다.
- `album_upload()` 호출 뒤 오류·timeout은 자동 재시도하지 않는다.

## 최초 설정

현재 Browser Harness 기본 연결과 기대 프로필을 등록한다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = '<workspace>/output'
$env:IG_ACCOUNT = 'newspick_studio'
$env:NEWS_PICK_CHROME_PROFILE = 'Profile 3'
python scripts/launch_chrome_profile.py --profile $env:NEWS_PICK_CHROME_PROFILE --account $env:IG_ACCOUNT
python scripts/carousel_queue.py configure --browser-harness-connection default --expected-profile $env:NEWS_PICK_CHROME_PROFILE --dedicated-profile
```

별도 Chrome이 loopback CDP URL을 직접 노출하는 환경에서는 `--endpoint http://127.0.0.1:<port>`를 대신 사용할 수 있다.

설정된 Chrome profile의 Instagram 로그인을 읽기 전용으로 확인한다.

```powershell
browser-harness < scripts/browser_web_preflight.py
```

`ready=true`, target account, `프로필 편집`, `새로운 게시물`, login/challenge 부재를 모두 확인해야 한다. 실패하면 사용자가 설정된 profile 창에서 로그인·MFA·challenge를 직접 완료할 때까지 멈춘다.

비공식 backend 설치를 사용자가 승인한 뒤에만 project-local venv를 만든다.

```powershell
python scripts/setup_backend.py
```

선택적 backend는 `<NEWS_PICK_OUTPUT_ROOT>/publish-news-pick/private-venv`에 만들며 skill 폴더에는 쓰지 않는다. Windows에서는 `Scripts/python.exe`, POSIX에서는 `bin/python`을 자동 선택한다.

## 선택적 private API probe

```powershell
python scripts/carousel_queue.py probe --account $env:IG_ACCOUNT
```

`probe_only`, `session_persisted=false`, `active_preserved`, `existing_target_preserved`, private client account 일치가 모두 필요하다.

## 준비와 승인

```powershell
python scripts/carousel_queue.py prepare --account $env:IG_ACCOUNT --scheduled-at <ISO-8601> --timezone Asia/Seoul --media <01.png> --media <02.png> --media <03.png> --caption-file <caption.txt>
```

표시된 계정, 시각, caption 글자 수, 정확한 이미지 순서, 각 SHA-256, `payload_sha256`을 확인한다. 사용자가 이 exact payload의 실게시를 승인한 뒤에만:

```powershell
python scripts/carousel_queue.py approve <job_id> --sha256 <payload_sha256>
```

파일·순서·caption이 바뀌면 승인은 무효다.

## 제출 — 기본 웹 UI 경로

Browser Harness로 설정된 Chrome profile의 Instagram 작성 화면을 열고 다음 순서를 지킨다.

1. `새로운 게시물` → `컴퓨터에서 선택`
2. 승인된 PNG 3~4장을 번호 순서로 한 번에 선택
3. 갤러리에 정확한 장수·순서가 보이는지 확인
4. 1:1 crop과 `원본` 필터 확인
5. 승인된 caption 입력. `AI로 재구성한 인포그래픽` 계열 문구가 없어야 함
6. 사실적 AI 재구성 카드에는 `AI 라벨 추가` 활성화
7. 게시 직전 장수·첫 카드·마지막 카드 출처 블록·caption 글자 수·AI 라벨을 재확인
8. `scripts/browser_web_share_once.py`로 `공유하기`를 한 번만 클릭
9. Instagram의 성공 표시를 확인하고 공개 프로필에서 shortcode를 수집

성공 표시와 shortcode가 확인되면 재업로드하지 않고 제출 기록을 연결한다.

```powershell
python scripts/carousel_queue.py record-web-submitted <job_id> --shortcode <code> --card-count <3|4>
```

## 제출 — 선택적 private API 경로

MVP에서는 due job 한 번만 실행한다.

```powershell
python scripts/carousel_queue.py run-due
```

private API가 shortcode를 반환해도 상태는 `submitted`다. 제출 호출 뒤 오류는 `needs_review`, 호출 전 오류는 `failed_pre_submit`이다. `needs_review`를 자동 재시도하지 않는다. 공개 프로필에 동일 payload가 없음을 확인한 뒤에만 승인된 웹 UI 경로로 전환할 수 있다.

## 공개 확인

[references/post-publish-verification.md](references/post-publish-verification.md)에 따라 Browser Harness background target으로 프로필과 게시물을 읽는다. `scripts/browser_web_verify.py`로 caption과 `AI 콘텐츠` 표시를 확인하고, shortcode, 카드 장수와 첫 카드까지 모두 맞을 때만:

```powershell
$env:IG_POST_URL="https://www.instagram.com/$env:IG_ACCOUNT/p/<code>/"
$env:IG_CAPTION_PREFIX='<caption 첫 문장>'
$env:IG_REQUIRE_AI_LABEL='1'
browser-harness < scripts/browser_web_verify.py
```

```powershell
python scripts/carousel_queue.py verify-published <job_id> --shortcode <code> --card-count <3|4> --caption-match --first-card-match
```

이 명령이 `result.json`과 `public_verified=true`를 기록한 뒤에만 성공을 보고한다.

작성 화면에서 AI switch가 `true`였지만 공개 페이지에 `AI 콘텐츠`가 없으면 새로 게시하지 않는다. 기존 게시물의 `옵션 더 보기 → 수정`에서 switch를 `false → true`로 한 번 순환하고 저장한 뒤 다시 검증한다. 한 번의 복구 후에도 없으면 `needs_review`로 남긴다.

## 상태 처리

```text
draft → approved → submitting → submitted → published
             │           ├─ failed_pre_submit ─┐
             │           └─ needs_review ──────┤
             └──── Browser Harness web UI ─────┘
```

cron·daemon은 MVP 범위가 아니다. 한 건 실게시와 공개 확인이 성공한 뒤 별도 승인으로 추가한다.
