from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

PATH = Path(__file__).with_name("check_visual_duplicates.py")
SPEC = importlib.util.spec_from_file_location("check_visual_duplicates", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class DuplicateTests(unittest.TestCase):
    def test_exact_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                Image.new("RGB", (1080, 1350), (10, 20, 30)).save(root / f"{index}.png")
            result = MOD.analyze_paths(sorted(root.glob("*.png")))
            self.assertFalse(result["passed"])
            self.assertTrue(any(pair["exact_duplicate"] for pair in result["failures"]))

    def test_distinct_cards_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boxes = ((40, 40, 400, 400), (620, 40, 1040, 430), (50, 520, 450, 930), (620, 650, 1040, 1100), (280, 1000, 820, 1330))
            for index, box in enumerate(boxes):
                image = Image.new("RGB", (1080, 1350), (5 + index * 12, 15 + index * 8, 40 + index * 18))
                draw = ImageDraw.Draw(image)
                draw.rectangle(box, fill=((220, 40 + index * 70, 30 + index * 60)))
                image.save(root / f"{index}.png")
            result = MOD.analyze_paths(sorted(root.glob("*.png")))
            self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
