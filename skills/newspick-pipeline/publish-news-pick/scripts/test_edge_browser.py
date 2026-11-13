from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edge_browser


class BrowserEntryTests(unittest.TestCase):
    """2026-11-06부터 뉴스픽은 ego lite만 쓴다. 이 모듈은 이름만 남은 ego 진입점이다."""

    def test_canonicalizes_account_scoped_instagram_post_links(self):
        expected = ("https://www.instagram.com/p/DciUenqIDuq/", "DciUenqIDuq")
        self.assertEqual(
            edge_browser.canonical_instagram_post_url(
                "https://www.instagram.com/newspick_studio/p/DciUenqIDuq/?utm_source=ig_web_copy_link"
            ),
            expected,
        )
        self.assertEqual(edge_browser.canonical_instagram_post_url("https://www.instagram.com/p/DciUenqIDuq/"), expected)
        with self.assertRaisesRegex(ValueError, "사진 게시물"):
            edge_browser.canonical_instagram_post_url("https://www.instagram.com/newspick_studio/reel/DciUenqIDuq/")

    def test_only_ego_is_allowed(self):
        self.assertEqual(edge_browser.selected_browser({}), "ego")
        self.assertEqual(edge_browser.selected_browser({"NEWS_PICK_BROWSER": "ego"}), "ego")
        for value in ("edge", "chrome", "default"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "ego"):
                edge_browser.selected_browser({"NEWS_PICK_BROWSER": value})

    def test_edge_connection_api_is_gone(self):
        for name in ("EDGE_CDP_URL", "EDGE_CONNECTION_NAME", "EDGE_RUNTIME_GUARD", "probe_edge_endpoint", "connection_settings", "browser_harness_environment"):
            self.assertFalse(hasattr(edge_browser, name), name)
        self.assertFalse((SCRIPTS / "launch_edge_profile.py").exists())

    def test_run_script_always_goes_to_ego(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "task.py"
            script.write_bytes(b"print('ego')\n")
            with patch.dict("os.environ", {}, clear=True), patch("ego_harness.run_script") as ego_run:
                ego_run.return_value.returncode = 0
                edge_browser.run_script(script, timeout=5, extra_env={"IG_ACCOUNT": "newspick_studio"})
            ego_run.assert_called_once()
            self.assertEqual(ego_run.call_args.args[0], script.resolve())
            self.assertEqual(ego_run.call_args.kwargs["timeout"], 5)
            self.assertEqual(ego_run.call_args.kwargs["extra_env"], {"IG_ACCOUNT": "newspick_studio"})

    def test_run_script_rejects_non_ego_selection_before_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "task.py"
            script.write_bytes(b"print('x')\n")
            with patch.dict("os.environ", {"NEWS_PICK_BROWSER": "edge"}, clear=True), patch("ego_harness.run_script") as ego_run:
                with self.assertRaises(ValueError):
                    edge_browser.run_script(script)
            ego_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
