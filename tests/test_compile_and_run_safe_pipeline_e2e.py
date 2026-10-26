import unittest
import tempfile
import asyncio
import sys
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.registry import skill_registry
from agent.planner import ByteXPlanner


class TestCompileAndRunSafePipelineE2E(unittest.IsolatedAsyncioTestCase):
    """
    Regression test suite for:
    'Compile and run 01_basic.cpp. Show me the exact output and report any compilation errors. Don't modify the source file.'
    and related variations (compile-only, run-only, compilation error, planner integration).
    """

    async def asyncSetUp(self):
        self.skill = skill_registry.get_skill("coding_workspace")
        self.temp_dir_obj = tempfile.TemporaryDirectory(prefix="bytex_test_compile_run_")
        self.temp_dir = Path(self.temp_dir_obj.name)
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

    async def asyncTearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    # 1. Exact reproduction test
    async def test_01_exact_compile_and_run_user_request(self):
        valid_cpp = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    cout << \"HELLO_COMPILATION_TEST\" << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(valid_cpp, encoding="utf-8")

        cmd = "Compile and run 01_basic.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."

        # Verify intent parsing & classification
        parsed = await CommandRouter.parse_skill_intent(cmd)
        self.assertIsNotNone(parsed)
        tool_name, args = parsed
        self.assertEqual(tool_name, "coding_workspace")
        self.assertEqual(args.get("action"), "execute_code")
        self.assertEqual(args.get("filename"), "01_basic.cpp")
        self.assertTrue(args.get("compile", True))

        # Verify route_command
        handled, response, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled)
        self.assertEqual(state, "speaking")
        self.assertNotIn("no registered safe pipeline matches", response)
        self.assertIn("HELLO_COMPILATION_TEST", response)
        self.assertEqual(data.get("exit_code"), 0)
        self.assertTrue(data.get("compiled"))
        self.assertIn("HELLO_COMPILATION_TEST", data.get("stdout", ""))

        # Verify source file was not modified
        self.assertEqual(test_file.read_text(encoding="utf-8"), valid_cpp)

    # 2. Compile-only request
    async def test_02_compile_only_request(self):
        valid_cpp = (
            "#include <iostream>\n"
            "int main() {\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(valid_cpp, encoding="utf-8")

        cmd = "Compile 01_basic.cpp. Show me any compilation errors. Don't modify the source file."
        parsed = await CommandRouter.parse_skill_intent(cmd)
        self.assertIsNotNone(parsed)
        tool_name, args = parsed
        self.assertEqual(tool_name, "coding_workspace")
        self.assertEqual(args.get("action"), "compile_code")
        self.assertEqual(args.get("filename"), "01_basic.cpp")
        self.assertTrue(args.get("compile_only"))

        handled, response, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled)
        self.assertEqual(state, "speaking")
        self.assertIn("Successfully compiled `01_basic.cpp`", response)
        self.assertEqual(data.get("exit_code"), 0)
        self.assertEqual(test_file.read_text(encoding="utf-8"), valid_cpp)

    # 3. Run-only where supported
    async def test_03_run_only_request(self):
        valid_py = 'print("PYTHON_RUN_SUCCESS")\n'
        test_file = self.temp_dir / "script.py"
        test_file.write_text(valid_py, encoding="utf-8")

        cmd = "Run script.py"
        parsed = await CommandRouter.parse_skill_intent(cmd)
        self.assertIsNotNone(parsed)
        tool_name, args = parsed
        self.assertEqual(tool_name, "coding_workspace")
        self.assertEqual(args.get("action"), "execute_code")
        self.assertEqual(args.get("filename"), "script.py")

        handled, response, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled)
        self.assertEqual(state, "speaking")
        self.assertIn("PYTHON_RUN_SUCCESS", response)
        self.assertEqual(data.get("exit_code"), 0)
        self.assertEqual(test_file.read_text(encoding="utf-8"), valid_py)

    # 4. Compile-and-run with compilation error
    async def test_04_compile_and_run_with_compilation_error(self):
        broken_cpp = (
            "#include <iostream>\n"
            "int main() {\n"
            "    undeclared_syntax_error_function();\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "bad.cpp"
        test_file.write_text(broken_cpp, encoding="utf-8")

        cmd = "Compile and run bad.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."
        handled, response, state, data = await CommandRouter.route_command(cmd)

        self.assertTrue(handled)
        self.assertEqual(state, "error")
        self.assertIn("Compilation failed", response)
        self.assertIn("undeclared_syntax_error_function", response)
        self.assertFalse(data.get("compiled"))
        self.assertNotEqual(data.get("exit_code"), 0)
        self.assertIn("undeclared_syntax_error_function", data.get("stderr", ""))

        # Binary should not have run, and source must be untouched
        self.assertEqual(test_file.read_text(encoding="utf-8"), broken_cpp)

    # 5. Agent Mode Planner Integration
    async def test_05_planner_generates_safe_plan_for_compile_and_run(self):
        cmd = "Compile and run 01_basic.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."
        plan = ByteXPlanner.generate_plan(cmd)
        self.assertIsNotNone(plan, "Planner returned None for compile and run goal!")
        self.assertGreaterEqual(len(plan.steps), 1)
        first_step = plan.steps[0]
        self.assertEqual(first_step.suggested_skill, "coding_workspace")
        self.assertEqual(first_step.arguments.get("action"), "execute_code")
        self.assertEqual(first_step.arguments.get("filename"), "01_basic.cpp")


if __name__ == "__main__":
    unittest.main()
