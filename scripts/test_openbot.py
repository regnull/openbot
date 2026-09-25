#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "openbot"


class OpenBotLauncherTests(unittest.TestCase):
    def run_launcher(self, *args, cwd=None, home=None, repository=None):
        with tempfile.TemporaryDirectory() as tmp:
            fake_make = Path(tmp) / "make"
            fake_make.write_text(
                "#!/bin/sh\n"
                "printf 'cwd=%s\\n' \"$PWD\"\n"
                "printf 'workspace=%s\\n' \"$WORKSPACE_ROOT\"\n"
                "printf 'database=%s\\n' \"$DATABASE_URL\"\n"
                "printf 'args='; printf '%s|' \"$@\"; printf '\\n'\n"
            )
            fake_make.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp}{os.pathsep}{env['PATH']}"
            if home is not None:
                env["HOME"] = str(home)
            if repository is not None:
                env["OPENBOT_REPOSITORY"] = str(repository)
            return subprocess.run(
                [str(SCRIPT), *args], cwd=cwd, env=env, text=True, capture_output=True, check=False
            )

    def test_defaults_use_current_directory_and_home_database(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            result = self.run_launcher(cwd=tmp, home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"workspace={Path(tmp).resolve()}", result.stdout)
            self.assertIn(f"database=sqlite+aiosqlite:///{Path(home).resolve() / '.openbot' / 'openbot.db'}", result.stdout)
            self.assertIn("args=-C|", result.stdout)

    def test_root_override_preserves_spaces(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            root = Path(tmp) / "workspace with spaces"
            root.mkdir()
            result = self.run_launcher("--root", str(root), cwd=tmp, home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"workspace={root.resolve()}", result.stdout)

    def test_db_root_override_expands_tilde(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            result = self.run_launcher("--db-root", "~/data with spaces", cwd=tmp, home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = Path(os.path.realpath(home)) / "data with spaces" / "openbot.db"
            self.assertIn(f"database=sqlite+aiosqlite:///{expected}", result.stdout)

    def test_both_overrides_are_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            root = Path(tmp) / "root"
            db = Path(tmp) / "db root"
            root.mkdir()
            result = self.run_launcher("--root", str(root), "--db-root", str(db), cwd=tmp, home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"workspace={root.resolve()}", result.stdout)
            self.assertIn(f"database=sqlite+aiosqlite:///{db.resolve() / 'openbot.db'}", result.stdout)

    def test_repository_location_is_used_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            caller = Path(tmp) / "caller"
            repository = Path(tmp) / "repository with spaces"
            caller.mkdir()
            repository.mkdir()
            result = self.run_launcher(cwd=caller, home=home, repository=repository)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"args=-C|{repository.resolve()}|run|", result.stdout)
            self.assertIn(f"workspace={caller.resolve()}", result.stdout)

    def test_repository_location_must_be_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp) / "missing-repository"
            result = self.run_launcher(cwd=tmp, repository=repository)
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not exist", result.stderr)

    def test_invalid_usage_is_clear(self):
        result = self.run_launcher("--root")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--root requires a directory", result.stderr)

    def test_missing_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_launcher("--root", str(Path(tmp) / "missing"), cwd=tmp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
