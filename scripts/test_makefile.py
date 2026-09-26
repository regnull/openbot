#!/usr/bin/env python3

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAKEFILE = ROOT / "Makefile"
BUILDER_CONFIG = ROOT / "electron-builder.yml"


class ElectronReleaseMakeTargetTests(unittest.TestCase):
    def test_release_target_runs_existing_packaging_script(self):
        result = subprocess.run(
            ["make", "-n", "electron-release"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cd frontend && pnpm electron:package", result.stdout)
        self.assertNotIn("--linux", result.stdout)
        self.assertNotIn("--mac", result.stdout)
        self.assertNotIn("--win", result.stdout)

    def test_release_target_is_phony_and_legacy_alias_is_preserved(self):
        makefile = MAKEFILE.read_text()
        self.assertIn("electron-release", makefile.splitlines()[0])
        self.assertIn("electron-package: electron-release", makefile)

    def test_builder_config_declares_host_platform_outputs(self):
        config = BUILDER_CONFIG.read_text()
        self.assertIn("directories:\n  output: release", config)
        self.assertIn("mac:\n", config)
        self.assertIn("win:\n", config)
        self.assertIn("linux:\n", config)


if __name__ == "__main__":
    unittest.main()
