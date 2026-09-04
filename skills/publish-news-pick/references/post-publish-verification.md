# 공개 프로필 검증

공유에 사용한 승인된 전용 Instagram target 하나에서 `https://www.instagram.com/<IG_ACCOUNT>/`와 제출 결과의 shortcode URL을 읽기 전용으로 연다. 이 검증기는 게시 성공 직후 같은 승인 거래에서 `IG_APPROVED_PUBLISH_VERIFY=1`을 설정했을 때만 사용하며 다른 탭을 만들거나 닫지 않는다. 독립 조회와 `needs_review` 조사는 background target 원칙을 유지한다.

확인:

- 로그인 challenge나 계정 전환 화면이 아님
- URL shortcode가 private API 또는 웹 UI 제출 기록과 같음
- carousel item 개수가 준비한 5장과 같음
- `?img_index=1..5`의 media source가 모두 다르고 각 주 이미지의 자연·렌더 비율이 `0.78~0.82`
- 첫 카드가 준비 payload의 첫 이미지와 시각적으로 일치
- caption의 고유한 첫 문장과 기준시각이 일치
- 사실적 AI 재구성 게시물은 공개 페이지에 `AI 콘텐츠` 표시가 보임
- 승인된 전용 Instagram target 외 다른 사용자 탭은 보존됨

`scripts/browser_web_verify_carousel.py`는 화면 상단의 4:5 본문 이미지만 고르고 페이지 아래 추천 게시물 thumbnail을 제외한다. 장수·active index 순서·서로 다른 source 5개·공개 4:5 비율·caption·AI 라벨을 통과해도 저장된 첫·마지막 JPEG screenshot에서 실제 첫 카드와 마지막 출처 카드가 렌더링됐는지 시각 확인해야 한다. 회색 placeholder는 통과로 간주하지 않는다.

이미 게시된 가능성이 있는 `needs_review`에서는 profile 최신 항목을 먼저 읽는다. 같은 payload가 보이면 재제출하지 않고 사람이 상태를 확정한다.
