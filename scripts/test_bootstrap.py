from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PATH = Path(__file__).with_name("bootstrap.py")
SPEC = importlib.util.spec_from_file_location("bootstrap", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class BootstrapTests(unittest.TestCase):
    def test_initialize_separates_runtime_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = MOD.initialize(workspace, "output", "@newspick_studio")
            output = workspace / "output"
            self.assertEqual(Path(result["output_root"]), output.resolve())
            self.assertTrue((output / "runs").is_dir())
            self.assertTrue((output / "publish-news-pick").is_dir())
            self.assertTrue((output / "daily-story").is_dir())
            self.assertTrue((output / "workspace.json").is_file())
            self.assertFalse((workspace / "skills").exists())
            self.assertEqual(result["browser"]["engine"], "edge")
            self.assertEqual(result["browser"]["connection_name"], "edge9333")
            self.assertEqual(result["environment"]["BU_CDP_URL"], "http://127.0.0.1:9333")

    def test_install_copies_all_skills_without_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            result = MOD.install(target)
            self.assertEqual(len(result["installed"]), 6)
            for name in MOD.SKILL_NAMES:
                self.assertTrue((target / name / "SKILL.md").is_file())
                self.assertFalse((target / name / ".local").exists())

    def test_update_existing_backs_up_old_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            MOD.install(target)
            marker = target / "publish-news-pick" / "old-marker.txt"
            marker.write_text("old", encoding="utf-8")
            result = MOD.install(target, update_existing=True)
            self.assertEqual(set(result["updated"]), set(MOD.SKILL_NAMES))
            self.assertFalse(marker.exists())
            backup = Path(result["backup_root"])
            self.assertEqual((backup / "publish-news-pick" / "old-marker.txt").read_text(encoding="utf-8"), "old")
            self.assertTrue((target / "publish-news-pick" / "scripts" / "launch_edge_profile.py").is_file())

    def test_dependency_status_has_aggregate_ready_flag(self):
        result = MOD.dependency_status()
        self.assertIn("ready", result)
        self.assertEqual(result["ready"], all(item["ok"] for item in result["dependencies"].values()))

    def test_publish_skill_has_only_edge_launcher(self):
        scripts = MOD.SOURCE_SKILLS / "publish-news-pick" / "scripts"
        self.assertTrue((scripts / "launch_edge_profile.py").is_file())
        self.assertTrue((scripts / "invoke_edge_browser_harness.py").is_file())
        self.assertFalse((scripts / "launch_chrome_profile.py").exists())
        skill = (MOD.SOURCE_SKILLS / "publish-news-pick" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("edge9333", skill)
        self.assertIn("Chrome/default/다른 endpoint는 fail closed", skill)

    def test_output_cannot_be_initialized_inside_skills_source(self):
        with self.assertRaisesRegex(ValueError, "skills"):
            MOD.initialize(MOD.SOURCE_SKILLS, "runtime-output", "newspick_studio")


if __name__ == "__main__":
    unittest.main()
