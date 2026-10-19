#!/usr/bin/env python3
"""Edge CDP로 붙은 Instagram 탭에서 '회원님을 위한 추천(모두 보기)' 계정을 천천히 팔로우한다."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time as time_module
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unfollow-non-followers" / "scripts"))
from unfollow_non_followers import (  # noqa: E402
    KST, ensure_edge, evaluate, in_busy_window, log_to_file_if_windowless, next_deadline,
)


OUTPUT_ROOT = Path("output")
FOLLOW_LOG = OUTPUT_ROOT / "follow" / "follow_log.jsonl"

# '모두 보기'(/explore/people/) 화면과 같은 쿼리다. /graphql/query를 직접 fetch하면 403이므로 페이지의 Relay를 쓴다
FETCH_SUGGESTIONS_JS = """(async () => {
  const R = window.require;
  const env = R("PolarisRelayEnvironment");
  const q = R("PolarisUserActionLoadSULV2Query.graphql");
  const seen = [], users = [];
  for (let page = 0; page < 3; page++) {
    const res = await R("CometRelay").fetchQuery(env, q, {data: {max_id: "[" + seen.join(",") + "]",
      max_number_to_display: 30, module: "discover_people", paginate: true}}).toPromise();
    const a = res && res.ayml;
    const items = a ? (a.groups || []).flatMap(g => g.items || []) : [];
    const fresh = items.map(i => i.user).filter(u => u && u.pk && !seen.includes(u.pk));
    fresh.forEach(u => { seen.push(u.pk); users.push(u); });
    // more_available이 false여도 다음 호출에 몇 개 더 오므로 새 계정이 없을 때만 멈춘다
    if (fresh.length === 0) break;
    await new Promise(r => setTimeout(r, 1500 + Math.random() * 1500));
  }
  return users;
})()"""

# 웹 화면의 팔로우 버튼과 같은 호출이다
FOLLOW_JS = """(async (id) => {
  const nav = window.require("IGNavChain").getInstance();
  try {
    const r = await window.require("PolarisInstapi").apiPost("/api/v1/friendships/create/{target_user_id}/", {
      body: {container_module: "discover_people", include_follow_friction_check: true,
             nav_chain: nav ? nav.getNavChainForSend() : "", user_id: id},
      path: {target_user_id: id}});
    const fs = (r.data && r.data.friendship_status) || {};
    return {status: r.statusCode, body: JSON.stringify({status: r.status, following: fs.following === true,
      outgoing_request: fs.outgoing_request === true})};
  } catch (e) {
    return {status: (e && e.statusCode) || 0, body: String(e).slice(0, 200)};
  }
})(%s)"""


def pick_candidates(users: list[dict], skip_ids: set[str], limit: int) -> list[dict]:
    picked: list[dict] = []
    seen: set[str] = set()
    for user in users:
        uid = str(user["pk"])
        fs = user.get("friendship_status") or {}
        if (uid in seen or uid in skip_ids or user.get("is_private")
                or fs.get("following") or fs.get("outgoing_request") or fs.get("followed_by")):
            continue
        seen.add(uid)
        picked.append({"id": uid, "username": user["username"]})
        if len(picked) >= limit:
            break
    return picked


def _log_ids(path: Path, step: str) -> set[str]:
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("step") == step:
                ids.add(row["id"])
    return ids


def skip_ids(output_root: Path) -> set[str]:
    """이미 팔로우했던 계정과 맞팔이 아니라 언팔했던 계정은 다시 팔로우하지 않는다."""
    ids: set[str] = set()
    follow_log = output_root / "follow" / "follow_log.jsonl"
    if follow_log.is_file():
        ids |= _log_ids(follow_log, "follow")
    for log in sorted((output_root / "unfollow").glob("*/unfollow_log.jsonl")):
        ids |= _log_ids(log, "unfollow")
    return ids


def is_follow_success(result: dict) -> bool:
    if result.get("status") != 200:
        return False
    try:
        body = json.loads(result.get("body", ""))
    except json.JSONDecodeError:
        return False
    return body.get("status") == "ok" and (body.get("following") or body.get("outgoing_request"))


def run(limit: int) -> int:
    deadline = next_deadline(datetime.now(KST))
    users = evaluate(FETCH_SUGGESTIONS_JS, timeout=120) or []
    targets = pick_candidates(users, skip_ids(OUTPUT_ROOT), limit)
    print(f"추천 {len(users)}개 중 팔로우 대상 {len(targets)}개, {deadline:%H:%M}에 자동 중단", flush=True)
    FOLLOW_LOG.parent.mkdir(parents=True, exist_ok=True)
    followed = 0
    for user in targets:
        if datetime.now(KST) >= deadline:
            print("예약 run 전 중단 시각에 도달했다.")
            return 4
        result = evaluate(FOLLOW_JS % json.dumps(user["id"]), timeout=60)
        record = {"id": user["id"], "username": user["username"], "step": "follow",
                  "at": datetime.now(KST).isoformat(timespec="seconds"), **result}
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if not is_follow_success(result):
            print("비정상 응답이라 중단한다. 작업 차단일 수 있으니 다음 회차까지 기다린다.")
            return 2
        with FOLLOW_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        followed += 1
        time_module.sleep(random.uniform(40, 70))
    print(f"완료: 이번 실행에서 {followed}개 팔로우")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="한 번에 팔로우할 최대 계정 수")
    parser.add_argument("--jitter-minutes", type=float, default=0, help="예약 실행 시 시작 전 무작위로 기다릴 최대 분")
    args = parser.parse_args()
    log_to_file_if_windowless(FOLLOW_LOG.parent / f"run-{datetime.now(KST):%Y%m%d-%H%M}.log")
    time_module.sleep(random.uniform(0, args.jitter_minutes * 60))
    if in_busy_window(datetime.now(KST)):
        print("예약 run 시간대(시작 15분 전~종료)라 Edge를 건드리지 않는다.")
        return 3
    ensure_edge()
    return run(args.limit)


if __name__ == "__main__":
    sys.exit(main())
