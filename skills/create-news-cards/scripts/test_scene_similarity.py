from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SUPPORT_PATH = Path(__file__).with_name("_test_support.py")
SUPPORT_SPEC = importlib.util.spec_from_file_location("_test_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SUPPORT_SPEC)
assert SUPPORT_SPEC and SUPPORT_SPEC.loader
SUPPORT_SPEC.loader.exec_module(SUPPORT)

PATH = Path(__file__).with_name("scene_similarity.py")
SPEC = importlib.util.spec_from_file_location("scene_similarity", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class SceneSimilarityTests(unittest.TestCase):
    def test_resized_copy_of_same_photo_is_same_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = SUPPORT.synthetic_photo(1)
            a = SUPPORT.save(root / "a.png", original)
            b = SUPPORT.save(root / "b.png", original.resize((480, 360), Image.Resampling.LANCZOS))
            result = MOD.compare(a, b)
            self.assertLessEqual(result["dhash_distance"], MOD.DHASH_NEAR_THRESHOLD)
            self.assertTrue(result["same_scene"])

    def test_cropped_rescaled_photo_is_same_scene_by_feature_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = SUPPORT.synthetic_photo(2)
            a = SUPPORT.save(root / "a.png", original)
            b = SUPPORT.save(root / "b.png", SUPPORT.cropped_rescaled(original))
            result = MOD.compare(a, b)
            self.assertGreaterEqual(result["orb_inliers"], MOD.ORB_INLIER_THRESHOLD)
            self.assertTrue(result["same_scene"])

    def test_unrelated_photos_are_not_same_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = SUPPORT.save(root / "a.png", SUPPORT.synthetic_photo(3))
            b = SUPPORT.save(root / "b.png", SUPPORT.synthetic_photo(4))
            result = MOD.compare(a, b)
            self.assertLess(result["orb_inliers"], MOD.ORB_INLIER_THRESHOLD)
            self.assertGreater(result["dhash_distance"], MOD.DHASH_NEAR_THRESHOLD)
            self.assertFalse(result["same_scene"])

    def test_find_same_scene_pairs_reports_one_based_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = SUPPORT.synthetic_photo(5)
            paths = [
                SUPPORT.save(root / "1.png", first),
                SUPPORT.save(root / "2.png", SUPPORT.synthetic_photo(6)),
                SUPPORT.save(root / "3.png", SUPPORT.cropped_rescaled(first)),
                SUPPORT.save(root / "4.png", SUPPORT.synthetic_photo(7)),
            ]
            pairs = MOD.find_same_scene_pairs(paths)
            self.assertEqual([(pair["left"], pair["right"]) for pair in pairs], [(1, 3)])

    def test_match_cards_to_references_finds_reused_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = SUPPORT.synthetic_photo(8)
            other = SUPPORT.synthetic_photo(9)
            references = [SUPPORT.save(root / "ref-1.png", reference), SUPPORT.save(root / "ref-2.png", other)]
            card_with_reference = Image.new("RGB", (1080, 1350), (250, 250, 250))
            card_with_reference.paste(reference.resize((800, 600), Image.Resampling.LANCZOS), (140, 300))
            card_without = Image.new("RGB", (1080, 1350), (240, 240, 240))
            card_without.paste(other.resize((640, 480), Image.Resampling.LANCZOS), (220, 200))
            cards = [SUPPORT.save(root / "card-1.png", card_with_reference), SUPPORT.save(root / "card-2.png", card_without)]
            matches = MOD.match_cards_to_references(cards, references)
            self.assertEqual(matches, [[1], [2]])


if __name__ == "__main__":
    unittest.main()
