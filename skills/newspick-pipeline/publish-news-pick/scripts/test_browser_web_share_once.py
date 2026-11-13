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

        share_reads = 0

        def fake_js(expression):
            nonlocal share_reads
            if "label==='공유하기'" in expression:
                share_reads += 1
                if share_reads == 1:
                    return {"present": True, "x": 820, "y": 70, "source": "dom"}
                return {"present": False}
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
            self.assertIn('"reinforced_with_pointer_sequence": false', output.getvalue())

    def _run_script(self, fake_js, clicks, pointer_calls):
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
            if method == "Accessibility.getFullAXTree":
                return {"nodes": []}
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"jpeg").decode("ascii")}
            return {}

        with tempfile.TemporaryDirectory() as temporary:
            screenshot = Path(temporary) / "shared.jpg"
            output = io.StringIO()
            with patch.dict(
                os.environ, {"IG_SCREENSHOT": str(screenshot)}, clear=False
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
            return output.getvalue()

    def test_pointer_sequence_reinforces_a_click_that_never_reached_the_page(self):
        clicks = []
        pointer_calls = []

        def fake_js(expression):
            if "label==='공유하기'" in expression:
                return {"present": True, "x": 820, "y": 70, "source": "dom"}
            if "new PointerEvent('pointerdown'" in expression:
                pointer_calls.append(expression)
                return True
            if "const dialogs=" in expression:
                return {
                    "text": "게시물이 공유되었습니다",
                    "dialogs": [],
                    "url": "https://www.instagram.com/newspick_studio/",
                }
            return None

        printed = self._run_script(fake_js, clicks, pointer_calls)
        self.assertEqual(clicks, [(820, 70)])
        self.assertEqual(len(pointer_calls), 1)
        self.assertIn('"reinforced_with_pointer_sequence": true', printed)

    def test_no_reinforcement_when_the_share_control_goes_away(self):
        clicks = []
        pointer_calls = []
        share_reads = 0

        def fake_js(expression):
            nonlocal share_reads
            if "label==='공유하기'" in expression:
                share_reads += 1
                if share_reads == 1:
                    return {"present": True, "x": 820, "y": 70, "source": "dom"}
                return {"present": False}
            if "new PointerEvent('pointerdown'" in expression:
                pointer_calls.append(expression)
                return True
            if "const dialogs=" in expression:
                return {
                    "text": "게시물이 공유되었습니다",
                    "dialogs": [],
                    "url": "https://www.instagram.com/newspick_studio/",
                }
            return None

        printed = self._run_script(fake_js, clicks, pointer_calls)
        self.assertEqual(clicks, [(820, 70)])
        self.assertEqual(pointer_calls, [])
        self.assertIn('"reinforced_with_pointer_sequence": false', printed)

    def test_absent_share_control_is_not_clicked_again(self):
        clicks = []
        pointer_calls = []

        def fake_js(expression):
            if "label==='공유하기'" in expression:
                return {"present": False}
            if "new PointerEvent('pointerdown'" in expression:
                pointer_calls.append(expression)
                return True
            if "const dialogs=" in expression:
                return {
                    "text": "게시물이 공유되었습니다",
                    "dialogs": [],
                    "url": "https://www.instagram.com/newspick_studio/",
                }
            return None

        printed = self._run_script(fake_js, clicks, pointer_calls)
        self.assertEqual(clicks, [])
        self.assertEqual(pointer_calls, [])
        self.assertIn('"submission_already_started": true', printed)
        self.assertIn('"success_marker": true', printed)


class ShareRecoveryGateTests(unittest.TestCase):
    """미게시가 확인된 회차의 복구 공유: 실패 10분 뒤부터 회차+60분까지, run당 한 번."""

    def _run(self, run_dir, edition_minutes_ago, failed_minutes_ago, recovery=True):
        from datetime import datetime, timedelta, timezone

        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        clicks = []

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
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"jpeg").decode("ascii")}
            return {}

        share_reads = 0

        def fake_js(expression):
            nonlocal share_reads
            if "label==='공유하기'" in expression:
                share_reads += 1
                if share_reads == 1:
                    return {"present": True, "x": 820, "y": 70, "source": "dom"}
                return {"present": False}
            if "const dialogs=" in expression:
                return {"text": "게시물이 공유되었습니다", "dialogs": [], "url": "https://www.instagram.com/newspick_studio/"}
            return None

        environment = {
            "IG_SCREENSHOT": str(Path(run_dir) / "shared.jpg"),
            "NEWS_PICK_SCHEDULED_MODE": "1",
            "NEWS_PICK_EDITION_AT": (now - timedelta(minutes=edition_minutes_ago)).isoformat(),
            "NEWS_PICK_RUN_DIR": str(run_dir),
            "NEWS_PICK_SHARE_FAILED_AT": (now - timedelta(minutes=failed_minutes_ago)).isoformat(),
            "NEWS_PICK_SHARE_RECOVERY": "1" if recovery else "",
        }
        error = None
        with patch.dict(os.environ, environment, clear=False), patch("time.sleep", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            try:
                runpy.run_path(
                    str(SCRIPT),
                    init_globals={
                        "cdp": fake_cdp,
                        "js": fake_js,
                        "switch_tab": lambda _target, activate=False: activate,
                        "click_at_xy": lambda x, y: clicks.append((x, y)),
                    },
                )
            except RuntimeError as exc:
                error = str(exc)
        return clicks, error

    def test_recovery_clicks_once_after_ten_minutes_inside_sixty_minute_window(self):
        with tempfile.TemporaryDirectory() as run_dir:
            (Path(run_dir) / "04-publish").mkdir()
            clicks, error = self._run(run_dir, edition_minutes_ago=40, failed_minutes_ago=12)
            self.assertIsNone(error)
            self.assertEqual(clicks, [(820, 70)])
            self.assertTrue((Path(run_dir) / "04-publish" / "share-recovery.lock").is_file())

    def test_second_recovery_in_same_run_is_refused_before_click(self):
        with tempfile.TemporaryDirectory() as run_dir:
            (Path(run_dir) / "04-publish").mkdir()
            (Path(run_dir) / "04-publish" / "share-recovery.lock").write_text("used", encoding="utf-8")
            clicks, error = self._run(run_dir, edition_minutes_ago=40, failed_minutes_ago=12)
            self.assertEqual(clicks, [])
            self.assertIn("nothing was clicked", error)

    def test_recovery_refused_within_ten_minutes_of_failure(self):
        with tempfile.TemporaryDirectory() as run_dir:
            (Path(run_dir) / "04-publish").mkdir()
            clicks, error = self._run(run_dir, edition_minutes_ago=20, failed_minutes_ago=5)
            self.assertEqual(clicks, [])
            self.assertIn("nothing was clicked", error)

    def test_recovery_refused_after_sixty_minutes(self):
        with tempfile.TemporaryDirectory() as run_dir:
            (Path(run_dir) / "04-publish").mkdir()
            clicks, error = self._run(run_dir, edition_minutes_ago=61, failed_minutes_ago=30)
            self.assertEqual(clicks, [])
            self.assertIn("nothing was clicked", error)

    def test_normal_scheduled_share_still_closes_after_thirty_minutes(self):
        with tempfile.TemporaryDirectory() as run_dir:
            (Path(run_dir) / "04-publish").mkdir()
            clicks, error = self._run(run_dir, edition_minutes_ago=40, failed_minutes_ago=12, recovery=False)
            self.assertEqual(clicks, [])
            self.assertIn("30 minutes", error)


if __name__ == "__main__":
    unittest.main()
