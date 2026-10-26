"""
Tests for macOS browser discovery in skills/browser.py.
"""

import unittest
from unittest.mock import patch
from pathlib import Path
import os

from skills.browser import detect_all_supported_browsers, resolve_browser_target, BrowserTarget


class TestBrowserDiscoveryMacOS(unittest.TestCase):
    def test_current_macos_environment_detects_chrome_or_brave(self):
        browsers = detect_all_supported_browsers()
        self.assertIn("chrome", browsers)
        self.assertIn("brave", browsers)
        self.assertIn("edge", browsers)

        # On this macOS environment, Google Chrome and Brave are installed
        chrome = browsers["chrome"]
        if os.path.exists("/Applications/Google Chrome.app"):
            self.assertTrue(chrome.is_installed)
            self.assertIsNotNone(chrome.executable)
            self.assertTrue(os.path.exists(chrome.executable))

        brave = browsers["brave"]
        if os.path.exists("/Applications/Brave Browser.app"):
            self.assertTrue(brave.is_installed)
            self.assertIsNotNone(brave.executable)
            self.assertTrue(os.path.exists(brave.executable))

    @patch("sys.platform", "darwin")
    def test_user_home_applications_discovery(self):
        fake_home = Path("/Users/fakeuser")
        with patch("pathlib.Path.home", return_value=fake_home):
            def fake_exists(path):
                # Simulate Chrome installed in ~/Applications/Google Chrome.app
                return path == str(fake_home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

            with patch("os.path.exists", side_effect=fake_exists):
                browsers = detect_all_supported_browsers()
                chrome = browsers["chrome"]
                self.assertTrue(chrome.is_installed)
                self.assertEqual(
                    chrome.executable,
                    str(fake_home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                )
                self.assertIn(str(fake_home / "Library" / "Application Support" / "ByteX"), chrome.user_data_dir)

    @patch("sys.platform", "darwin")
    def test_browser_not_installed_returns_false(self):
        with patch("os.path.exists", return_value=False):
            browsers = detect_all_supported_browsers()
            for b_name, b_target in browsers.items():
                self.assertFalse(b_target.is_installed)
                self.assertIsNone(b_target.executable)

    def test_resolve_browser_target_explicit(self):
        browsers = detect_all_supported_browsers()
        if browsers["chrome"].is_installed:
            ok, target, err = resolve_browser_target(requested_browser="chrome")
            self.assertTrue(ok)
            self.assertEqual(target.browser_name, "chrome")
            self.assertEqual(err, "")

        if browsers["brave"].is_installed:
            ok, target, err = resolve_browser_target(requested_browser="brave")
            self.assertTrue(ok)
            self.assertEqual(target.browser_name, "brave")
            self.assertEqual(err, "")

    @patch("sys.platform", "win32")
    def test_windows_candidates_preserved(self):
        expected_win_path = os.path.join(r"C:\Program Files", r"Google\Chrome\Application\chrome.exe")
        with patch.dict(os.environ, {
            "ProgramFiles": r"C:\Program Files",
            "ProgramFiles(x86)": r"C:\Program Files (x86)",
            "LOCALAPPDATA": r"C:\Users\Default\AppData\Local",
        }):
            def fake_win_exists(path):
                return path == expected_win_path

            with patch("os.path.exists", side_effect=fake_win_exists):
                browsers = detect_all_supported_browsers()
                chrome = browsers["chrome"]
                self.assertTrue(chrome.is_installed)
                self.assertEqual(chrome.executable, expected_win_path)
                self.assertIn(r"C:\Users\Default\AppData\Local", chrome.user_data_dir)


if __name__ == "__main__":
    unittest.main()
