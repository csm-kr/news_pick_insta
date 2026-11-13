import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SPEC = importlib.util.spec_from_file_location("audit_generated_crops", Path(__file__).with_name("audit_generated_crops.py"))
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class CropAuditTests(unittest.TestCase):
    def test_two_by_three_raw_loses_128_pixels_per_edge(self):
        geometry = AUDIT.crop_geometry((1024, 1536), {"crop_width": 1024, "crop_height": 1280, "x_offset": 0, "y_offset": 128}, (1080, 1350))
        self.assertEqual(geometry["removed_top_px"], 128)
        self.assertEqual(geometry["removed_bottom_px"], 128)
        self.assertAlmostEqual(geometry["removed_area_fraction"], 1 / 6, places=5)
        self.assertTrue(geometry["visual_review_required"])

    def test_unexpected_tall_raw_uses_actual_geometry_not_requested_size(self):
        geometry = AUDIT.crop_geometry((916, 1717), {"crop_width": 916, "crop_height": 1145, "x_offset": 0, "y_offset": 286}, (1080, 1350))
        self.assertEqual(geometry["removed_bottom_px"], 286)
        self.assertGreater(geometry["removed_area_fraction"], 0.33)

    def test_no_crop_still_requires_content_review(self):
        geometry = AUDIT.crop_geometry((1122, 1402), {"crop_width": 1122, "crop_height": 1402, "x_offset": 0, "y_offset": 0}, (1080, 1350))
        self.assertEqual(geometry["removed_area_fraction"], 0)
        self.assertTrue(geometry["visual_review_required"])

    def test_invalid_rectangle_fails(self):
        with self.assertRaises(ValueError):
            AUDIT.crop_geometry((100, 150), {"crop_width": 100, "crop_height": 150, "x_offset": 10, "y_offset": 0}, (1080, 1350))

    def test_audit_preserves_pixels_and_rejects_stale_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            output = work / "jobs" / "direction-01" / "card-01" / "output"
            output.mkdir(parents=True)
            candidate = work / "candidates" / "direction-01" / "card-01.png"
            candidate.parent.mkdir(parents=True)
            raw = output / "raw.png"
            Image.new("RGB", (80, 120), "white").save(raw)
            Image.new("RGB", (80, 100), "white").save(candidate)
            raw_hash, final_hash = AUDIT.digest(raw), AUDIT.digest(candidate)
            (work / "generation-plan.json").write_text(json.dumps({"card_count": 1, "jobs": [{"direction_id": "direction-01", "card_index": 1, "job": str(output.parent / "job.json") }]}))
            (output / "manifest.json").write_text(json.dumps({"images": [{"backend_raw": {"path": str(raw), "sha256": raw_hash}, "sha256": final_hash, "raw_size": {"width": 80, "height": 120}, "postprocess_plan": {"crop_width": 80, "crop_height": 100, "x_offset": 0, "y_offset": 10}}]}))
            report = AUDIT.audit(work, "direction-01")
            self.assertEqual(report["status"], "visual_review_required")
            self.assertEqual((AUDIT.digest(raw), AUDIT.digest(candidate)), (raw_hash, final_hash))
            Image.new("RGB", (80, 100), "red").save(candidate)
            with self.assertRaisesRegex(ValueError, "hash"):
                AUDIT.audit(work, "direction-01")
