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
            result = MOD.initialize(workspace, "output", "@newspick_studio", "Profile 3")
            output = workspace / "output"
            self.assertEqual(Path(result["output_root"]), output.resolve())
            self.assertTrue((output / "runs").is_dir())
            self.assertTrue((output / "publish-news-pick").is_dir())
            self.assertTrue((output / "workspace.json").is_file())
            self.assertFalse((workspace / "skills").exists())

    def test_install_copies_all_skills_without_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            result = MOD.install(target)
            self.assertEqual(len(result["installed"]), 5)
            for name in MOD.SKILL_NAMES:
                self.assertTrue((target / name / "SKILL.md").is_file())
                self.assertFalse((target / name / ".local").exists())

    def test_dependency_status_has_aggregate_ready_flag(self):
        result = MOD.dependency_status()
        self.assertIn("ready", result)
        self.assertEqual(result["ready"], all(item["ok"] for item in result["dependencies"].values()))

    def test_output_cannot_be_initialized_inside_skills_source(self):
        with self.assertRaisesRegex(ValueError, "skills"):
            MOD.initialize(MOD.SOURCE_SKILLS, "runtime-output", "newspick_studio", "Profile 3")


if __name__ == "__main__":
    unittest.main()
