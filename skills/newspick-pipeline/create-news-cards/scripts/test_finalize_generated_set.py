from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

SUPPORT_PATH = Path(__file__).with_name("_test_support.py")
SUPPORT_SPEC = importlib.util.spec_from_file_location("_test_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SUPPORT_SPEC)
assert SUPPORT_SPEC and SUPPORT_SPEC.loader
SUPPORT_SPEC.loader.exec_module(SUPPORT)


PATH = Path(__file__).with_name("finalize_generated_set.py")
SPEC = importlib.util.spec_from_file_location("finalize_generated_set", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class FinalizeGeneratedSetTests(unittest.TestCase):
    def setup_work(self, root: Path, primary_seeds: tuple[int, ...] = (11, 12, 13, 14, 15)) -> Path:
        work = root / "work"
        folder = work / "candidates" / "direction-01"
        folder.mkdir(parents=True)
        (work / "generation-plan.json").write_text(
            json.dumps({"target_size": "1080x1350"}), encoding="utf-8"
        )
        style = SUPPORT.save(root / "references" / "style.png", SUPPORT.synthetic_photo(99))
        self.reference_paths = []
        for index, seed in enumerate(primary_seeds, 1):
            primary = SUPPORT.save(root / "references" / f"primary-{index}.png", SUPPORT.synthetic_photo(seed))
            self.reference_paths.append(primary)
            self.write_job(work, index, [primary, style])
        return work

    def write_job(self, work: Path, index: int, references: list[Path]) -> None:
        job_dir = work / "jobs" / "direction-01" / f"card-{index:02d}"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(
            json.dumps({"prompt": "p", "references": [str(path) for path in references]}), encoding="utf-8"
        )

    def write_distinct_candidates(self, folder: Path) -> None:
        boxes = ((40, 40, 400, 360), (620, 40, 1030, 400), (60, 500, 440, 900), (610, 700, 1040, 1120), (300, 980, 800, 1320))
        palettes = ((230, 30, 40), (20, 190, 70), (20, 70, 220), (235, 220, 35), (120, 35, 180))
        for index, box in enumerate(boxes, 1):
            image = Image.new("RGB", (1080, 1350), palettes[index - 1])
            ImageDraw.Draw(image).rectangle(box, fill=(40 * index, 220 - 30 * index, 30 * index))
            image.save(folder / f"card-{index:02d}.png")

    def test_same_scene_primary_references_block_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = self.setup_work(root)
            self.write_distinct_candidates(work / "candidates" / "direction-01")
            republished = SUPPORT.save(
                root / "references" / "republished.png",
                SUPPORT.cropped_rescaled(Image.open(self.reference_paths[0])),
            )
            self.write_job(work, 3, [republished, root / "references" / "style.png"])
            with self.assertRaisesRegex(ValueError, "같은 장면"):
                MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            report = json.loads((work / "duplicate-qa.json").read_text(encoding="utf-8"))
            self.assertFalse(report["scene_qa"]["passed"])
            self.assertEqual([(pair["left"], pair["right"]) for pair in report["scene_qa"]["same_scene_reference_pairs"]], [(1, 3)])
            self.assertFalse((work / "slides").exists())

    def test_two_cards_reproducing_one_reference_block_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = self.setup_work(root)
            folder = work / "candidates" / "direction-01"
            self.write_distinct_candidates(folder)
            reused = Image.open(self.reference_paths[0]).convert("RGB")
            for index, (size, position) in ((2, ((800, 600), (140, 120))), (4, ((640, 480), (220, 700)))):
                card = Image.open(folder / f"card-{index:02d}.png").convert("RGB")
                card.paste(reused.resize(size, Image.Resampling.LANCZOS), position)
                card.save(folder / f"card-{index:02d}.png")
            with self.assertRaisesRegex(ValueError, "같은 reference"):
                MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            report = json.loads((work / "duplicate-qa.json").read_text(encoding="utf-8"))
            self.assertFalse(report["scene_qa"]["passed"])
            self.assertIn([2, 4], report["scene_qa"]["cards_sharing_reference"])

    def test_duplicate_candidates_block_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.setup_work(Path(tmp))
            folder = work / "candidates" / "direction-01"
            for index in range(1, 6):
                Image.new("RGB", (1080, 1350), (10, 20, 30)).save(folder / f"card-{index:02d}.png")
            with self.assertRaisesRegex(ValueError, "중복"):
                MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            self.assertTrue((work / "duplicate-qa.json").is_file())
            self.assertFalse((work / "slides").exists())

    def test_shared_layout_reference_does_not_merge_distinct_factual_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = self.setup_work(root)
            folder = work / "candidates" / "direction-01"
            self.write_distinct_candidates(folder)
            layout = SUPPORT.save(root / "references" / "style" / "generated-layout.png", SUPPORT.synthetic_photo(99))
            for index, primary in enumerate(self.reference_paths, 1):
                self.write_job(work, index, [primary, layout])
            reused = Image.open(layout).convert("RGB")
            for index, (size, position) in ((2, ((800, 600), (140, 120))), (4, ((640, 480), (220, 700)))):
                card = Image.open(folder / f"card-{index:02d}.png").convert("RGB")
                card.paste(reused.resize(size, Image.Resampling.LANCZOS), position)
                card.save(folder / f"card-{index:02d}.png")
            qa = MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            scene = qa["duplicate_qa"]["scene_qa"]
            self.assertTrue(scene["passed"])
            self.assertNotIn(str(layout), scene["reference_pool"])
            self.assertEqual(scene["excluded_style_references"], [str(layout)])
            self.assertEqual(len(scene["reference_pool"]), 5)

    def test_primary_in_style_folder_is_still_checked_for_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = self.setup_work(root)
            folder = work / "candidates" / "direction-01"
            self.write_distinct_candidates(folder)
            primary = SUPPORT.save(root / "references" / "style" / "misplaced-primary.png", SUPPORT.synthetic_photo(99))
            self.write_job(work, 2, [primary])
            self.write_job(work, 4, [primary])
            with self.assertRaisesRegex(ValueError, "같은 장면"):
                MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            report = json.loads((work / "duplicate-qa.json").read_text(encoding="utf-8"))
            self.assertFalse(report["scene_qa"]["passed"])
            self.assertIn(str(primary), report["scene_qa"]["reference_pool"])

    def test_distinct_candidates_include_duplicate_qa_in_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.setup_work(Path(tmp))
            folder = work / "candidates" / "direction-01"
            boxes = ((40, 40, 400, 360), (620, 40, 1030, 400), (60, 500, 440, 900), (610, 700, 1040, 1120), (300, 980, 800, 1320))
            palettes = ((230, 30, 40), (20, 190, 70), (20, 70, 220), (235, 220, 35), (120, 35, 180))
            for index, box in enumerate(boxes, 1):
                image = Image.new("RGB", (1080, 1350), palettes[index - 1])
                ImageDraw.Draw(image).rectangle(box, fill=(40 * index, 220 - 30 * index, 30 * index))
                image.save(folder / f"card-{index:02d}.png")
            qa = MOD.finalize(work, {"story_id": "s", "card_count": 5}, "direction-01", True)
            self.assertTrue(qa["duplicate_qa"]["passed"])
            self.assertTrue(qa["duplicate_qa"]["scene_qa"]["passed"])
            self.assertTrue(qa["checks"]["no_exact_or_near_duplicate"])
            self.assertTrue(qa["checks"]["no_same_scene_reference_reuse"])
            self.assertEqual(len(list((work / "slides").glob("*.png"))), 5)


if __name__ == "__main__":
    unittest.main()
