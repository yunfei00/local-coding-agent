import unittest
from unittest.mock import patch
from scripts.validation.check import commands, extract_failures


class LocalValidationTests(unittest.TestCase):
    def test_prefers_uv_and_resolves_npm_executable(self):
        def which(name):
            return {"uv": "uv-resolved", "npm": "npm-resolved", "npm.cmd": "npm-cmd-resolved"}.get(name)
        with patch("scripts.validation.check.shutil.which", side_effect=which):
            selected = commands()
        self.assertEqual(selected[0][1][:4], ["uv-resolved", "run", "--locked", "python"])
        self.assertIn(selected[1][1][0], ("npm-resolved", "npm-cmd-resolved"))

    def test_unrecognized_failure_keeps_useful_output(self):
        failures = extract_failures("Unable to launch compiler: missing binary", "BUILD", 1)
        self.assertIn("missing binary", failures[0]["detail"])
        self.assertEqual(failures[0]["stage"], "BUILD")

    def test_python_failure_has_test_name_and_error(self):
        failures = extract_failures("ERROR: test_cancel (ShellTests)\nTraceback\nPermissionError: locked directory", "PYTHON", 1)
        self.assertIn("test_cancel", failures[0]["detail"])
        self.assertIn("locked directory", failures[0]["detail"])
