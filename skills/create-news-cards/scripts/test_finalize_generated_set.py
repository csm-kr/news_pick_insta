from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


PATH = Path(__file__).with_name("finalize_generated_set.py")
SPEC = importlib.util.spec_from_file_location("finalize_generated_set", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class FinalizeGeneratedSetTests(unittest.TestCase):
    def setup_work(self, root: Path) -> Path:
        work = root / "work"
        folder = work / "candidates" / "direction-01"
        folder.mkdir(parents=True)
        (work / "generation-plan.json").write_text(
            json.dumps({"target_size": "1024x1024"}), encoding="utf-8"
        )
        return work

    def test_duplicate_candidates_block_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.setup_work(Path(tmp))
            folder = work / "candidates" / "direction-01"
            for index in range(1, 5):
                Image.new("RGB", (1024, 1024), (10, 20, 30)).save(folder / f"card-{index:02d}.png")
            with self.assertRaisesRegex(ValueError, "중복"):
                MOD.finalize(work, {"story_id": "s", "card_count": 4}, "direction-01", True)
            self.assertTrue((work / "duplicate-qa.json").is_file())
            self.assertFalse((work / "slides").exists())

    def test_distinct_candidates_include_duplicate_qa_in_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.setup_work(Path(tmp))
            folder = work / "candidates" / "direction-01"
            boxes = ((40, 40, 380, 380), (610, 40, 980, 400), (60, 610, 420, 980), (600, 600, 980, 980))
            for index, box in enumerate(boxes, 1):
                image = Image.new("RGB", (1024, 1024), (4, 15, 40))
                ImageDraw.Draw(image).rectangle(box, fill=(40 * index, 220 - 30 * index, 30 * index))
                image.save(folder / f"card-{index:02d}.png")
            qa = MOD.finalize(work, {"story_id": "s", "card_count": 4}, "direction-01", True)
            self.assertTrue(qa["duplicate_qa"]["passed"])
            self.assertTrue(qa["checks"]["no_exact_or_near_duplicate"])
            self.assertEqual(len(list((work / "slides").glob("*.png"))), 4)


if __name__ == "__main__":
    unittest.main()
