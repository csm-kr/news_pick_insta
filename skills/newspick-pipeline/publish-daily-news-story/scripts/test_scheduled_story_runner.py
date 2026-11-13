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
        self.assertEqual(value.isoformat(), "2026-08-20T19:00:00+09:00")

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
                / "2026-08-20-1900.json"
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
                        "story_count": 3,
                        "stories": [
                            {"story_url": "https://www.instagram.com/stories/newspick_studio/1/"},
                            {"story_url": "https://www.instagram.com/stories/newspick_studio/2/"},
                            {"story_url": "https://www.instagram.com/stories/newspick_studio/3/"},
                        ],
                    }
                },
            }
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr=""
            )
            with patch.object(
                MOD,
                "dependency_paths",
                return_value={"ego_browser": "ego-browser.exe"},
            ), patch.object(
                MOD.subprocess, "run", side_effect=[completed]
            ) as run:
                code, result = MOD.run_job(root, target, settings, target)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "published")
            # Edge launcher 없이 스토리 실행기 하나만 돌고, 브라우저는 ego다.
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["env"]["NEWS_PICK_BROWSER"], "ego")
            self.assertNotIn("BU_CDP_URL", run.call_args.kwargs["env"])


    def test_run_job_starts_children_without_console_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self.settings(root)
            target = MOD.story_at(date(2026, 8, 20))
            completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            with patch.object(
                MOD, "dependency_paths", return_value={"ego_browser": "ego-browser.exe"}
            ), patch.object(MOD.subprocess, "run", side_effect=[completed]) as run:
                MOD.run_job(root, target, settings, target)
            for call in run.call_args_list:
                self.assertEqual(call.kwargs.get("creationflags", 0), MOD.NO_WINDOW_FLAGS)
            if MOD.sys.platform == "win32":
                self.assertEqual(MOD.NO_WINDOW_FLAGS, subprocess.CREATE_NO_WINDOW)

    def test_dependencies_require_ego_browser_not_edge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "newspick-pipeline" / "publish-daily-news-story" / "scripts").mkdir(parents=True)
            (root / "skills" / "newspick-pipeline" / "publish-daily-news-story" / "scripts" / "run_daily_story.py").write_text("", encoding="utf-8")
            output_root = root / "output"
            (output_root / "publish-news-pick" / "private-venv" / "Lib" / "site-packages").mkdir(parents=True)
            with patch.object(MOD.shutil, "which", side_effect=lambda name: f"C:/bin/{name}.exe"):
                dependencies = MOD.dependency_paths(root, output_root)
        self.assertEqual(dependencies["ego_browser"], "C:/bin/ego-browser.exe")
        self.assertNotIn("edge_launcher", dependencies)
        self.assertNotIn("browser_harness", dependencies)

    def test_windows_task_uses_pythonw_so_no_console_opens(self):
        script = Path(__file__).with_name("manage_windows_story_schedule.ps1").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", script)

if __name__ == "__main__":
    unittest.main()
