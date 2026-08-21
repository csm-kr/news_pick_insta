import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image


SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import private_video_story_task
import publish_story_video
import render_story_video


class DiscoveryTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        run_id: str,
        hour: int,
        color: tuple[int, int, int],
        edition_date: str = "2026-08-19",
        verified_date: str = "2026-08-19",
    ):
        run = root / "runs" / run_id
        (run / "run.json").parent.mkdir(parents=True, exist_ok=True)
        (run / "run.json").write_text(
            json.dumps({"edition_at": f"{edition_date}T{hour:02d}:00:00+09:00"}),
            encoding="utf-8",
        )
        cover = run / "03-create" / "slides" / "01.png"
        cover.parent.mkdir(parents=True)
        Image.new("RGB", (1024, 1024), color).save(cover)
        result = run / "04-publish" / "result.json"
        result.parent.mkdir(parents=True)
        result.write_text(
            json.dumps(
                {
                    "status": "published",
                    "public_verified": True,
                    "first_card_match": True,
                    "verified_at": f"{verified_date}T{hour:02d}:30:00+09:00",
                    "shortcode": f"code{hour}",
                    "url": f"https://www.instagram.com/p/code{hour}/",
                }
            ),
            encoding="utf-8",
        )

    def test_discovers_every_post_by_public_verification_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_run(root, "run-a", 7, (255, 0, 0))
            self.make_run(root, "run-b", 12, (0, 255, 0))
            self.make_run(root, "run-c", 17, (0, 0, 255))
            self.make_run(root, "run-d", 20, (255, 255, 0))
            self.make_run(
                root,
                "prior-day-late-verification",
                6,
                (255, 0, 255),
                edition_date="2026-08-18",
                verified_date="2026-08-19",
            )
            sources = render_story_video.discover_sources(root, date(2026, 8, 19))
            self.assertEqual(
                [source.run_id for source in sources],
                [
                    "prior-day-late-verification",
                    "run-a",
                    "run-b",
                    "run-c",
                    "run-d",
                ],
            )

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg and ffprobe are required",
    )
    def test_renders_six_second_vertical_story_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_run(root, "run-a", 7, (210, 40, 40))
            self.make_run(root, "run-b", 12, (40, 160, 70))
            self.make_run(root, "run-c", 17, (40, 80, 210))
            self.make_run(root, "run-d", 20, (180, 90, 30))
            rendered = render_story_video.render(root, date(2026, 8, 19))
            self.assertEqual(
                [item["run_id"] for item in rendered["sources"]],
                ["run-a", "run-b", "run-c", "run-d"],
            )
            self.assertEqual(rendered["video"]["technical"]["width"], 1080)
            self.assertEqual(rendered["video"]["technical"]["height"], 1920)
            self.assertAlmostEqual(
                rendered["video"]["technical"]["duration_seconds"], 6.0, places=2
            )
            self.assertEqual(len(rendered["proof_frames"]), 4)
            self.assertEqual(rendered["source_count"], 4)
            reused = render_story_video.render(root, date(2026, 8, 19))
            self.assertTrue(reused["reused"])


class PublishContractTests(unittest.TestCase):
    def test_private_video_requires_matching_mp4_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "story.mp4"
            media.write_bytes(b"approved-video")
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            self.assertEqual(
                private_video_story_task.validate_story_video(media, digest),
                media.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                private_video_story_task.validate_story_video(media, "0" * 64)

    def test_parser_uses_last_contract_line(self):
        output = "\n".join(
            [
                publish_story_video.PRIVATE_PREFIX + json.dumps({"ok": False}),
                "diagnostic",
                publish_story_video.PRIVATE_PREFIX + json.dumps({"ok": True}),
            ]
        )
        self.assertEqual(
            publish_story_video.parse_prefixed(
                output, publish_story_video.PRIVATE_PREFIX
            ),
            {"ok": True},
        )

    def test_safe_error_redacts_session(self):
        secret = "1234567890%3Aexample-session-secret"
        message = private_video_story_task.safe_error(
            RuntimeError("failed " + secret), secret
        )
        self.assertNotIn(secret, message)
        self.assertIn("[redacted-session]", message)

    def test_moviepy_storybuilder_error_is_proven_pre_submit(self):
        result = {
            "status": "needs_review",
            "submission": {
                "error": "video_upload_to_story: StoryBuilder requires MoviePy 2.2.1"
            },
        }
        self.assertTrue(publish_story_video.proven_local_pre_submit_failure(result))


if __name__ == "__main__":
    unittest.main()
