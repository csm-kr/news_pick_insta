import base64
import contextlib
import io
import itertools
import json
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import publish_story_batch


class BrowserStoryVerificationTests(unittest.TestCase):
    def run_task(self, change_state=None, capture_error=False, duplicate_urls=False):
        navigations = []
        captures = []
        closed = []
        reads = []
        urls = [f"https://www.instagram.com/stories/example/{index}/" for index in (1, 2, 3)]
        if duplicate_urls:
            urls[2] = urls[0]

        def fake_cdp(method, **arguments):
            if method == "Target.createTarget":
                self.assertTrue(arguments["background"])
                return {"targetId": "work"}
            if method == "Target.attachToTarget":
                return {"sessionId": "attached"}
            if method == "Target.closeTarget":
                closed.append(arguments["targetId"])
                return {}
            if method == "Page.captureScreenshot":
                captures.append(navigations[-1])
                if capture_error:
                    raise TimeoutError("capture timed out")
                return {"data": base64.b64encode(b"fresh-frame").decode("ascii")}
            self.fail(f"unexpected browser call: {method}")

        def fake_js(source):
            reads.append(source)
            state = {
                "url": navigations[-1],
                "focus": False,
                "text": "example",
                "login": False,
                "challenge": False,
                "videos": [{
                    "w": 720, "h": 1280, "ready": 4, "duration": 6.0,
                    "paused": True, "currentTime": 0.2, "error": None,
                }],
            }
            if change_state:
                change_state(state, len(reads))
            return state

        switch = types.FunctionType(
            (lambda: None).__code__, {"_send": Mock(), "_mark_tab": Mock()}
        )
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "verified-01.jpg"
            screenshot.write_bytes(b"stale-frame")
            environment = {
                "IG_ACCOUNT": "example",
                "IG_STORY_URLS_JSON": json.dumps(urls),
                "IG_STORY_VERIFY_SCREENSHOT_DIR": directory,
            }
            output = io.StringIO()
            error = None
            with patch.dict(os.environ, environment), contextlib.redirect_stdout(output), patch(
                "time.monotonic", side_effect=itertools.count(0, 5)
            ), patch("time.sleep"):
                try:
                    runpy.run_path(str(SCRIPTS / "browser_verify_video_story_batch.py"), init_globals={
                        "cdp": fake_cdp,
                        "js": fake_js,
                        "switch_tab": switch,
                        "current_tab": lambda: {"targetId": "previous"},
                        "goto_url": navigations.append,
                        "wait_for_load": lambda: None,
                    })
                except RuntimeError as exc:
                    error = str(exc)
            prefix = "INSTAGRAM_VIDEO_STORY_BATCH_VERIFY="
            records = [json.loads(line[len(prefix):]) for line in output.getvalue().splitlines() if line.startswith(prefix)]
            return {
                "result": records[-1] if records else None,
                "error": error,
                "navigations": navigations,
                "captures": captures,
                "closed": closed,
                "read_count": len(reads),
                "screenshot_bytes": screenshot.read_bytes(),
            }

    def test_three_loaded_exact_stories_capture_fresh_frames(self):
        outcome = self.run_task()
        self.assertIsNone(outcome["error"])
        self.assertTrue(outcome["result"]["ok"])
        self.assertEqual(outcome["result"]["story_count"], 3)
        self.assertEqual(outcome["captures"], outcome["navigations"])
        self.assertTrue(all(item["url_match"] for item in outcome["result"]["stories"]))
        self.assertEqual(outcome["screenshot_bytes"], b"fresh-frame")
        self.assertEqual(outcome["closed"], ["work"])

    def test_loading_timeout_never_captures_placeholder_or_reuses_old_file(self):
        def unloaded(state, count):
            state["videos"][0].update(w=0, h=0, ready=0, duration=None, currentTime=0)

        outcome = self.run_task(unloaded)
        record = outcome["result"]["stories"][0]
        self.assertFalse(outcome["result"]["ok"])
        self.assertEqual(record["failure"], "video_not_ready")
        self.assertIsNone(record["screenshot"])
        self.assertEqual(outcome["captures"], [])
        self.assertEqual(len(outcome["navigations"]), 1)
        self.assertEqual(outcome["screenshot_bytes"], b"stale-frame")

    def test_wrong_story_id_is_not_success_even_with_loaded_video(self):
        def wrong_story(state, count):
            state["url"] = "https://www.instagram.com/stories/example/99/"

        outcome = self.run_task(wrong_story)
        self.assertEqual(outcome["result"]["stories"][0]["failure"], "story_url_mismatch")
        self.assertEqual(outcome["captures"], [])
        self.assertEqual(len(outcome["navigations"]), 1)

    def test_focus_change_during_polling_stops_remaining_browser_work(self):
        def focus_change(state, count):
            state["videos"][0]["ready"] = 0
            state["focus"] = count >= 2

        outcome = self.run_task(focus_change)
        self.assertFalse(outcome["result"]["focus_preserved"])
        self.assertEqual(outcome["read_count"], 2)
        self.assertEqual(outcome["captures"], [])
        self.assertEqual(len(outcome["navigations"]), 1)
        self.assertEqual(outcome["closed"], ["work"])

    def test_focus_is_checked_before_and_after_screenshot(self):
        for change_at in (1, 2, 3):
            with self.subTest(change_at=change_at):
                def focus_change(state, count):
                    state["focus"] = count >= change_at

                outcome = self.run_task(focus_change)
                self.assertFalse(outcome["result"]["ok"])
                self.assertEqual(outcome["result"]["stories"][0]["failure"], "focus_changed")
                self.assertEqual(len(outcome["captures"]), 1 if change_at == 3 else 0)
                self.assertEqual(len(outcome["navigations"]), 1)

    def test_screenshot_timeout_does_not_accept_stale_file(self):
        outcome = self.run_task(capture_error=True)
        record = outcome["result"]["stories"][0]
        self.assertFalse(record["ok"])
        self.assertEqual(record["failure"], "screenshot_failed")
        self.assertIsNone(record["screenshot"])
        self.assertEqual(outcome["screenshot_bytes"], b"stale-frame")

    def test_playback_duration_and_portrait_dimensions_are_required(self):
        for invalid in ({"currentTime": 0}, {"duration": 18}, {"w": 1280, "h": 720}):
            with self.subTest(invalid=invalid):
                def invalid_video(state, count):
                    state["videos"][0].update(invalid)

                outcome = self.run_task(invalid_video)
                self.assertFalse(outcome["result"]["ok"])
                self.assertEqual(outcome["captures"], [])

    def test_duplicate_story_ids_fail_before_browser_creation(self):
        outcome = self.run_task(duplicate_urls=True)
        self.assertIn("distinct IDs", outcome["error"])
        self.assertEqual(outcome["navigations"], [])
        self.assertEqual(outcome["closed"], [])


