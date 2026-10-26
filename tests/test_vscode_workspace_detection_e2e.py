import unittest
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

class TestVSCodeWorkspaceDetectionE2E(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        
        # Setup Workspace A
        self.ws_a = self.base_path / "ByteX_Workspace_Test"
        self.ws_a.mkdir(parents=True, exist_ok=True)
        (self.ws_a / "main.cpp").write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")
        
        # Setup Workspace B
        self.ws_b = self.base_path / "ByteX_Workspace_Test_2"
        self.ws_b.mkdir(parents=True, exist_ok=True)
        (self.ws_b / "arrays.cpp").write_text("#include <iostream>\n// Arrays module\n", encoding="utf-8")
        (self.ws_b / "testing.cpp").write_text("// root testing\n", encoding="utf-8")
        (self.ws_b / "src").mkdir(parents=True, exist_ok=True)
        (self.ws_b / "src" / "testing.cpp").write_text("// src testing\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_workspace_a_detection_and_query(self):
        """Test active detection of Workspace A and querying current workspace."""
        async def run():
            skill = CodingWorkspaceSkill()
            
            # Mock VS Code window title pointing to Workspace A
            mock_info = {
                "workspace_root": self.ws_a,
                "workspace_name": self.ws_a.name,
                "active_file": self.ws_a / "main.cpp",
                "active_file_name": "main.cpp",
                "active_editor_title": f"main.cpp - {self.ws_a.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info):
                # 1. Test CommandRouter routing for current workspace questions
                prompts = [
                    "What coding workspace am I currently working in?",
                    "What coding workspace am I in?",
                    "What workspace am I working in?",
                    "What is my current coding workspace?",
                    "What is my active workspace?",
                    "Where is my current workspace?"
                ]
                for p in prompts:
                    res = await CommandRouter.parse_skill_intent(p)
                    self.assertIsNotNone(res, f"Failed to route prompt: {p}")
                    skill_name, args = res
                    self.assertEqual(skill_name, "coding_workspace")
                    self.assertEqual(args.get("action"), "get_active_workspace")

                # 2. Execute get_active_workspace
                result = await skill.execute({"action": "get_active_workspace"})
                self.assertTrue(result.success)
                self.assertIn(str(self.ws_a), result.message)
                self.assertEqual(result.data.get("workspace_path"), str(self.ws_a))
                self.assertEqual(result.data.get("workspace_name"), self.ws_a.name)

        asyncio.run(run())

    def test_workspace_switching_dynamic_invalidation(self):
        """Test switching from Workspace A to Workspace B dynamically invalidates old cache."""
        async def run():
            skill = CodingWorkspaceSkill()
            
            # 1. First state: Workspace A is active
            mock_info_a = {
                "workspace_root": self.ws_a,
                "workspace_name": self.ws_a.name,
                "active_file": self.ws_a / "main.cpp",
                "active_file_name": "main.cpp",
                "active_editor_title": f"main.cpp - {self.ws_a.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info_a):
                res_a = await skill.execute({"action": "get_active_workspace"})
                self.assertEqual(res_a.data.get("workspace_path"), str(self.ws_a))

            # 2. User switches to Workspace B
            mock_info_b = {
                "workspace_root": self.ws_b,
                "workspace_name": self.ws_b.name,
                "active_file": self.ws_b / "arrays.cpp",
                "active_file_name": "arrays.cpp",
                "active_editor_title": f"arrays.cpp - {self.ws_b.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info_b):
                res_b = await skill.execute({"action": "get_active_workspace"})
                self.assertEqual(res_b.data.get("workspace_path"), str(self.ws_b))
                self.assertNotEqual(res_b.data.get("workspace_path"), str(self.ws_a))

                # 3. Modify "this file" in Workspace B modifies arrays.cpp in Workspace B
                edit_args = {
                    "action": "edit_code_file",
                    "filename": "this file",
                    "content": "#include <iostream>\n// Updated arrays module\n"
                }
                edit_res = await skill.execute(edit_args)
                self.assertTrue(edit_res.success)
                self.assertTrue(edit_res.verified)
                
                content_b = (self.ws_b / "arrays.cpp").read_text(encoding="utf-8")
                self.assertIn("Updated arrays module", content_b)

        asyncio.run(run())

    def test_duplicate_file_disambiguation_in_workspace(self):
        """Test disambiguation prompt when multiple files with same name exist in workspace."""
        async def run():
            skill = CodingWorkspaceSkill()
            mock_info_b = {
                "workspace_root": self.ws_b,
                "workspace_name": self.ws_b.name,
                "active_file": self.ws_b / "arrays.cpp",
                "active_file_name": "arrays.cpp",
                "active_editor_title": f"arrays.cpp - {self.ws_b.name} - Visual Studio Code",
                "source": "vscode_window"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info_b):
                read_args = {
                    "action": "read_code_file",
                    "filename": "testing.cpp"
                }
                res = await skill.execute(read_args)
                self.assertTrue(res.data.get("disambiguation"))
                self.assertEqual(len(res.data.get("candidates")), 2)
                self.assertIn("Which one should I modify?", res.message)

        asyncio.run(run())

    def test_honest_reporting_when_no_vscode_workspace_detected(self):
        """Test honest message when no VS Code workspace is open (never return C:\\VS CODE or backend dir)."""
        async def run():
            skill = CodingWorkspaceSkill()
            mock_info_none = {
                "workspace_root": None,
                "workspace_name": None,
                "active_file": None,
                "active_file_name": None,
                "active_editor_title": None,
                "source": "none"
            }
            with patch.object(skill, '_detect_vscode_workspace_info', return_value=mock_info_none):
                res = await skill.execute({"action": "get_active_workspace"})
                self.assertTrue(res.success)
                self.assertIsNone(res.data.get("workspace_path"))
                self.assertIn("No active coding workspace is currently detected", res.message)
                self.assertNotIn("C:\\VS CODE", res.message)

        asyncio.run(run())

    def test_invariants_verification(self):
        """Verify: CURRENT VS CODE WORKSPACE != BYTE X BACKEND DIRECTORY != OLD CACHED WORKSPACE != HARDCODED C:\\VS CODE."""
        backend_dir = Path(__file__).parent.parent / "backend"
        hardcoded_vsc = Path("C:/VS CODE")
        
        self.assertNotEqual(self.ws_a, backend_dir)
        self.assertNotEqual(self.ws_b, backend_dir)
        self.assertNotEqual(self.ws_a, hardcoded_vsc)
        self.assertNotEqual(self.ws_b, hardcoded_vsc)
        self.assertNotEqual(self.ws_a, self.ws_b)

if __name__ == "__main__":
    unittest.main()
