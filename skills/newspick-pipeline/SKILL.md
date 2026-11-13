---
name: newspick-pipeline
description: 뉴스픽(@newspick_studio) Instagram 카드뉴스 운영 전체를 맡는다. 검증된 한국 뉴스 한 건을 찾아 5장 1080×1350 카드로 기획·생성하고 ego lite에서 게시·공개 검증하는 일, 07·12·17시 예약 게시, 19시 Story, 추천 계정 팔로우, 맞팔 아닌 계정 언팔, 예약 등록·수정, 정규 회차 대체 기록까지 모두 이 스킬이다. "뉴스픽 하나 올려줘", "연예로 하나 올려", "카드뉴스 만들어줘", "오늘 뉴스 3개 스토리로", "추천 계정 팔로우해줘", "맞팔 아닌 사람 언팔", "예약 다시 걸어줘", "12시꺼 정규로 넣어줘"처럼 뉴스픽을 만들거나 올리거나 운영하는 요청이면 이 스킬을 쓴다. 진행 상황을 묻기만 하면 newspick-status를 쓴다.
---

# 뉴스픽 파이프라인

뉴스 검색부터 게시, Story, 팔로우·언팔, 예약까지 뉴스픽 운영 전부를 담은 스킬이다. 단계마다 자세한 안내가 하위 폴더에 있으니, 아래 표에서 하려는 일에 맞는 안내를 **그 일을 하기 직전에** 완전히 읽고 따른다. 진행 상황 보고는 형제 스킬 `newspick-status`가 맡는다.

## 하려는 일 → 읽을 안내

| 하려는 일 | 읽을 안내 |
|---|---|
| 뉴스픽 한 건 만들어 올리기(수동 1건, 예약 회차, 중단된 run 재개) | `upload-news-pick/SKILL.md` — 아래 네 단계를 차례로 부른다 |
| 1단계: 뉴스 찾기·교차검증 | `search-news/SKILL.md` |
| 2단계: 후킹·5장 스토리보드 | `plan-news-pick/SKILL.md` |
| 3단계: 카드 후보 15장 생성·세트 선택·QA | `create-news-cards/SKILL.md` |
| 4단계: Instagram 게시·4:5·AI 라벨·공개 검증 | `publish-news-pick/SKILL.md` |
| 19시 Story(그날 정규 3건 표지를 6초 영상으로) | `publish-daily-news-story/SKILL.md` |
| 추천 계정 팔로우 | `follow-suggested/SKILL.md` |
| 맞팔 아닌 계정 언팔 | `unfollow-non-followers/SKILL.md` |
| 예약 등록·확인 | 아래 "예약" |

한 건을 올릴 때는 `upload-news-pick/SKILL.md`부터 읽는다. 그 안내가 단계마다 해당 안내를 읽으라고 이끈다. 한 단계의 출력 검증이 끝나기 전에 다음 단계로 넘어가지 않는다.

## 모든 단계에 공통인 규칙

- **운영 위치와 설정**: 저장소 루트의 `AGENTS.md`와 `output/workspace.json`이 기준이다. `AGENTS.md` 맨 위에 운영 중지 문구가 있으면 자동 게시를 하지 않는다. 실행물은 모두 `NEWS_PICK_OUTPUT_ROOT`(기본 저장소 루트의 `output/`)에 쓰고, 스킬 폴더 안에는 쓰지 않는다.
- **Instagram 브라우저**: ego lite의 `뉴스픽` 프로필(`workspace.json`의 `browser.ego_profile_id`)만 쓴다. Instagram 조작은 `publish-news-pick/scripts/invoke_edge_browser_harness.py`를 거친다. 프로필이 다르면 연결이 막히며, 다른 프로필이나 브라우저로 우회하지 않는다. 연결마다 실제 프로필이 `output/logs/ego-sessions.jsonl`에 남는다.
- **공개 조사 브라우저**: 기사·공식 자료·reference 수집은 `aside-browser` 스킬과 Aside CLI로 한다. Instagram용 ego 공간에서 언론사·기관 사이트를 열지 않는다. 사용자가 연 탭은 건드리지 않는다.
- **게시 승인**: 모든 QA를 통과한 exact payload hash를 잠근 뒤 그 한 건만 승인한다. 공유는 한 번만 누르고, 실패하면 자동 재시도하지 않고 공개 프로필을 읽기 전용으로 확인한다. 기존 게시물을 지우거나 고치지 않는다.
- **정규 회차 대체**: 정규 회차가 빠져서 수동으로 올린 게시를 사용자가 그 회차로 넣으라고 하면 `output/scheduler/editions/<YYYY-MM-DD>-<HHMM>.replacement.json`에 `{slot, run_id, reason, approved_by: "user"}`를 남긴다. run 기록(`run.json`)은 고치지 않는다. 19시 Story와 보고가 이 기록을 읽는다.

## 예약

등록 스크립트는 저장소 루트를 작업 폴더로 등록한다. 운영 폴더를 옮기면 새 위치에서 세 개를 다시 `install`한다.

```powershell
powershell -ExecutionPolicy Bypass -File skills/newspick-pipeline/upload-news-pick/scripts/manage_windows_schedule.ps1 install          # 07·12·17시 게시(Claude Code)
powershell -ExecutionPolicy Bypass -File skills/newspick-pipeline/publish-daily-news-story/scripts/manage_windows_story_schedule.ps1 install  # 19시 Story
powershell -ExecutionPolicy Bypass -File skills/newspick-pipeline/follow-suggested/scripts/manage_windows_growth_schedule.ps1 install   # 팔로우·언팔·19:30 보고
python skills/newspick-pipeline/upload-news-pick/scripts/scheduled_runner.py --slot 12:00 --dry-run                                   # 실행 명령·프롬프트 확인
```

## 폴더 구성

```text
newspick-pipeline/
├── SKILL.md                     # 이 안내
├── upload-news-pick/            # 오케스트레이터, 예약 실행기(scheduled_runner.py), 게시 시각 게이트
├── search-news/                 # 뉴스 검색·검증
├── plan-news-pick/              # 기획·카피 QA
├── create-news-cards/           # 카드 생성·QA
├── publish-news-pick/           # 게시·검증, ego 연결(ego_harness.py, ego_bridge.mjs)
├── publish-daily-news-story/    # 19시 Story
├── follow-suggested/            # 팔로우, 팔로우·언팔·보고 예약 등록
└── unfollow-non-followers/      # 언팔
```

하위 폴더의 `SKILL.md`는 단계 안내다. 독립 스킬로 따로 설치하거나 부르지 않는다.
