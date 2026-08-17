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
            story = {"verification_status": "verified", "sources": [{"source_type": "press_article", "publisher": "A"}]}
            (run / "01-search" / "selected-story.json").write_text(json.dumps(story), encoding="utf-8")
            with self.assertRaises(ValueError):
                MOD.complete_stage(run, "search-news")


if __name__ == "__main__":
    unittest.main()
