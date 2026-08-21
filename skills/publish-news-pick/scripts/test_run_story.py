import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_story


class RunStoryTests(unittest.TestCase):
    def test_parse_result_uses_last_prefixed_line(self):
        first = {"ok": False}
        last = {"ok": True, "story_pk": "123"}
        output = "\n".join(
            [
                run_story.PREFIX + json.dumps(first),
                "diagnostic",
                run_story.PREFIX + json.dumps(last),
            ]
        )
        self.assertEqual(run_story.parse_result(output), last)

    def test_parse_result_returns_none_without_contract_line(self):
        self.assertIsNone(run_story.parse_result("diagnostic only"))


if __name__ == "__main__":
    unittest.main()
