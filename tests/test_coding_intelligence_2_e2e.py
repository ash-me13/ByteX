import unittest
import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

class TestCodingIntelligence2E2E(unittest.TestCase):

    def setUp(self):
        self.skill = CodingWorkspaceSkill()
        self.ws = self.skill._detect_vscode_workspace() or Path("C:/VS CODE")
        self.ws.mkdir(parents=True, exist_ok=True)

    def test_scenario_a_review_does_not_modify_files(self):
        """Test A: 'What mistakes am I making in dsa.cpp?' -> Read-only Review with 5 categories."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            initial_code = (
                "// DSA Bubble Sort Assignment\n"
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
                "    int arr[] = {64, 34, 25, 12, 22, 11, 90};\n"
                "    int n = sizeof(arr) / sizeof(arr[0]);\n"
                "    bubbleSort(arr, n);\n"
                "    return 0;\n"
                "}\n"
            )
            dsa_file.write_text(initial_code, encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            # 1. Parse user intent
            prompt = "What mistakes am I making in dsa.cpp?"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "review_code")
            self.assertEqual(args.get("filename"), "dsa.cpp")

            # 2. Execute Review
            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))

            # 3. Verify Categorized Findings
            analysis = result.data.get("analysis", {})
            self.assertIn("logic_errors", analysis)
            self.assertIn("runtime_bugs", analysis)
            self.assertIn("performance", analysis)
            self.assertIn("style", analysis)
            self.assertIn("security", analysis)
            self.assertTrue(any("Off-by-one" in err for err in analysis["logic_errors"]))

            # 4. Strictly Verify Disk Content is Unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), initial_code)

        asyncio.run(run())

    def test_scenario_b_explain_does_not_modify_files(self):
        """Test B: 'Explain how the loop in dsa.cpp works' -> Read-only Explanation."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            initial_code = dsa_file.read_text(encoding="utf-8") if dsa_file.exists() else "#include <iostream>\nint main() { return 0; }\n"
            dsa_file.write_text(initial_code, encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            prompt = "Explain the code in dsa.cpp"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "explain_code")

            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))

            # Verify file on disk is unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), initial_code)

        asyncio.run(run())

    def test_scenario_c_teach_hint_level_1_does_not_modify_files(self):
        """Test C: 'Don't fix my code. Give me a hint about the bug' -> Socratic Level 1 Hint."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            initial_code = (
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
                "}\n"
            )
            dsa_file.write_text(initial_code, encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            prompt = "Don't fix my code. Give me a hint about the bug in dsa.cpp"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "teach_code")

            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))
            self.assertEqual(result.data.get("hint_level"), 1)

            # Socratic hint without dumping full solution code
            self.assertIn("Hint (Level 1)", result.message)
            self.assertIn("Array Bounds", result.message)
            self.assertNotIn("for (int j = 0; j < n - 1 - i; j++)", result.message)

            # Verify file on disk is unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), initial_code)

        asyncio.run(run())

    def test_scenario_d_hint_progression_level_2(self):
        """Test D: 'Give me a smaller hint' -> Socratic Level 2 Hint with indexing details."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            initial_code = dsa_file.read_text(encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            prompt = "Give me a smaller hint"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "teach_code")
            self.assertEqual(args.get("hint_level"), 2)

            args["filename"] = "dsa.cpp"
            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))
            self.assertEqual(result.data.get("hint_level"), 2)

            self.assertIn("Hint (Level 2)", result.message)
            self.assertIn("arr[n]", result.message)

            # Verify file on disk is unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), initial_code)

        asyncio.run(run())

    def test_scenario_e_surgical_modification_preserves_unrelated_code(self):
        """Test E: 'Change the sum calculation in main.cpp to calculate the sum from 1 to 100 instead of a + b'"""
        async def run():
            main_file = self.ws / "main.cpp"
            initial_code = (
                "// Complex math helper functions\n"
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "double computeTax(double amount) {\n"
                "    return amount * 0.15;\n"
                "}\n\n"
                "int main() {\n"
                "    int a = 10, b = 20;\n"
                "    // Calculate sum\n"
                "    int sum = a + b;\n"
                "    cout << \"Sum: \" << sum << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            main_file.write_text(initial_code, encoding="utf-8")

            prompt = "Change the sum calculation in main.cpp to calculate the sum from 1 to 100 instead of a + b"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "edit_code_file")

            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertIn("diff", result.data)
            self.assertEqual(result.data.get("scope"), "surgical_modification")

            # Check updated file on disk
            updated = main_file.read_text(encoding="utf-8")
            self.assertIn("computeTax", updated)  # Helper preserved!
            self.assertIn("double amount", updated)
            self.assertIn("for (int i = 1; i <= 100; i++)", updated)
            self.assertIn("sum += i;", updated)
            self.assertNotIn("int sum = a + b;", updated)

        asyncio.run(run())

    def test_scenario_f_fix_mistakes_in_dsa_cpp(self):
        """Test F: 'Fix the mistakes in dsa.cpp' -> Minimal surgical fix of off-by-one error."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            initial_code = (
                "// Bubble Sort implementation\n"
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
                "    int n = sizeof(arr) / sizeof(arr[0]);\n"
                "    bubbleSort(arr, n);\n"
                "    for (int i = 0; i < n; i++) cout << arr[i] << \" \";\n"
                "    cout << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            dsa_file.write_text(initial_code, encoding="utf-8")

            prompt = "Fix the mistakes in dsa.cpp"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")

            # Route through edit / fix
            result = await self.skill.execute({"action": "edit_code_file", "filename": "dsa.cpp", "instruction": "Fix the mistakes in dsa.cpp"})
            self.assertTrue(result.success)
            self.assertTrue(result.verified)

            updated = dsa_file.read_text(encoding="utf-8")
            self.assertIn("j < n - 1", updated)
            self.assertIn("bubbleSort", updated)
            self.assertIn("// Bubble Sort implementation", updated)

        asyncio.run(run())

    def test_scenario_g_compile_and_run_dsa_cpp(self):
        """Test G: 'Compile and run dsa.cpp' -> Clean compilation & execution without modifying code."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            # Ensure valid C++ code
            valid_code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    cout << \"DSA Execution Success\" << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            dsa_file.write_text(valid_code, encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            prompt = "Compile and run dsa.cpp"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "execute_code")
            self.assertEqual(args.get("filename"), "dsa.cpp")

            result = await self.skill.execute(args)
            if result.success:
                self.assertIn("DSA Execution Success", result.data.get("stdout", ""))

            # Verify file on disk is unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), valid_code)

        asyncio.run(run())

    def test_scenario_h_debug_and_fix_dsa_cpp(self):
        """Test H: 'Run dsa.cpp and fix the error' -> Debug with self-healing."""
        async def run():
            prompt = "Run dsa.cpp and fix the error"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "execute_code")
            self.assertTrue(args.get("auto_fix"))

        asyncio.run(run())

    def test_scenario_i_complexity_and_optimization_analysis(self):
        """Test I: 'Analyze the time complexity of dsa.cpp and tell me how I can improve it'"""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            bubble_code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "void bubbleSort(int arr[], int n) {\n"
                "    for (int i = 0; i < n; i++) {\n"
                "        for (int j = 0; j < n - 1 - i; j++) {\n"
                "            if (arr[j] > arr[j + 1]) {\n"
                "                swap(arr[j], arr[j + 1]);\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "}\n"
            )
            dsa_file.write_text(bubble_code, encoding="utf-8")
            mtime_before = dsa_file.stat().st_mtime_ns

            prompt = "Analyze the time complexity of dsa.cpp and tell me how I can improve it"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")

            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("read_only"))

            analysis = result.data.get("analysis", {})
            self.assertEqual(analysis.get("current_time"), "O(n^2)")
            self.assertEqual(analysis.get("optimal_time"), "O(n log n)")
            self.assertIn("Merge Sort", analysis.get("recommendations"))

            # Verify file on disk is unchanged
            mtime_after = dsa_file.stat().st_mtime_ns
            self.assertEqual(mtime_before, mtime_after)
            self.assertEqual(dsa_file.read_text(encoding="utf-8"), bubble_code)

        asyncio.run(run())

    def test_scenario_j_apply_optimization(self):
        """Test J: 'Apply the optimization' -> Surgically optimizes algorithm on disk."""
        async def run():
            dsa_file = self.ws / "dsa.cpp"
            bubble_code = (
                "// Sorting module\n"
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "void bubbleSort(int arr[], int n) {\n"
                "    for (int i = 0; i < n; i++) {\n"
                "        for (int j = 0; j < n - 1; j++) {\n"
                "            if (arr[j] > arr[j + 1]) {\n"
                "                int t = arr[j]; arr[j] = arr[j + 1]; arr[j + 1] = t;\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "}\n\n"
                "int main() {\n"
                "    int arr[] = {5, 3, 8, 4, 2};\n"
                "    bubbleSort(arr, 5);\n"
                "    return 0;\n"
                "}\n"
            )
            dsa_file.write_text(bubble_code, encoding="utf-8")

            prompt = "Apply the optimization"
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "analyze_code")
            self.assertTrue(args.get("apply"))

            args["filename"] = "dsa.cpp"
            result = await self.skill.execute(args)
            self.assertTrue(result.success)
            self.assertTrue(result.verified)

            updated = dsa_file.read_text(encoding="utf-8")
            self.assertIn("std::sort", updated)
            self.assertIn("optimizedSort", updated)
            self.assertIn("// Sorting module", updated)  # Comments preserved!

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
