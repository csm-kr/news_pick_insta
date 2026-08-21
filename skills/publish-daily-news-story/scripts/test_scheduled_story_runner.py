from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("scheduled_story_runner.py")
SPEC = importlib.util.spec_from_file_location("scheduled_story_runner", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class ScheduledStoryRunnerTests(unittest.TestCase):
    def settings(self, root: Path):
        return {"output_root": root / "output", "account": "newspick_studio"}

    def test_story_time_uses_korean_time(self):
        value = MOD.story_at(date(2026, 8, 20))
        self.assertEqual(value.isoformat(), "2026-08-20T21:00:00+09:00")

    def test_start_window_rejects_early_and_catch_up_runs(self):
        target = MOD.story_at(date(2026, 8, 20))
        self.assertFalse(MOD.within_start_window(target, target - timedelta(seconds=1)))
        self.assertTrue(MOD.within_start_window(target, target))
        self.assertTrue(MOD.within_start_window(target, target + timedelta(minutes=30)))
        self.assertFalse(
            MOD.within_start_window(target, target + timedelta(minutes=30, seconds=1))
        )

    def test_dry_run_uses_story_publish_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self.settings(root)
            target = MOD.story_at(date(2026, 8, 20))
            with patch.object(MOD, "dependency_paths", return_value={"ok": "yes"}):
                code, result = MOD.run_job(
                    root, target, settings, target - timedelta(hours=1), dry_run=True
                )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "dry_run")
            self.assertIn("--publish", result["command"])
            self.assertIn("2026-08-20", result["command"])

    def test_existing_state_suppresses_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self.settings(root)
            target = MOD.story_at(date(2026, 8, 20))
            state = (
                settings["output_root"]
                / "scheduler"
                / "daily-story"
                / "editions"
                / "2026-08-20-2100.json"
            )
            MOD.atomic_json(state, {"status": "published"})
            with patch.object(MOD, "dependency_paths", return_value={"ok": "yes"}):
                code, result = MOD.run_job(root, target, settings, target)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "duplicate_suppressed")

    def test_published_result_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self.settings(root)
            target = MOD.story_at(date(2026, 8, 20))
            response = {
                "ok": True,
                "result": {
                    "publish": {
                        "status": "published",
                        "public_verified": True,
                        "story_url": "https://www.instagram.com/stories/newspick_studio/1/",
                    }
                },
            }
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr=""
            )
            with patch.object(MOD, "dependency_paths", return_value={"ok": "yes"}), patch.object(
                MOD.subprocess, "run", return_value=completed
            ):
                code, result = MOD.run_job(root, target, settings, target)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "published")


if __name__ == "__main__":
    unittest.main()
