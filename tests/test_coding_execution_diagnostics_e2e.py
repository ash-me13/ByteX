import unittest
import asyncio
import tempfile
import shutil
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.coding import CodingWorkspaceSkill
from skills.registry import skill_registry
from core.command_router import CommandRouter
from agent.planner import ByteXPlanner


class TestCodingExecutionDiagnosticsE2E(unittest.TestCase):
    """
    Comprehensive Regression Test Suite for C++ compilation, execution,
    precise diagnostic state isolation, output verification, and full natural-language
    optimization workflow.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temp_dir.name)
        self.skill = CodingWorkspaceSkill()
        self.skill._cached_vscode_workspace = self.workspace_path
        reg_skill = skill_registry.get_skill("coding_workspace")
        if reg_skill:
            reg_skill._cached_vscode_workspace = self.workspace_path

    def tearDown(self):
        reg_skill = skill_registry.get_skill("coding_workspace")
        if reg_skill:
            reg_skill._cached_vscode_workspace = None
        self.temp_dir.cleanup()

    def test_a_real_cpp_compile_run_capture_stdout(self):
        """
        Test A: Real C++ source exists -> compile -> run -> capture stdout.
        Uses the real available compiler (e.g. g++) to compile and execute a real C++ file.
        """
        async def run():
            cpp_file = self.workspace_path / "hello.cpp"
            cpp_file.write_text(
                "#include <iostream>\n"
                "int main() {\n"
                "    std::cout << \"Hello from ByteX Real Execution!\" << std::endl;\n"
                "    return 0;\n"
                "}\n",
                encoding="utf-8"
            )

            res = await self.skill.execute({
                "action": "execute_code",
                "filename": "hello.cpp"
            })

            # If a C++ compiler is installed on this machine (g++ found in PATH)
            runner_p, comp_p, _, _ = self.skill._resolve_runner("cpp")
            if comp_p:
                self.assertTrue(res.success, f"Execution failed: {res.message}")
                self.assertTrue(res.verified)
                self.assertIn("Hello from ByteX Real Execution!", res.data.get("stdout", ""))
                self.assertEqual(res.data.get("exit_code"), 0)
                self.assertEqual(res.data.get("verification_state"), "EXECUTION_VERIFIED")
            else:
                self.assertFalse(res.success)
                self.assertEqual(res.data.get("verification_state"), "COMPILER_NOT_FOUND")

        asyncio.run(run())

    def test_b_compiler_missing_precise_state(self):
        """
        Test B: Compiler missing -> precise COMPILER_NOT_FOUND state.
        Ensures that when no compiler is available, it does NOT confuse with file not found or runtime error.
        """
        async def run():
            cpp_file = self.workspace_path / "test_nocomp.cpp"
            cpp_file.write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

            with patch.object(self.skill, "_resolve_runner", return_value=(None, None, "g++", "C++")):
                res = await self.skill.execute({
                    "action": "execute_code",
                    "filename": "test_nocomp.cpp"
                })

                self.assertFalse(res.success)
                self.assertFalse(res.verified)
                self.assertEqual(res.data.get("verification_state"), "COMPILER_NOT_FOUND")
                self.assertEqual(res.data.get("status"), "COMPILER_NOT_FOUND")
                self.assertIn("compiler (g++) is not available", res.message)

                # Also test inside _verify_execution_semantics
                reqs = {"kind": "even_numbers", "start": 1, "end": 100}
                dyn_ok, _, dyn_summary, dyn_info = self.skill._verify_execution_semantics(cpp_file, reqs)
                self.assertFalse(dyn_ok)
                self.assertEqual(dyn_info.get("verification_state"), "COMPILER_NOT_FOUND")

        asyncio.run(run())

    def test_c_compilation_error_precise_state(self):
        """
        Test C: Compilation error -> precise COMPILATION_FAILED state.
        Ensures that real syntax/compiler errors are captured with exact compiler diagnostics.
        """
        async def run():
            cpp_file = self.workspace_path / "syntax_error.cpp"
            cpp_file.write_text(
                "#include <iostream>\n"
                "int main() {\n"
                "    int x = 10 // missing semicolon\n"
                "    return 0;\n"
                "}\n",
                encoding="utf-8"
            )

            runner_p, comp_p, _, _ = self.skill._resolve_runner("cpp")
            if comp_p:
                res = await self.skill.execute({
                    "action": "execute_code",
                    "filename": "syntax_error.cpp"
                })
                self.assertFalse(res.success)
                self.assertFalse(res.verified)
                self.assertEqual(res.data.get("verification_state"), "COMPILATION_FAILED")
                self.assertEqual(res.data.get("status"), "COMPILATION_FAILED")
                self.assertIn("Compilation failed", res.message)
                self.assertTrue(len(res.data.get("stderr", "")) > 0 or len(res.data.get("stdout", "")) > 0)

        asyncio.run(run())

    def test_d_executable_path_missing_precise_state(self):
        """
        Test D: Executable path missing -> precise EXECUTABLE_NOT_FOUND state.
        Ensures that if compiler claims success but output executable is not produced,
        it produces precise EXECUTABLE_NOT_FOUND error.
        """
        reqs = {"kind": "even_numbers", "start": 1, "end": 100}
        cpp_file = self.workspace_path / "valid.cpp"
        cpp_file.write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

        # Mock subprocess.run for compilation to succeed but not create the exe
        with patch("subprocess.run") as mock_run:
            class DummyCompResult:
                returncode = 0
                stdout = ""
                stderr = ""
            mock_run.return_value = DummyCompResult()

            dyn_ok, _, dyn_summary, dyn_info = self.skill._verify_execution_semantics(cpp_file, reqs)
            self.assertFalse(dyn_ok)
            self.assertEqual(dyn_info.get("verification_state"), "EXECUTABLE_NOT_FOUND")
            self.assertIn("Executable was not generated", dyn_summary)

    def test_e_runtime_failure_precise_state(self):
        """
        Test E: Runtime failure -> precise RUNTIME_FAILED state.
        A program that compiles but segfaults / exits with non-zero exit code.
        """
        async def run():
            cpp_file = self.workspace_path / "runtime_err.cpp"
            cpp_file.write_text(
                "#include <iostream>\n"
                "#include <cstdlib>\n"
                "int main() {\n"
                "    std::cerr << \"Fatal runtime exception occurred!\" << std::endl;\n"
                "    return 42;\n"
                "}\n",
                encoding="utf-8"
            )

            runner_p, comp_p, _, _ = self.skill._resolve_runner("cpp")
            if comp_p:
                res = await self.skill.execute({
                    "action": "execute_code",
                    "filename": "runtime_err.cpp"
                })
                self.assertFalse(res.success)
                self.assertEqual(res.data.get("exit_code"), 42)
                self.assertEqual(res.data.get("verification_state"), "RUNTIME_FAILED")

                # Test via dynamic verifier
                reqs = {"kind": "even_numbers", "start": 1, "end": 100}
                dyn_ok, _, dyn_summary, dyn_info = self.skill._verify_execution_semantics(cpp_file, reqs)
                self.assertFalse(dyn_ok)
                self.assertEqual(dyn_info.get("verification_state"), "RUNTIME_FAILED")

        asyncio.run(run())

    def test_f_output_verification_failed_on_wrong_semantics(self):
        """
        Test F: Successful execution (exit 0) but wrong semantic output -> OUTPUT_VERIFICATION_FAILED.
        E.g. requested even numbers, but program outputs odd numbers or plain sequence 1..100.
        """
        cpp_file = self.workspace_path / "wrong_output.cpp"
        cpp_file.write_text(
            "#include <iostream>\n"
            "int main() {\n"
            "    for (int i = 1; i <= 100; i++) {\n"
            "        std::cout << i << \"\\n\";\n"
            "    }\n"
            "    return 0;\n"
            "}\n",
            encoding="utf-8"
        )

        runner_p, comp_p, _, _ = self.skill._resolve_runner("cpp")
        if comp_p:
            reqs = {"kind": "even_numbers", "start": 1, "end": 100}
            dyn_ok, stdout, dyn_summary, dyn_info = self.skill._verify_execution_semantics(cpp_file, reqs)
            self.assertFalse(dyn_ok)
            self.assertEqual(dyn_info.get("verification_state"), "OUTPUT_VERIFICATION_FAILED")
            self.assertIn("OUTPUT_VERIFICATION_FAILED", dyn_summary)
            self.assertIn("contained odd numbers", dyn_summary)

    def test_g_correct_even_number_output_verified(self):
        """
        Test G: Correct even-number output -> EXECUTION_VERIFIED.
        Exact sequence 2, 4, 6, ..., 100.
        """
        cpp_file = self.workspace_path / "correct_evens.cpp"
        cpp_file.write_text(
            "#include <iostream>\n"
            "int main() {\n"
            "    for (int i = 2; i <= 100; i += 2) {\n"
            "        std::cout << i << \"\\n\";\n"
            "    }\n"
            "    return 0;\n"
            "}\n",
            encoding="utf-8"
        )

        runner_p, comp_p, _, _ = self.skill._resolve_runner("cpp")
        if comp_p:
            reqs = {"kind": "even_numbers", "start": 1, "end": 100, "is_optimize": True}
            dyn_ok, stdout, dyn_summary, dyn_info = self.skill._verify_execution_semantics(cpp_file, reqs)
            self.assertTrue(dyn_ok)
            self.assertEqual(dyn_info.get("verification_state"), "EXECUTION_VERIFIED")
            self.assertIn("EXECUTION_VERIFIED", dyn_summary)
            self.assertIn("50 even numbers", dyn_summary)

    def test_h_full_natural_language_modify_save_compile_execute_verify(self):
        """
        Test H: The full live request:
        'Optimize testing.cpp to print even numbers from 1 to 100 more efficiently. Apply the optimization, save the file, and run it to verify the output.'
        Verifies:
        1. Resolves testing.cpp in workspace.
        2. Reads source before modifying.
        3. Applies stride optimization (i += 2) instead of modulo (% 2 == 0).
        4. Saves testing.cpp to disk.
        5. Compiles with dynamic compiler.
        6. Executes binary and semantically verifies stdout.
        7. Returns EXECUTION_VERIFIED state and structured report.
        """
        async def run():
            testing_file = self.workspace_path / "testing.cpp"
            initial_source = (
                "#include <iostream>\n\n"
                "int main() {\n"
                "    for (int i = 1; i <= 100; i++) {\n"
                "        if (i % 2 == 0) {\n"
                "            std::cout << i << \"\\n\";\n"
                "        }\n"
                "    }\n"
                "    return 0;\n"
                "}\n"
            )
            testing_file.write_text(initial_source, encoding="utf-8")

            prompt = "Optimize testing.cpp to print even numbers from 1 to 100 more efficiently. Apply the optimization, save the file, and run it to verify the output."

            # Test route_command
            is_handled, resp_text, state, data = await CommandRouter.route_command(prompt)
            self.assertTrue(is_handled)
            self.assertEqual(state, "speaking")
            self.assertIsNotNone(data)

            # Check that testing.cpp was modified on disk
            saved_code = testing_file.read_text(encoding="utf-8")
            self.assertIn("i += 2", saved_code)
            self.assertNotIn("if (i % 2 == 0)", saved_code)

            # Check report fields
            self.assertIn("File Modified", resp_text)
            self.assertIn("testing.cpp", resp_text)
            self.assertIn("Optimization Applied", resp_text)
            self.assertIn("Stride optimization", resp_text)
            self.assertIn("Compiler Used", resp_text)
            self.assertIn("Compile Result", resp_text)
            self.assertIn("Execution Result", resp_text)
            self.assertIn("EXECUTION_VERIFIED", resp_text)

            # Check structured data
            self.assertEqual(data.get("file_modified"), "testing.cpp")
            self.assertEqual(data.get("final_verification_state"), "EXECUTION_VERIFIED")
            self.assertEqual(data.get("compile_result"), "SUCCESS")
            self.assertEqual(data.get("execution_result"), "SUCCESS")
            self.assertTrue(data.get("verified"))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
