from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

PATH = Path(__file__).with_name("carousel_queue.py")
SPEC = importlib.util.spec_from_file_location("carousel_queue", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class QueueTests(unittest.TestCase):
    def test_output_root_uses_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NEWS_PICK_OUTPUT_ROOT": tmp}):
            self.assertEqual(MOD.default_output_root(), Path(tmp).resolve())

    def test_output_root_inside_installed_skills_is_rejected(self):
        skills_root = Path(MOD.__file__).resolve().parents[2]
        with patch.dict("os.environ", {"NEWS_PICK_OUTPUT_ROOT": str(skills_root / "runtime-output")}):
            with self.assertRaisesRegex(ValueError, "skills"):
                MOD.default_output_root()

    def files(self, root, count=3):
        result = []
        for i in range(count):
            path = root / f"{i}.png"
            path.write_bytes(b"png" + bytes([i]))
            result.append(path)
        return result

    def test_prepare_approve_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            job = MOD.prepare("@newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root), "caption", jobs)
            approved = MOD.approve(job["job_id"], job["payload_sha256"], jobs)
            self.assertEqual(approved["status"], "approved")
            path, stored = MOD.load_job(job["job_id"], jobs)
            stored["status"] = "submitted"
            stored["private_result"] = {"shortcode": "abc"}
            MOD.atomic_json(path, stored)
            result = MOD.verify_published(job["job_id"], "abc", 3, True, True, jobs)
            self.assertTrue(result["public_verified"])

    def test_hash_detects_order_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            job = MOD.prepare("newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root), "caption", jobs)
            path, stored = MOD.load_job(job["job_id"], jobs)
            stored["media"][0], stored["media"][1] = stored["media"][1], stored["media"][0]
            with self.assertRaises(ValueError):
                MOD.validate_job(stored, path)

    def test_record_web_submission_then_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            job = MOD.prepare("newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root, 4), "caption", jobs)
            MOD.approve(job["job_id"], job["payload_sha256"], jobs)
            recorded = MOD.record_web_submitted(job["job_id"], "DcKLQMmk5lp", 4, jobs)
            self.assertEqual(recorded["status"], "submitted")
            self.assertEqual(recorded["submission_result"]["backend"], "browser_harness_web_ui")
            result = MOD.verify_published(job["job_id"], "DcKLQMmk5lp", 4, True, True, jobs)
            self.assertTrue(result["public_verified"])

    def test_verify_writes_orchestrator_run_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NEWS_PICK_OUTPUT_ROOT": tmp}):
            root = Path(tmp)
            jobs = root / "publish-news-pick" / "jobs"
            run = root / "runs" / "run-1"
            run.mkdir(parents=True)
            (run / "run.json").write_text('{"account":"newspick_studio"}', encoding="utf-8")
            job = MOD.prepare("newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root, 4), "caption", jobs)
            MOD.approve(job["job_id"], job["payload_sha256"], jobs)
            MOD.record_web_submitted(job["job_id"], "DcKLQMmk5lp", 4, jobs)
            result = MOD.verify_published(job["job_id"], "DcKLQMmk5lp", 4, True, True, jobs, run)
            stored = json.loads((run / "04-publish" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(stored, result)
            self.assertEqual(MOD.load_job(job["job_id"], jobs)[1]["public_result"], result)

    def test_verify_rejects_run_outside_output_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other, patch.dict("os.environ", {"NEWS_PICK_OUTPUT_ROOT": tmp}):
            root = Path(tmp)
            jobs = root / "publish-news-pick" / "jobs"
            job = MOD.prepare("newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root), "caption", jobs)
            MOD.approve(job["job_id"], job["payload_sha256"], jobs)
            MOD.record_web_submitted(job["job_id"], "DcKLQMmk5lp", 3, jobs)
            with self.assertRaisesRegex(ValueError, "NEWS_PICK_OUTPUT_ROOT/runs"):
                MOD.verify_published(job["job_id"], "DcKLQMmk5lp", 3, True, True, jobs, Path(other))

    def test_record_web_submission_requires_matching_card_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            job = MOD.prepare("newspick_studio", "2026-08-17T17:00:00+09:00", "Asia/Seoul", self.files(root, 4), "caption", jobs)
            MOD.approve(job["job_id"], job["payload_sha256"], jobs)
            with self.assertRaises(ValueError):
                MOD.record_web_submitted(job["job_id"], "DcKLQMmk5lp", 3, jobs)

    def test_prepare_rejects_ai_reconstruction_caption_phrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "caption 금지 문구"):
                MOD.prepare(
                    "newspick_studio",
                    "2026-08-17T17:00:00+09:00",
                    "Asia/Seoul",
                    self.files(root, 4),
                    "기사·공식 이미지를 참고해 AI로 재구성한 인포그래픽입니다.",
                    root / "jobs",
                )


if __name__ == "__main__":
    unittest.main()
