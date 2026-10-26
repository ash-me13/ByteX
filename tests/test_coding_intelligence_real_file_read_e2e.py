import unittest
import asyncio
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

class TestCodingIntelligenceRealFileReadE2E(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ws_path = Path(self.temp_dir.name) / "ByteX_Real_Workspace"
        self.ws_path.mkdir(parents=True, exist_ok=True)
        
        self.testing_cpp_content = (
            "// Real testing code file\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "void bubbleSort(int arr[], int n) {\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        for (int j = 0; j < n; j++) {\n"
            "            if (arr[j] > arr[j + 1]) {\n"
            "                int temp = arr[j];\n"
            "                arr[j] = arr[j + 1];\n"
            "                arr[j + 1] = temp;\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n\n"
            "int main() {\n"
            "    int arr[] = {5, 2, 8, 1, 9};\n"
            "    bubbleSort(arr, 5);\n"
            "    return 0;\n"
            "}\n"
        )
        self.testing_cpp = self.ws_path / "testing.cpp"
        self.testing_cpp.write_text(self.testing_cpp_content, encoding="utf-8")
        
        self.skill = CodingWorkspaceSkill()
        self.mock_info = {
            "workspace_root": self.ws_path,
            "workspace_name": self.ws_path.name,
            "active_file": self.testing_cpp,
            "active_file_name": "testing.cpp",
            "active_editor_title": f"testing.cpp - {self.ws_path.name} - Visual Studio Code",
            "source": "vscode_window"
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_request_a_review_reads_actual_file_no_paste_no_modification(self):
        """Test A: 'Review testing.cpp and tell me what mistakes I'm making. Don't modify it.'"""
        async def run():
            prompt = "Review testing.cpp and tell me what mistakes I'm making. Don't modify it."
            hash_before = self._file_hash(self.testing_cpp)
            mtime_before = self.testing_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "review_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            # 2. Execution with workspace detection
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                
                # Verify successful review
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertEqual(result.data.get("filename"), "testing.cpp")
                
                # Verify actual file contents were analyzed (off-by-one error found)
                analysis = result.data.get("analysis", {})
                self.assertTrue(any("Off-by-one" in err or "out-of-bounds" in err for err in analysis.get("logic_errors", [])))
                self.assertNotIn("Please paste the contents", result.message)

                # Verify file integrity on disk (Read-Only invariant)
                hash_after = self._file_hash(self.testing_cpp)
                mtime_after = self.testing_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_request_b_teach_hints_reads_actual_file_no_modification(self):
        """Test B: 'Don't fix testing.cpp. Give me a hint about the biggest problem.'"""
        async def run():
            prompt = "Don't fix testing.cpp. Give me a hint about the biggest problem."
            hash_before = self._file_hash(self.testing_cpp)
            mtime_before = self.testing_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "teach_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            # 2. Execution
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertIn("Pedagogical Hint", result.message)
                self.assertIn("Array Bounds", result.message)
                self.assertNotIn("Please paste the contents", result.message)

                # Verify file integrity
                hash_after = self._file_hash(self.testing_cpp)
                mtime_after = self.testing_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_request_c_explain_reads_actual_file_no_modification(self):
        """Test C: 'Explain testing.cpp.'"""
        async def run():
            prompt = "Explain testing.cpp."
            hash_before = self._file_hash(self.testing_cpp)
            mtime_before = self.testing_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "explain_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            # 2. Execution
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertIn("Program Overview", result.message)
                self.assertIn("testing.cpp", result.message)
                self.assertNotIn("Please paste the contents", result.message)

                # Verify file integrity
                hash_after = self._file_hash(self.testing_cpp)
                mtime_after = self.testing_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_request_d_analyze_time_complexity_reads_actual_file_no_modification(self):
        """Test D: 'Analyze the time complexity of testing.cpp.'"""
        async def run():
            prompt = "Analyze the time complexity of testing.cpp."
            hash_before = self._file_hash(self.testing_cpp)
            mtime_before = self.testing_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            # 2. Execution
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertIn("Algorithmic & Performance Analysis", result.message)
                self.assertIn("O(n^2)", result.data.get("analysis", {}).get("current_time", ""))
                self.assertNotIn("Please paste the contents", result.message)

                # Verify file integrity
                hash_after = self._file_hash(self.testing_cpp)
                mtime_after = self.testing_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_request_e_find_file_routes_to_workspace_not_vision(self):
        """Test E: 'Find testing.cpp in my current project.' -> coding_workspace / find_file."""
        async def run():
            prompt = "Find testing.cpp in my current project."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "find_file")
            self.assertEqual(args.get("filename"), "testing.cpp")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertIn("testing.cpp", result.message)
                self.assertNotIn("Found button 'Login'", result.message)

        asyncio.run(run())

    def test_request_f_find_login_button_routes_to_vision(self):
        """Test F: 'Find the Login button.' -> screen_vision / find_ui_element."""
        async def run():
            prompt = "Find the Login button."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "screen_vision")
            self.assertEqual(args.get("action"), "find_ui_element")
            self.assertEqual(args.get("target").lower(), "login button")

        asyncio.run(run())

    def test_request_live_absolute_path_open_and_analyze(self):
        r"""Test Live Request: 'Open and analyze this file: C:\...\testing.cpp. Don't modify it.'"""
        async def run():
            prompt = f"Open and analyze this file: {str(self.testing_cpp)}. Don't modify it."
            hash_before = self._file_hash(self.testing_cpp)
            mtime_before = self.testing_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(Path(args.get("filename")), self.testing_cpp)

            # 2. Execution
            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))
            self.assertIn("Algorithmic & Performance Analysis", result.message)
            self.assertIn("Bubble Sort", result.message)
            self.assertNotIn("Please paste the contents", result.message)
            self.assertNotIn("do not have a direct 'read file' tool", result.message)

            # Invariant: Read-only, file unchanged on disk
            hash_after = self._file_hash(self.testing_cpp)
            mtime_after = self.testing_cpp.stat().st_mtime_ns
            self.assertEqual(hash_before, hash_after)
            self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_request_workspace_relative_analyze(self):
        """Test Relative Request: 'Analyze testing.cpp.'"""
        async def run():
            prompt = "Analyze testing.cpp."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertIn("Algorithmic & Performance Analysis", result.message)
                self.assertIn("Bubble Sort", result.message)

        asyncio.run(run())

    def test_request_active_file_analyze(self):
        """Test Active File Request: 'Analyze this file.'"""
        async def run():
            prompt = "Analyze this file."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "this file")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertIn("Algorithmic & Performance Analysis", result.message)
                self.assertIn("Bubble Sort", result.message)

        asyncio.run(run())

    def test_negative_nonexistent_absolute_path(self):
        """Negative Test A: Nonexistent absolute path."""
        async def run():
            nonexistent = Path(self.temp_dir.name) / "does_not_exist" / "missing.cpp"
            prompt = f"Open and analyze this file: {str(nonexistent)}. Don't modify it."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")

            result = await self.skill.execute(args)
            self.assertFalse(result.success)
            self.assertFalse(result.verified)
            self.assertEqual(result.error, "File not found")
            self.assertIn("couldn't find source file", result.message)

        asyncio.run(run())

    def test_negative_inaccessible_file(self):
        """Negative Test B: Inaccessible file (simulated read failure)."""
        async def run():
            with patch.object(Path, "read_text", side_effect=PermissionError("Access is denied")):
                result = await self.skill.execute({
                    "action": "analyze_code",
                    "filename": str(self.testing_cpp),
                    "prompt": "Analyze testing.cpp"
                })
                self.assertFalse(result.success)
                self.assertFalse(result.verified)
                self.assertIn("Failed to read file", result.message)
                self.assertIn("Access is denied", result.error)

        asyncio.run(run())

    def test_negative_directory_supplied_as_file(self):
        """Negative Test C: Directory supplied where source file expected."""
        async def run():
            sub_dir = self.ws_path / "src_folder"
            sub_dir.mkdir(parents=True, exist_ok=True)
            result = await self.skill.execute({
                "action": "analyze_code",
                "filename": str(sub_dir),
                "prompt": f"Analyze {str(sub_dir)}"
            })
            self.assertFalse(result.success)
            self.assertFalse(result.verified)
            self.assertEqual(result.error, "Target is a directory")
            self.assertIn("is a directory, not a source code file", result.message)

        asyncio.run(run())

    def test_negative_duplicate_workspace_filename(self):
        """Negative Test D: Duplicate workspace filename disambiguation for analyze_code."""
        async def run():
            dup_dir = self.ws_path / "nested_dir"
            dup_dir.mkdir(parents=True, exist_ok=True)
            (dup_dir / "testing.cpp").write_text("// duplicate\n", encoding="utf-8")

            no_act_mock = dict(self.mock_info)
            no_act_mock["active_file"] = None
            no_act_mock["active_file_name"] = None

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=no_act_mock):
                result = await self.skill.execute({"action": "analyze_code", "filename": "testing.cpp"})
                self.assertTrue(result.success)
                self.assertFalse(result.verified)
                self.assertTrue(result.data.get("disambiguation"))
                self.assertEqual(len(result.data.get("candidates")), 2)
                self.assertIn("I found 2 testing.cpp files in your workspace", result.message)
                self.assertIn("Which one should I modify?", result.message)

        asyncio.run(run())

    def test_real_target_file_live_analysis(self):
        """Test on the REAL C:\\Users\\ryzzn\\OneDrive\\Desktop\\ByteX_Real_Test\\testing.cpp if present on disk."""
        async def run():
            real_path = Path(r"C:\Users\ryzzn\OneDrive\Desktop\ByteX_Real_Test\testing.cpp")
            if not real_path.exists():
                self.skipTest(f"Real path {real_path} not found on this machine")

            prompt = f"Open and analyze this file: {str(real_path)}. Don't modify it."
            success, msg, tool, data = await CommandRouter.route_command(prompt)
            self.assertTrue(success)
            self.assertTrue(data.get("read_only"))
            self.assertEqual(data.get("filename"), "testing.cpp")
            self.assertIn("Algorithmic & Performance Analysis", msg)
            self.assertIn("for (int i = 2; i <= 100; i += 2)", msg)
            self.assertNotIn("paste the code", msg.lower())
            self.assertNotIn("do not have a direct 'read file' tool", msg.lower())

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
