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

if __name__ == "__main__":
    unittest.main()