class StoryRecoveryTests(unittest.TestCase):
    def test_focus_failure_skips_metadata_browser_call_and_keeps_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.json"
            result = {
                "submission_started": True,
                "submission": {"ok": True},
                "metadata_verification": {"ok": True},
                "stories": [{"story_pk": str(index), "story_url": f"https://www.instagram.com/stories/example/{index}/"} for index in (1, 2, 3)],
            }
            with patch.object(publish_story_batch.legacy, "harness_call", return_value=(1, {
                "ok": False, "focus_preserved": False, "story_count": 1,
            }, "focus changed")) as harness:
                updated = publish_story_batch.verify_existing(result, result_path, "example", [])
            self.assertEqual(harness.call_count, 1)
            self.assertEqual(updated["status"], "needs_review")
            self.assertFalse(updated["public_verified"])
            self.assertTrue(updated["submission"]["ok"])
            self.assertTrue(updated["metadata_verification"]["ok"])
            self.assertEqual(len(json.loads(result_path.read_text(encoding="utf-8"))["stories"]), 3)

    def test_complete_pending_batch_only_verifies_without_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = {
                "status": "needs_review", "submission_started": True,
                "input_set_sha256": "approved", "stories": [{}, {}, {}],
            }
            (root / "result.json").write_text(json.dumps(existing), encoding="utf-8")
            with patch.object(publish_story_batch, "load_manifest", return_value=(
                {"input_set_sha256": "approved"}, [], root
            )), patch.object(publish_story_batch, "verify_existing", return_value=existing) as verify, patch.object(
                publish_story_batch.legacy, "harness_call"
            ) as harness:
                publish_story_batch.publish(root / "manifest.json", "example", "approved")
            verify.assert_called_once()
            harness.assert_not_called()

    def test_partial_pending_batch_never_uploads_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.json").write_text(json.dumps({
                "status": "needs_review", "submission_started": True,
                "input_set_sha256": "approved", "stories": [{}],
            }), encoding="utf-8")
            with patch.object(publish_story_batch, "load_manifest", return_value=(
                {"input_set_sha256": "approved"}, [], root
            )), patch.object(publish_story_batch.legacy, "harness_call") as harness:
                with self.assertRaisesRegex(RuntimeError, "inspect Instagram"):
                    publish_story_batch.publish(root / "manifest.json", "example", "approved")
            harness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
