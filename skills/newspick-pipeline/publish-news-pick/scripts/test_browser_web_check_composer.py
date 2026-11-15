import base64
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_check_composer.py")


class FakeComposer:
    """작성기 DOM 대신 표식 주석으로 JS 호출을 구분해 답한다."""

    def __init__(self, thumbs=5, scroller=False, caption="캡션", ai=True, share=True):
        self.thumbs = thumbs
        self.scroller = scroller
        self.caption = caption
        self.ai = ai
        self.share = share
        self.gallery_open = False
        self.clicks = []
        self.shots = 0

    def cdp(self, method, **_kwargs):
        if method == "Target.getTargets":
            return {"targetInfos": [{"type": "page", "url": "https://www.instagram.com/newspick_studio/", "targetId": "t"}]}
        if method == "Page.captureScreenshot":
            self.shots += 1
            return {"data": base64.b64encode(b"jpeg").decode("ascii")}
        return {}

    def js(self, expression):
        if "/*gallery-control*/" in expression:
            return {"x": 10, "y": 20}
        if "/*gallery-open*/" in expression:
            return self.gallery_open
        if "/*gallery-state*/" in expression:
            items = [{"source": f"blob:{i}"} for i in range(self.thumbs)]
            return {"count": len(items), "items": items, "scrollable": self.scroller}
        if "/*gallery-scroll*/" in expression:
            if not self.scroller:
                raise RuntimeError("Cannot set properties of null (setting 'scrollLeft')")
            return True
        if "/*pre-share-state*/" in expression:
            return {"caption": self.caption, "ai": [{"checked": self.ai}], "has_share": self.share}
        if "/*arrow:" in expression:
            return {"x": 1, "y": 2}
        raise AssertionError("unexpected js: " + expression[:80])

    def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == (10, 20):
            self.gallery_open = not self.gallery_open

    def run(self, mode, root, caption_file=None):
        env = {"IG_COMPOSER_CHECK": mode, "IG_COMPOSER_SCREENSHOT_DIR": str(root)}
        if caption_file:
            env["IG_CAPTION_FILE"] = str(caption_file)
        with patch.dict(os.environ, env, clear=False), patch("time.sleep", lambda _s: None):
            runpy.run_path(str(SCRIPT), init_globals={
                "cdp": self.cdp, "js": self.js, "click_at_xy": self.click,
                "switch_tab": lambda _t, activate=False: activate,
            })


class GalleryCheckTests(unittest.TestCase):
    def test_gallery_without_horizontal_scroller_is_checked_and_closed(self):
        # 2026-11-15: 썸네일 5장이 한 화면에 다 보여 스크롤 영역이 없자 scrollLeft 오류로 갤러리가 열린 채 남았다
        fake = FakeComposer(scroller=False)
        with tempfile.TemporaryDirectory() as tmp:
            fake.run("gallery", Path(tmp))
            saved = json.loads((Path(tmp) / "gallery.json").read_text(encoding="utf-8"))
            self.assertTrue((Path(tmp) / "gallery-left.jpg").is_file())
        self.assertEqual(saved["count"], 5)
        self.assertFalse(fake.gallery_open)

    def test_gallery_with_wrong_count_fails_after_closing(self):
        fake = FakeComposer(thumbs=1)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(RuntimeError, "five"):
            fake.run("gallery", Path(tmp))
        self.assertFalse(fake.gallery_open)


class PreShareCheckTests(unittest.TestCase):
    def test_caption_mismatch_stops_before_any_click(self):
        fake = FakeComposer(caption="다른 캡션")
        with tempfile.TemporaryDirectory() as tmp:
            caption = Path(tmp) / "caption.txt"
            caption.write_text("캡션", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "caption"):
                fake.run("pre_share", Path(tmp), caption)
        self.assertEqual(fake.clicks, [])

    def test_ai_label_off_stops(self):
        fake = FakeComposer(ai=False)
        with tempfile.TemporaryDirectory() as tmp:
            caption = Path(tmp) / "caption.txt"
            caption.write_text("캡션", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "AI"):
                fake.run("pre_share", Path(tmp), caption)

    def test_pre_share_visits_last_card_and_returns_to_first(self):
        fake = FakeComposer()
        with tempfile.TemporaryDirectory() as tmp:
            caption = Path(tmp) / "caption.txt"
            caption.write_text("캡션\n", encoding="utf-8")
            fake.run("pre_share", Path(tmp), caption)
            names = sorted(p.name for p in Path(tmp).glob("*.jpg"))
        self.assertEqual(names, ["pre-share-confirmed.jpg", "pre-share-first.jpg", "pre-share-last.jpg"])
        self.assertEqual(len(fake.clicks), 8)


if __name__ == "__main__":
    unittest.main()
