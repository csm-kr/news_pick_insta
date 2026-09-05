import base64
import contextlib
import io
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_verify_carousel.py")


class PublicCarouselTests(unittest.TestCase):
    def exercise(self, root, capture_all=False, overrides=None):
        clock = SimpleNamespace(seconds=0, index=0)
        navigations = []
        activations = []

        def sleep(seconds):
            clock.seconds += seconds

        def navigate(url):
            navigations.append(url)
            clock.index = int(url.rsplit("=", 1)[1])

        def fake_cdp(method, **_kwargs):
            if method == "Target.getTargets":
                return {"targetInfos": [{"type": "page", "url": "https://www.instagram.com/p/approved/", "targetId": "instagram"}]}
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(f"jpeg-{clock.index}".encode()).decode()}
            raise AssertionError("unexpected browser mutation: " + method)

        def fake_js(_expression):
            return {
                "dot_count": 0, "active_index": clock.index - 1,
                "caption_match": True, "account_visible": True, "ai_label": True,
                "media_ready": True, "media_src": f"public-media-{clock.index}",
                "natural_w": 1080, "natural_h": 1350, "natural_ratio": 0.8, "render_ratio": 0.8,
                "has_left": False, "has_right": False, "login_wall": False, "challenge": False,
                **(overrides or {}),
            }

        env = {"IG_POST_URL": "https://www.instagram.com/p/approved/", "IG_CARD_COUNT": "5",
               "IG_CAPTION_PREFIX": "승인된 문장", "IG_ACCOUNT": "newspick_studio",
               "IG_REQUIRE_AI_LABEL": "1", "IG_APPROVED_PUBLISH_VERIFY": "1",
               "IG_SCREENSHOT_DIR": str(root), "IG_CAPTURE_ALL_CARDS": "1" if capture_all else "0"}
        failure = None
        with patch.dict(os.environ, env), patch("time.sleep", side_effect=sleep), patch("time.monotonic", side_effect=lambda: clock.seconds), contextlib.redirect_stdout(io.StringIO()):
            try:
                runpy.run_path(str(SCRIPT), init_globals={
                    "cdp": fake_cdp, "js": fake_js, "goto_url": navigate,
                    "wait_for_load": lambda: None,
                    "switch_tab": lambda target, activate=False: activations.append((target, activate)),
                })
            except RuntimeError as error:
                failure = error
        return json.loads((root / "verification.json").read_text(encoding="utf-8")), navigations, activations, failure

    def test_all_five_screenshots_are_captured_in_one_read_only_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, navigations, activations, failure = self.exercise(root, capture_all=True)
            self.assertIsNone(failure)
            self.assertTrue(result["verified"])
            self.assertEqual(result["active_sequence"], list(range(5)))
            self.assertEqual(len(result["card_screenshots"]), 5)
            self.assertEqual(navigations, [f"https://www.instagram.com/p/approved/?img_index={index}" for index in range(1, 6)])
            self.assertEqual(activations, [("instagram", True)])
            for index in range(1, 6):
                self.assertEqual((root / f"public-card-{index:02d}.jpg").read_bytes(), f"jpeg-{index}".encode())
            self.assertTrue(result["visual_confirmation_required"])
            self.assertFalse(result["navigation_boundary"])

    def test_default_preserves_first_and_last_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, _navigations, _activations, failure = self.exercise(root)
            self.assertIsNone(failure)
            self.assertEqual(len(result["card_screenshots"]), 2)
            self.assertFalse((root / "public-card-03.jpg").exists())

    def test_failed_verification_is_saved_and_never_promoted_by_screenshots(self):
        for overrides in ({"ai_label": False}, {"media_src": "repeated"}, {"render_ratio": 1}, {"caption_match": False}, {"challenge": True}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as directory:
                result, _navigations, _activations, failure = self.exercise(Path(directory), capture_all=True, overrides=overrides)
                self.assertIsInstance(failure, RuntimeError)
                self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
