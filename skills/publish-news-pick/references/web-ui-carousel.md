# Browser Harness 웹 캐러셀 런북

## 제출 전

1. [login-and-session.md](login-and-session.md)의 preflight를 통과한다.
2. 공개 프로필 최신 게시물을 읽어 동일한 첫 카드와 caption 첫 문장이 없는지 확인한다.
3. 승인 payload의 계정, 5장 순서, 각 SHA-256, caption, 예약시각을 다시 확인한다.
4. 모든 이미지는 정확히 1080×1350이어야 한다.
5. caption에 `AI로 재구성한 인포그래픽`과 그 변형 문구가 없어야 한다.
6. 마지막 카드에 모든 출처의 출처명·날짜·도메인이 읽을 수 있게 들어 있어야 한다.

쓰기 가능한 Instagram target은 하나만 둔다. 공유 성공 직후 같은 승인 거래 안의 공개 검증도 그 승인된 전용 target 하나에서 읽기 전용으로 진행하고, 다른 사용자 탭은 만들거나 닫거나 탐색하지 않는다. 이 예외는 독립 조회에는 적용하지 않는다.

## 작성 화면

1. `새로운 게시물`을 누른다. link wrapper에 이름이 없고 자식 SVG에만 `aria-label="새로운 게시물"` 또는 `aria-label="만들기"`가 있으면 그 exact descendant label로 wrapper를 한 번만 누른다.
2. `컴퓨터에서 선택` 단계의 `input[type=file][multiple]`에 승인된 PNG를 번호 순서로 한 번에 전달한다. `input[type=file]`처럼 단일 input도 잡는 넓은 selector는 금지한다.
3. 업로드 뒤 React가 file input을 DOM에서 제거할 수 있다. `files.length`는 input이 남아 있을 때만 선택 이벤트의 진단값이며 게시 장수의 증거가 아니다. dialog에 `자르기`·`다음`이 있고 exact `미디어 갤러리 열기` label 또는 5개 carousel dot이 있으면 열린 crop session을 성공 상태로 재사용하며 create control이나 file input을 다시 요구하지 않는다. `미디어 갤러리 열기`에서 5개 thumbnail의 장수·순서·첫 카드를 screenshot으로 확인한다. 썸네일이 1개면 다음으로 진행하지 않는다.
4. `자르기` 화면에서 실제 접근성 이름이 `자르기 선택`인 종횡비 control을 열고 exact `4:5` 항목을 직접 선택한다. control wrapper에 이름이 없어도 내부 SVG의 `aria-label="자르기 선택"`을 exact fallback으로 쓸 수 있다. 1080×1350 입력 크기, 정방형처럼 보이는 crop preview, carousel dot만으로 비율이 유지됐다고 판단하지 않는다. 선택 뒤 첫 카드 상단과 하단 문구가 모두 보이는 세로 프레임 screenshot을 남기고, 주 이미지의 자연 비율과 렌더 비율이 모두 `0.78~0.82`인지 확인한다. 주 미디어가 `<img>`가 아니라 `background-image: blob(...)`로 렌더링되면 exact `4:5` 선택과 입력 계약을 확인한 뒤 해당 CSS 배경 요소의 렌더 비율을 검사한다. crop viewport가 정방형이거나 필수 문구가 잘리면 제출하지 않는다.
5. 첫 번째 `다음` 뒤 편집 화면에서 `원본` 필터가 선택됐는지 확인한다. 두 번째 `다음`이 무시되면 화면이 여전히 `필터·조정` 단계임을 확인한 경우에만 한 번 더 누른다.
   - `browser_web_advance_to_caption.py`는 crop→편집→caption 전환을 한 Harness 프로세스에서 처리한다. 고정 DOM selector가 기본 경로이고, exact control을 DOM에서 찾지 못했을 때만 전체 AX tree를 한 번 fallback한다. 의미 있는 클릭 사이에는 `0.22~0.48초` jitter를 둔다.
6. 두 번째 `다음` 뒤 승인된 caption을 그대로 입력한다. 입력 요소는 `<textarea>` 또는 `[role=textbox][contenteditable=true]`일 수 있으므로 둘 다 지원한다. `type_text` 뒤 본문이 줄바꿈만 남는 Lexical 편집기에서는 전체 선택·삭제 후 `ClipboardEvent('paste')`를 한 번 보내고, 끝의 추가 개행만 제거해 로컬 원문과 비교한다. 내부 줄바꿈과 문단은 정규화하지 않는다.
7. 사실적 AI 재구성 카드이면 `AI 라벨 추가` switch의 `aria-checked=true`를 확인한다.

게시 직전 screenshot에 첫 카드, caption 끝부분, 글자 수, AI switch를 함께 남긴다.

## 정확히 한 번 공유

`공유하기`를 정확히 한 번만 클릭한다. 가능하면 `scripts/browser_web_share_once.py`를 사용한다. 다음 문구 중 하나가 보일 때만 제출 성공으로 간주한다.

