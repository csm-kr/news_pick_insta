#!/usr/bin/env python3
"""Edge CDP로 붙은 Instagram 탭에서 맞팔이 아닌 팔로잉을 찾고 천천히 팔로우 취소한다."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time as time_module
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import websocket


KST = ZoneInfo("Asia/Seoul")
CDP_URL = "http://127.0.0.1:9333"
# 예약 run(07·12·17시 게시, 19시 스토리)이 같은 Edge를 쓰는 시작~종료 시각
SCHEDULED_RUNS = (
    (time(6, 30), time(7, 40)),
    (time(11, 30), time(12, 40)),
    (time(16, 30), time(17, 40)),
    (time(19, 0), time(19, 40)),
)
GUARD = timedelta(minutes=15)

FETCH_LISTS_JS = """(async () => {
  const H = {"X-IG-App-ID": "936619743392459", "X-Requested-With": "XMLHttpRequest"};
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const uid = document.cookie.match(/ds_user_id=(\\d+)/)[1];
  async function all(kind) {
    const out = []; let max = "";
    for (let i = 0; i < 200; i++) {
      const r = await fetch(`/api/v1/friendships/${uid}/${kind}/?count=100${max ? "&max_id=" + max : ""}`, {headers: H, credentials: "include"});
      if (!r.ok) throw new Error(kind + " " + r.status);
      const j = await r.json();
      out.push(...j.users.map(u => ({id: u.pk_id || String(u.pk), username: u.username, full_name: u.full_name})));
      if (!j.next_max_id) break;
      max = j.next_max_id; await sleep(1500 + Math.random() * 1500);
    }
    return out;
  }
  return {uid, following: await all("following"), followers: await all("followers")};
})()"""

# 취소 직전에 맞팔 여부를 다시 확인한다. 목록 페이지 누락으로 맞팔을 끊지 않기 위한 장치다.
UNFOLLOW_JS = """(async (id) => {
  const H = {"X-IG-App-ID": "936619743392459", "X-Requested-With": "XMLHttpRequest"};
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)[1];
  const s = await fetch(`/api/v1/friendships/show/${id}/`, {headers: H, credentials: "include"});
  if (!s.ok) return {step: "show", status: s.status, body: (await s.text()).slice(0, 200)};
  const f = await s.json();
  if (f.followed_by) return {step: "skip_mutual"};
  if (!f.following && !f.outgoing_request) return {step: "skip_not_following"};
  const r = await fetch(`/api/v1/web/friendships/${id}/unfollow/`, {method: "POST", credentials: "include",
    headers: {...H, "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded"}, body: ""});
  return {step: "unfollow", status: r.status, body: (await r.text()).slice(0, 200)};
})(%s)"""


def non_mutual(following: list[dict], followers: list[dict], exclude: set[str] = frozenset()) -> list[dict]:
    follower_ids = {u["id"] for u in followers}
    excluded = {name.strip().lstrip("@").lower() for name in exclude}
    seen: set[str] = set()
    result = []
    for user in following:
        if user["id"] in seen or user["id"] in follower_ids or user["username"].lower() in excluded:
            continue
        seen.add(user["id"])
        result.append(user)
    return result


def is_success(result: dict) -> bool:
    if result["step"].startswith("skip_"):
        return True
    return result["step"] == "unfollow" and result.get("status") == 200 and '"ok"' in result.get("body", "")


def pending(targets: list[dict], log_path: Path) -> list[dict]:
    done = set()
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    return [u for u in targets if u["id"] not in done]


def _windows(day: datetime) -> list[tuple[datetime, datetime]]:
    return [
        (datetime.combine(day.date(), start, tzinfo=KST) - GUARD, datetime.combine(day.date(), end, tzinfo=KST))
        for start, end in SCHEDULED_RUNS
    ]


def in_busy_window(now: datetime) -> bool:
    return any(start <= now < end for start, end in _windows(now))


def next_deadline(now: datetime) -> datetime:
    for start, _ in _windows(now) + _windows(now + timedelta(days=1)):
        if start > now:
            return start
    raise AssertionError("다음 예약 run 시각을 찾지 못했다")


def evaluate(expression: str, timeout: int = 600):
    tabs = json.load(urllib.request.urlopen(f"{CDP_URL}/json/list", timeout=10))
    page = next((t for t in tabs if t["type"] == "page" and "instagram.com" in t["url"]), None)
    if page is None:
        raise SystemExit("Edge(9333)에 열린 instagram.com 탭이 없다. launch_edge_profile.py로 먼저 연다.")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break
    finally:
        ws.close()
    result = message["result"]
    if "exceptionDetails" in result:
        raise SystemExit("브라우저 스크립트 실패: " + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:500])
    return result["result"].get("value")


def collect(out_dir: Path, exclude: set[str]) -> Path:
    data = evaluate(FETCH_LISTS_JS)
    targets = non_mutual(data["following"], data["followers"], exclude)
    path = out_dir / "targets.json"
    path.write_text(json.dumps({
        "collected_at": datetime.now(KST).isoformat(timespec="seconds"),
        "following_count": len({u["id"] for u in data["following"]}),
        "followers_count": len({u["id"] for u in data["followers"]}),
        "targets": targets,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"팔로잉 {len(data['following'])} · 팔로워 {len(data['followers'])} · 맞팔 아님 {len(targets)} → {path}")
    return path


def apply(out_dir: Path) -> int:
    deadline = next_deadline(datetime.now(KST))
    targets = json.loads((out_dir / "targets.json").read_text(encoding="utf-8"))["targets"]
    log_path = out_dir / "unfollow_log.jsonl"
    todo = pending(targets, log_path)
    print(f"남은 대상 {len(todo)}개, {deadline:%H:%M}에 자동 중단", flush=True)
    unfollowed = 0
    for user in todo:
        if datetime.now(KST) >= deadline:
            print("예약 run 전 중단 시각에 도달했다. 같은 명령으로 이어서 실행하면 된다.")
            return 4
        result = evaluate(UNFOLLOW_JS % json.dumps(user["id"]), timeout=60)
        record = {"id": user["id"], "username": user["username"],
                  "at": datetime.now(KST).isoformat(timespec="seconds"), **result}
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if not is_success(result):
            # 로그에 남기지 않아야 재개할 때 이 계정을 다시 시도한다
            print("비정상 응답이라 중단한다. 작업 차단일 수 있으니 몇 시간 뒤 재개한다.")
            return 2
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        if result["step"] == "unfollow":
            unfollowed += 1
            time_module.sleep(random.uniform(35, 60))
            if unfollowed % 20 == 0:
                time_module.sleep(random.uniform(600, 780))
        else:
            time_module.sleep(random.uniform(3, 6))
    print(f"완료: 이번 실행에서 {unfollowed}개 취소")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="targets.json 대상을 실제로 팔로우 취소한다")
    parser.add_argument("--exclude", default="", help="남길 계정, 쉼표 구분")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if in_busy_window(datetime.now(KST)):
        print("예약 run 시간대(시작 15분 전~종료)라 Edge를 건드리지 않는다.")
        return 3
    if args.apply:
        return apply(args.out_dir)
    collect(args.out_dir, {name for name in args.exclude.split(",") if name.strip()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
