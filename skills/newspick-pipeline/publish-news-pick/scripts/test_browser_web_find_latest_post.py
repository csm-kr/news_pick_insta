import contextlib
import io
import itertools
import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_find_latest_post.py")
GRID = [
    {"href": "https://www.instagram.com/newspick_studio/p/NEWCODE/", "alts": ["Photo by 뉴스픽 on November 19, 2026. 텍스트의 이미지일 수 있음."]},
    {"href": "https://www.instagram.com/newspick_studio/p/OLDCODE/", "alts": ["Photo by 뉴스픽 on November 16, 2026. 텍스트의 이미지일 수 있음."]},
]
CAPTIONS = {"NEWCODE": "올해 7월 리트에서 만점을 받은 수험생이", "OLDCODE": "코스피가 하루 5% 내렸다"}


def run(environment, grid=GRID, captions=CAPTIONS):
    visited = []
    current = {"url": "https://www.instagram.com/newspick_studio/"}

    def fake_goto(url):
        current["url"] = url
        visited.append(url)

    def fake_js(expression):
        if "a[href*=\"/p/\"]" in expression:
            return {"url": current["url"], "posts": grid}
        if "document.body.innerText" in expression:
            code = current["url"].rstrip("/").rsplit("/", 1)[-1]
            return {"url": current["url"], "text": "newspick_studio " + captions.get(code, "")}
        return None

    def fake_cdp(method, **_kwargs):
        if method == "Target.getTargets":
            return {"targetInfos": [{"type": "page", "url": "https://www.instagram.com/newspick_studio/", "targetId": "t"}]}
        return {}

    output = io.StringIO()
    error = None
    with patch.dict(os.environ, environment, clear=False), patch("time.sleep", return_value=None), \
            patch("time.monotonic", side_effect=itertools.count(0, 10)), contextlib.redirect_stdout(output):
        try:
            runpy.run_path(str(SCRIPT), init_globals={
                "cdp": fake_cdp, "js": fake_js, "goto_url": fake_goto,
                "wait_for_load": lambda: None, "switch_tab": lambda _t, activate=False: activate,
            })
        except RuntimeError as exc:
            error = str(exc)
    return output.getvalue(), error, visited


class FindLatestPostTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("IG_EXPECTED_ALT_TOKENS", None)
        os.environ.pop("IG_EXPECTED_CAPTION_PREFIX", None)

    def test_caption_prefix_finds_new_post_when_alt_has_only_generic_text(self):
        printed, error, _ = run({"IG_EXPECTED_CAPTION_PREFIX": "올해 7월 리트에서 만점을"})
        self.assertIsNone(error)
        self.assertIn('"shortcode": "NEWCODE"', printed)
        self.assertIn('"url": "https://www.instagram.com/p/NEWCODE/"', printed)

    def test_caption_prefix_skips_newest_post_with_different_caption(self):
        printed, error, visited = run({"IG_EXPECTED_CAPTION_PREFIX": "코스피가 하루"})
        self.assertIsNone(error)
        self.assertIn('"shortcode": "OLDCODE"', printed)
        self.assertIn("https://www.instagram.com/p/NEWCODE/", visited)

    def test_caption_prefix_with_no_match_fails(self):
        _, error, _ = run({"IG_EXPECTED_CAPTION_PREFIX": "없는 문장"})
        self.assertIn("not found", error)

    def test_alt_tokens_still_work(self):
        printed, error, _ = run({"IG_EXPECTED_ALT_TOKENS": "November 16"})
        self.assertIsNone(error)
        self.assertIn('"shortcode": "OLDCODE"', printed)

    def test_requires_tokens_or_caption_prefix(self):
        _, error, _ = run({})
        self.assertIn("IG_EXPECTED_CAPTION_PREFIX", error)


if __name__ == "__main__":
    unittest.main()
