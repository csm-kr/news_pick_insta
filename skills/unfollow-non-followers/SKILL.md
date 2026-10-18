---
name: unfollow-non-followers
description: newspick_studio Instagram 계정에서 나를 팔로우하지 않는(맞팔이 아닌) 팔로잉을 찾아 천천히 팔로우 취소한다. "맞팔 아닌 사람 언팔", "나 안 따라오는 계정 정리", "맞팔만 남겨" 같은 요청에 사용한다.
---

# Unfollow Non-Followers

Edge 디버그 프로필(CDP `127.0.0.1:9333`)에 로그인된 Instagram 탭에서 인스타그램 웹 API를 호출해 맞팔이 아닌 팔로잉을 정리한다. 스크립트: `scripts/unfollow_non_followers.py`

## 절차

1. **Edge 확인**: `curl -s http://127.0.0.1:9333/json/list`에 `instagram.com` 탭이 있어야 한다. 없으면 `skills/publish-news-pick/scripts/launch_edge_profile.py --account newspick_studio`로 연다. 기존 탭을 닫거나 다른 페이지로 옮기지 않는다.
2. **목록 추출(읽기 전용)**:
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; python skills/unfollow-non-followers/scripts/unfollow_non_followers.py --out-dir output/unfollow/<YYYYMMDD>
   ```
   남길 계정이 있으면 `--exclude "name1,name2"`를 붙인다. 결과는 `targets.json`에 저장된다. 대상 수와 대표 계정을 사용자에게 보여 주고, 사용자가 이미 "다 지워"라고 승인한 경우가 아니면 확인을 받는다.
3. **팔로우 취소**: 같은 `--out-dir`에 `--apply`를 붙여 **백그라운드로** 실행한다. 몇 시간 걸린다.
4. **진행 보고**: `unfollow_log.jsonl`의 줄 수와 `step`별 개수(`unfollow`, `skip_mutual`, `skip_not_following`)로 보고한다.

## 안전장치 (스크립트에 내장)

- 취소 직전에 계정마다 `friendships/show`로 맞팔 여부를 다시 확인하고 맞팔이면 건너뛴다. 목록 페이지를 넘기다 누락된 팔로워가 있어도 맞팔은 끊기지 않는다.
- 속도: 취소 1건마다 35~60초, 20건마다 10~13분 쉰다. 150건이면 약 3시간이다.
- 예약 run(06:30·11:30·16:30 시작 게시, 19:00 스토리)과 Edge를 같이 쓰므로 각 run 시작 15분 전부터 종료까지는 시작하지 않고, 실행 중이면 다음 run 15분 전에 멈춘다.
- 응답이 `{"status":"ok"}` JSON이 아니면(HTML, 429, 작업 차단 등) 즉시 멈춘다. 이때 재시도를 반복하지 말고 몇 시간 뒤 같은 명령으로 재개한다.
- 성공한 계정만 `unfollow_log.jsonl`에 남기므로, 같은 `--out-dir`로 `--apply`를 다시 실행하면 남은 계정부터 이어서 한다.

## 주의

- 팔로우 취소는 페이지 내부 모듈 `require("PolarisInstapi").apiPost("/api/v1/friendships/destroy/{target_user_id}/", {body: {container_module, nav_chain, user_id}})`로 한다. 웹 언팔 버튼과 같은 호출이다. `/api/v1/web/friendships/{id}/unfollow/`는 2026-10-18부터 404 HTML을 돌려주고, destroy 경로도 직접 `fetch`하면 HTML이 온다.
- 대량 취소는 인스타그램 작업 제한을 부를 수 있고, 제한이 걸리면 예약 게시까지 막힐 수 있다. 속도 상수를 올리지 않는다.
