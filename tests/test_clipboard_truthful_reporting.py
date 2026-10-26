"""
Tests for clipboard skill truthful reporting on macOS and Windows.
"""

import unittest
from unittest.mock import patch, MagicMock
import subprocess
import asyncio

from skills.clipboard import ClipboardSkill


class TestClipboardTruthfulReporting(unittest.TestCase):
    def setUp(self):
        self.skill = ClipboardSkill()

    def test_paste_empty_clipboard_fails_truthfully(self):
        with patch.object(self.skill, "_read_clipboard", return_value=""):
            result = asyncio.run(self.skill.execute({"action": "paste"}))
            self.assertFalse(result.success)
            self.assertFalse(result.verified)
            self.assertIn("empty", result.message.lower())

    @patch("sys.platform", "darwin")
    @patch("skills.clipboard.audit_logger")
    def test_macos_paste_accessibility_denied_reports_failure(self, mock_audit):
        with patch.object(self.skill, "_read_clipboard", return_value="hello world"):
            # Mock run_applescript to simulate -1743 (permission denied)
            def mock_run_script(script, timeout=2.0):
                if "get name of first process" in script:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="Terminal\n", stderr="")
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="",
                    stderr="System Events got an error: Terminal is not allowed to send keystrokes. (-1743)"
                )

            with patch("core.applescript.run_applescript", side_effect=mock_run_script):
                result = asyncio.run(self.skill.execute({"action": "paste"}))
                self.assertFalse(result.success)
                self.assertFalse(result.verified)
                self.assertIn("Accessibility permission denied", result.message)
                self.assertIn("Privacy & Security", result.message)

    @patch("sys.platform", "darwin")
    @patch("skills.clipboard.audit_logger")
    def test_macos_paste_generic_failure_reports_failure(self, mock_audit):
        with patch.object(self.skill, "_read_clipboard", return_value="hello world"):
            def mock_run_script(script, timeout=2.0):
                if "get name of first process" in script:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="Code\n", stderr="")
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="",
                    stderr="execution error: Some internal failure (-10000)"
                )

            with patch("core.applescript.run_applescript", side_effect=mock_run_script):
                result = asyncio.run(self.skill.execute({"action": "paste"}))
                self.assertFalse(result.success)
                self.assertFalse(result.verified)
                self.assertIn("Failed to dispatch paste keystroke", result.message)

    @patch("sys.platform", "darwin")
    @patch("skills.clipboard.audit_logger")
    def test_macos_paste_exception_reports_failure(self, mock_audit):
        with patch.object(self.skill, "_read_clipboard", return_value="hello world"):
            with patch("core.applescript.run_applescript", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=2.0)):
                result = asyncio.run(self.skill.execute({"action": "paste"}))
                self.assertFalse(result.success)
                self.assertFalse(result.verified)
                self.assertIn("Failed to paste on macOS", result.message)

    @patch("sys.platform", "darwin")
    @patch("skills.clipboard.audit_logger")
    def test_macos_paste_success_reports_verified(self, mock_audit):
        with patch.object(self.skill, "_read_clipboard", return_value="hello world"):
            def mock_run_script(script, timeout=2.0):
                if "get name of first process" in script:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="Notes\n", stderr="")
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            with patch("core.applescript.run_applescript", side_effect=mock_run_script):
                result = asyncio.run(self.skill.execute({"action": "paste"}))
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertIn("Pasted clipboard content into Notes", result.message)

    def test_read_and_write_clipboard(self):
        with patch("pyperclip.copy") as mock_copy, patch("pyperclip.paste", return_value="test text"):
            write_ok = self.skill._write_clipboard("test text")
            self.assertTrue(write_ok)
            mock_copy.assert_called_with("test text")

            read_text = self.skill._read_clipboard()
            self.assertEqual(read_text, "test text")


if __name__ == "__main__":
    unittest.main()
