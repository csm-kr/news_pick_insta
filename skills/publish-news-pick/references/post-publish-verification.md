# 공개 프로필 검증

Browser Harness background target으로 `https://www.instagram.com/newspick_studio/`와 제출 결과의 shortcode URL을 연다.

확인:

- 로그인 challenge나 계정 전환 화면이 아님
- URL shortcode가 private API 또는 웹 UI 제출 기록과 같음
- carousel item 개수가 준비한 3~4장과 같음
- 첫 카드가 준비 payload의 첫 이미지와 시각적으로 일치
- caption의 고유한 첫 문장과 기준시각이 일치
- 사실적 AI 재구성 게시물은 공개 페이지에 `AI 콘텐츠` 표시가 보임
- 기존 사용자 탭·포커스가 보존됨

이미 게시된 가능성이 있는 `needs_review`에서는 profile 최신 항목을 먼저 읽는다. 같은 payload가 보이면 재제출하지 않고 사람이 상태를 확정한다.