- `게시물이 공유되었습니다`
- `게시물을 공유했습니다`
- `Your post has been shared`

성공 문구가 없거나 timeout이면 버튼을 다시 누르지 않는다. `needs_review`로 남기고 공개 프로필에서 동일 payload를 먼저 찾는다.

성공 문구 뒤 프로필 최신 permalink를 읽고 다음을 기록한다.

프로필 grid의 링크는 `https://www.instagram.com/<account>/p/<code>/`일 수 있다. shortcode를 추출한 뒤 공개 검증 URL은 `https://www.instagram.com/p/<code>/`로 정규화하며, 최신 카드의 image alt에 `IG_EXPECTED_ALT_TOKENS`가 모두 있는 게시물만 선택한다.

```powershell
python scripts/carousel_queue.py record-web-submitted <job_id> --shortcode <code> --card-count 5
```

## 공개 검증

공유 성공 직후 같은 승인 거래에서만, 공유에 사용한 승인된 전용 Instagram target에서 permalink를 열어 다음을 확인한다.

- 프로필 게시물 수가 예상대로 증가
- shortcode와 계정이 일치
- 첫 카드가 승인 payload와 시각적으로 일치
- 마지막 카드의 전체 출처 블록이 승인 payload와 일치하고 판독 가능
- carousel 장수가 일치
- 5개 index가 서로 다른 media source이며 모든 주 이미지의 자연·렌더 비율이 `0.78~0.82`
- caption 첫 문장과 기준시각이 일치
- 사실적 AI 재구성 카드에 현재 Instagram 공개 DOM의 `AI 콘텐츠`, `AI 크리에이터` 또는 `Made with AI` 표시가 보임

화살표와 pagination dot은 DOM에서 사라질 수 있다. 공유 성공 직후 같은 승인 거래임을 나타내는 `IG_APPROVED_PUBLISH_VERIFY=1`을 설정하고 `scripts/browser_web_verify_carousel.py`로 permalink의 `?img_index=1`부터 `?img_index=<장수>`까지 열어 active index 순서와 서로 다른 media source 5개를 확인한다. 본문 주 이미지는 화면 상단의 4:5 이미지와 자연·렌더 비율로 고르며, 페이지 아래 `게시물 더 보기`의 정방형 thumbnail을 제외한다. 첫·마지막 JPEG screenshot을 남기고 실제 마지막 출처 카드가 보이지 않으면 검증 실패다.

모두 맞을 때만 `verify-published --run-dir <run-directory>`를 실행해 queue result와 run의 `04-publish/result.json`을 함께 쓴다.

## AI 라벨 저장 누락 복구

작성 직전 switch가 `true`였어도 공개 페이지에 `AI 콘텐츠`, `AI 크리에이터`, `Made with AI` 중 어느 표시도 없을 수 있다. 이 경우 새 게시물을 만들지 않는다.

1. 해당 permalink의 `옵션 더 보기` → `수정`을 연다.
2. `AI 라벨 추가`가 `true`인지 확인한다.
3. 공개 표시가 없으면 switch를 `false`로 바꾼 뒤 다시 `true`로 바꾼다.
4. `완료`를 눌러 저장한다.
5. 새 background target으로 permalink를 다시 열어 `AI 콘텐츠`를 확인한다.

caption과 이미지에는 손대지 않는다. 한 번의 저장 뒤에도 표시가 없으면 반복하지 말고 `needs_review`로 보고한다.

## 실제 실패에서 확정한 규칙

- visible Edge 로그인과 private API 로그인은 별개다. private API의 `login_required` 뒤에도 웹 UI는 정상 게시될 수 있다.
- private API가 제출 경계 뒤 실패했으면 공개 프로필에 중복이 없는지 확인한 후에만 웹 UI로 전환한다.
- Instagram 성공 문구와 공개 permalink를 둘 다 확인해야 한다.
- 성공한 웹 게시를 queue job에 연결해야 `failed_pre_submit` 또는 `needs_review`가 다음 실행에서 재게시되지 않는다.
- 공개 permalink 직후 마지막 장은 지연 로딩될 수 있다. 회색 placeholder와 pagination dot만으로 마지막 카드 일치를 판정하지 않는다.
- 다른 수동·예약 run이 작성기를 사용 중이면 그 draft를 stale로 간주해 닫지 않는다. 작성기 소유자가 하나인지 먼저 확인하고, 예약 실행은 `composer_busy`로 건너뛴다.
- `switch_tab` attach만으로 writable Edge target이 전면 활성화됐다고 가정하지 않는다. 변경 helper는 target을 명시적으로 활성화한다.
- 활성 작성 화면의 일반 PNG screenshot이 timeout이면 같은 화면을 저용량 JPEG CDP 캡처로 한 번 남긴다. 이 timeout 때문에 업로드를 반복하지 않는다.
