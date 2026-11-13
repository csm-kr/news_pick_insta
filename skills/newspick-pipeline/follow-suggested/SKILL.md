---
name: follow-suggested
description: newspick_studio Instagram 계정에서 '회원님을 위한 추천(모두 보기)' 계정을 천천히 팔로우해 맞팔로 팔로워를 늘린다. "추천 계정 팔로우", "모두 보기 눌러서 팔로우", "팔로워 늘려" 같은 요청과 팔로우·언팔 자동 예약 관리에 사용한다.
---

# Follow Suggested

ego lite 기본 프로필에 로그인된 Instagram 탭(TaskSpace `newspick-growth`, 게시용 `newspick-instagram`과 분리)에서 `/explore/people/`('모두 보기')과 같은 추천 쿼리로 계정을 받아 팔로우한다. 목적은 맞팔로 팔로워 수를 늘리는 것이고, 맞팔하지 않은 계정은 매주 `unfollow-non-followers`가 정리한다. 스크립트: `scripts/follow_suggested.py`

## 절차

1. **수동 실행**:
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; python skills/newspick-pipeline/follow-suggested/scripts/follow_suggested.py --limit 30
   ```
   ego TaskSpace에 Instagram 탭이 없으면 스크립트가 홈을 연다(`ego-browser` CLI 필요). 30개면 30~40분 걸리므로 백그라운드로 돌린다.
2. **진행 보고**: `output/follow/follow_log.jsonl`의 오늘 날짜 줄 수로 보고한다. 예약 실행 출력은 `output/follow/run-YYYYMMDD-HHMM.log`에 남는다.

## 자동 예약

`scripts/manage_windows_growth_schedule.ps1 install|status|remove`로 관리한다.

| 작업 | 시각 | 내용 |
|---|---|---|
| `NewsPickFollow-Morning` | 매일 08:00~10:50 사이 무작위 | `--session morning` |
| `NewsPickFollow-Afternoon` | 매일 13:00~15:30 사이 무작위 | `--session afternoon` |
| `NewsPickFollow-Evening` | 매일 20:00~23:00 사이 무작위 | `--session evening` |
| `NewsPickUnfollow-Weekly` | 매주 월·목요일 00:30 | `unfollow_non_followers.py --auto`, 팔로우한 지 7일 안 된 계정은 남긴다 |

시작 시각은 작업 스케줄러의 RandomDelay가 매일 다르게 정한다. `--session`은 날짜로 시드를 준 `daily_plan()`으로 그날 목표(40~55명)와 실제로 돌 구간(2~3개)을 정하고, `follow_log.jsonl`의 오늘 건수를 빼서 이번 몫을 나눈다(구간당 최대 30). 쉬는 구간이어도 앞 구간이 실패해 뒤 구간만으로 못 채우면 돈다. 예전 `NewsPickFollow-1000`·`-2100`은 `install` 때 지운다.

## 대상 선정 (스크립트에 내장)

- 건너뛴다: 비공개 계정(요청만 걸려 팔로워로 잘 안 이어진다), 이미 팔로우·요청 중인 계정, 이미 나를 팔로우하는 계정
- 다시 팔로우하지 않는다: `follow_log.jsonl`에 있는 계정, `output/unfollow/*/unfollow_log.jsonl`에서 언팔한 계정(맞팔을 안 해 준 계정)
- 추천은 한 번에 30개 남짓만 온다(`more_available`이 false여도 다음 호출에 몇 개 더 온다). 날마다 거의 같은 계정이라 금방 바닥난다(10-23·24에 2·4명).
- 추천만으로 몫을 못 채우면 최근 14일 안에 팔로우한 계정 5개를 골라 `/api/v1/discover/chaining/?target_id=`('비슷한 계정', 계정당 최대 80개)로 후보를 더한다. 이 응답에는 `friendship_status`가 없어 이미 나를 팔로우하는 계정이 섞일 수 있다.

## 안전장치

- 팔로우 1건마다 40~70초 쉰다.
- 예약 게시 run(06:30·11:30·16:30 시작, 19:00 스토리) 15분 전부터 종료까지는 시작하지 않고, 실행 중이면 다음 run 15분 전에 멈춘다(`unfollow_non_followers.py`의 시간표를 같이 쓴다).
- 응답이 `status: ok`이면서 `following` 또는 `outgoing_request`가 true가 아니면 즉시 멈춘다. 작업 차단일 수 있으니 재시도를 반복하지 않는다.
- 속도와 1회 상한(30)을 올리지 않는다. 하루 목표는 사용자 지시(2026-10-28)로 40명 이상이다. 팔로우 제한이 걸리면 예약 게시까지 막힐 수 있다.

## 주의

- 추천 목록은 `require("CometRelay").fetchQuery(require("PolarisRelayEnvironment"), require("PolarisUserActionLoadSULV2Query.graphql"), {data: {module: "discover_people", ...}})`로 받는다. `/graphql/query`를 직접 fetch하면 403 HTML이 온다(2026-10-19 확인).
- 팔로우는 `require("PolarisInstapi").apiPost("/api/v1/friendships/create/{target_user_id}/", ...)`로 한다. 웹 팔로우 버튼과 같은 호출이다.
