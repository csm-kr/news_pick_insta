---
name: publish-daily-news-story
description: 지정일의 07·12·17시 공개 검증 뉴스픽 표지 3장을 각각 6초 세로 MP4로 만들어 19시에 Instagram Story 3개로 연속 게시·검증한다. "오늘 뉴스 3개 스토리로", "19시 스토리 예약" 같은 요청에 사용한다.
---

# Publish Daily News Story

지정일의 07·12·17시 검증 뉴스픽 표지 3장을 각각 독립된 무음 Story 영상으로 만든다. 각 1080×1350 세로 표지는 1080×1920 화면의 `x=0, y=285`에 잘림 없이 원형 그대로 놓고, 같은 표지를 확대한 어두운 블러 배경 위에 배치한다. Story마다 정확히 6초, H.264, 30fps, `yuv420p`, fast-start MP4여야 한다.

게시 또는 공개 확인 전 [../publish-news-pick/references/edge-browser-contract.md](../publish-news-pick/references/edge-browser-contract.md)를 읽고 Microsoft Edge `edge9333` 외의 Browser Harness 연결은 사용하지 않는다.

## 입력 선택

- `NEWS_PICK_OUTPUT_ROOT` 또는 `--output-root`의 `runs/`를 읽는다.
- 기준일은 Asia/Seoul의 오늘이며 `--date YYYY-MM-DD`로 바꿀 수 있다.
- `04-publish/result.json`이 `status=published`, `public_verified=true`, `first_card_match=true`인 run만 허용한다.
- `04-publish/result.json`의 `verified_at`을 Asia/Seoul로 해석해 기준일에 공개 검증 완료된 run을 전부 포함한다. 이것을 그날 게시 완료 목록의 기준으로 사용한다.
- 해당 날짜의 공개 검증 후보가 정확히 3개여야 한다. 하나라도 누락되거나 추가 수동 게시물 때문에 4개 이상이면 임의 선택하지 않고 게시 없이 중단한다.
- 각 run의 실제 표지는 `03-create/slides/01.png`이며 1080×1350인지 확인한다.

기본 배치는 설정된 정규 회차를 각각 하나씩 요구한다. 사용자가 **지금 오늘 게시물로 스토리 게시**를 요청했고 당일 공개 검증본이 정확히 3개지만 수동 회차가 섞였다면 `--include-manual-editions`로 당일 `verified_at` 순서의 세 게시물을 사용한다. 이 옵션은 `NEWS_PICK_DAILY_STORY_SCHEDULED_MODE=1`에서 거부되며, 기존 run의 회차·시각이나 실패한 예약 상태를 수정하지 않는다. 오늘 3개가 맞는지, 기존 스토리 제출 이력이 없는지 먼저 확인한다.

## 한 번에 실행

