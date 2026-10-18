from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PATH = Path(__file__).with_name("unfollow_non_followers.py")
SPEC = importlib.util.spec_from_file_location("unfollow_non_followers", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)
KST = ZoneInfo("Asia/Seoul")


def at(hour, minute):
    return datetime(2026, 9, 26, hour, minute, tzinfo=KST)


class NonMutualTests(unittest.TestCase):
    def test_keeps_only_accounts_that_do_not_follow_back_without_duplicates(self):
        following = [
            {"id": "1", "username": "a"},
            {"id": "2", "username": "b"},
            {"id": "2", "username": "b"},
            {"id": "3", "username": "c"},
        ]
        followers = [{"id": "3", "username": "c"}, {"id": "9", "username": "z"}]
        self.assertEqual([u["id"] for u in MOD.non_mutual(following, followers)], ["1", "2"])

    def test_excluded_usernames_are_never_targets(self):
        following = [{"id": "1", "username": "Keep.Me"}, {"id": "2", "username": "drop"}]
        self.assertEqual(
            [u["username"] for u in MOD.non_mutual(following, [], exclude={"@keep.me"})],
            ["drop"],
        )


class ResultTests(unittest.TestCase):
    def test_only_json_ok_unfollow_counts_as_success(self):
        self.assertTrue(MOD.is_success({"step": "unfollow", "status": 200, "body": '{"status":"ok"}'}))
        self.assertFalse(MOD.is_success({"step": "unfollow", "status": 200, "body": "<!DOCTYPE html>"}))
        self.assertFalse(MOD.is_success({"step": "unfollow", "status": 429, "body": '{"status":"fail"}'}))
        self.assertFalse(MOD.is_success({"step": "show", "status": 400, "body": ""}))

    def test_unfollow_uses_page_instapi_destroy_endpoint(self):
        # 2026-10-18부터 /api/v1/web/friendships/{id}/unfollow/는 404 HTML을 돌려준다
        self.assertIn('require("PolarisInstapi").apiPost("/api/v1/friendships/destroy/{target_user_id}/"', MOD.UNFOLLOW_JS)
        self.assertNotIn("/api/v1/web/friendships/", MOD.UNFOLLOW_JS)

    def test_unfollow_body_keeps_status_even_when_response_is_long(self):
        # 전체 응답을 잘라 담으면 맨 끝의 "status":"ok"가 잘려 성공을 실패로 판정한다
        self.assertIn("body: JSON.stringify({status: r.status", MOD.UNFOLLOW_JS)
        self.assertNotIn("JSON.stringify(r).slice", MOD.UNFOLLOW_JS)

    def test_skips_are_normal_results(self):
        self.assertTrue(MOD.is_success({"step": "skip_mutual"}))
        self.assertTrue(MOD.is_success({"step": "skip_not_following"}))

    def test_resume_skips_ids_already_in_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            log.write_text(json.dumps({"id": "1", "step": "unfollow"}) + "\n", encoding="utf-8")
            targets = [{"id": "1", "username": "a"}, {"id": "2", "username": "b"}]
            self.assertEqual([u["id"] for u in MOD.pending(targets, log)], ["2"])


class ScheduleGuardTests(unittest.TestCase):
    def test_busy_during_scheduled_runs_and_guard_margin(self):
        self.assertTrue(MOD.in_busy_window(at(6, 20)))
        self.assertTrue(MOD.in_busy_window(at(7, 10)))
        self.assertTrue(MOD.in_busy_window(at(19, 20)))
        self.assertFalse(MOD.in_busy_window(at(8, 0)))
        self.assertFalse(MOD.in_busy_window(at(22, 0)))

    def test_deadline_is_before_next_scheduled_run(self):
        self.assertEqual(MOD.next_deadline(at(7, 45)), at(11, 15))
        self.assertEqual(MOD.next_deadline(at(17, 50)), at(18, 45))
        self.assertEqual(MOD.next_deadline(at(21, 0)).strftime("%m-%d %H:%M"), "09-27 06:15")


if __name__ == "__main__":
    unittest.main()
