# Browser Harness 웹 캐러셀 런북

## 제출 전

1. [login-and-session.md](login-and-session.md)의 preflight를 통과한다.
2. 공개 프로필 최신 게시물을 읽어 동일한 첫 카드와 caption 첫 문장이 없는지 확인한다.
3. 승인 payload의 계정, 3~4장 순서, 각 SHA-256, caption, 예약시각을 다시 확인한다.
4. 모든 이미지는 정확히 1024×1024여야 한다.
5. caption에 `AI로 재구성한 인포그래픽`과 그 변형 문구가 없어야 한다.
6. 마지막 카드에 모든 출처의 출처명·날짜·도메인이 읽을 수 있게 들어 있어야 한다.

쓰기 가능한 Instagram target은 하나만 둔다. 공개 검증용 background target은 작업 뒤 닫고, 다른 사용자 탭은 닫거나 탐색하지 않는다.

## 작성 화면

1. `새로운 게시물`을 누른다.
2. `컴퓨터에서 선택` 단계의 `input[type=file][multiple]`에 승인된 PNG를 번호 순서로 한 번에 전달한다. `input[type=file]`처럼 단일 input도 잡는 넓은 selector는 금지한다.
3. 업로드 뒤 React가 file input을 DOM에서 제거할 수 있다. `files.length`는 input이 남아 있을 때만 선택 이벤트의 진단값이며 게시 장수의 증거가 아니다. `미디어 갤러리 열기`에서 3~4개 thumbnail의 장수·순서·첫 카드를 screenshot으로 확인한다. 썸네일이 1개면 다음으로 진행하지 않는다.
4. `자르기` 화면에서 1:1 정방형을 확인한다. 첫 카드의 상단·하단 문구가 잘리면 제출하지 않는다.
5. 첫 번째 `다음` 뒤 편집 화면에서 `원본` 필터가 선택됐는지 확인한다.
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

```powershell
python scripts/carousel_queue.py record-web-submitted <job_id> --shortcode <code> --card-count <3|4>
```

## 공개 검증

background target으로 permalink를 열어 다음을 확인한다.

- 프로필 게시물 수가 예상대로 증가
- shortcode와 계정이 일치
- 첫 카드가 승인 payload와 시각적으로 일치
- 마지막 카드의 전체 출처 블록이 승인 payload와 일치하고 판독 가능
- carousel 장수가 일치
- caption 첫 문장과 기준시각이 일치
- 사실적 AI 재구성 카드에 `AI 콘텐츠` 표시가 보임

화살표는 hover 상태에서만 DOM에 나타날 수 있다. `scripts/browser_web_verify_carousel.py`로 permalink의 `?img_index=1`부터 `?img_index=<장수>`까지 열어 pagination dot 수와 active index 순서를 확인하고 첫·마지막 screenshot을 남긴다. 직접 연 마지막 장은 `wait_for_load()` 뒤에도 회색 placeholder가 남을 수 있으므로 최대 15초 기다린다. screenshot에 실제 마지막 출처 카드가 보이지 않으면 검증 실패다.

모두 맞을 때만 `verify-published --run-dir <run-directory>`를 실행해 queue result와 run의 `04-publish/result.json`을 함께 쓴다.

## AI 라벨 저장 누락 복구

작성 직전 switch가 `true`였어도 공개 페이지에 `AI 콘텐츠`가 누락될 수 있다. 이 경우 새 게시물을 만들지 않는다.

1. 해당 permalink의 `옵션 더 보기` → `수정`을 연다.
2. `AI 라벨 추가`가 `true`인지 확인한다.
3. 공개 표시가 없으면 switch를 `false`로 바꾼 뒤 다시 `true`로 바꾼다.
4. `완료`를 눌러 저장한다.
5. 새 background target으로 permalink를 다시 열어 `AI 콘텐츠`를 확인한다.

caption과 이미지에는 손대지 않는다. 한 번의 저장 뒤에도 표시가 없으면 반복하지 말고 `needs_review`로 보고한다.

## 실제 실패에서 확정한 규칙

- visible Chrome 로그인과 private API 로그인은 별개다. private API의 `login_required` 뒤에도 웹 UI는 정상 게시될 수 있다.
- private API가 제출 경계 뒤 실패했으면 공개 프로필에 중복이 없는지 확인한 후에만 웹 UI로 전환한다.
- Instagram 성공 문구와 공개 permalink를 둘 다 확인해야 한다.
- 성공한 웹 게시를 queue job에 연결해야 `failed_pre_submit` 또는 `needs_review`가 다음 실행에서 재게시되지 않는다.
- 공개 permalink 직후 마지막 장은 지연 로딩될 수 있다. 회색 placeholder와 pagination dot만으로 마지막 카드 일치를 판정하지 않는다.
