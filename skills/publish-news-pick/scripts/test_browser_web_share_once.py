import base64
import contextlib
import io
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_share_once.py")


class ShareOnceRegressionTests(unittest.TestCase):
    def test_share_uses_dom_fast_path_and_clicks_once(self):
        clicks = []
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
            if "label==='공유하기'" in expression:
                return {"x": 820, "y": 70, "source": "dom"}
            if "const dialogs=" in expression:
                return {
                    "text": "게시물이 공유되었습니다",
                    "dialogs": [],
                    "url": "https://www.instagram.com/newspick_studio/",
                }
            return None

        with tempfile.TemporaryDirectory() as temporary:
            screenshot = Path(temporary) / "shared.jpg"
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {"IG_SCREENSHOT": str(screenshot)},
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
            self.assertEqual(clicks, [(820, 70)])
            self.assertIn('"success_marker": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
