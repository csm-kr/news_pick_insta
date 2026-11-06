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


class RecentFollowTests(unittest.TestCase):
    def test_only_follows_within_grace_days_are_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow_log.jsonl"
            rows = [
                {"id": "old", "step": "follow", "at": "2026-09-18T10:00:00+09:00"},
                {"id": "new", "step": "follow", "at": "2026-09-24T21:00:00+09:00"},
            ]
            log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            self.assertEqual(MOD.recent_follow_ids(log, at(0, 30), days=7), {"new"})

    def test_missing_follow_log_means_no_recent_follows(self):
        self.assertEqual(MOD.recent_follow_ids(Path("없는/follow_log.jsonl"), at(0, 30), days=7), set())


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

    def test_edge_connection_is_gone(self):
        for name in ("CDP_URL", "LAUNCH_EDGE", "ensure_edge", "_has_instagram_tab", "is_instagram_app_tab"):
            self.assertFalse(hasattr(MOD, name), name)

    def test_reopens_instagram_home_when_page_modules_are_missing(self):
        calls, answers = [], iter(["undefined", "undefined", "function"])

        def send(method, params):
            calls.append(method)
            if method == "Runtime.evaluate":
                return {"result": {"value": next(answers)}}
            return {}

        MOD.wait_for_page_modules(send, attempts=5, sleep=lambda _s: None)
        self.assertEqual(calls.count("Page.navigate"), 1)
        self.assertEqual(calls[-1], "Runtime.evaluate")

    def test_ready_page_is_not_navigated(self):
        calls = []

        def send(method, params):
            calls.append(method)
            return {"result": {"value": "function"}}

        MOD.wait_for_page_modules(send, attempts=5, sleep=lambda _s: None)
        self.assertNotIn("Page.navigate", calls)

    def test_gives_up_when_page_modules_never_load(self):
        def send(method, params):
            return {"result": {"value": "undefined"}}

        with self.assertRaises(SystemExit):
            MOD.wait_for_page_modules(send, attempts=3, sleep=lambda _s: None)


class FakeEgoTransport:
    """ego_bridge 대신 탭·goto·page_cdp만 흉내 낸다."""

    instances = []

    def __init__(self, space, call_timeout=120.0):
        self.space = space
        self.call_timeout = call_timeout
        self.tabs = [{"label": "p1", "url": "about:blank", "title": ""}]
        self.calls = []
        self.closed = False
        FakeEgoTransport.instances.append(self)

    def call(self, op):
        self.calls.append(op)
        if op["op"] == "tabs":
            return [dict(t) for t in self.tabs]
        if op["op"] == "goto":
            self.tabs[0]["url"] = op["url"]
            return {}
        if op["op"] == "page_cdp" and op["method"] == "Runtime.evaluate":
            if op["params"]["expression"] == "typeof window.require":
                return {"result": {"type": "string", "value": "function"}}
            return {"result": {"type": "object", "value": {"answer": 42}}}
        raise AssertionError(op)

    def close(self):
        self.closed = True


class EgoBrowserTests(unittest.TestCase):
    """2026-11-06부터 팔로우·언팔도 Edge 대신 ego lite를 쓴다(게시 탭과 분리된 newspick-growth)."""

    def setUp(self):
        FakeEgoTransport.instances = []

    def test_evaluate_runs_on_ego_growth_space_by_default(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {}, clear=True), patch.object(MOD.ego_harness, "BridgeTransport", FakeEgoTransport):
            value = MOD.evaluate("doWork()", timeout=60)
        self.assertEqual(value, {"answer": 42})
        transport = FakeEgoTransport.instances[-1]
        self.assertEqual(transport.space, "newspick-growth")
        self.assertTrue(transport.closed)
        self.assertIn({"op": "goto", "page": "p1", "url": "https://www.instagram.com/"}, transport.calls)
        expressions = [c["params"]["expression"] for c in transport.calls if c["op"] == "page_cdp"]
        self.assertEqual(expressions[-1], "doWork()")

    def test_ensure_browser_starts_ego_when_needed(self):
        from unittest.mock import patch
        with patch.object(MOD.shutil, "which", return_value="C:/bin/ego-browser.exe"), patch.object(
            MOD.ego_harness, "ensure_ego_running", return_value=True
        ) as ensure:
            MOD.ensure_browser()
        ensure.assert_called_once()

    def test_ensure_browser_requires_ego_cli(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {}, clear=True), patch.object(MOD.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit):
                MOD.ensure_browser()


if __name__ == "__main__":
    unittest.main()
