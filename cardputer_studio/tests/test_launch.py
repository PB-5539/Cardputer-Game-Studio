import os
import tempfile
import unittest
from unittest import mock

from helpers import ROOT
import importlib.util

spec = importlib.util.spec_from_file_location("launch", os.path.join(ROOT, "launch.py"))
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


class LauncherTests(unittest.TestCase):
    def fake_env(self, tmp):
        venv_dir = os.path.join(tmp, ".venv")
        py = os.path.join(venv_dir, "bin", "python")
        return mock.patch.multiple(launch, VENV=venv_dir, STAMP=os.path.join(venv_dir, ".requirements.sha256"),
                                   venv_python=lambda: py), py

    def test_fresh_checkout_plans_full_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch, py = self.fake_env(tmp)
            with patch:
                self.assertFalse(launch.env_is_ready())
                steps = launch.plan()
                self.assertEqual(len(steps), 3)
                self.assertIn("create virtual environment", steps[0])
                self.assertIn("pip install", steps[1])

    def test_ready_env_only_starts_app_until_requirements_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch, py = self.fake_env(tmp)
            with patch:
                os.makedirs(os.path.dirname(py))
                open(py, "w").close()
                with open(launch.STAMP, "w") as f:
                    f.write(launch.requirements_hash())
                self.assertTrue(launch.env_is_ready())
                self.assertEqual(len(launch.plan()), 1)
                with open(launch.STAMP, "w") as f:
                    f.write("stale")
                self.assertFalse(launch.env_is_ready())
                self.assertEqual(len(launch.plan()), 2)       # reinstall, no new venv

    def test_check_flag_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch, py = self.fake_env(tmp)
            with patch, mock.patch.object(launch.subprocess, "call") as call:
                self.assertEqual(launch.main(["--check"]), 0)
                call.assert_not_called()
                self.assertFalse(os.path.exists(os.path.join(tmp, ".venv")))

    def test_failed_install_gives_clear_error_and_no_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch, py = self.fake_env(tmp)
            with patch, mock.patch.object(launch.venv.EnvBuilder, "create",
                                          lambda self, d: (os.makedirs(os.path.dirname(py)), open(py, "w").close())), \
                    mock.patch.object(launch.subprocess, "call", return_value=1):
                with self.assertRaises(SystemExit) as cm:
                    launch.setup()
                self.assertIn("pip install failed", str(cm.exception))
                self.assertFalse(os.path.exists(launch.STAMP))

    def test_requirements_list_the_real_dependencies(self):
        with open(os.path.join(ROOT, "requirements.txt")) as f:
            text = f.read().lower()
        self.assertIn("pyside6", text)


if __name__ == "__main__":
    unittest.main()
