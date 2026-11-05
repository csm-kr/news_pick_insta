from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edge_browser


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class EdgeBrowserTests(unittest.TestCase):
    def test_canonicalizes_account_scoped_instagram_post_links(self):
        expected = ("https://www.instagram.com/p/DciUenqIDuq/", "DciUenqIDuq")
        self.assertEqual(
            edge_browser.canonical_instagram_post_url(
                "https://www.instagram.com/newspick_studio/p/DciUenqIDuq/?utm_source=ig_web_copy_link"
            ),
            expected,
        )
        self.assertEqual(
            edge_browser.canonical_instagram_post_url(
                "https://www.instagram.com/p/DciUenqIDuq/"
            ),
            expected,
        )
        with self.assertRaisesRegex(ValueError, "사진 게시물"):
            edge_browser.canonical_instagram_post_url(
                "https://www.instagram.com/newspick_studio/reel/DciUenqIDuq/"
            )

    def test_connection_is_fixed_to_named_edge(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                edge_browser.connection_settings(),
                {"name": "edge9333", "endpoint": "http://127.0.0.1:9333"},
            )
        with patch.dict("os.environ", {"BU_NAME": "default"}, clear=True):
            with self.assertRaisesRegex(ValueError, "edge9333"):
                edge_browser.connection_settings()
        with patch.dict(
            "os.environ",
            {"NEWS_PICK_BROWSER_HARNESS_NAME": "edge9333", "BU_NAME": "default"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "BU_NAME"):
                edge_browser.connection_settings()
        with patch.dict("os.environ", {"NEWS_PICK_BROWSER": "chrome"}, clear=True):
            with self.assertRaisesRegex(ValueError, "edge"):
                edge_browser.connection_settings()

    def test_run_script_routes_to_ego_when_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "task.py"
            script.write_bytes(b"print('ego')\n")
            with patch.dict("os.environ", {"NEWS_PICK_BROWSER": "ego"}, clear=True), patch.object(
                edge_browser, "probe_edge_endpoint"
            ) as probe, patch.object(edge_browser.subprocess, "run") as run, patch(
                "ego_harness.run_script"
            ) as ego_run:
                ego_run.return_value.returncode = 0
                edge_browser.run_script(script, timeout=5, extra_env={"IG_ACCOUNT": "newspick_studio"})
            probe.assert_not_called()
            run.assert_not_called()
            ego_run.assert_called_once()
            self.assertEqual(ego_run.call_args.args[0], script.resolve())
            self.assertEqual(ego_run.call_args.kwargs["timeout"], 5)
            self.assertEqual(ego_run.call_args.kwargs["extra_env"], {"IG_ACCOUNT": "newspick_studio"})

    def test_connection_settings_tolerates_ego_selection(self):
        self.assertEqual(
            edge_browser.connection_settings({"NEWS_PICK_BROWSER": "ego"}),
            {"name": "edge9333", "endpoint": "http://127.0.0.1:9333"},
        )

    def test_ego_is_the_only_other_allowed_browser(self):
        self.assertEqual(edge_browser.selected_browser({}), "edge")
        self.assertEqual(edge_browser.selected_browser({"NEWS_PICK_BROWSER": "ego"}), "ego")
        with self.assertRaisesRegex(ValueError, "edge"):
            edge_browser.selected_browser({"NEWS_PICK_BROWSER": "chrome"})

    def test_probe_accepts_edge_and_rejects_chrome(self):
        edge = {"Browser": "Edg/151.0", "Protocol-Version": "1.3", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/id"}
        with patch.object(edge_browser.urllib.request, "urlopen", return_value=_Response(edge)):
            self.assertEqual(edge_browser.probe_edge_endpoint()["browser"], "Edg/151.0")
        chrome = {**edge, "Browser": "Chrome/151.0"}
        with patch.object(edge_browser.urllib.request, "urlopen", return_value=_Response(chrome)):
            with self.assertRaisesRegex(ValueError, "Microsoft Edge"):
                edge_browser.probe_edge_endpoint()

    def test_run_script_passes_exact_source_bytes_once(self):
        source = b"print('one process')\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "task.py"
            script.write_bytes(source)
            with patch.object(edge_browser, "probe_edge_endpoint"), patch.object(
                edge_browser.shutil, "which", return_value="browser-harness"
            ), patch.object(edge_browser.subprocess, "run") as run:
                run.return_value.returncode = 0
                edge_browser.run_script(script)
            self.assertEqual(run.call_count, 1)
            browser_source = run.call_args.kwargs["input"]
            self.assertTrue(browser_source.startswith(edge_browser.EDGE_RUNTIME_GUARD))
            self.assertTrue(browser_source.endswith(source))
            self.assertEqual(browser_source.count(source), 1)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["BU_NAME"], "edge9333")
            self.assertEqual(env["BU_CDP_URL"], "http://127.0.0.1:9333")
            self.assertEqual(env["NEWS_PICK_BROWSER"], "edge")


    def test_launch_keeps_rendering_when_window_is_covered(self):
        import launch_edge_profile
        command = launch_edge_profile.launch_command(Path("msedge.exe"), "newspick_studio", Path("profile"))
        # 다른 창에 덮인 Edge 탭도 hidden이 되면 Instagram 작성기가 멈춘다
        self.assertIn("--disable-backgrounding-occluded-windows", command)
        self.assertIn("--disable-features=CalculateNativeWinOcclusion", command)
        self.assertEqual(command[-1], "https://www.instagram.com/newspick_studio/")


if __name__ == "__main__":
    unittest.main()
