---
name: publish-daily-news-story
description: 지정일에 올린 공개 검증 뉴스픽 게시물 전부의 1024×1024 표지를 FFmpeg로 6초 세로 MP4에 이어 Instagram Story로 게시한다. "오늘 올린 거 전부 스토리로", "4개면 4개 모두 올려" 같은 일일 요약 스토리 요청에 사용한다.
---

# Publish Daily News Story

지정일의 검증된 뉴스픽 게시물 전부를 한 장씩 보여주는 무음 Story 영상으로 만든다. 각 1024×1024 표지는 1080×1920 화면 중앙에 원형 그대로 놓고, 같은 표지를 확대한 어두운 블러 배경 위에서 0.4초 크로스페이드한다. 장수와 관계없이 완성 영상은 정확히 6초, H.264, 30fps, `yuv420p`, fast-start MP4여야 한다.

## 입력 선택

- `NEWS_PICK_OUTPUT_ROOT` 또는 `--output-root`의 `runs/`를 읽는다.
- 기준일은 Asia/Seoul의 오늘이며 `--date YYYY-MM-DD`로 바꿀 수 있다.
- `04-publish/result.json`이 `status=published`, `public_verified=true`, `first_card_match=true`인 run만 허용한다.
- `04-publish/result.json`의 `verified_at`을 Asia/Seoul로 해석해 기준일에 공개 검증 완료된 run을 전부 포함한다. 이것을 그날 게시 완료 목록의 기준으로 사용한다.
- 해당 날짜 후보가 하나도 없으면 게시하지 않는다. 3개면 3개, 4개면 4개처럼 발견된 전부를 `verified_at` 순서로 사용하며 임의로 일부를 빼거나 덜 검증된 run을 보충하지 않는다.
- 각 run의 실제 표지는 `03-create/slides/01.png`이며 1024×1024인지 확인한다.

## 한 번에 실행

사용자가 생성과 게시를 모두 명시적으로 요청했을 때만 다음을 실행한다.

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = '<workspace>/output'
$env:IG_ACCOUNT = 'newspick_studio'
python scripts/run_daily_story.py --date <YYYY-MM-DD> --account $env:IG_ACCOUNT --publish
```

이 명령은 후보 선택, FFmpeg 렌더, `ffprobe` 검증, 게시물별 proof frame 생성, 계정 probe, Story 업로드, 공개 Story 확인을 순서대로 한 번만 수행한다. 출력은 `<NEWS_PICK_OUTPUT_ROOT>/daily-story/<YYYY-MM-DD>/` 아래의 `story.mp4`, `manifest.json`, 게시물 수만큼의 `proof-NN.jpg`, `result.json`, `verified.png`다.

사용자가 게시를 요청하지 않았다면 미리보기까지만 만든다.

```powershell
python scripts/run_daily_story.py --date <YYYY-MM-DD>
```

모든 proof frame과 manifest의 전체 source run, Instagram URL, SHA-256을 확인한 뒤 결과를 보여준다. 사용자가 이후 게시를 승인하면 같은 명령에 `--publish`를 붙인다. 이미 `status=published`인 동일 SHA-256 결과는 재게시하지 않고 성공으로 재사용한다.

## 매일 21시 예약 게시

사용자가 매일 `21:00` KST Story 게시를 명시적으로 승인한 계정에서는 그 승인을 예약 실행의 standing approval로 적용한다. 예약 실행은 당일 `verified_at`에 해당하는 공개 검증 뉴스 캐러셀 전부의 `01.png` 대문을 사용하며, 후보가 없을 때만 만들거나 게시하지 않는다.

```powershell
python scripts/scheduled_story_runner.py --dry-run
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage_windows_story_schedule.ps1 remove
```

Windows 작업은 매일 `21:00` KST에 시작한다. 같은 날짜의 상태 파일이 이미 있으면 중복 실행하지 않고, `21:30`을 넘긴 missed run은 보충 게시하지 않는다. 상태는 `<NEWS_PICK_OUTPUT_ROOT>/scheduler/daily-story/editions/`, 로그는 `<NEWS_PICK_OUTPUT_ROOT>/logs/scheduler/daily-story/`에 기록한다. 업로드 시작 뒤 오류나 공개 검증 실패는 `needs_review`로 끝내며 자동 재시도하지 않는다.

## 게시 불변 조건

- 게시라는 외부 변경에는 현재 대화의 명시적 승인이 필요하다. 단순 제작·미리보기 요청은 게시 권한이 아니다.
- 지정된 `IG_ACCOUNT`와 현재 표시형 Instagram profile 계정이 일치해야 한다.
- Browser Harness로 현재 로그인 세션을 메모리 안에서만 전달한다. cookie, `sessionid`, password, MFA 정보를 출력하거나 저장하지 않는다.
- private API 계정 probe가 성공한 뒤 `video_upload_to_story()`를 한 번만 호출한다.
- 업로드 시작 뒤 timeout·오류·공개 확인 실패가 나면 `needs_review`로 끝내고 자동 재시도하지 않는다.
- 기존 `result.json`이 `needs_review`이고 `submission_started=true`면 공개 Story를 사람이 확인하기 전에는 다시 올리지 않는다.
- 공개 확인은 background target에서 수행하고 기존 Chrome tab과 focus를 보존한다.

## 개발과 검증

FFmpeg·ffprobe·Pillow·Browser Harness와 `publish-news-pick`이 준비한 project-local `instagrapi` venv가 필요하다.

```powershell
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/render_story_video.py --date <YYYY-MM-DD>
```

렌더 결과는 `ffprobe`에서 1080×1920, H.264, 30fps, 6.0초, `yuv420p`를 모두 만족해야 한다.
