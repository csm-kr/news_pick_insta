import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_story_batch
import render_story_video


class ManualStorySelectionTests(unittest.TestCase):
    def sources(self, root, hours=(1, 7, 17)):
        return [render_story_video.Source(
            run_id=f"run-{hour}", run_dir=root / f"run-{hour}", cover=root / f"{hour}.png",
            cover_sha256=str(hour) * 32, post_url=f"https://www.instagram.com/p/code{hour}/",
            shortcode=f"code{hour}", edition_at=datetime(2026, 9, 5, hour, 21, tzinfo=render_story_video.KST),
            verified_at=datetime(2026, 9, 5, hour, 30, tzinfo=render_story_video.KST),
        ) for hour in hours]

    def test_manual_mode_keeps_verified_order_without_changing_editions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = self.sources(root)
            with patch.object(render_story_batch.shutil, "which", return_value="tool"), patch.object(render_story_video, "discover_sources", return_value=sources), patch.object(render_story_batch, "render_one", side_effect=lambda source, index, *_args: {"index": index, "source": source.record()}):
                result = render_story_batch.render(root, date(2026, 9, 5), include_manual_editions=True)
            self.assertEqual(result["source_selection"], "verified_date")
            self.assertEqual([item["source"]["run_id"] for item in result["stories"]], ["run-1", "run-7", "run-17"])
            self.assertEqual(result["sources"][0]["edition_at"], "2026-09-05T01:21:00+09:00")

    def test_default_and_scheduled_modes_do_not_relax_fixed_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(render_story_batch.shutil, "which", return_value="tool"), patch.object(render_story_video, "discover_sources", return_value=self.sources(root)), self.assertRaisesRegex(ValueError, render_story_batch.EDITION_SLOTS[0]):
                render_story_batch.render(root, date(2026, 9, 5))
            with patch.dict(os.environ, {"NEWS_PICK_DAILY_STORY_SCHEDULED_MODE": "1"}), self.assertRaisesRegex(ValueError, "cannot include manual"):
                render_story_batch.render(root, date(2026, 9, 5), include_manual_editions=True)

    def test_manual_mode_still_requires_exactly_three_posts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for hours in ((1, 7), (1, 7, 17, 20)):
                with self.subTest(hours=hours), patch.object(render_story_batch.shutil, "which", return_value="tool"), patch.object(render_story_video, "discover_sources", return_value=self.sources(root, hours)), self.assertRaisesRegex(ValueError, "exactly 3"):
                    render_story_batch.render(root, date(2026, 9, 5), include_manual_editions=True)


if __name__ == "__main__":
    unittest.main()
