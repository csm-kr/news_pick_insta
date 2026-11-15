from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

PATH = Path(__file__).with_name("orchestrate.py")
SPEC = importlib.util.spec_from_file_location("orchestrate", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class OrchestrateTests(unittest.TestCase):
    def test_default_output_root_uses_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NEWS_PICK_OUTPUT_ROOT": tmp}):
            self.assertEqual(MOD.default_output_root(), Path(tmp).resolve())

    def test_initialize_output_root_creates_runtime_only_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = MOD.initialize_output_root(Path(tmp) / "output")
            self.assertTrue((root / "runs").is_dir())
            self.assertTrue((root / "publish-news-pick").is_dir())
            self.assertFalse((root / "skills").exists())

    def test_output_root_inside_installed_skills_is_rejected(self):
        skills_root = Path(MOD.__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, "skills"):
            MOD.initialize_output_root(skills_root / "runtime-output")

    def test_init_and_search_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MOD.init_run(Path(tmp), "2026-08-17T17:00:00+09:00", "@newspick_studio")
            run = Path(result["run"])
            story = {
                "verification_status": "verified",
                "reaction_signals": [{"type": "portal"}, {"type": "coverage"}],
                "sources": [
                    {"source_type": "press_article", "publisher": "A"},
                    {"source_type": "press_article", "publisher": "B"},
                ],
            }
            (run / "01-search" / "selected-story.json").write_text(json.dumps(story), encoding="utf-8")
            state = MOD.complete_stage(run, "search-news")
            self.assertEqual(state["current_stage"], "plan-news-pick")
            self.assertEqual(len(state["stages"]["search-news"]["output_sha256"]), 64)

    def test_rejects_one_publisher(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MOD.init_run(Path(tmp), "2026-08-17T17:00:00+09:00", "newspick_studio")
            run = Path(result["run"])
            story = {"verification_status": "verified", "reaction_signals": [{"type": "portal"}, {"type": "coverage"}], "sources": [{"source_type": "press_article", "publisher": "A"}]}
            (run / "01-search" / "selected-story.json").write_text(json.dumps(story), encoding="utf-8")
            with self.assertRaises(ValueError):
                MOD.complete_stage(run, "search-news")

    def test_cancel_run_preserves_outputs_and_clears_current_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MOD.init_run(Path(tmp), "2026-08-17T17:00:00+09:00", "newspick_studio")
            run = Path(result["run"])
            artifact = run / "01-search" / "candidate.txt"
            artifact.write_text("keep", encoding="utf-8")
            state = MOD.cancel_run(run, "superseded by manual publication")
            self.assertEqual(state["status"], "cancelled")
            self.assertIsNone(state["current_stage"])
            self.assertEqual(state["stages"]["search-news"]["status"], "cancelled")
            self.assertEqual(state["cancellation_reason"], "superseded by manual publication")
            self.assertEqual(artifact.read_text(encoding="utf-8"), "keep")
            with self.assertRaises(ValueError):
                MOD.cancel_run(run, "again")


    def cancelled_preparation(self, root):
        run = Path(MOD.init_run(root, "2026-11-10T07:00:00+09:00", "newspick_studio")["run"])
        story = {"verification_status": "verified", "reaction_signals": [{"type": "portal"}, {"type": "coverage"}], "sources": [{"source_type": "press_article", "publisher": "A"}, {"source_type": "press_article", "publisher": "B"}]}
        MOD.atomic_json(run / "01-search/selected-story.json", story)
        MOD.complete_stage(run, "search-news")
        MOD.cancel_run(run, "user requested stop")
        return run

    def test_resume_reuses_unchanged_completed_stage_and_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.cancelled_preparation(Path(tmp))
            artifact = run / "01-search/selected-story.json"
            before = artifact.read_bytes()
            previous = MOD.load_json(run / "run.json")["stages"]["search-news"]
            state = MOD.resume_run(run, "user explicitly requested continue")
            self.assertEqual(state["status"], "in_progress")
            self.assertEqual(state["current_stage"], "plan-news-pick")
            self.assertEqual(state["stages"]["search-news"], previous)
            self.assertEqual(artifact.read_bytes(), before)
            self.assertEqual(state["resume_history"][0]["cancellation_reason"], "user requested stop")
            self.assertEqual(state["stages"]["plan-news-pick"]["status"], "pending")

    def test_resume_invalidates_changed_completed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.cancelled_preparation(Path(tmp))
            story = MOD.load_json(run / "01-search/selected-story.json")
            story["updated_at"] = "2026-11-10T21:00:00+09:00"
            MOD.atomic_json(run / "01-search/selected-story.json", story)
            state = MOD.resume_run(run, "resume after changed input")
            self.assertEqual(state["current_stage"], "search-news")
            self.assertTrue(all(r == {"status": "pending", "output_sha256": None} for r in state["stages"].values()))
            self.assertEqual(MOD.load_json(run / "01-search/selected-story.json"), story)

    def test_resume_refuses_submission_evidence_without_mutation(self):
        for evidence in ("external_submission_pending", "publish-job.json", "attempts.jsonl", "result.json"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as tmp:
                run = self.cancelled_preparation(Path(tmp))
                if evidence == "external_submission_pending":
                    state = MOD.load_json(run / "run.json")
                    state[evidence] = True
                    MOD.atomic_json(run / "run.json", state)
                else:
                    (run / "04-publish" / evidence).write_text("{}", encoding="utf-8")
                before = (run / "run.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "제출 기록"):
                    MOD.resume_run(run, "continue")
                self.assertEqual((run / "run.json").read_bytes(), before)

    def test_resume_refuses_cancelled_publish_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.cancelled_preparation(Path(tmp))
            state = MOD.load_json(run / "run.json")
            state["stages"]["plan-news-pick"]["status"] = "completed"
            state["stages"]["publish-news-pick"]["status"] = "cancelled"
            MOD.atomic_json(run / "run.json", state)
            with self.assertRaisesRegex(ValueError, "게시 단계"):
                MOD.resume_run(run, "continue")

    def test_resume_requires_explicit_reason_and_cancelled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.cancelled_preparation(Path(tmp))
            with self.assertRaisesRegex(ValueError, "사유"):
                MOD.resume_run(run, "  ")
            MOD.resume_run(run, "continue")
            with self.assertRaisesRegex(ValueError, "cancelled"):
                MOD.resume_run(run, "again")


class ClonePreparedTests(unittest.TestCase):
    """게시 단계에서 멈춘 예약 run의 검증된 준비물을 새 수동 run으로 옮긴다(2026-11-15 07시 대체)."""

    def prepared_then_publish_stopped(self, root):
        run = Path(MOD.init_run(root, "2026-11-15T07:00:00+09:00", "newspick_studio")["run"])
        story = {"verification_status": "verified", "reaction_signals": [{"type": "portal"}, {"type": "coverage"}],
                 "sources": [{"source_type": "press_article", "publisher": "A"}, {"source_type": "press_article", "publisher": "B"}]}
        MOD.atomic_json(run / "01-search/selected-story.json", story)
        MOD.complete_stage(run, "search-news")
        cards = [{"index": i, "evidence_ids": ["e1"]} for i in range(1, 6)]
        MOD.atomic_json(run / "02-plan/storyboard.json",
                        {"card_count": 5, "cards": cards, "qa": {"hard_fail_passed": True, "editorial_score": 18}})
        MOD.complete_stage(run, "plan-news-pick")
        create = run / "03-create"
        for i in range(15):
            (create / "candidates").mkdir(exist_ok=True)
            (create / "candidates" / f"c{i:02d}.png").write_bytes(b"c%d" % i)
        (create / "slides").mkdir()
        for i in range(1, 6):
            (create / "slides" / f"{i:02d}.png").write_bytes(b"s%d" % i)
        MOD.atomic_json(create / "selection.json", {"card_count": 5})
        MOD.atomic_json(create / "qa-report.json", {"passed": True, "checks": {"no_exact_or_near_duplicate": True}})
        MOD.atomic_json(create / "duplicate-qa.json", {"passed": True})
        MOD.complete_stage(run, "create-news-cards")
        (run / "references").mkdir()
        (run / "references" / "photo.jpg").write_bytes(b"ref")
        (run / "04-publish" / "caption.txt").write_text("캡션", encoding="utf-8")
        (run / "04-publish" / "needs-review.json").write_text("{}", encoding="utf-8")
        MOD.cancel_run(run, "needs_review: capture timeout")
        return run

    def test_clone_copies_verified_preparation_and_waits_at_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.prepared_then_publish_stopped(Path(tmp))
            before = (source / "run.json").read_bytes()
            state = MOD.clone_prepared(Path(tmp), source, "사용자가 07시 카드 수동 게시를 지시")
            clone = Path(state["run"])
            self.assertNotEqual(clone, source)
            self.assertEqual(state["status"], "in_progress")
            self.assertEqual(state["current_stage"], "publish-news-pick")
            self.assertEqual(state["edition_at"], "2026-11-15T07:00:00+09:00")
            self.assertEqual(state["account"], "newspick_studio")
            source_state = MOD.load_json(source / "run.json")
            for stage in ("search-news", "plan-news-pick", "create-news-cards"):
                self.assertEqual(state["stages"][stage]["status"], "completed")
                self.assertEqual(state["stages"][stage]["output_sha256"], source_state["stages"][stage]["output_sha256"])
            self.assertEqual(state["stages"]["publish-news-pick"], {"status": "pending", "output_sha256": None})
            self.assertEqual(state["cloned_from"]["run_id"], source.name)
            self.assertEqual(state["cloned_from"]["reason"], "사용자가 07시 카드 수동 게시를 지시")
            self.assertEqual((clone / "references" / "photo.jpg").read_bytes(), b"ref")
            self.assertEqual((clone / "04-publish" / "caption.txt").read_text(encoding="utf-8"), "캡션")
            self.assertFalse((clone / "04-publish" / "needs-review.json").exists())
            self.assertEqual((source / "run.json").read_bytes(), before)

    def test_clone_refuses_changed_source_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.prepared_then_publish_stopped(Path(tmp))
            (source / "03-create" / "slides" / "01.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash"):
                MOD.clone_prepared(Path(tmp), source, "manual")
            self.assertEqual(len([p for p in Path(tmp).iterdir() if p.is_dir()]), 1)

    def test_clone_refuses_runs_that_are_not_stopped_at_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.prepared_then_publish_stopped(Path(tmp))
            state = MOD.load_json(source / "run.json")
            state["stages"]["create-news-cards"]["status"] = "pending"
            MOD.atomic_json(source / "run.json", state)
            with self.assertRaisesRegex(ValueError, "준비"):
                MOD.clone_prepared(Path(tmp), source, "manual")
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(MOD.init_run(Path(tmp), "2026-11-15T07:00:00+09:00", "newspick_studio")["run"])
            with self.assertRaisesRegex(ValueError, "cancelled"):
                MOD.clone_prepared(Path(tmp), run, "manual")

    def test_clone_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.prepared_then_publish_stopped(Path(tmp))
            with self.assertRaisesRegex(ValueError, "사유"):
                MOD.clone_prepared(Path(tmp), source, " ")


if __name__ == "__main__":
    unittest.main()
