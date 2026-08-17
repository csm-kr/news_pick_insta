# 게시 상태 머신

- `draft`: 파일이 복사되고 payload hash가 만들어짐
- `approved`: 현재 hash에 대한 사람 승인
- `submitting`: 외부 제출 경계 직전
- `submitted`: private API가 pk/shortcode를 반환했거나 Browser Harness 웹 UI 성공 표시와 shortcode가 확인됐지만 공개 검증 전
- `published`: 공개 프로필 검증까지 완료
- `failed_pre_submit`: `album_upload` 호출 전 실패. 같은 payload 재승인 후 재시도 가능
- `needs_review`: 호출 뒤 오류·timeout 또는 제출 여부 불명. 자동 재시도 금지

모든 attempt에 시작·종료 시각, `submission_started`, redacted 오류, private 응답 식별자만 기록한다. sessionid와 cookie는 기록하지 않는다.

`failed_pre_submit` 또는 `needs_review`에서 웹 UI로 전환할 때는 먼저 공개 프로필에 동일 payload가 없는지 확인한다. 웹 UI의 `공유하기`는 한 번만 클릭하며 성공 표시가 모호하면 `needs_review`로 남기고 자동 재시도하지 않는다. 성공 표시와 shortcode가 모두 확인되면 `record-web-submitted`로 동일 승인 payload에 연결한다.
