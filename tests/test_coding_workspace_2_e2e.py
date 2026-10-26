import unittest
import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

class TestCodingWorkspace2E2E(unittest.TestCase):

    def test_scenario_1_modify_main_cpp_on_disk(self):
        """User Test 1: 'Modify my main.cpp to print numbers from 1 to 100 instead of Hello ByteX.'"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_main = ws / "main.cpp"
            
            # 1. Setup initial main.cpp with Hello ByteX
            initial_code = (
                "#include <iostream>\n\n"
                "int main() {\n"
                "    std::cout << \"Hello ByteX!\" << std::endl;\n"
                "    return 0;\n"
                "}\n"
            )
            target_main.parent.mkdir(parents=True, exist_ok=True)
            target_main.write_text(initial_code, encoding="utf-8")

            # 2. Parse user prompt
            prompt = "Modify my main.cpp to print numbers from 1 to 100 instead of Hello ByteX."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "edit_code_file")

            # 3. Execute modification
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            
            # 4. Strictly verify actual disk content
            self.assertTrue(target_main.exists())
            updated_content = target_main.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", updated_content)
            self.assertIn("using namespace std;", updated_content)
            self.assertIn("for (int i = 1; i <= 100; i++)", updated_content)
            self.assertIn("cout << i << endl;", updated_content)
            self.assertNotIn("Hello ByteX", updated_content)

        asyncio.run(run())

    def test_scenario_2_cpp_sum_of_two_numbers(self):
        """User Test 2: 'Write a C++ program to calculate the sum of two numbers.'"""
        async def run():
            prompt = "Write a C++ program to calculate the sum of two numbers."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.name, "sum.cpp")
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", content)
            self.assertIn("using namespace std;", content)
            self.assertIn("sum = a + b;", content)
            self.assertIn("cout << \"Sum: \" << sum << endl;", content)

        asyncio.run(run())

    def test_scenario_3_python_factorial(self):
        """User Test 3: 'Create a Python program to calculate factorial.'"""
        async def run():
            prompt = "Create a Python program to calculate factorial."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.name, "factorial.py")
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("def factorial(n):", content)
            self.assertIn("return n * factorial(n - 1)", content)

        asyncio.run(run())

    def test_scenario_4_create_and_run_cpp_hello_world(self):
        """User Test 4: 'Create and run a C++ program that prints Hello World.'"""
        async def run():
            prompt = "Create and run a C++ program that prints Hello World."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")
            self.assertTrue(args.get("run"))

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.name, "hello.cpp")
            
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", content)
            self.assertIn("using namespace std;", content)
            self.assertIn("cout << \"Hello, World!\" << endl;", content)

            exec_data = result.data.get("execution")
            if exec_data and exec_data.get("success"):
                self.assertIn("Hello, World!", exec_data.get("stdout", ""))

        asyncio.run(run())

    def test_scenario_5_create_and_run_python_hello_world(self):
        """Scenario: 'Create and run a Python program that prints Hello World.'"""
        async def run():
            prompt = "Create and run a Python program that prints Hello World."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")
            self.assertTrue(args.get("run"))

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.suffix, ".py")
            
            exec_data = result.data.get("execution")
            self.assertIsNotNone(exec_data)
            self.assertTrue(exec_data.get("success"))
            self.assertIn("Hello, World!", exec_data.get("stdout", ""))

        asyncio.run(run())

    def test_scenario_6_java_binary_search(self):
        """Scenario: 'Write a Java program for binary search.'"""
        async def run():
            prompt = "Write a Java program for binary search."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.name, "BinarySearch.java")
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("binarySearch", content)
            self.assertIn("public class BinarySearch", content)

        asyncio.run(run())

    def test_scenario_7_create_python_file_hello_world(self):
        """User Test: 'Create a Python file that prints Hello World.'"""
        async def run():
            prompt = "Create a Python file that prints Hello World."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "generate_code")

            skill = CodingWorkspaceSkill()
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))
            
            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.suffix, ".py")
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("print(\"Hello, World!\")", content)

        asyncio.run(run())

    def test_scenario_8_create_cpp_and_run_it_phrase(self):
        """User Test: 'Create a C++ program that prints Hello World and run it.'"""
        async def run():
            prompt = "Create a C++ program that prints Hello World and run it."
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertTrue(classification.get("arguments", {}).get("run"))

            skill = CodingWorkspaceSkill()
            args = classification.get("arguments", {})
            args["overwrite"] = True
            result = await skill.execute(args)

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(result.data.get("written"))

            file_path = Path(result.data.get("path"))
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.suffix, ".cpp")

            content = file_path.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", content)
            self.assertIn("using namespace std;", content)
            self.assertIn("cout << \"Hello, World!\" << endl;", content)

            exec_data = result.data.get("execution")
            if exec_data and exec_data.get("success"):
                self.assertIn("Hello, World!", exec_data.get("stdout", ""))

        asyncio.run(run())

    def test_scenario_9_open_and_modify_main_cpp(self):
        """User Test: 'Open main.cpp and modify it to print numbers from 1 to 100 instead of Hello ByteX.'"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_main = ws / "main.cpp"
            
            initial_code = (
                "#include <iostream>\n\n"
                "int main() {\n"
                "    std::cout << \"Hello ByteX!\" << std::endl;\n"
                "    return 0;\n"
                "}\n"
            )
            target_main.parent.mkdir(parents=True, exist_ok=True)
            target_main.write_text(initial_code, encoding="utf-8")

            prompt = "Open main.cpp and modify it to print numbers from 1 to 100 instead of Hello ByteX."
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertEqual(classification.get("arguments", {}).get("action"), "edit_code_file")

            result = await skill.execute(classification.get("arguments", {}))

            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(target_main.exists())

            updated_content = target_main.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", updated_content)
            self.assertIn("using namespace std;", updated_content)
            self.assertIn("for (int i = 1; i <= 100; i++)", updated_content)
            self.assertIn("cout << i << endl;", updated_content)
            self.assertNotIn("Hello ByteX", updated_content)

        asyncio.run(run())

    def test_vscode_workspace_detection(self):
        """Verify active VS Code workspace is detected accurately."""
        skill = CodingWorkspaceSkill()
        ws = skill._detect_vscode_workspace()
        self.assertIsNotNone(ws)
        self.assertTrue(ws.exists())
        self.assertTrue(ws.is_dir())

    def test_scenario_10_edit_dsa_cpp_even_odd(self):
        """User Test: 'Edit dsa.cpp and make it print the even and odd numbers from 1 to 100'"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_file = ws / "dsa.cpp"
            
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

            prompt = "Edit dsa.cpp and make it print the even and odd numbers from 1 to 100"
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertEqual(classification.get("arguments", {}).get("action"), "edit_code_file")

            result = await skill.execute(classification.get("arguments", {}))
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(target_file.exists())

            content = target_file.read_text(encoding="utf-8")
            self.assertIn("#include <iostream>", content)
            self.assertIn("using namespace std;", content)
            self.assertIn("Even numbers from 1 to 100:", content)
            self.assertIn("Odd numbers from 1 to 100:", content)
            self.assertIn("if (i % 2 == 0)", content)
            self.assertIn("if (i % 2 != 0)", content)

        asyncio.run(run())

    def test_scenario_11_edit_hello_html_navbar(self):
        """User Test: 'Edit hello.html and add a simple navigation bar'"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_file = ws / "hello.html"
            
            initial_html = "<!DOCTYPE html>\n<html>\n<head><title>Test</title></head>\n<body>\n<h1>Hello</h1>\n</body>\n</html>"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(initial_html, encoding="utf-8")

            prompt = "Edit hello.html and add a simple navigation bar"
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertEqual(classification.get("arguments", {}).get("action"), "edit_code_file")

            result = await skill.execute(classification.get("arguments", {}))
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(target_file.exists())

            content = target_file.read_text(encoding="utf-8")
            self.assertIn("<nav>", content)
            self.assertIn("<ul>", content)
            self.assertIn("<li><a href=\"#home\">Home</a></li>", content)

        asyncio.run(run())

    def test_scenario_12_add_function_largest_element_this_file(self):
        """User Test: 'Add a function to find the largest element in this file'"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_file = ws / "arrays.cpp"
            
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("#include <iostream>\nint main() { return 0; }\n", encoding="utf-8")

            prompt = "Add a function to find the largest element in arrays.cpp"
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertEqual(classification.get("arguments", {}).get("action"), "edit_code_file")

            result = await skill.execute(classification.get("arguments", {}))
            self.assertTrue(result.success)
            self.assertTrue(result.verified)
            self.assertTrue(target_file.exists())

            content = target_file.read_text(encoding="utf-8")
            self.assertIn("findLargest", content)
            self.assertIn("maxVal", content)
            self.assertIn("#include <iostream>", content)

        asyncio.run(run())

    def test_scenario_13_duplicate_file_disambiguation(self):
        """User Test: Disambiguation prompt when multiple files with same name exist."""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            
            sub1 = ws / "week1"
            sub2 = ws / "week2"
            sub1.mkdir(parents=True, exist_ok=True)
            sub2.mkdir(parents=True, exist_ok=True)
            
            f1 = sub1 / "nested_dsa.cpp"
            f2 = sub2 / "nested_dsa.cpp"
            f1.write_text("// week 1", encoding="utf-8")
            f2.write_text("// week 2", encoding="utf-8")

            target, disambig_msg, candidates = skill.resolve_workspace_file("nested_dsa.cpp")
            self.assertIsNone(target)
            self.assertIsNotNone(disambig_msg)
            self.assertEqual(len(candidates), 2)
            self.assertIn("I found 2 nested_dsa.cpp files", disambig_msg)
            self.assertIn("Which one should I modify?", disambig_msg)

        asyncio.run(run())

    def test_scenario_14_run_and_self_healing_recovery(self):
        """User Test: 'Run dsa.cpp and fix the error' (Self-healing recovery)"""
        async def run():
            skill = CodingWorkspaceSkill()
            ws = skill._detect_vscode_workspace() or Path("C:/VS CODE")
            target_file = ws / "broken.py"
            
            # Write a python file with an intentional syntax/logic error
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("print('Starting')\nundefined_function_call()\n", encoding="utf-8")

            prompt = "Run broken.py and fix the error"
            classification = await CommandRouter.classify_request(prompt)
            self.assertEqual(classification.get("route"), "SINGLE_ACTION")
            self.assertEqual(classification.get("skill"), "coding_workspace")
            self.assertEqual(classification.get("arguments", {}).get("action"), "execute_code")
            self.assertTrue(classification.get("arguments", {}).get("auto_fix"))

            # Execute run with auto_fix triggered
            result = await skill.execute(classification.get("arguments", {}))
            self.assertIsNotNone(result)

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
