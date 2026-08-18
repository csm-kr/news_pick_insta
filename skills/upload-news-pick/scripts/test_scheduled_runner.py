from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("scheduled_runner.py")
SPEC = importlib.util.spec_from_file_location("scheduled_runner", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class ScheduledRunnerTests(unittest.TestCase):
    def test_edition_uses_korean_time(self):
        value = MOD.edition_at("17:00", date(2026, 8, 18))
        self.assertEqual(value.isoformat(), "2026-08-18T17:00:00+09:00")

    def test_start_window_rejects_catch_up_posts(self):
        scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
        self.assertTrue(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=30)))
        self.assertFalse(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=31)))

    def test_prompt_contains_standing_approval_and_fail_closed_rules(self):
        settings = {"output_root": Path("C:/work/output"), "account": "newspick_studio", "chrome_profile": "Profile 3"}
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 8, 18)), settings)
        self.assertIn("예약 정책 범위의 실게시를 사전 승인", prompt)
        self.assertIn("자동 재시도하지 않고", prompt)
        self.assertIn("자연스러운 뉴스 문단 하나", prompt)
        self.assertIn("공개 페이지에서 확인", prompt)

    def test_existing_edition_state_suppresses_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "upload-news-pick" / "references").mkdir(parents=True)
            settings = {"output_root": root / "output", "account": "newspick_studio", "chrome_profile": "Profile 3"}
            scheduled = MOD.edition_at("12:00", date(2026, 8, 18))
            state = settings["output_root"] / "scheduler" / "editions" / "2026-08-18-1200.json"
            MOD.atomic_json(state, {"status": "published"})
            with patch.object(MOD, "find_codex", return_value=Path(__file__)):
                code, result = MOD.run_job(root, scheduled, settings, scheduled)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "duplicate_suppressed")

    def test_outside_window_records_skip_without_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "upload-news-pick" / "references").mkdir(parents=True)
            settings = {"output_root": root / "output", "account": "newspick_studio", "chrome_profile": "Profile 3"}
            scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
            with patch.object(MOD, "find_codex", return_value=Path(__file__)), patch.object(MOD.subprocess, "run") as run:
                code, result = MOD.run_job(root, scheduled, settings, scheduled + timedelta(hours=2))
            self.assertEqual(code, 0)
            self.assertEqual(result["reason"], "outside_start_window")
            run.assert_not_called()
            state = settings["output_root"] / "scheduler" / "editions" / "2026-08-18-0700.json"
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
