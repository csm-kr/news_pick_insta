import base64
import contextlib
import io
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_advance_to_caption.py")


class AdvanceToCaptionRegressionTests(unittest.TestCase):
    def test_css_background_portrait_uses_dom_fast_path(self):
        clicks = []
        stage_reads = 0
        ax_reads = 0

        def fake_cdp(method, **_kwargs):
            nonlocal ax_reads
            if method == "Target.getTargets":
                return {
                    "targetInfos": [
                        {
                            "type": "page",
                            "url": "https://www.instagram.com/newspick_studio/",
                            "targetId": "instagram-target",
                        }
                    ]
                }
            if method == "Accessibility.getFullAXTree":
                ax_reads += 1
                return {"nodes": []}
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"jpeg").decode("ascii")}
            return {}

        def fake_js(expression):
            nonlocal stage_reads
            if "source:'css_background'" in expression:
                return {
                    "source": "css_background",
                    "background_url_scheme": "blob",
                    "natural_w": 0,
                    "natural_h": 0,
                    "natural_ratio": 0.8,
                    "natural_verified_by": "expected_4x5_input",
                    "x": 200,
                    "y": 100,
                    "w": 480,
                    "h": 600,
                    "render_ratio": 0.8,
                    "area": 288000,
                }
            if "has_filter:text.includes" in expression:
                stage_reads += 1
                if stage_reads == 1:
                    return {
                        "url": "https://www.instagram.com/newspick_studio/",
                        "has_filter": True,
                        "has_adjust": True,
                        "has_original": True,
                        "has_caption": False,
                        "has_share": False,
                        "login_wall": False,
                        "challenge": False,
                    }
                return {
                    "url": "https://www.instagram.com/newspick_studio/",
                    "has_filter": False,
                    "has_adjust": False,
                    "has_original": False,
                    "has_caption": True,
                    "has_share": True,
                    "login_wall": False,
                    "challenge": False,
                }
            if '"4:5"' in expression:
                return {"name": "4:5", "role": "DIV", "x": 310, "y": 690, "source": "dom"}
            if '"원본"' in expression:
                return {"name": "원본", "role": "BUTTON", "x": 420, "y": 180, "source": "dom"}
            if '"다음"' in expression:
                return {"name": "다음", "role": "BUTTON", "x": 850, "y": 72, "source": "dom"}
            return None

        with tempfile.TemporaryDirectory() as temporary:
            screenshot = Path(temporary) / "ratio.jpg"
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "IG_RATIO_SCREENSHOT": str(screenshot),
                    "IG_EXPECTED_MEDIA_RATIO": "0.8",
                },
                clear=False,
            ), patch("time.sleep", return_value=None), contextlib.redirect_stdout(output):
                runpy.run_path(
                    str(SCRIPT),
                    init_globals={
                        "cdp": fake_cdp,
                        "js": fake_js,
                        "switch_tab": lambda _target, activate=False: activate,
                        "click_at_xy": lambda x, y: clicks.append((x, y)),
                    },
                )

            self.assertTrue(screenshot.is_file())
            self.assertEqual(ax_reads, 0)
            self.assertEqual(len(clicks), 4)
            self.assertIn('"source": "css_background"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
