import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.coding import CodingWorkspaceSkill

class TestSemanticModificationVerificationE2E(unittest.TestCase):
    """
    End-to-End verification test suite for Coding Intelligence Semantic Modification
    and 5-layer verification pipeline.
    """

    def setUp(self):
        from core.session import session_manager
        session_manager.reset()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temp_dir.name)
        self.skill = CodingWorkspaceSkill()
        self.mock_info = {
            "workspace_root": self.workspace_path,
            "workspace_name": self.workspace_path.name,
            "active_file": None,
            "active_file_name": None,
            "source": "vscode_window"
        }
        self.skill._cached_vscode_workspace = self.workspace_path

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_even_numbers_surgical_modification_and_verification(self):
        """
        Tests the exact user scenario:
        'Modify testing.cpp to print the even numbers from 1 to 100. Don't change anything else.'
        Verifies:
        1. Surgical preservation of existing helper functions.
        2. Static semantic verification (contains % 2 == 0).
        3. Dynamic execution verification (no odd numbers in stdout).
        4. Explicit MODIFIED_AND_VERIFIED status.
        """
        async def run():
            testing_file = self.workspace_path / "testing.cpp"
            initial_content = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "void bubbleSort(int arr[], int n) {\n"
                "    for (int i = 0; i < n - 1; i++) {\n"
                "        for (int j = 0; j < n - 1 - i; j++) {\n"
                "            if (arr[j] > arr[j + 1]) {\n"
                "                int tmp = arr[j];\n"
                "                arr[j] = arr[j + 1];\n"
                "                arr[j + 1] = tmp;\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "}\n\n"
                "int main() {\n"
                "    cout << \"Hello World\" << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            testing_file.write_text(initial_content, encoding="utf-8")

            res = await self.skill.execute({
                "action": "edit_code_file",
                "filename": "testing.cpp",
                "instruction": "Modify testing.cpp to print the even numbers from 1 to 100. Don't change anything else."
            })

            self.assertTrue(res.success, f"Action failed: {res.message}")
            self.assertTrue(res.verified, f"Verification failed: {res.message}")
            self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
            self.assertTrue(res.data.get("semantic_verified"))

            # Verify disk contents
            saved_content = testing_file.read_text(encoding="utf-8")

            # 1. Helper function bubbleSort MUST be preserved
            self.assertIn("void bubbleSort", saved_content)
            self.assertIn("int tmp = arr[j];", saved_content)

            # 2. Even condition MUST be present
            self.assertIn("% 2 == 0", saved_content)

            # 3. Dynamic execution verification check
            if res.data.get("execution_verified") is not None:
                self.assertTrue(res.data.get("execution_verified"))
                self.assertIn("0 odd numbers", res.data.get("execution_summary", ""))

        asyncio.run(run())

    def test_odd_numbers_modification_and_verification(self):
        """
        Tests odd numbers semantic modification:
        'Print odd numbers from 1 to 50.'
        """
        async def run():
            py_file = self.workspace_path / "odd_test.py"
            py_file.write_text("print('start')", encoding="utf-8")

            res = await self.skill.execute({
                "action": "edit_code_file",
                "filename": "odd_test.py",
                "instruction": "Print odd numbers from 1 to 50."
            })

            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
            self.assertTrue(res.data.get("semantic_verified"))

            saved_content = py_file.read_text(encoding="utf-8")
            self.assertTrue("% 2 != 0" in saved_content or "% 2 == 1" in saved_content)

        asyncio.run(run())

    def test_sum_calculation_modification_and_verification(self):
        """
        Tests sum calculation modification:
        'Change the sum calculation in main.cpp to calculate the sum from 1 to 100'
        """
        async def run():
            cpp_file = self.workspace_path / "main.cpp"
            cpp_file.write_text(
                "#include <iostream>\nusing namespace std;\nint main() {\n    int sum = 0;\n    cout << sum << endl;\n    return 0;\n}\n",
                encoding="utf-8"
            )

            res = await self.skill.execute({
                "action": "edit_code_file",
                "filename": "main.cpp",
                "instruction": "Change the sum calculation in main.cpp to calculate the sum from 1 to 100"
            })

            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
            self.assertTrue(res.data.get("semantic_verified"))

            saved_content = cpp_file.read_text(encoding="utf-8")
            self.assertIn("sum += i", saved_content)

        asyncio.run(run())

    def test_semantic_verifier_rejects_unconditional_all_numbers(self):
        """
        Tests that static semantic verification accurately flags unconditional loops
        when user specifically asked for even numbers.
        """
        reqs = self.skill._extract_semantic_requirements("print even numbers from 1 to 100")
        self.assertEqual(reqs["kind"], "even_numbers")

        flawed_content = (
            "#include <iostream>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    for (int i = 1; i <= 100; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )

        is_valid, summary, errors = self.skill._verify_code_semantics(
            new_content=flawed_content,
            original_content="",
            instruction="print even numbers from 1 to 100",
            filename="testing.cpp",
            reqs=reqs
        )

        self.assertFalse(is_valid)
        self.assertTrue(any("does not filter for even numbers" in e for e in errors))

    def test_preservation_verifier_rejects_removal_of_helper_functions(self):
        """
        Tests that preservation verifier detects if helper functions were deleted.
        """
        reqs = self.skill._extract_semantic_requirements("Modify testing.cpp to print the even numbers from 1 to 100. Don't change anything else.")
        self.assertTrue(reqs["preserve_others"])

        original_content = (
            "void bubbleSort(int a[], int n) {}\n"
            "int main() { return 0; }"
        )
        stripped_content = (
            "#include <iostream>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    for (int i = 1; i <= 100; i++) if (i % 2 == 0) cout << i << endl;\n"
            "    return 0;\n"
            "}\n"
        )

        is_valid, summary, errors = self.skill._verify_code_semantics(
            new_content=stripped_content,
            original_content=original_content,
            instruction="Modify testing.cpp to print the even numbers from 1 to 100. Don't change anything else.",
            filename="testing.cpp",
            reqs=reqs
        )

        self.assertFalse(is_valid)
        self.assertTrue(any("bubbleSort" in e for e in errors))

    def test_divisible_by_k_modification_and_verification(self):
        """
        Tests divisible by k modification:
        'Print numbers divisible by 5 from 1 to 50.'
        """
        async def run():
            cpp_file = self.workspace_path / "div_test.cpp"
            cpp_file.write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

            res = await self.skill.execute({
                "action": "edit_code_file",
                "filename": "div_test.cpp",
                "instruction": "Print numbers divisible by 5 from 1 to 50."
            })

            self.assertTrue(res.success, f"Action failed: {res.message}")
            self.assertTrue(res.verified, f"Verification failed: {res.message} data: {res.data}")
            self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
            self.assertTrue(res.data.get("semantic_verified"))

            saved_content = cpp_file.read_text(encoding="utf-8")
            self.assertIn("% 5 == 0", saved_content)

        asyncio.run(run())

    def test_largest_element_modification_and_verification(self):
        """
        Tests find largest element in array modification.
        """
        async def run():
            py_file = self.workspace_path / "max_test.py"
            py_file.write_text("# array max\n", encoding="utf-8")

            res = await self.skill.execute({
                "action": "edit_code_file",
                "filename": "max_test.py",
                "instruction": "Find the largest element in an array"
            })

            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertEqual(res.data.get("status"), "MODIFIED_AND_VERIFIED")
            saved_content = py_file.read_text(encoding="utf-8")
            self.assertIn("find_largest", saved_content)

        asyncio.run(run())

    def test_readonly_review_does_not_modify_file(self):
        """
        Ensures read-only review cannot modify the file.
        """
        async def run():
            target_file = self.workspace_path / "testing.cpp"
            original = "// Original code\nint main() { return 0; }\n"
            target_file.write_text(original, encoding="utf-8")

            res = await self.skill.execute({
                "action": "review_code",
                "filename": "testing.cpp",
                "instruction": "Review testing.cpp and fix any bugs"
            })

            self.assertTrue(res.success)
            self.assertEqual(target_file.read_text(encoding="utf-8"), original)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
