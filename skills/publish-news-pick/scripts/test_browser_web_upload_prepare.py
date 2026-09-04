import base64
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_upload_prepare.py")


def _send(_payload):
    return None


def _mark_tab():
    return None


def switch_tab(_target_id, activate=False):
    return activate


class UploadPrepareRegressionTests(unittest.TestCase):
    def test_create_link_uses_exact_descendant_svg_label(self):
        input_reads = 0
        state_reads = 0
        uploaded = []

        def fake_cdp(method, **_kwargs):
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
            if method == "Target.attachToTarget":
                return {"sessionId": "session"}
            if method == "Accessibility.getFullAXTree":
                return {"nodes": []}
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"jpeg").decode("ascii")}
            return {}

        def fake_js(expression):
            nonlocal input_reads, state_reads
            if "const expected=`https://www.instagram.com/${account}/`" in expression:
                return {
                    "href": "https://www.instagram.com/newspick_studio/",
                    "image_alts": ["newspick_studio님의 프로필 사진"],
                }
            if "location.href.split" in expression:
                return "https://www.instagram.com/newspick_studio"
            if "const candidates=[...document.querySelectorAll" in expression:
                if "querySelector('svg[aria-label]')" not in expression:
                    return None
                return {"x": 36, "y": 511, "label": "새로운 게시물"}
            if "return {exists:!!input,multiple:input?.multiple===true}" in expression:
                input_reads += 1
                return {"exists": input_reads > 1, "multiple": input_reads > 1}
            if "file_names:input?" in expression:
                state_reads += 1
                ready = state_reads > 1
                return {
                    "url": "https://www.instagram.com/newspick_studio/",
                    "dialog_present": ready,
                    "input_present": False,
                    "file_count": 0,
                    "file_names": [],
                    "multiple": False,
                    "has_next": ready,
                    "has_crop": ready,
                    "has_media_gallery": ready,
                    "media_dot_count": 5 if ready else 0,
                    "login_wall": False,
                    "challenge": False,
                }
            return True

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            screenshot = root / "crop.jpg"
            media = [root / f"{index:02d}.png" for index in range(1, 6)]
            for path in media:
                path.write_bytes(b"png")
            environment = {
                "IG_ACCOUNT": "newspick_studio",
                "IG_MEDIA_FILES": "|".join(str(path) for path in media),
                "IG_CROP_SCREENSHOT": str(screenshot),
            }
            with patch.dict(os.environ, environment, clear=False):
                runpy.run_path(
                    str(SCRIPT),
                    init_globals={
                        "cdp": fake_cdp,
                        "js": fake_js,
                        "switch_tab": switch_tab,
                        "goto_url": lambda _url: None,
                        "wait_for_load": lambda: None,
                        "click_at_xy": lambda _x, _y: None,
                        "upload_file": lambda selector, files: uploaded.append(
                            (selector, files)
                        ),
                    },
                )
            self.assertTrue(screenshot.is_file())
            self.assertEqual(uploaded, [("input[type=file][multiple]", [str(path) for path in media])])

    def test_existing_confirmed_crop_session_is_not_reopened(self):
        uploaded = []

        def fake_cdp(method, **_kwargs):
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
            if method == "Target.attachToTarget":
                return {"sessionId": "session"}
            if method == "Accessibility.getFullAXTree":
                return {"nodes": []}
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"jpeg").decode("ascii")}
            return {}

        def fake_js(expression):
            if "const expected=`https://www.instagram.com/${account}/`" in expression:
                return {
                    "href": "https://www.instagram.com/newspick_studio/",
                    "image_alts": ["newspick_studio님의 프로필 사진"],
                }
            if "location.href.split" in expression:
                return "https://www.instagram.com/newspick_studio"
            if "file_names:input?" in expression:
                return {
                    "url": "https://www.instagram.com/newspick_studio/",
                    "dialog_present": True,
                    "input_present": False,
                    "file_count": 0,
                    "file_names": [],
                    "multiple": False,
                    "has_next": True,
                    "has_crop": True,
                    "has_media_gallery": True,
                    "login_wall": False,
                    "challenge": False,
                }
            if "const candidates=[...document.querySelectorAll" in expression:
                self.fail("confirmed crop session must not reopen the create control")
            if "return {exists:!!input,multiple:input?.multiple===true}" in expression:
                return {"exists": False, "multiple": False}
            return True

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            screenshot = root / "crop.jpg"
            media = [root / f"{index:02d}.png" for index in range(1, 6)]
            for path in media:
                path.write_bytes(b"png")
            with patch.dict(
                os.environ,
                {
                    "IG_ACCOUNT": "newspick_studio",
                    "IG_MEDIA_FILES": "|".join(str(path) for path in media),
                    "IG_CROP_SCREENSHOT": str(screenshot),
                },
                clear=False,
            ):
                runpy.run_path(
                    str(SCRIPT),
                    init_globals={
                        "cdp": fake_cdp,
                        "js": fake_js,
                        "switch_tab": switch_tab,
                        "goto_url": lambda _url: None,
                        "wait_for_load": lambda: None,
                        "click_at_xy": lambda _x, _y: None,
                        "upload_file": lambda selector, files: uploaded.append(
                            (selector, files)
                        ),
                    },
                )
            self.assertTrue(screenshot.is_file())
            self.assertEqual(uploaded, [])


if __name__ == "__main__":
    unittest.main()
