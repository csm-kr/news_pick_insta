from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SUPPORT_PATH = Path(__file__).with_name("_test_support.py")
SUPPORT_SPEC = importlib.util.spec_from_file_location("_test_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SUPPORT_SPEC)
assert SUPPORT_SPEC and SUPPORT_SPEC.loader
SUPPORT_SPEC.loader.exec_module(SUPPORT)


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
        for index in range(1, 6):
            primary = root / f"primary-{index}.png"
            SUPPORT.save(primary, SUPPORT.synthetic_photo(100 + index))
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
        return {"story_id": "s", "card_count": 5, "cards": cards}

    def test_unique_roles_and_primary_references_prepare_fifteen_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path = root / "storyboard.json"
            board = self.make_board(root)
            plan = MOD.prepare(board, board_path, root / "work", "1080x1350", seed=12345)
            self.assertEqual(plan["candidate_count"], 15)
            self.assertEqual(plan["direction_pool_count"], 10)
            first_job = Path(plan["jobs"][0]["job"]).read_text(encoding="utf-8")
            self.assertIn("SET DIVERSITY", first_job)
            self.assertIn("verified consequence, loss, gap, reversal, or deadline", first_job)
            self.assertIn("Never postpone a crucial limitation", first_job)
            self.assertIn("LOWER 35-42%", first_job.upper())

    def test_every_prompt_starts_with_role_specific_safe_area_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            plan = MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=12345)
            prompts = {}
            for job in plan["jobs"]:
                prompt = json.loads(Path(job["job"]).read_text(encoding="utf-8"))["prompt"]
                self.assertTrue(prompt.startswith("SAFE AREA — THE MOST IMPORTANT RULE OF THIS CARD"), prompt[:80])
                prompts[job["card_index"]] = prompt
            self.assertIn("No text in the top 160px", prompts[1])
            for index in (2, 3, 4):
                self.assertIn("The top 110px of the card is EMPTY background", prompts[index])
                self.assertIn("about 26% of the card height", prompts[index])
            self.assertIn("The top 110px and bottom 110px are empty background", prompts[5])

    def test_body_card_prompt_locks_article_paragraph_from_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["copy"] = "첫 문장입니다. 두 번째 문장입니다."
            board["cards"][0]["copy"] = "표지 제목\n표지 부제"
            plan = MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=12345)
            body_job = json.loads(Path(plan["jobs"][1]["job"]).read_text(encoding="utf-8"))
            cover_job = json.loads(Path(plan["jobs"][0]["job"]).read_text(encoding="utf-8"))
            self.assertIn('Article paragraph', body_job["prompt"])
            self.assertIn('"첫 문장입니다. 두 번째 문장입니다."', body_job["prompt"])
            self.assertNotIn("Article paragraph", cover_job["prompt"])

    def test_article_paragraph_already_in_required_text_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["copy"] = "첫 문장입니다. 두 번째 문장입니다."
            board["cards"][1]["required_text"] = [*board["cards"][1]["required_text"], "첫 문장입니다. 두 번째 문장입니다."]
            plan = MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=12345)
            body_job = json.loads(Path(plan["jobs"][1]["job"]).read_text(encoding="utf-8"))
            self.assertEqual(body_job["prompt"].count("첫 문장입니다. 두 번째 문장입니다."), 1)

    def test_duplicate_primary_reference_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["reference_images"] = board["cards"][0]["reference_images"]
            with self.assertRaisesRegex(ValueError, "대표 reference"):
                MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=7)

    def test_same_scene_primary_reference_from_other_outlet_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            first_primary = Image.open(board["cards"][0]["reference_images"][0])
            republished = root / "republished-copy.png"
            SUPPORT.save(republished, SUPPORT.cropped_rescaled(first_primary))
            board["cards"][2]["reference_images"] = [str(republished)]
            with self.assertRaisesRegex(ValueError, "같은 장면"):
                MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=7)

    def test_duplicate_visual_role_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = self.make_board(root)
            board["cards"][1]["visual_role"] = board["cards"][0]["visual_role"]
            with self.assertRaisesRegex(ValueError, "visual_role"):
                MOD.prepare(board, root / "storyboard.json", root / "work", "1080x1350", seed=7)


if __name__ == "__main__":
    unittest.main()
