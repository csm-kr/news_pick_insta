# Story 게시 후 검증·복구

## 업로드와 공개 검증을 분리한다

2026-09-05에는 세 Story의 업로드와 계정 Story 목록의 ID·6초 영상 metadata 확인이 모두 성공했지만, Edge background에서는 두 영상이 `readyState=0`, `videoWidth=0`인 채 남았고 캡처가 timeout 또는 검은 placeholder였다. 세 번째 영상은 실제 화면을 표시했지만 검증 중 focus가 바뀌었다. 따라서 `needs_review`, `public_verified=false`가 맞으며 업로드 실패나 이미지 잘림으로 단정할 수 없다. 전면 활성화로 세 영상 모두 복구됐다는 검증은 아직 없다.

- 먼저 날짜 폴더의 `result.json`, `submission-intent.json`이 있으면 그 내용, `manifest.json`의 입력 SHA-256과 Story ID·URL 세 개를 읽는다. `visual-review.json`의 제작 시점 `submission_started=false`보다 실제 제출 결과가 우선이다.
- `submission.ok=true`, `confirmed=true`, Story ID 세 개와 계정 목록 metadata가 확인되면 사용자에게 **세 개 업로드 성공, 공개 재생 검증 미완료**로 보고한다. 공개 검증 실패만으로 업로드를 반복하지 않는다.
- `submission_started=true` 또는 `needs_review`이면 기존 출력·제출 기록을 삭제하거나 날짜 폴더를 바꿔 새 배치를 올리지 않는다. ID가 일부만 있거나 제출 결과가 모호해도 자동 재시도하지 않는다.
- 세 ID가 모두 있고 입력 해시가 같을 때 `publish_story_batch.py`는 기존 결과의 검증 경로만 실행한다. 다만 focus 실패 후에는 같은 명령을 반복하지 말고 사용자에게 확인한다. 수동 복구는 업로드 helper 없이 기록된 세 URL만 대상으로 한다.

## Edge 재생 증거

1. 고정 Microsoft Edge `edge9333`만 사용한다. 공개 검증 helper는 기본 background를 유지하고, polling 및 캡처 전후의 focus·정확한 Story URL·계정·영상 상태를 확인한다.
2. `readyState>=2`, 세로 영상 크기, 약 6초 duration과 `currentTime>0`을 확인한다. 다른 Story로 자동 이동했거나 login/challenge가 나타나면 성공으로 처리하지 않는다.
3. 로딩되지 않은 영상은 캡처해도 검은 화면일 수 있다. 이 경우 캡처를 반복하지 않고 실패 상태를 남긴다. 실제 frame이 표시되면 영상을 일시정지하고 새 JPEG를 캡처해 정확한 ID가 유지되는지 재확인한다. 기존 screenshot 파일이 있다는 사실만으로 성공 처리하지 않는다.
4. focus가 바뀌면 남은 background 조회를 즉시 중단한다. 작업용 target만 정리하고 기존 사용자 탭은 탐색·닫기·활성화하지 않는다.
5. background 검증이 실패하면 **Edge 창을 잠시 활성화해 이미 게시된 세 Story만 확인해도 되는지** 묻는다. 게시 승인이나 스킬 수정·commit 승인 자체는 foreground 검증 승인이 아니다. 승인 없이는 `needs_review`를 유지한다.
6. 별도로 승인받은 전면 검증도 동일 Edge 연결을 사용한다. 작업용 target 하나에서 기록된 URL만 열고 ID·계정·재생과 screenshot을 확인한다. 공유·삭제·재업로드 control은 누르지 않는다. 기존 background 검증 helper에는 foreground 옵션이 없으므로 focus guard를 제거해서 재사용하지 않는다.

각 screenshot을 직접 열어 제목·날짜·표지 상하단이 원본 proof와 일치하고 잘리지 않았는지 확인한다. 세 URL의 공개 화면과 metadata가 모두 확인됐을 때만 `published`, `public_verified=true`로 바꾸고 검증 시각·방식·증거 경로를 남긴다. 이전 실패 진단은 별도 복구 기록으로 보존한다.

## MP4 의존성과 원형 보존

- 제작 단계에서 각 표지를 원래 비율로 유지하고 같은 표지를 확대한 블러는 배경에만 쓴다. 승인된 manifest의 `layout.foreground`와 `foreground_xy`, proof 세 장을 확인한다. 게시 직전에 비율·입력 이미지·해시를 바꾸지 않는다.
- 이번 환경의 `instagrapi==2.18.12`는 표준 MP4와 승인 proof를 `thumbnail`으로 주고 `resize_mode="fill"`을 사용했을 때 native MP4 metadata parser로 세 업로드에 성공했다. 이 경로에는 MoviePy가 필요하지 않았다. 이 관찰을 다른 버전·형식에 일반화하지 않는다.
- `ModuleNotFoundError: moviepy`를 별도 import 점검에서 봤다는 이유만으로 backend venv를 재생성하거나 패키지를 추가하지 않는다. 먼저 실제 venv의 SDK 버전과 `video_upload_to_story`·`analyze_video_for_upload` 호출 경로를 확인하고, 필요하면 승인 MP4와 proof로 로컬 metadata 분석만 실행한다. 업로드 함수는 의존성 테스트에 쓰지 않는다.
- 다른 경로에서 MoviePy가 실제 필요하면 그 버전의 의존성 요구를 확인한 뒤 별도 처리한다. cookie·session·인증 파일은 로그나 복구 기록, Git에 포함하지 않는다.
