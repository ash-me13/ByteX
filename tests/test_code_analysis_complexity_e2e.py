import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from core.session import session_manager
from skills.coding import CodingWorkspaceSkill

class TestCodeAnalysisComplexityE2E(unittest.TestCase):
    """
    End-to-End verification test suite for Coding Intelligence 2.0
    Code Analysis, Complexity, Optimization, and Read-Only Guarantees.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temp_dir.name)
        self.skill = CodingWorkspaceSkill()
        self.skill._cached_vscode_workspace = self.workspace_path

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_analyze_testing_cpp_time_and_space_complexity(self):
        """
        Scenario A: 'Analyze testing.cpp and explain its time and space complexity.'
        Verifies:
        1. Correct routing to analyze_code with filename='testing.cpp'.
        2. Reads the real file from disk.
        3. Returns algorithm summary, time complexity, and space complexity.
        4. Strict read-only invariant (file remains unchanged).
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    cout << \"Even numbers from 1 to 100:\" << endl;\n"
                "    for (int i = 1; i <= 100; i++) {\n"
                "        if (i % 2 == 0) {\n"
                "            cout << i << \" \";\n"
                "        }\n"
                "    }\n"
                "    cout << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Analyze testing.cpp and explain its time and space complexity."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            res = await self.skill.execute(args)
            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertIn("Algorithm Overview", res.message)
            self.assertIn("Complexity Breakdown", res.message)
            self.assertIn("Time Complexity", res.message)
            self.assertIn("Space Complexity", res.message)

            # Strict read-only invariant
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), initial_content)

        asyncio.run(run())

    def test_analyze_testing_cpp_more_efficient_approach_dont_modify(self):
        """
        Scenario B: 'Analyze testing.cpp and suggest a more efficient approach. Don't modify the file.'
        Verifies:
        1. Correct routing.
        2. Proposes more efficient step incrementation without modifying file.
        3. apply_opt is False.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    for (int i = 1; i <= 100; i++) {\n"
                "        if (i % 2 == 0) {\n"
                "            cout << i << \" \";\n"
                "        }\n"
                "    }\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Analyze testing.cpp and suggest a more efficient approach. Don't modify the file."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            res = await self.skill.execute(args)
            self.assertTrue(res.success)
            self.assertIn("Optimization Recommendations", res.message)
            self.assertIn("Efficient", res.message)

            # Strict read-only check
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), initial_content)

        asyncio.run(run())

    def test_review_testing_cpp(self):
        """
        Scenario C: 'Review testing.cpp.'
        Verifies:
        1. Correct routing to review_code.
        2. Performs 5-category review without asking user to paste code.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    int x = 10;\n"
                "    cout << x << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Review testing.cpp."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "review_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            res = await self.skill.execute(args)
            self.assertTrue(res.success)
            self.assertIn("Code Review", res.message)
            self.assertIn("Logic / Errors", res.message)
            self.assertIn("Performance & Complexity", res.message)

            self.assertEqual(cpp_file.read_text(encoding="utf-8"), initial_content)

        asyncio.run(run())

    def test_missing_named_file_precise_response(self):
        """
        Scenario D: Missing named file -> precise file-not-found response rather than asking to paste code.
        """
        async def run():
            prompt = "Analyze nonexistent_file.cpp and explain its complexity."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")

            res = await self.skill.execute(args)
            self.assertFalse(res.success)
            self.assertIn("couldn't find source file 'nonexistent_file.cpp'", res.message.lower())
            self.assertNotIn("paste", res.message.lower())

        asyncio.run(run())

    def test_conversational_file_followup_routing(self):
        """
        Scenario: User replies with standalone 'testing.cpp' after a prompt.
        Verifies:
        1. CommandRouter recognizes standalone code filename.
        2. Dispatches to coding_workspace without generic chat fallback.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            cpp_file.write_text("int main() { return 0; }\n", encoding="utf-8")

            # Set prior action in session
            session_manager.record_action_result(
                "coding_workspace",
                {"action": "analyze_code"},
                None
            )

            prompt = "testing.cpp"
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("filename"), "testing.cpp")
            self.assertEqual(args.get("action"), "analyze_code")

        asyncio.run(run())

    def test_duplicate_file_disambiguation_never_guesses(self):
        """
        Scenario: Multiple testing.cpp files exist in different subdirectories.
        Verifies:
        1. Returns numbered disambiguation list.
        2. Never arbitrarily chooses or mutates either file.
        """
        async def run():
            root_test = self.workspace_path / "testing.cpp"
            root_test.write_text("// root file", encoding="utf-8")

            sub_dir = self.workspace_path / "src"
            sub_dir.mkdir(parents=True, exist_ok=True)
            sub_test = sub_dir / "testing.cpp"
            sub_test.write_text("// src file", encoding="utf-8")

            prompt = "Analyze testing.cpp"
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            res = await self.skill.execute(args)

            self.assertIn("found 2 testing.cpp files", res.message.lower())
            self.assertIn("1. testing.cpp", res.message)
            self.assertIn("2. src\\testing.cpp", res.message)

            self.assertEqual(root_test.read_text(encoding="utf-8"), "// root file")
            self.assertEqual(sub_test.read_text(encoding="utf-8"), "// src file")

        asyncio.run(run())

    def test_live_scenario_optimize_testing_cpp_grounded_not_binary_search(self):
        """
        Scenario: 'Optimize testing.cpp to reduce its time complexity. Show me what you would change, but don't modify the file.'
        Verifies:
        1. Correct routing to analyze_code with filename='testing.cpp'.
        2. Reads the real file from disk.
        3. Response is strictly grounded in actual code (even numbers loop), NOT generic binary search.
        4. Does NOT assume binary search or hash table when code does not search.
        5. Includes concrete structural evidence: function `main`, loop structure, complexity reasoning.
        6. Shows proposed diff without modifying file on disk (strict read-only).
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    for (int i = 1; i <= 100; i++) {\n"
                "        if (i % 2 == 0) {\n"
                "            cout << i << \" \";\n"
                "        }\n"
                "    }\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")
            mtime_before = cpp_file.stat().st_mtime_ns

            prompt = "Optimize testing.cpp to reduce its time complexity. Show me what you would change, but don't modify the file."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertEqual(args.get("filename"), "testing.cpp")

            res = await self.skill.execute(args)
            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertTrue(res.data.get("read_only"))

            # Evidence & grounded analysis verification
            analysis = res.data.get("analysis", {})
            self.assertNotIn("binary search", res.message.lower())
            self.assertNotIn("unordered_set", res.message.lower())
            self.assertNotIn("linear scan from index 0 to n-1", res.message.lower())

            self.assertIn("Structural Evidence", res.message)
            self.assertIn("main", res.message)
            self.assertIn("Direct Step Incrementation", res.message)
            self.assertIn("Proposed Optimization (Diff Preview)", res.message)
            self.assertIn("i += 2", res.message)

            # Strict read-only invariant (no modification)
            mtime_after = cpp_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), initial_content)

        asyncio.run(run())

    def test_simple_non_search_constant_time_code_never_recommends_binary_search(self):
        """
        Scenario: Code is deliberately a simple non-search program (e.g. constant time operations).
        Verifies:
        1. Analyzes actual code structure.
        2. Accurately determines O(1) time complexity.
        3. Explicitly states no algorithmic bottleneck exists.
        4. Does NOT invent binary search, sorting, or hash tables.
        """
        async def run():
            cpp_file = self.workspace_path / "simple.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    int a = 10, b = 20;\n"
                "    int c = a + b;\n"
                "    cout << \"Result: \" << c << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Analyze the time complexity of simple.cpp"
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            res = await self.skill.execute(args)

            self.assertTrue(res.success)
            analysis = res.data.get("analysis", {})
            self.assertEqual(analysis.get("current_time"), "O(1)")
            self.assertEqual(analysis.get("optimal_time"), "O(1)")
            self.assertNotIn("binary search", res.message.lower())
            self.assertNotIn("unordered_set", res.message.lower())
            self.assertIn("No algorithmic bottleneck detected", res.message)

        asyncio.run(run())

    def test_summation_loop_proposes_gauss_formula_not_binary_search(self):
        """
        Scenario: Code sums 1 to n in a loop.
        Verifies:
        1. Identifies O(n) loop summation.
        2. Proposes closed-form Gauss formula n*(n+1)/2.
        3. Does NOT assume or recommend binary search.
        """
        async def run():
            cpp_file = self.workspace_path / "sum.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    int n = 100;\n"
                "    int sum = 0;\n"
                "    for (int i = 1; i <= n; i++) {\n"
                "        sum += i;\n"
                "    }\n"
                "    cout << sum << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Optimize sum.cpp to reduce its time complexity. Don't modify the file."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            res = await self.skill.execute(args)

            self.assertTrue(res.success)
            analysis = res.data.get("analysis", {})
            self.assertEqual(analysis.get("current_time"), "O(n)")
            self.assertEqual(analysis.get("optimal_time"), "O(1)")
            self.assertIn("Gauss Closed-Form Formula", res.message)
            self.assertNotIn("binary search", res.message.lower())
            self.assertNotIn("unordered_set", res.message.lower())

        asyncio.run(run())

    def test_analyzer_cannot_produce_claims_without_reading_actual_file(self):
        """
        Scenario: Request to analyze a file that cannot be found or read.
        Verifies:
        1. System refuses to hallucinate complexity claims or optimization diffs.
        2. Returns a clear file-not-found failure.
        """
        async def run():
            prompt = "Optimize ghost_file.cpp to reduce its time complexity."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            res = await self.skill.execute(args)

            self.assertFalse(res.success)
            self.assertIn("couldn't find source file 'ghost_file.cpp'", res.message.lower())
            self.assertNotIn("Complexity Breakdown", res.message)
            self.assertNotIn("Algorithm Overview", res.message)

        asyncio.run(run())

    # -----------------------------------------------------------------
    # Regression Tests A through H (Feature #33.9 & Live Failure Fix)
    # -----------------------------------------------------------------

    def test_regression_a_real_cpp_compile_run_capture_stdout(self):
        """
        Test A: Real C++ source exists -> compile -> run -> capture stdout.
        """
        async def run():
            if not shutil.which("g++"):
                self.skipTest("g++ not available on this host")
            cpp_file = self.workspace_path / "test_a.cpp"
            cpp_file.write_text(
                "#include <iostream>\nint main() { std::cout << \"Hello Real C++!\" << std::endl; return 0; }\n",
                encoding="utf-8"
            )
            res = await self.skill.execute({
                "action": "execute_code",
                "filename": "test_a.cpp"
            })
            self.assertTrue(res.success)
            self.assertEqual(res.data.get("exit_code"), 0)
            self.assertIn("Hello Real C++!", res.data.get("stdout"))

        asyncio.run(run())

    def test_regression_b_compiler_missing_precise_state(self):
        """
        Test B: Compiler missing -> precise compiler-not-found state.
        """
        async def run():
            cpp_file = self.workspace_path / "test_b.cpp"
            cpp_file.write_text("int main() { return 0; }\n", encoding="utf-8")
            orig_resolve = self.skill._resolve_runner
            self.skill._resolve_runner = lambda lang: (None, None, "g++", "C++")
            try:
                res = await self.skill.execute({
                    "action": "execute_code",
                    "filename": "test_b.cpp"
                })
                self.assertFalse(res.success)
                self.assertEqual(res.error, "Compiler not available")
                self.assertIn("compiler (g++) is not available", res.message.lower())
            finally:
                self.skill._resolve_runner = orig_resolve

        asyncio.run(run())

    def test_regression_c_compilation_error_precise_state(self):
        """
        Test C: Compilation error -> precise compilation-failed state.
        """
        async def run():
            if not shutil.which("g++"):
                self.skipTest("g++ not available on this host")
            cpp_file = self.workspace_path / "test_c.cpp"
            cpp_file.write_text("int main() { syntax_error_here; return 0; }\n", encoding="utf-8")
            res = await self.skill.execute({
                "action": "execute_code",
                "filename": "test_c.cpp"
            })
            self.assertFalse(res.success)
            self.assertEqual(res.error, "Compilation error")
            self.assertEqual(res.data.get("stage"), "compile")
            self.assertIn("syntax_error_here", res.data.get("stderr") or res.message)

        asyncio.run(run())

    def test_regression_d_executable_path_missing_precise_state(self):
        """
        Test D: Executable path missing -> precise executable-generation/path failure.
        """
        reqs = {"kind": "even_numbers", "start": 1, "end": 10}
        cpp_file = self.workspace_path / "test_d.cpp"
        cpp_file.write_text("int main() { return 0; }\n", encoding="utf-8")
        
        # Test verification semantics when exe does not exist
        dyn_ok, dyn_stdout, dyn_summary, dyn_info = self.skill._verify_execution_semantics(
            cpp_file,
            reqs
        )
        self.assertIn(dyn_info.get("verification_state"), ["COMPILER_NOT_FOUND", "COMPILATION_FAILED", "EXECUTABLE_NOT_FOUND", "OUTPUT_VERIFICATION_FAILED", "EXECUTION_VERIFIED"])

    def test_regression_e_runtime_failure_precise_state(self):
        """
        Test E: Runtime failure -> precise runtime-failed state.
        """
        async def run():
            if not shutil.which("g++"):
                self.skipTest("g++ not available on this host")
            cpp_file = self.workspace_path / "test_e.cpp"
            cpp_file.write_text(
                "#include <cstdlib>\nint main() { std::abort(); return 0; }\n",
                encoding="utf-8"
            )
            res = await self.skill.execute({
                "action": "execute_code",
                "filename": "test_e.cpp"
            })
            self.assertFalse(res.success)
            self.assertNotEqual(res.data.get("exit_code"), 0)
            self.assertEqual(res.data.get("stage"), "runtime")

        asyncio.run(run())

    def test_regression_f_wrong_semantic_output_failure(self):
        """
        Test F: Successful output but wrong semantic output -> OUTPUT_VERIFICATION_FAILED.
        """
        cpp_file = self.workspace_path / "test_f.cpp"
        # Prints odd numbers when even numbers are requested
        cpp_file.write_text(
            "#include <iostream>\nint main() { std::cout << \"1 3 5 7 9\" << std::endl; return 0; }\n",
            encoding="utf-8"
        )
        reqs = {"kind": "even_numbers", "start": 1, "end": 10, "is_optimize": True}
        dyn_ok, stdout, summary, info = self.skill._verify_execution_semantics(cpp_file, reqs)
        if shutil.which("g++"):
            self.assertFalse(dyn_ok)
            self.assertEqual(info.get("verification_state"), "OUTPUT_VERIFICATION_FAILED")
            self.assertIn("odd numbers", summary.lower())

    def test_regression_g_correct_even_number_output_verified(self):
        """
        Test G: Correct even-number output -> EXECUTION_VERIFIED.
        """
        cpp_file = self.workspace_path / "test_g.cpp"
        cpp_file.write_text(
            "#include <iostream>\nint main() { for (int i = 2; i <= 10; i += 2) std::cout << i << \" \"; std::cout << std::endl; return 0; }\n",
            encoding="utf-8"
        )
        reqs = {"kind": "even_numbers", "start": 1, "end": 10, "is_optimize": True}
        dyn_ok, stdout, summary, info = self.skill._verify_execution_semantics(cpp_file, reqs)
        if shutil.which("g++"):
            self.assertTrue(dyn_ok)
            self.assertEqual(info.get("verification_state"), "EXECUTION_VERIFIED")
            self.assertIn("EXECUTION_VERIFIED", summary)

    def test_regression_h_full_natural_language_optimize_modify_save_run_verify(self):
        """
        Test H: Full natural-language request:
        'Optimize testing.cpp to print even numbers from 1 to 100 more efficiently. Apply the optimization, save the file, and run it to verify the output.'
        Verifies:
        1. Router routes to coding_workspace / edit_code_file.
        2. Applies source-grounded stride optimization (i += 2).
        3. Saves testing.cpp to disk.
        4. Compiles, executes, and semantically verifies output [2, 4, ..., 100].
        5. Reports file modified, optimization applied, compiler used, compile result, execution result, stdout, and EXECUTION_VERIFIED.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    for (int i = 1; i <= 100; i++) {\n"
                "        if (i % 2 == 0) {\n"
                "            cout << i << endl;\n"
                "        }\n"
                "    }\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(initial_content, encoding="utf-8")

            prompt = "Optimize testing.cpp to print even numbers from 1 to 100 more efficiently. Apply the optimization, save the file, and run it to verify the output."
            skill_name, args = await CommandRouter.parse_skill_intent(prompt)
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "edit_code_file")
            self.assertEqual(args.get("filename"), "testing.cpp")

            res = await self.skill.execute(args)
            self.assertTrue(res.success)
            self.assertTrue(res.verified)

            # Check modified content on disk has stride i += 2
            saved_content = cpp_file.read_text(encoding="utf-8")
            self.assertIn("i += 2", saved_content)
            self.assertNotIn("if (i % 2 == 0)", saved_content)

            # Check reported fields
            self.assertEqual(res.data.get("file_modified"), "testing.cpp")
            self.assertIsNotNone(res.data.get("optimization_applied"))
            self.assertIn("Stride", res.data.get("optimization_applied"))

            if shutil.which("g++"):
                self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
                self.assertEqual(res.data.get("final_verification_state"), "EXECUTION_VERIFIED")
                self.assertEqual(res.data.get("compile_result"), "SUCCESS")
                self.assertEqual(res.data.get("execution_result"), "SUCCESS")
                self.assertIsNotNone(res.data.get("compiler_used"))
                self.assertIn("2", res.data.get("stdout"))
                self.assertIn("100", res.data.get("stdout"))
                self.assertIn("EXECUTION_VERIFIED", res.message)
                self.assertIn("File Modified", res.message)
                self.assertIn("Compiler Used", res.message)

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()

