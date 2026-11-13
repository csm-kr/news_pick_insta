import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("codex_executor", Path(__file__).with_name("codex_executor.py"))
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class CodexExecutorTests(unittest.TestCase):
    def test_command_is_native_ephemeral_structured_and_has_no_shared_daemon(self):
        with patch.dict(os.environ, {"NEWS_PICK_CODEX_MODEL": "", "NEWS_PICK_CODEX_EFFORT": ""}):
            command = MOD.build_command(Path("codex.exe"), Path("C:/work"), Path("schema.json"), Path("result.json"), Path("C:/work/output"))
        self.assertEqual(command[:3], ["codex.exe", "--no-daemon", "exec"])
        self.assertIn("--approve-for-me", command)
        self.assertIn("--json", command)
        self.assertIn("--ephemeral", command)
        self.assertNotIn("--model", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertEqual(command[-1], "-")

    def test_native_discovery_skips_shell_wrappers_and_unsupported_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / name for name in ("codex.cmd", "old.exe", "current.exe")]
            for path in paths:
                path.touch()
            with patch.object(MOD, "codex_candidates", return_value=paths), patch.object(MOD, "supports_exec", side_effect=lambda p: p.name == "current.exe"):
                self.assertEqual(MOD.find_codex(), paths[2].resolve())

    def test_codex_events_record_failure_and_thread_without_guessing_success(self):
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            events.write_text('\n'.join(json.dumps(e) for e in [
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.failed", "error": {"message": "usage limit"}},
            ]), encoding="utf-8")
            final, meta = MOD.parse_stream_result(events)
            self.assertIsNone(final)
            self.assertEqual(meta["thread_id"], "thread-1")
            self.assertTrue(meta["is_error"])
            self.assertEqual(meta["error"], "usage limit")


if __name__ == "__main__":
    unittest.main()
