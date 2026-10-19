from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
