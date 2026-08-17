from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PATH = Path(__file__).with_name("prepare_reference_candidates.py")
SPEC = importlib.util.spec_from_file_location("prepare_reference_candidates", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class ReferenceDiversityTests(unittest.TestCase):
    def make_board(self, root: Path) -> dict:
        style = root / "style.png"
        Image.new("RGB", (32, 32), (10, 10, 10)).save(style)
        cards = []
        for index in range(1, 5):
            primary = root / f"primary-{index}.png"
            Image.new("RGB", (32, 32), (index * 45, index * 30, index * 20)).save(primary)
            cards.append(
                {
                    "index": index,
                    "visual_role": f"role-{index}",
                    "required_text": [f"card {index}"],
                    "reference_images": [str(primary)],
                    "style_reference_images": {
                        "direction-01": [str(style)],
                        "direction-02": [str(style)],
                        "direction-03": [str(style)],
                    },
                }
            )
        return {"story_id": "s", "card_count": 4, "cards": cards}

    def test_unique_roles_and_primary_references_prepare_twelve_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path = root / "storyboard.json"
            board = self.make_board(root)
            plan = MOD.prepare(board, board_path, root / "work", "1024x1024")
            self.assertEqual(plan["candidate_count"], 12)
            first_job = Path(plan["jobs"][0]["job"]).read_text(encoding="utf-8")
            self.assertIn("SET DIVERSITY", first_job)

    def test_duplicate_primary_reference_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["reference_images"] = board["cards"][0]["reference_images"]
            with self.assertRaisesRegex(ValueError, "대표 reference"):
                MOD.prepare(board, root / "storyboard.json", root / "work", "1024x1024")

    def test_duplicate_visual_role_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["visual_role"] = board["cards"][0]["visual_role"]
            with self.assertRaisesRegex(ValueError, "visual_role"):
                MOD.prepare(board, root / "storyboard.json", root / "work", "1024x1024")


if __name__ == "__main__":
    unittest.main()
