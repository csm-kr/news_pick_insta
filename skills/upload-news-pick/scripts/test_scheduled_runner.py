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
        self.assertTrue(MOD.within_start_window(scheduled, scheduled - timedelta(minutes=30)))
        self.assertFalse(MOD.within_start_window(scheduled, scheduled - timedelta(minutes=31)))
        self.assertTrue(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=30)))
        self.assertFalse(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=31)))

    def test_prompt_contains_standing_approval_and_fail_closed_rules(self):
        settings = {"output_root": Path("C:/work/output"), "account": "newspick_studio", "chrome_profile": "Profile 3"}
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 8, 18)), settings)
        self.assertIn("예약 정책 범위의 실게시를 사전 승인", prompt)
        self.assertIn("자동 재시도하지 않고", prompt)
        self.assertIn("자연스러운 뉴스 문단 하나", prompt)
        self.assertIn("공개 페이지에서 확인", prompt)
        self.assertIn("30분 전에 시작", prompt)
        self.assertIn("wait_for_publish_time.py", prompt)
        self.assertIn("edition_at 이전에 절대 누르지 않는다", prompt)
        self.assertIn("Get-Content -Raw -Encoding UTF8", prompt)
        self.assertIn("Tibo/GPT Image 백엔드로 전송", prompt)
        self.assertIn("references/content", prompt)
        self.assertIn("references/style", prompt)
        self.assertIn("--approve-public-reference-egress", prompt)
        self.assertIn("이 플래그가 빠진 생성 명령은 한 번도 시도하지 말고", prompt)
        self.assertIn("target editorial lane: popular_interest", prompt)
        self.assertIn("생활 관련성·대화 가치·4장 설명력·새로움", prompt)
        self.assertIn("정치·부동산", prompt)
        self.assertIn("하루 1건", prompt)
        self.assertIn("연속 편성하지 않는다", prompt)
        self.assertIn("browser_web_resolve_targets.py", prompt)
        self.assertIn("중복 Instagram target만 닫는다", prompt)
        self.assertIn("Instagram이 아닌 다른 사이트 탭은 절대 닫거나 탐색하지 않는다", prompt)

    def test_editorial_lane_uses_two_popular_slots_and_one_public_slot(self):
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 8, 18))), "popular_interest")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("12:00", date(2026, 8, 18))), "popular_interest")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("17:00", date(2026, 8, 18))), "public_impact")

    def test_recent_history_contains_only_public_verified_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "output"
            for run_id, topic, published in (
                ("20260818-070000-new", "science_technology", True),
                ("20260817-170000-old", "politics", True),
                ("20260817-120000-draft", "real_estate", False),
            ):
                run = output_root / "runs" / run_id
                (run / "01-search").mkdir(parents=True)
                (run / "04-publish").mkdir(parents=True)
                MOD.atomic_json(run / "01-search" / "selected-story.json", {"edition_at": run_id, "topic": topic, "verified_headline": topic})
                MOD.atomic_json(run / "04-publish" / "result.json", {"status": "published" if published else "submitted", "public_verified": published})
            history = MOD.recent_published_stories(output_root)
            self.assertEqual([item["topic"] for item in history], ["science_technology", "politics"])

    def test_find_codex_skips_binary_without_auto_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old-codex.exe"
            current = Path(tmp) / "current-codex.exe"
            old.touch()
            current.touch()
            with patch.object(MOD, "codex_candidates", return_value=[old, current]), patch.object(
                MOD, "supports_auto_approval", side_effect=lambda path: path == current.resolve()
            ):
                self.assertEqual(MOD.find_codex(), current.resolve())

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

    def test_dry_run_uses_auto_approval_without_conflicting_sandbox_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "upload-news-pick" / "references").mkdir(parents=True)
            settings = {"output_root": root / "output", "account": "newspick_studio", "chrome_profile": "Profile 3"}
            scheduled = MOD.edition_at("17:00", date(2026, 8, 18))
            with patch.object(MOD, "find_codex", return_value=Path(__file__)):
                code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30), dry_run=True)
            self.assertEqual(code, 0)
            self.assertIn("--approve-for-me", result["command"])
            self.assertNotIn("--sandbox", result["command"])

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