사용자가 생성과 게시를 모두 명시적으로 요청했을 때만 다음을 실행한다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = '<workspace>/output'
$env:IG_ACCOUNT = 'newspick_studio'
python scripts/run_daily_story.py --date <YYYY-MM-DD> --account $env:IG_ACCOUNT --publish
```

이 명령은 후보 선택, Story MP4 3개 렌더, `ffprobe` 검증, proof 3개 생성, 한 번의 브라우저 세션 확인, Story 3개 배치 업로드, ego 별도 탭 공개 확인을 수행한다. 출력은 `<NEWS_PICK_OUTPUT_ROOT>/daily-story/<YYYY-MM-DD>/` 아래의 `story-01.mp4`~`story-03.mp4`, `manifest.json`, `proof-01.jpg`~`proof-03.jpg`, `result.json`, `verified-stories/verified-01.jpg`~`verified-03.jpg`다.

사용자가 게시를 요청하지 않았다면 미리보기까지만 만든다.

```powershell
python scripts/run_daily_story.py --date <YYYY-MM-DD>
```

수동 회차를 포함한 오늘 게시물 3개를 미리보기로 준비할 때는 같은 명령에 `--include-manual-editions`를 추가한다. 비공식 API 사용과 게시 승인을 확인한 뒤에만 `--publish`를 추가한다.

모든 proof frame과 manifest의 전체 source run, Instagram URL, SHA-256을 확인한 뒤 결과를 보여준다. 사용자가 이후 게시를 승인하면 같은 명령에 `--publish`를 붙인다. 이미 `status=published`인 동일 SHA-256 결과는 재게시하지 않고 성공으로 재사용한다.

## 매일 19시 예약 게시

사용자가 매일 `19:00` KST Story 3개 게시를 명시적으로 승인한 계정에서는 그 승인을 예약 실행의 standing approval로 적용한다. 예약 실행은 당일 07·12·17시 공개 검증 뉴스 캐러셀의 `01.png` 대문 3개를 시간순으로 사용하며, 정확히 3개가 아니면 만들거나 게시하지 않는다.

```powershell
python scripts/scheduled_story_runner.py --dry-run
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 remove
```

Windows 작업은 매일 `19:00` KST에 시작한다. 같은 날짜의 상태 파일이 이미 있으면 중복 실행하지 않고, `19:30`을 넘긴 missed run은 보충 게시하지 않는다. 예약 executor는 ego lite(`NEWS_PICK_BROWSER=ego`)로 게시·검증하고, ego가 꺼져 있으면 helper 실행기가 켠다. 상태는 `<NEWS_PICK_OUTPUT_ROOT>/scheduler/daily-story/editions/`, 로그는 `<NEWS_PICK_OUTPUT_ROOT>/logs/scheduler/daily-story/`에 기록한다. 업로드 시작 뒤 오류나 공개 검증 실패는 `needs_review`로 끝내며 자동 재시도하지 않는다.

## 게시 불변 조건

- 게시라는 외부 변경에는 현재 대화의 명시적 승인이 필요하다. 단순 제작·미리보기 요청은 게시 권한이 아니다.
- 지정된 `IG_ACCOUNT`와 현재 표시형 Instagram profile 계정이 일치해야 한다.
- Browser Harness로 현재 로그인 세션을 메모리 안에서만 전달한다. cookie, `sessionid`, password, MFA 정보를 출력하거나 저장하지 않는다.
- 한 helper 프로세스(기본 ego lite)에서 계정·private client를 한 번 확인한 뒤 승인된 영상마다 `video_upload_to_story()`를 정확히 한 번씩, 총 3번 호출한다. 호출 사이에는 1.8~3.2초 random jitter를 둔다.
- 업로드 시작 뒤 timeout·오류·공개 확인 실패가 나면 `needs_review`로 끝내고 자동 재시도하지 않는다.
- 기존 `result.json`이 `needs_review`이고 `submission_started=true`면 공개 Story를 사람이 확인하기 전에는 다시 올리지 않는다.
- 세 Story URL과 영상 metadata를 모두 확인해야 성공이다. 공개 확인은 ego lite `newspick-instagram`의 새 탭 하나에서 순서대로 수행하고 포커스를 보존한다(ego 새 탭은 앞으로 가져오지 않아도 visible이라 영상이 재생된다). Chrome/default/다른 CDP 연결은 사용하지 않는다.

## 개발과 검증

업로드 후 검은 화면·캡처 timeout·focus 변경이 발생했거나 MoviePy 설치 여부가 불분명하면 [references/story-recovery.md](references/story-recovery.md)를 먼저 읽는다. **업로드 성공과 공개 검증 성공은 별개**이며, 검증 탭을 앞으로 가져오는 전면 활성화는 별도 승인 없이 시도하지 않는다. 복구는 기록된 Story ID를 확인하는 작업이지 재업로드가 아니다.

FFmpeg·ffprobe·Pillow, `ego-browser` CLI(ego lite), `publish-news-pick`이 준비한 project-local `instagrapi` venv가 필요하다. ego 경로의 helper는 그 venv의 python(3.12)으로 돈다.

```powershell
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/render_story_batch.py --date <YYYY-MM-DD>
```

세 렌더 결과 각각이 `ffprobe`에서 1080×1920, H.264, 30fps, 6.0초, `yuv420p`를 모두 만족해야 한다.
