import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("private_story_task.py")


def load_module():
    spec = importlib.util.spec_from_file_location("private_story_task", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PrivateStoryTaskTests(unittest.TestCase):
    def test_media_requires_matching_jpeg_hash(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / "story.jpg"
            media.write_bytes(b"approved-story")
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            self.assertEqual(module.validate_story_media(media, digest), media.resolve())
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                module.validate_story_media(media, "0" * 64)

    def test_media_rejects_non_jpeg(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / "story.png"
            media.write_bytes(b"not-a-jpeg")
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "JPEG"):
                module.validate_story_media(media, digest)

    def test_safe_error_redacts_session(self):
        module = load_module()
        secret = "1234567890%3Aexample-session-secret"
        message = module.safe_error(RuntimeError("failed " + secret), secret)
        self.assertNotIn(secret, message)
        self.assertIn("[redacted-session]", message)


if __name__ == "__main__":
    unittest.main()
