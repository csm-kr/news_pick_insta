from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PATH = Path(__file__).with_name("wait_for_publish_time.py")
SPEC = importlib.util.spec_from_file_location("wait_for_publish_time", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class WaitForPublishTimeTests(unittest.TestCase):
    def test_accepts_powershell_seven_digit_fraction(self):
        value = MOD.parse_iso_datetime("2026-08-18T17:00:00.1234567+09:00")
        self.assertEqual(value.isoformat(), "2026-08-18T17:00:00.123456+09:00")

    def test_requires_scheduled_mode_and_timezone(self):
        with self.assertRaises(ValueError):
            MOD.scheduled_time({"NEWS_PICK_EDITION_AT": "2026-08-18T17:00:00+09:00"})
        with self.assertRaises(ValueError):
            MOD.scheduled_time({"NEWS_PICK_SCHEDULED_MODE": "1", "NEWS_PICK_EDITION_AT": "2026-08-18T17:00:00"})

    def test_accepts_preparation_and_publish_windows(self):
        target = datetime(2026, 8, 18, 17, 0, tzinfo=timezone(timedelta(hours=9)))
        self.assertEqual(MOD.validate_window(target, target - timedelta(minutes=30)), 1800)
        self.assertEqual(MOD.validate_window(target, target), 0)
        self.assertEqual(MOD.validate_window(target, target + timedelta(minutes=30)), -1800)

    def test_rejects_too_early_and_too_late(self):
        target = datetime(2026, 8, 18, 17, 0, tzinfo=timezone(timedelta(hours=9)))
        with self.assertRaises(ValueError):
            MOD.validate_window(target, target - timedelta(minutes=36))
        with self.assertRaises(ValueError):
            MOD.validate_window(target, target + timedelta(minutes=31))


    def test_publish_offset_defaults_to_zero_and_is_bounded(self):
        self.assertEqual(MOD.publish_offset({}), timedelta(0))
        self.assertEqual(MOD.publish_offset({"NEWS_PICK_PUBLISH_OFFSET_SECONDS": "437"}), timedelta(seconds=437))
        with self.assertRaises(ValueError):
            MOD.publish_offset({"NEWS_PICK_PUBLISH_OFFSET_SECONDS": "1500"})
        with self.assertRaises(ValueError):
            MOD.publish_offset({"NEWS_PICK_PUBLISH_OFFSET_SECONDS": "-5"})

    def test_offset_delays_release_but_keeps_edition_windows(self):
        target = datetime(2026, 8, 18, 17, 0, tzinfo=timezone(timedelta(hours=9)))
        offset = timedelta(minutes=7)
        self.assertEqual(MOD.validate_window(target, target, offset), 420)
        self.assertEqual(MOD.validate_window(target, target - timedelta(minutes=30), offset), 2220)
        with self.assertRaises(ValueError):
            MOD.validate_window(target, target - timedelta(minutes=36), offset)
        with self.assertRaises(ValueError):
            MOD.validate_window(target, target + timedelta(minutes=31), offset)

    def test_recovery_requires_flag_and_timezone_aware_failed_at(self):
        self.assertIsNone(MOD.recovery_failed_at({}))
        failed = MOD.recovery_failed_at(
            {"NEWS_PICK_SHARE_RECOVERY": "1", "NEWS_PICK_SHARE_FAILED_AT": "2026-10-21T07:13:00+09:00"}
        )
        self.assertEqual(failed.isoformat(), "2026-10-21T07:13:00+09:00")
        with self.assertRaises(ValueError):
            MOD.recovery_failed_at({"NEWS_PICK_SHARE_RECOVERY": "1"})
        with self.assertRaises(ValueError):
            MOD.recovery_failed_at({"NEWS_PICK_SHARE_RECOVERY": "1", "NEWS_PICK_SHARE_FAILED_AT": "2026-10-21T07:13:00"})

    def test_recovery_waits_ten_minutes_after_failure_within_sixty_minute_window(self):
        target = datetime(2026, 10, 21, 7, 0, tzinfo=timezone(timedelta(hours=9)))
        failed = target + timedelta(minutes=13)
        self.assertEqual(MOD.validate_recovery_window(target, failed, failed), 600)
        self.assertEqual(MOD.validate_recovery_window(target, target + timedelta(minutes=35), failed), -720)
        self.assertEqual(MOD.validate_recovery_window(target, target + timedelta(minutes=60), failed), -2220)
        with self.assertRaises(ValueError):
            MOD.validate_recovery_window(target, target + timedelta(minutes=61), failed)
        with self.assertRaises(ValueError):
            MOD.validate_recovery_window(target, failed, target - timedelta(minutes=1))

    def _fake_clock(self, start):
        state = {"now": start, "slept": 0.0}

        def now(_tz=None):
            return state["now"]

        def sleep(seconds):
            state["slept"] += seconds
            state["now"] = state["now"] + timedelta(seconds=seconds)

        return state, now, sleep

    def test_wait_returns_none_after_max_wait_so_tool_call_ends_before_timeout(self):
        # 11-21·11-22 07시: 게이트가 25분까지 기다려 도구 제한(10분)을 넘자 백그라운드로 돌리고 턴을 끝내 결과가 강제됐다.
        target = datetime(2026, 11, 22, 7, 0, tzinfo=timezone(timedelta(hours=9)))
        state, now, sleep = self._fake_clock(target - timedelta(minutes=10))
        released = MOD.wait_until(target, timedelta(minutes=15), max_wait=540, now_fn=now, sleep_fn=sleep)
        self.assertIsNone(released)
        self.assertLessEqual(state["slept"], 540)

    def test_wait_releases_within_max_wait(self):
        target = datetime(2026, 11, 22, 7, 0, tzinfo=timezone(timedelta(hours=9)))
        state, now, sleep = self._fake_clock(target - timedelta(minutes=2))
        released = MOD.wait_until(target, timedelta(minutes=1), max_wait=540, now_fn=now, sleep_fn=sleep)
        self.assertEqual(released, target + timedelta(minutes=1))

    def test_main_exits_3_while_still_waiting(self):
        import io
        import os
        from contextlib import redirect_stdout
        from unittest.mock import patch

        target = datetime.now(timezone(timedelta(hours=9))) + timedelta(minutes=20)
        environment = {"NEWS_PICK_SCHEDULED_MODE": "1", "NEWS_PICK_EDITION_AT": target.isoformat(),
                       "NEWS_PICK_PUBLISH_OFFSET_SECONDS": "0", "NEWS_PICK_GATE_MAX_WAIT_SECONDS": "0"}
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=False), redirect_stdout(output):
            code = MOD.main()
        self.assertEqual(code, 3)
        self.assertIn('"waiting": true', output.getvalue())
        self.assertIn('"ok": false', output.getvalue())

    def test_default_max_wait_is_below_ten_minute_tool_limit(self):
        self.assertLessEqual(MOD.DEFAULT_MAX_WAIT_SECONDS, 540)


if __name__ == "__main__":
    unittest.main()
