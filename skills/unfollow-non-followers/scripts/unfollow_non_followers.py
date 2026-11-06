#!/usr/bin/env python3
"""ego lite의 Instagram 탭(TaskSpace newspick-growth)에서 맞팔이 아닌 팔로잉을 찾고 천천히 팔로우 취소한다."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time as time_module
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PUBLISH_SCRIPTS = Path(__file__).resolve().parents[2] / "publish-news-pick" / "scripts"
if str(PUBLISH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PUBLISH_SCRIPTS))
import ego_harness  # noqa: E402


KST = ZoneInfo("Asia/Seoul")
# 예약 run(07·12·17시 게시, 19시 스토리)이 같은 Instagram 계정을 쓰는 시작~종료 시각
SCHEDULED_RUNS = (
    (time(6, 30), time(7, 40)),
    (time(11, 30), time(12, 40)),
    (time(16, 30), time(17, 40)),
    (time(19, 0), time(19, 40)),
)
GUARD = timedelta(minutes=15)
# follow-suggested 스킬이 남기는 팔로우 기록. 최근에 팔로우한 계정은 맞팔할 시간을 준다
FOLLOW_LOG = Path("output/follow/follow_log.jsonl")
# 게시 helper의 `newspick-instagram` 탭(작성기)과 섞이지 않게 팔로우·언팔은 별도 ego TaskSpace를 쓴다.
GROWTH_SPACE = "newspick-growth"

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
  const s = await fetch(`/api/v1/friendships/show/${id}/`, {headers: H, credentials: "include"});
  if (!s.ok) return {step: "show", status: s.status, body: (await s.text()).slice(0, 200)};
  const f = await s.json();
  if (f.followed_by) return {step: "skip_mutual"};
  if (!f.following && !f.outgoing_request) return {step: "skip_not_following"};
  // 웹 화면의 언팔 버튼과 같은 호출이다. 직접 fetch하면 HTML이 오므로 페이지의 PolarisInstapi를 쓴다
  const nav = window.require("IGNavChain").getInstance();
  try {
    const r = await window.require("PolarisInstapi").apiPost("/api/v1/friendships/destroy/{target_user_id}/", {
      body: {container_module: "profile", nav_chain: nav ? nav.getNavChainForSend() : "", user_id: id},
      path: {target_user_id: id}});
    const following = r.data && r.data.friendship_status ? r.data.friendship_status.following : null;
    return {step: "unfollow", status: r.statusCode, body: JSON.stringify({status: r.status, following})};
  } catch (e) {
    return {step: "unfollow", status: (e && e.statusCode) || 0, body: String(e).slice(0, 200)};
  }
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


def recent_follow_ids(log_path: Path, now: datetime, days: int) -> set[str]:
    if not log_path.is_file():
        return set()
    cutoff = now - timedelta(days=days)
    ids = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("step") == "follow" and datetime.fromisoformat(row["at"]) > cutoff:
                ids.add(row["id"])
    return ids


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


def ensure_browser() -> None:
    """ego lite가 꺼져 있으면 켜고, 응답할 때까지 기다린다."""
    if not shutil.which("ego-browser"):
        raise SystemExit("ego-browser CLI가 없다. ego lite를 설치하거나 PATH를 확인한다.")
    ego_harness.ensure_ego_running()


def log_to_file_if_windowless(path: Path) -> None:
    """pythonw로 예약 실행되면 stdout이 없으므로 출력을 파일로 돌린다."""
    if sys.stdout is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = path.open("a", encoding="utf-8", buffering=1)


def wait_for_page_modules(send, attempts: int = 30, sleep=time_module.sleep) -> None:
    """페이지 모듈(window.require)이 없으면 탭을 Instagram 홈으로 다시 열고 로드될 때까지 기다린다."""
    check = {"expression": "typeof window.require", "returnByValue": True}
    navigated = False
    for _ in range(attempts):
        if send("Runtime.evaluate", check).get("result", {}).get("value") == "function":
            return
        if not navigated:
            send("Page.navigate", {"url": "https://www.instagram.com/"})
            navigated = True
        sleep(1)
    raise SystemExit("Instagram 탭에 페이지 모듈(window.require)이 로드되지 않는다.")


def _evaluate_on_ego(expression: str, timeout: int):
    transport = ego_harness.BridgeTransport(space=GROWTH_SPACE, call_timeout=timeout + 30)
    try:
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/", cdp_timeout_ms=timeout * 1000)

        def send(method: str, params: dict) -> dict:
            return session.send({"method": method, "params": params, "session_id": None}).get("result", {})

        wait_for_page_modules(send)
        return send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
    finally:
        transport.close()


def evaluate(expression: str, timeout: int = 600):
    result = _evaluate_on_ego(expression, timeout)
    if "exceptionDetails" in result:
        raise SystemExit("브라우저 스크립트 실패: " + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:500])
    return result["result"].get("value")


def collect(out_dir: Path, exclude: set[str], exclude_ids: set[str] = frozenset()) -> Path:
    data = evaluate(FETCH_LISTS_JS)
    targets = [u for u in non_mutual(data["following"], data["followers"], exclude) if u["id"] not in exclude_ids]
    path = out_dir / "targets.json"
    path.write_text(json.dumps({
        "collected_at": datetime.now(KST).isoformat(timespec="seconds"),
        "following_count": len({u["id"] for u in data["following"]}),
        "followers_count": len({u["id"] for u in data["followers"]}),
        "targets": targets,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"팔로잉 {len(data['following'])} · 팔로워 {len(data['followers'])} · 맞팔 아님 {len(targets)}"
          f" (최근 팔로우 유예 {len(exclude_ids)}개 제외) → {path}", flush=True)
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
    parser.add_argument("--out-dir", type=Path, default=Path("output/unfollow") / datetime.now(KST).strftime("%Y%m%d"))
    parser.add_argument("--apply", action="store_true", help="targets.json 대상을 실제로 팔로우 취소한다")
    parser.add_argument("--auto", action="store_true", help="예약 실행용: 목록을 추출한 뒤 바로 팔로우 취소한다")
    parser.add_argument("--exclude", default="", help="남길 계정, 쉼표 구분")
    parser.add_argument("--min-follow-age-days", type=int, default=7,
                        help="follow-suggested로 팔로우한 지 이 일수가 안 된 계정은 대상에서 뺀다")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    log_to_file_if_windowless(args.out_dir / "run.log")
    now = datetime.now(KST)
    if in_busy_window(now):
        print("예약 run 시간대(시작 15분 전~종료)라 Instagram을 건드리지 않는다.")
        return 3
    ensure_browser()
    if args.apply:
        return apply(args.out_dir)
    recent = recent_follow_ids(FOLLOW_LOG, now, args.min_follow_age_days)
    collect(args.out_dir, {name for name in args.exclude.split(",") if name.strip()}, recent)
    if args.auto:
        return apply(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
