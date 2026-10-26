import unittest
import asyncio
import tempfile
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from agent.planner import ByteXPlanner
from agent.pipeline import agent_pipeline
from skills.code_fixer import CodeFixEngine
from skills.diagnostics import CodeDiagnosticEngine


BUGGY_SOURCE = """#include <iostream>
using namespace std;

int main() {
    int a = 10;
    int b = 20;
    int sum = a + b // Intentional compilation error: missing semicolon
    cout << "Sum: " << sum << endl;
    return 0;
}
"""

class TestFixCompilationErrorAndRunRegression(unittest.TestCase):
    def test_01_diagnose_and_patch_missing_semicolon_with_inline_comment(self):
        """Verify that CodeFixEngine proposes inserting semicolon before inline comment."""
        compiler_err = (
            "03_buggy.cpp: In function 'int main()':\n"
            "03_buggy.cpp:8:5: error: expected ',' or ';' before 'cout'\n"
            "     cout << \"Sum: \" << sum << endl;"
        )
        diag = CodeDiagnosticEngine.diagnose(compiler_err, language="cpp", file_path="03_buggy.cpp")
        patch = CodeFixEngine.propose_patch(diag, BUGGY_SOURCE, language="cpp", file_path="03_buggy.cpp")
        
        self.assertIsNotNone(patch)
        self.assertEqual(patch.line, 7)
        self.assertEqual(patch.before, "    int sum = a + b // Intentional compilation error: missing semicolon")
        self.assertEqual(patch.after, "    int sum = a + b; // Intentional compilation error: missing semicolon")
        
        applied, mod_src, chg = CodeFixEngine.apply_patch_to_text(BUGGY_SOURCE, patch)
        self.assertTrue(applied)
        self.assertIn("int sum = a + b; // Intentional compilation error: missing semicolon", mod_src)
        self.assertIn("#include <iostream>", mod_src)
        self.assertIn("return 0;", mod_src)

    def test_02_planner_decomposes_fix_and_run_compound_goal(self):
        """Verify ByteXPlanner decomposes the compound fix + compile & run goal into fix then execute steps."""
        goal = (
            "Fix the compilation error in 03_buggy.cpp. "
            "Preserve the existing code and make only the necessary change. "
            "Then compile and run it, and show me the output."
        )
        plan = ByteXPlanner.generate_plan(goal)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.steps), 2)
        
        step1 = plan.steps[0]
        self.assertEqual(step1.suggested_skill, "coding_workspace")
        self.assertEqual(step1.arguments.get("action"), "fix_code_error")
        self.assertEqual(step1.arguments.get("filename"), "03_buggy.cpp")
        
        step2 = plan.steps[1]
        self.assertEqual(step2.suggested_skill, "coding_workspace")
        self.assertEqual(step2.arguments.get("action"), "execute_code")
        self.assertEqual(step2.arguments.get("filename"), "03_buggy.cpp")

    def test_03_end_to_end_fix_compilation_and_execution_verification(self):
        """Verify full pipeline modifies source, compiles, executes, and outputs 'Sum: 30'."""
        async def _run():
            tmp_dir = Path(tempfile.gettempdir()) / "bytex_regression_03_buggy"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            test_file = tmp_dir / "03_buggy.cpp"
            test_file.write_text(BUGGY_SOURCE, encoding="utf-8")

            goal = (
                f"Fix the compilation error in {test_file}. "
                "Preserve the existing code and make only the necessary change. "
                "Then compile and run it, and show me the output."
            )
            success, message, state, data = await CommandRouter.route_command(goal)
            
            self.assertTrue(success)
            self.assertEqual(state, "speaking")
            self.assertIn("Sum: 30", message)

            updated_src = test_file.read_text(encoding="utf-8")
            self.assertIn("int sum = a + b; // Intentional compilation error: missing semicolon", updated_src)
            self.assertNotIn("int sum = a + b // Intentional compilation error: missing semicolon", updated_src)

            # Cleanup
            shutil.rmtree(tmp_dir, ignore_errors=True)

        asyncio.run(_run())

if __name__ == "__main__":
    unittest.main()
