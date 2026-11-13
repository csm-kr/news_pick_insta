import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("image_backend_runtime", SCRIPTS / "image_backend_runtime.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class ImageBackendRuntimeTests(unittest.TestCase):
    def setup_home(self, root):
        (root / "auth.json").write_text("not-read-credential-content", encoding="utf-8")
        (root / "config.toml").write_text('model = "available-model"\n[profiles.old]\nmodel = "old-model"\n', encoding="utf-8")
        (root / "models_cache.json").write_text(json.dumps({"models": [{"slug": "available-model"}]}), encoding="utf-8")

    def test_configured_model_replaces_obsolete_library_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_home(root)
            environment = {"CODEX_HOME": str(root)}
            child, report = RUNTIME.resolve_runtime(environment=environment)
            self.assertEqual(child["CODEX_IMAGEGEN_MODEL"], "available-model")
            self.assertEqual(report["model_source"], "codex_config")
            self.assertFalse(report["credentials_recorded"])
            self.assertNotIn("CODEX_IMAGEGEN_MODEL", environment)
            self.assertNotIn("not-read-credential-content", json.dumps(report))

    def test_explicit_auth_path_is_child_only_and_never_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_home(root)
            fresh = root / "fresh.json"
            fresh.write_text("new-login", encoding="utf-8")
            child, report = RUNTIME.resolve_runtime(fresh, environment={"CODEX_HOME": str(root)})
            self.assertEqual(child["CODEX_IMAGEGEN_AUTH_FILE"], str(fresh.resolve()))
            self.assertEqual(report["auth_file_source"], "explicit_or_environment")
            self.assertEqual((root / "auth.json").read_text(), "not-read-credential-content")

    def test_missing_auth_does_not_search_other_homes(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "인증 파일"):
                RUNTIME.resolve_runtime(environment={"CODEX_HOME": directory})

    def test_unlisted_model_fails_before_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_home(root)
            with self.assertRaisesRegex(ValueError, "로컬 지원 목록"):
                RUNTIME.resolve_runtime(model="obsolete-model", environment={"CODEX_HOME": str(root)})

    def test_explicit_model_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_home(root)
            child, _report = RUNTIME.resolve_runtime(model="available-model", environment={"CODEX_HOME": str(root), "CODEX_IMAGEGEN_MODEL": "obsolete-model"})
            self.assertEqual(child["CODEX_IMAGEGEN_MODEL"], "available-model")

    def test_profile_model_is_not_silently_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_home(root)
            (root / "config.toml").write_text('[profiles.only]\nmodel = "available-model"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "imagegen-model"):
                RUNTIME.resolve_runtime(environment={"CODEX_HOME": str(root)})

    def test_preflight_failure_skips_remaining_candidates(self):
        records = [{"card_index": index} for index in range(15)]
        calls = []

        def fail(record):
            calls.append(record)
            return {**record, "ok": False, "error": "HTTP 401"}

        results = RUNTIME.run_checked_batch(records, fail, 15)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 15)
        self.assertEqual(sum(bool(record.get("skipped")) for record in results), 14)

    def test_reused_candidate_is_not_a_live_authentication_check(self):
        records = [{"card_index": index} for index in range(4)]
        calls = []

        def invoke(record):
            calls.append(record["card_index"])
            return {**record, "ok": record["card_index"] == 0, "reused": record["card_index"] == 0}

        results = RUNTIME.run_checked_batch(records, invoke, 4)
        self.assertEqual(calls, [0, 1])
        self.assertEqual(sum(bool(record.get("skipped")) for record in results), 2)

    def test_process_failure_is_recorded_and_stops_fanout(self):
        def invoke(record):
            raise OSError("process unavailable")

        results = RUNTIME.run_checked_batch([{"card_index": 1}, {"card_index": 2}], invoke, 2)
        self.assertIn("OSError", results[0]["error"])
        self.assertTrue(results[1]["skipped"])

    def test_success_and_dry_run_preserve_input_order(self):
        records = [{"card_index": index} for index in range(15)]
        for dry_run in (False, True):
            results = RUNTIME.run_checked_batch(records, lambda record: {**record, "ok": True}, 15, dry_run)
            self.assertEqual([record["card_index"] for record in results], list(range(15)))

    def test_diagnostic_redacts_secrets_and_preserves_response(self):
        script = "globalThis.fetch=async()=>new Response(JSON.stringify({detail:'unsupported model Bearer secret eyJabcdef.xyz sk-secret https://example.com/private data:image/png;base64,abcd'}),{status:400});"
        script += f"await import({json.dumps((SCRIPTS / 'image_backend_diagnostic.mjs').resolve().as_uri())});"
        script += "const response=await fetch('unused'); if(response.status!==400 || !(await response.json()).detail)process.exit(1);"
        result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        self.assertIn("unsupported model", result.stderr)
        for secret in ("Bearer secret", "eyJabcdef", "sk-secret", "https://example.com", "base64,abcd"):
            self.assertNotIn(secret, result.stderr)

    def test_null_error_payload_does_not_mask_http_status(self):
        script = "globalThis.fetch=async()=>new Response('null',{status:400});"
        script += f"await import({json.dumps((SCRIPTS / 'image_backend_diagnostic.mjs').resolve().as_uri())});"
        script += "if((await fetch('unused')).status!==400)process.exit(1);"
        subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, check=True)


if __name__ == "__main__":
    unittest.main()
