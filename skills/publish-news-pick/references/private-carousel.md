# Private carousel backend

기존 `instagram-upload-skill`의 Reel 코어에서 다음만 재사용했다.

- 전용 Microsoft Edge·`http://127.0.0.1:9333`·Browser Harness `edge9333` 연결
- Browser Harness의 정확한 Instagram target read-only attach와 focus 보존
- sessionid 메모리 전달
- payload hash와 승인 무효화
- 제출 후 모호한 오류의 자동 재시도 금지

사진 캐러셀은 `Client.album_upload([Path...], caption)`을 호출한다. 정확히 5개 PNG를 job 폴더로 복사하고 순서를 hash에 포함한다. 비공식 API 계약은 바뀔 수 있으며 계정 제재 위험을 제거하지 못한다.

worker는 고정 Edge 연결의 기존 Instagram page target을 계정 프로필 URL로 정확히 특정할 수 있을 때만 read-only attach한다. 탐색·클릭·포커스 변경 없이 session cookie를 메모리로 전달하고 private client의 실제 username으로 계정을 재검증한 뒤 session만 detach한다. target을 특정하지 못하면 세션을 읽지 않고 멈춘다.
