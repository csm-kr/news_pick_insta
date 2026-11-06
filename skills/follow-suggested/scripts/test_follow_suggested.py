from __future__ import annotations

import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
