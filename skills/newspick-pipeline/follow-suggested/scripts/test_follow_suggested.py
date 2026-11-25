from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path


PATH = Path(__file__).with_name("follow_suggested.py")
SPEC = importlib.util.spec_from_file_location("follow_suggested", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def user(pk, private=False, following=False, outgoing=False, followed_by=False):
    return {"pk": pk, "username": f"u{pk}", "is_private": private,
            "friendship_status": {"following": following, "outgoing_request": outgoing, "followed_by": followed_by}}


class PickCandidatesTests(unittest.TestCase):
    def test_skips_private_already_related_and_logged_accounts(self):
        users = [
            user("1"),
            user("2", private=True),
            user("3", following=True),
            user("4", outgoing=True),
            user("5", followed_by=True),
            user("6"),
            user("1"),
            user("7"),
        ]
        picked = MOD.pick_candidates(users, skip_ids={"6"}, limit=10)
        self.assertEqual([u["id"] for u in picked], ["1", "7"])
        self.assertEqual(picked[0], {"id": "1", "username": "u1"})

    def test_stops_at_limit(self):
        users = [user(str(i)) for i in range(50)]
        self.assertEqual(len(MOD.pick_candidates(users, skip_ids=set(), limit=30)), 30)


class SkipIdsTests(unittest.TestCase):
    def test_collects_followed_and_unfollowed_ids_from_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "follow").mkdir()
            (root / "follow" / "follow_log.jsonl").write_text(
                json.dumps({"id": "10", "step": "follow"}) + "\n", encoding="utf-8")
            for day, rows in {"20261018": [{"id": "20", "step": "unfollow"}, {"id": "21", "step": "skip_mutual"}],
                              "20261025": [{"id": "30", "step": "unfollow"}]}.items():
                (root / "unfollow" / day).mkdir(parents=True)
                (root / "unfollow" / day / "unfollow_log.jsonl").write_text(
                    "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            self.assertEqual(MOD.skip_ids(root), {"10", "20", "30"})

    def test_missing_logs_mean_nothing_to_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(MOD.skip_ids(Path(tmp)), set())


class FollowResultTests(unittest.TestCase):
    def test_success_needs_ok_and_following_or_request(self):
        self.assertTrue(MOD.is_follow_success({"status": 200, "body": '{"status": "ok", "following": true, "outgoing_request": false}'}))
        self.assertTrue(MOD.is_follow_success({"status": 200, "body": '{"status": "ok", "following": false, "outgoing_request": true}'}))
        self.assertFalse(MOD.is_follow_success({"status": 200, "body": '{"status": "ok", "following": false, "outgoing_request": false}'}))
        self.assertFalse(MOD.is_follow_success({"status": 400, "body": "feedback_required"}))
        self.assertFalse(MOD.is_follow_success({"status": 200, "body": "<!DOCTYPE html>"}))

    def test_follow_uses_page_instapi_create_endpoint(self):
        self.assertIn('require("PolarisInstapi").apiPost("/api/v1/friendships/create/{target_user_id}/"', MOD.FOLLOW_JS)

    def test_suggestions_use_page_relay_query(self):
        self.assertIn('"PolarisUserActionLoadSULV2Query.graphql"', MOD.FETCH_SUGGESTIONS_JS)
        self.assertIn('module: "discover_people"', MOD.FETCH_SUGGESTIONS_JS)

    def test_similar_accounts_use_chaining_endpoint(self):
        self.assertIn("/api/v1/discover/chaining/?target_id=", MOD.FETCH_SIMILAR_JS)


def run_similar_js(responses: list[str]) -> dict:
    """FETCH_SIMILAR_JS를 node에서 돌린다. fetch는 responses를 차례로 200으로 돌려준다."""
    seeds = [str(i) for i in range(len(responses))]
    script = (
        "globalThis.setTimeout = (f) => f();\n"
        f"const bodies = {json.dumps(responses)};\n"
        "let calls = 0;\n"
        "globalThis.fetch = async () => { const b = bodies[calls++];\n"
        "  return {ok: true, text: async () => b, json: async () => JSON.parse(b)}; };\n"
        f"({MOD.FETCH_SIMILAR_JS % json.dumps(seeds)})\n"
        "  .then(users => console.log(JSON.stringify({users, calls})))\n"
        "  .catch(e => { console.log(JSON.stringify({error: String(e), calls})); });\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node가 없으면 JS 동작은 확인하지 않는다")
class SimilarAccountScriptTests(unittest.TestCase):
    def test_html_response_stops_quietly_and_keeps_users_already_fetched(self):
        # 11-24 비슷한 계정 응답이 HTML로 와서 JSON 파싱 오류로 그날 팔로우 세 번이 모두 0명이 됐다.
        # 비슷한 계정이 안 나오면 무리하지 않고 추천에서 고른 만큼만 팔로우한다(사용자 요청 11-25).
        result = run_similar_js([json.dumps({"users": [{"pk": "8", "username": "u8"}]}),
                                 "<!DOCTYPE html><html></html>",
                                 json.dumps({"users": [{"pk": "9", "username": "u9"}]})])
        self.assertNotIn("error", result)
        self.assertEqual([u["pk"] for u in result["users"]], ["8"])
        self.assertEqual(result["calls"], 2)

    def test_json_responses_are_all_collected(self):
        result = run_similar_js([json.dumps({"users": [{"pk": "8"}]}), json.dumps({"users": [{"pk": "9"}]})])
        self.assertEqual([u["pk"] for u in result["users"]], ["8", "9"])


class SimilarAccountTests(unittest.TestCase):
    def test_chaining_users_without_friendship_status_are_picked(self):
        users = [{"pk": "8", "username": "u8", "is_private": False},
                 {"pk": "9", "username": "u9", "is_private": True}]
        self.assertEqual([u["id"] for u in MOD.pick_candidates(users, skip_ids=set(), limit=10)], ["8"])


class DailyPlanTests(unittest.TestCase):
    def test_plan_is_stable_per_day_with_40_to_55_follows_over_2_or_3_sessions(self):
        for day in range(1, 29):
            d = date(2026, 11, day)
            target, active = MOD.daily_plan(d)
            self.assertEqual((target, active), MOD.daily_plan(d))
            self.assertTrue(40 <= target <= 55)
            self.assertIn(len(active), (2, 3))
            self.assertTrue(set(active) <= set(MOD.SESSIONS))

    def test_plans_differ_across_days(self):
        plans = {MOD.daily_plan(date(2026, 11, day)) for day in range(1, 29)}
        self.assertGreater(len(plans), 5)


class SessionQuotaTests(unittest.TestCase):
    def test_active_session_splits_remaining_over_itself_and_later_active_sessions(self):
        self.assertEqual(MOD.session_quota("morning", 45, ("morning", "afternoon", "evening"), followed=0), 15)
        self.assertEqual(MOD.session_quota("afternoon", 45, ("morning", "afternoon", "evening"), followed=15), 15)

    def test_last_active_session_takes_the_rest_up_to_session_cap(self):
        self.assertEqual(MOD.session_quota("evening", 50, ("morning", "evening"), followed=25), 25)
        self.assertEqual(MOD.session_quota("evening", 50, ("morning", "evening"), followed=0), MOD.SESSION_CAP)

    def test_inactive_session_skips_when_later_sessions_can_cover(self):
        self.assertEqual(MOD.session_quota("afternoon", 50, ("morning", "evening"), followed=25), 0)

    def test_inactive_session_runs_when_earlier_session_failed(self):
        # 오전이 실패해 45명이 남았고 저녁 한 번(상한 30)으로는 못 채운다
        self.assertEqual(MOD.session_quota("afternoon", 45, ("morning", "evening"), followed=0), 23)

    def test_nothing_left_means_no_follows(self):
        self.assertEqual(MOD.session_quota("evening", 40, ("morning", "evening"), followed=41), 0)


class FollowedOnTests(unittest.TestCase):
    def test_counts_only_follow_rows_of_that_kst_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow_log.jsonl"
            rows = [{"id": "1", "step": "follow", "at": "2026-10-27T23:59:00+09:00"},
                    {"id": "2", "step": "follow", "at": "2026-10-28T00:01:00+09:00"},
                    {"id": "3", "step": "follow", "at": "2026-10-28T21:30:00+09:00"},
                    {"id": "4", "step": "other", "at": "2026-10-28T10:00:00+09:00"}]
            log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            self.assertEqual(MOD.followed_on(log, date(2026, 10, 28)), 2)

    def test_missing_log_counts_zero(self):
        self.assertEqual(MOD.followed_on(Path("no-such-log.jsonl"), date(2026, 10, 28)), 0)


class GrowthScheduleTests(unittest.TestCase):
    def test_unfollow_runs_twice_a_week_on_monday_and_thursday(self):
        # 팔로우가 하루 40~50명이라 주 1회 언팔로는 팔로잉만 쌓였다(사용자 요청 11-12).
        script = PATH.with_name("manage_windows_growth_schedule.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("-Weekly -DaysOfWeek Monday, Thursday -At ([datetime]::Today.AddMinutes(30))", script)
        self.assertIn("target = 'Monday, Thursday 00:30'", script)

    def test_follow_tasks_start_late_when_the_scheduled_start_was_missed(self):
        # 11-15 저녁 팔로우가 21:32 시작을 놓친 뒤 대신 돌지 않고 다음 날로 넘어갔다.
        # 팔로우 세 작업만 놓친 시작을 나중에 대신 돈다(늦게 돌아도 하루 목표와 게시 시간대 보호는 스크립트가 지킨다).
        script = PATH.with_name("manage_windows_growth_schedule.ps1").read_text(encoding="utf-8-sig")
        specs = {line.split("name = '")[1].split("'")[0]: line
                 for line in script.splitlines() if "@{ name = 'NewsPick" in line}
        for name, line in specs.items():
            self.assertEqual("catchUp = $true" in line, name.startswith("NewsPickFollow-"), name)
        self.assertIn("-StartWhenAvailable:([bool]$spec.catchUp)", script)


if __name__ == "__main__":
    unittest.main()
