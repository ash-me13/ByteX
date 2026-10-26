"""
Tests for AppleScript escaping, quoting, and injection prevention.
"""

import unittest
from unittest.mock import patch, MagicMock
import subprocess

from core.applescript import (
    escape_applescript_string,
    applescript_quote,
    run_applescript,
    activate_application,
    quit_application,
    delete_to_trash,
)


class TestAppleScriptSecurity(unittest.TestCase):
    def test_escape_double_quotes(self):
        input_str = 'My "Special" App'
        escaped = escape_applescript_string(input_str)
        self.assertEqual(escaped, 'My \\"Special\\" App')

    def test_escape_backslashes(self):
        input_str = r"C:\Path\To\File"
        escaped = escape_applescript_string(input_str)
        self.assertEqual(escaped, r"C:\\Path\\To\\File")

    def test_escape_newlines_and_returns(self):
        input_str = "Line 1\nLine 2\rLine 3"
        escaped = escape_applescript_string(input_str)
        self.assertEqual(escaped, r"Line 1\nLine 2\rLine 3")

    def test_reject_null_bytes(self):
        input_str = "Malicious\0App"
        with self.assertRaises(ValueError):
            escape_applescript_string(input_str)

    def test_applescript_quote_wraps_in_quotes(self):
        input_str = 'App "Name"'
        quoted = applescript_quote(input_str)
        self.assertEqual(quoted, '"App \\"Name\\""')

    def test_preserves_shell_metacharacters_safely(self):
        # Shell metacharacters like $(whoami), `id`, ; rm -rf /, etc. should be preserved literally
        # without being interpreted, since subprocess uses shell=False and argv passing
        input_str = "App $(touch /tmp/evil) ; rm -rf / | echo test"
        escaped = escape_applescript_string(input_str)
        self.assertEqual(escaped, input_str)

    @patch("subprocess.run")
    def test_run_applescript_never_uses_shell_true(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["osascript", "-e", "return 1"], returncode=0, stdout="1\n", stderr=""
        )

        res = run_applescript("return 1", args=["arg1", "arg2"])
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        call_args = mock_run.call_args.args[0]

        # Verify shell=True is NOT passed
        self.assertNotIn("shell", call_kwargs)
        self.assertEqual(call_args, ["osascript", "-e", "return 1", "arg1", "arg2"])
        self.assertEqual(res.returncode, 0)

    @patch("core.applescript.run_applescript")
    def test_activate_application_uses_on_run_argv(self, mock_run_script):
        mock_run_script.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        ok, msg = activate_application('Google "Chrome"')
        self.assertTrue(ok)
        mock_run_script.assert_called_once()
        args = mock_run_script.call_args[0]
        script = args[0]
        cmd_args = mock_run_script.call_args[1].get("args")

        self.assertIn("on run argv", script)
        self.assertIn("set appName to item 1 of argv", script)
        self.assertEqual(cmd_args, ['Google "Chrome"'])

    @patch("core.applescript.run_applescript")
    def test_quit_application_uses_on_run_argv(self, mock_run_script):
        mock_run_script.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        ok, msg = quit_application("Safari")
        self.assertTrue(ok)
        mock_run_script.assert_called_once()
        args = mock_run_script.call_args[0]
        script = args[0]
        cmd_args = mock_run_script.call_args[1].get("args")

        self.assertIn("on run argv", script)
        self.assertIn("set appName to item 1 of argv", script)
        self.assertEqual(cmd_args, ["Safari"])

    @patch("core.applescript.run_applescript")
    def test_delete_to_trash_uses_on_run_argv_and_alias(self, mock_run_script):
        mock_run_script.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        ok, msg = delete_to_trash("/Users/test/file with space.txt")
        self.assertTrue(ok)
        mock_run_script.assert_called_once()
        args = mock_run_script.call_args[0]
        script = args[0]
        cmd_args = mock_run_script.call_args[1].get("args")

        self.assertIn("on run argv", script)
        self.assertIn("set filePath to item 1 of argv", script)
        self.assertIn("POSIX file filePath as alias", script)
        self.assertEqual(cmd_args, ["/Users/test/file with space.txt"])

    def test_invalid_names_rejected_early(self):
        ok, msg = activate_application("")
        self.assertFalse(ok)

        ok, msg = quit_application("   ")
        self.assertFalse(ok)

        ok, msg = delete_to_trash("")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
