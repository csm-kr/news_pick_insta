from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_carousel


class RunCarouselBrowserTests(unittest.TestCase):
    def run_probe(self, environment):
        completed = MagicMock(returncode=0, stdout=(run_carousel.PREFIX + '{"ok": true}\n').encode("utf-8"), stderr=b"")
        with patch.dict("os.environ", environment, clear=True), patch.object(
            sys, "argv", ["run_carousel.py", "--probe-account", "newspick_studio"]
        ), patch.object(run_carousel, "site_packages", return_value=Path("C:/venv/site-packages")), patch.object(
            run_carousel.edge_browser, "run_script", return_value=completed
        ) as run_script, redirect_stdout(io.StringIO()):
            code = run_carousel.main()
        return code, run_script

    def test_probe_runs_on_ego_without_edge_config(self):
        code, run_script = self.run_probe({})
        self.assertEqual(code, 0)
        self.assertEqual(run_script.call_args.kwargs["extra_env"]["CAROUSEL_PRIVATE_MODE"], "probe")


if __name__ == "__main__":
    unittest.main()
