from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("orchestrate.py")
SPEC = importlib.util.spec_from_file_location("pipeline_orchestrate", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class PipelineIntegrationTests(unittest.TestCase):
    def test_all_four_skills_contracts_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(MOD.init_run(Path(tmp), "2026-08-17T17:00:00+09:00", "newspick_studio")["run"])

            story = {
                "schema_version": "1.0",
                "story_id": "story-1",
                "edition_at": "2026-08-17T17:00:00+09:00",
                "topic": "real_estate",
                "verified_headline": "검증 문장",
                "why_it_matters": "국내 영향",
                "claims": [{"id": "c1", "text": "사실", "status": "verified", "evidence_ids": ["p1", "p2"]}],
                "sources": [
                    {"id": "p1", "source_type": "press_article", "publisher": "A"},
                    {"id": "p2", "source_type": "press_article", "publisher": "B"},
                ],
                "verification_status": "verified",
            }
            (run / "01-search" / "selected-story.json").write_text(json.dumps(story), encoding="utf-8")
            MOD.complete_stage(run, "search-news")

            board = {
                "schema_version": "1.0",
                "story_id": "story-1",
                "card_count": 3,
                "cards": [
                    {"index": 1, "role": "hook", "copy": "a", "evidence_ids": ["c1"]},
                    {"index": 2, "role": "facts_and_context", "copy": "b", "evidence_ids": ["c1"]},
                    {"index": 3, "role": "impact_unknowns_sources", "copy": "c", "evidence_ids": ["c1"]},
                ],
                "qa": {"hard_fail_passed": True, "editorial_score": 13},
            }
            (run / "02-plan" / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
            (run / "02-plan" / "editorial-plan.json").write_text("{}", encoding="utf-8")
            MOD.complete_stage(run, "plan-news-pick")

            candidates = run / "03-create" / "candidates"
            for direction in range(1, 5):
                folder = candidates / f"direction-{direction:02d}"
                folder.mkdir(parents=True)
                for card in range(1, 4):
                    (folder / f"card-{card:02d}.png").write_bytes(b"synthetic-png")
            slides = run / "03-create" / "slides"
            slides.mkdir()
            for card in range(1, 4):
                (slides / f"{card:02d}.png").write_bytes(b"synthetic-final-png")
            (run / "03-create" / "selection.json").write_text(json.dumps({"story_id": "story-1", "direction_id": "direction-01", "card_count": 3}), encoding="utf-8")
            (run / "03-create" / "qa-report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
            MOD.complete_stage(run, "create-news-cards")

            (run / "04-publish" / "publish-job.json").write_text("{}", encoding="utf-8")
            (run / "04-publish" / "result.json").write_text(json.dumps({"status": "published", "public_verified": True}), encoding="utf-8")
            final = MOD.complete_stage(run, "publish-news-pick")
            self.assertEqual(final["status"], "completed")
            self.assertIsNone(final["current_stage"])


if __name__ == "__main__":
    unittest.main()
