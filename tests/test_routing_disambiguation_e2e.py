import unittest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add backend directory to sys.path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

class TestRoutingDisambiguationE2E(unittest.TestCase):

    def setUp(self):
        from core.session import session_manager
        session_manager.reset()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ws_path = Path(self.temp_dir.name) / "ByteX_Real_Test"
        self.ws_path.mkdir(parents=True, exist_ok=True)
        (self.ws_path / "testing.cpp").write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_routing_disambiguation_10_scenarios(self):
        """Regression tests for exact routing collision between coding workspace and vision."""
        test_cases = [
            ("Find testing.cpp in my current project.", "coding_workspace", "find_file"),
            ("Find main.cpp.", "coding_workspace", "find_file"),
            ("Locate dsa.cpp in my workspace.", "coding_workspace", "find_file"),
            ("Search for hello.html in my project.", "coding_workspace", "find_file"),
            ("Find the Login button.", "screen_vision", "find_ui_element"),
            ("Find the Settings button.", "screen_vision", "find_ui_element"),
            ("Locate the search bar.", "screen_vision", "find_ui_element"),
            ("Where is the Submit button?", "screen_vision", "find_ui_element"),
            ("Find settings.py in my project.", "coding_workspace", "find_file"),
            ("Find this file.", "coding_workspace", "find_file"),
        ]

        async def run():
            for prompt, expected_skill, expected_action in test_cases:
                res = await CommandRouter.parse_skill_intent(prompt)
                self.assertIsNotNone(res, f"Prompt '{prompt}' failed to match any skill!")
                skill, args = res
                self.assertEqual(
                    skill, expected_skill,
                    f"Prompt '{prompt}' routed to '{skill}', expected '{expected_skill}'"
                )
                self.assertEqual(
                    args.get("action"), expected_action,
                    f"Prompt '{prompt}' action was '{args.get('action')}', expected '{expected_action}'"
                )

        asyncio.run(run())

    def test_find_file_execution_in_workspace(self):
        """Test executing find_file in CodingWorkspace with unique match."""
        async def run():
            skill = CodingWorkspaceSkill()
            mock_info = {
                "workspace_root": self.ws_path,
                "workspace_name": self.ws_path.name,
                "active_file": self.ws_path / "testing.cpp",
                "active_file_name": "testing.cpp",
                "active_editor_title": f"testing.cpp - {self.ws_path.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info):
                # 1. Parse prompt
                prompt = "Find testing.cpp in my current project."
                skill_name, args = await CommandRouter.parse_skill_intent(prompt)
                self.assertEqual(skill_name, "coding_workspace")
                
                # 2. Execute
                result = await skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertIn("testing.cpp", result.message)
                self.assertIn(str(self.ws_path), str(result.data.get("file_path")))
                self.assertNotIn("Found button 'Login'", result.message)

        asyncio.run(run())

    def test_find_file_duplicate_disambiguation(self):
        """Test duplicate files found during find_file returns disambiguation list."""
        async def run():
            # Add second testing.cpp in subfolder
            src_dir = self.ws_path / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "testing.cpp").write_text("// nested testing\n", encoding="utf-8")

            skill = CodingWorkspaceSkill()
            mock_info = {
                "workspace_root": self.ws_path,
                "workspace_name": self.ws_path.name,
                "active_file": None,
                "active_file_name": None,
                "active_editor_title": f"{self.ws_path.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info):
                prompt = "Find testing.cpp in my current project."
                skill_name, args = await CommandRouter.parse_skill_intent(prompt)
                result = await skill.execute(args)
                
                self.assertTrue(result.data.get("disambiguation"))
                self.assertEqual(len(result.data.get("candidates")), 2)
                self.assertIn("Which one should I modify?", result.message)

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
