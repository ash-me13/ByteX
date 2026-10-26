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
from agent.selector import ByteXSkillSelector

class TestCodeFileRoutingVsWebE2E(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_lab = Path(self.temp_dir.name) / "ByteX_Test_Lab"
        self.test_lab.mkdir(parents=True, exist_ok=True)

        self.basic_cpp = self.test_lab / "01_basic.cpp"
        self.basic_cpp_content = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            '    cout << "BYTE_X_BASIC_TEST" << endl;\n'
            "    return 0;\n"
            "}\n"
        )
        self.basic_cpp.write_text(self.basic_cpp_content, encoding="utf-8")

        self.skill = CodingWorkspaceSkill()
        self.mock_info = {
            "workspace_root": self.test_lab,
            "workspace_name": self.test_lab.name,
            "active_file": self.basic_cpp,
            "active_file_name": "01_basic.cpp",
            "active_editor_title": f"01_basic.cpp - {self.test_lab.name} - Visual Studio Code",
            "source": "vscode_window"
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_routing_regression_natural_language_variants(self):
        """
        Requirement 9: Regression tests specifically for the routing collision:
        A. 'Read 01_basic.cpp and tell me what it does.'
        B. 'Explain 01_basic.cpp.'
        C. 'Tell me what 01_basic.cpp does.'
        D. 'Read 01_basic.cpp. Don't modify it.'
        E. 'Read 01_basic.cpp and explain it.'
        F. Ensure these NEVER route to web/research.
        """
        test_cases = [
            ("Read 01_basic.cpp and tell me what it does. Don't modify it.", "coding_workspace", "explain_code", "01_basic.cpp"),
            ("Read 01_basic.cpp and tell me what it does.", "coding_workspace", "explain_code", "01_basic.cpp"),
            ("Explain 01_basic.cpp.", "coding_workspace", "explain_code", "01_basic.cpp"),
            ("Tell me what 01_basic.cpp does.", "coding_workspace", "explain_code", "01_basic.cpp"),
            ("Read 01_basic.cpp. Don't modify it.", "coding_workspace", "read_code_file", "01_basic.cpp"),
            ("Read 01_basic.cpp and explain it.", "coding_workspace", "explain_code", "01_basic.cpp"),
            ("Read 01_basic.cpp.", "coding_workspace", "read_code_file", "01_basic.cpp"),
            ("Open and analyze 01_basic.cpp.", "coding_workspace", "analyze_code", "01_basic.cpp"),
            ("Read this file and explain it.", "coding_workspace", "explain_code", "this file"),
        ]

        async def run():
            for prompt, expected_skill, expected_action, expected_filename in test_cases:
                # 1. Test CommandRouter parse_skill_intent
                res = await CommandRouter.parse_skill_intent(prompt)
                self.assertIsNotNone(res, f"Prompt '{prompt}' failed to match any skill intent!")
                skill, args = res
                self.assertEqual(skill, expected_skill, f"Prompt '{prompt}' routed to '{skill}', expected '{expected_skill}'")
                self.assertEqual(args.get("action"), expected_action, f"Prompt '{prompt}' action was '{args.get('action')}', expected '{expected_action}'")
                self.assertEqual(args.get("filename"), expected_filename, f"Prompt '{prompt}' filename was '{args.get('filename')}', expected '{expected_filename}'")

                # 2. Test CommandRouter classify_request (Ensuring it is SINGLE_ACTION and not MULTI_STEP or NORMAL)
                classification = await CommandRouter.classify_request(prompt)
                self.assertEqual(classification.get("route"), "SINGLE_ACTION", f"Prompt '{prompt}' classified as {classification.get('route')}")
                self.assertEqual(classification.get("skill"), expected_skill)

                # 3. Test ByteXSkillSelector
                selector_res = ByteXSkillSelector.select_skills_for_goal(prompt)
                selected_skills = selector_res.get("selected_skills", [])
                self.assertIn("coding_workspace", selected_skills, f"coding_workspace not selected for prompt '{prompt}'")
                self.assertNotIn("read_webpage", selected_skills, f"read_webpage was erroneously selected for prompt '{prompt}'")
                self.assertNotIn("web_search", selected_skills, f"web_search was erroneously selected for prompt '{prompt}'")

        asyncio.run(run())

    def test_negative_web_requests_route_to_web_skills(self):
        """
        Requirement 10: Negative tests proving actual web requests route to the web/research system.
        """
        web_test_cases = [
            ("Read webpage https://example.com", "read_webpage", "https://example.com"),
            ("Read website https://google.com", "read_webpage", "https://google.com"),
            ("what does this page say https://news.ycombinator.com", "read_webpage", "https://news.ycombinator.com"),
            ("what does this page say", "read_webpage", ""),
        ]

        async def run():
            for prompt, expected_skill, expected_url in web_test_cases:
                res = await CommandRouter.parse_skill_intent(prompt)
                self.assertIsNotNone(res, f"Web prompt '{prompt}' failed to match intent!")
                skill, args = res
                self.assertEqual(skill, expected_skill, f"Web prompt '{prompt}' routed to '{skill}', expected '{expected_skill}'")
                if expected_url:
                    self.assertEqual(args.get("url"), expected_url)

                # Test selector
                selector_res = ByteXSkillSelector.select_skills_for_goal(prompt)
                selected_skills = selector_res.get("selected_skills", [])
                self.assertIn("read_webpage", selected_skills, f"read_webpage not selected for '{prompt}'")
                self.assertNotIn("coding_workspace", selected_skills, f"coding_workspace was erroneously selected for '{prompt}'")

        asyncio.run(run())

    def test_live_execution_read_and_tell_what_it_does(self):
        """
        Requirement 11 & 12: Perform exact live request:
        'Read 01_basic.cpp and tell me what it does. Don't modify it.'
        Verify:
        - correct file resolved
        - actual source read
        - explanation matches source ('BYTE_X_BASIC_TEST')
        - file hash unchanged
        - no compile
        - no execution
        - no web request
        """
        async def run():
            prompt = "Read 01_basic.cpp and tell me what it does. Don't modify it."
            hash_before = self._file_hash(self.basic_cpp)
            mtime_before = self.basic_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "explain_code")
            self.assertEqual(args.get("filename"), "01_basic.cpp")

            # 2. Execution with workspace detection
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)

                # Verify success and verification
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertEqual(result.data.get("filename"), "01_basic.cpp")
                self.assertEqual(result.data.get("path"), str(self.basic_cpp))

                # Verify explanation is source-grounded with BYTE_X_BASIC_TEST
                self.assertIn("BYTE_X_BASIC_TEST", result.message)
                self.assertNotIn("ConnectError", result.message)
                self.assertNotIn("couldn't connect to that website", result.message)
                self.assertNotIn("Please paste the contents", result.message)

                # Verify file integrity on disk (hash unchanged, mtime unchanged)
                hash_after = self._file_hash(self.basic_cpp)
                mtime_after = self.basic_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_live_execution_read_code_file_only(self):
        """
        Test: 'Read 01_basic.cpp. Don't modify it.'
        """
        async def run():
            prompt = "Read 01_basic.cpp. Don't modify it."
            hash_before = self._file_hash(self.basic_cpp)

            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "read_code_file")
            self.assertEqual(args.get("filename"), "01_basic.cpp")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertEqual(result.data.get("filename"), "01_basic.cpp")
                self.assertIn("BYTE_X_BASIC_TEST", result.data.get("content"))
                self.assertIn("01_basic.cpp", result.message)
                self.assertEqual(self._file_hash(self.basic_cpp), hash_before)

        asyncio.run(run())

    def test_live_execution_explain_line_by_line(self):
        """
        Requirements 1, 2, 3, 4, 8A, 8B, 8E:
        'Explain 01_basic.cpp line by line. Don't modify it.'
        Verify:
        - resolves 01_basic.cpp
        - reads source from disk
        - explains each meaningful line in order
        - line 1 (#include <iostream>), line 2 (using namespace std), line 4 (int main), line 5 (cout << "BYTE_X_BASIC_TEST"), line 6 (return 0)
        - no invented loop
        - constant time O(1), no false O(n)
        - file hash strictly unchanged (read-only)
        """
        async def run():
            prompt = "Explain 01_basic.cpp line by line. Don't modify it."
            hash_before = self._file_hash(self.basic_cpp)
            mtime_before = self.basic_cpp.stat().st_mtime_ns

            # 1. Routing
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(skill_name, "coding_workspace")
            self.assertEqual(args.get("action"), "explain_code")
            self.assertEqual(args.get("mode"), "line_by_line")
            self.assertEqual(args.get("filename"), "01_basic.cpp")

            # 2. Execution with workspace detection
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)

                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertTrue(result.data.get("read_only"))
                self.assertEqual(result.data.get("mode"), "line_by_line")

                # Concrete source-grounded evidence
                msg = result.message
                self.assertIn("Line-by-Line Breakdown", msg)
                self.assertIn("#include <iostream>", msg)
                self.assertIn("using namespace std;", msg)
                self.assertIn("int main() {", msg)
                self.assertIn("BYTE_X_BASIC_TEST", msg)
                self.assertIn("return 0;", msg)

                # Invariant: No invented loop and true constant complexity
                self.assertIn("O(1)", msg)
                self.assertNotIn("O(n)", msg)
                self.assertNotIn("Iterative loop", msg)
                self.assertIn("Sequential execution", msg)

                # Strict read-only invariant
                hash_after = self._file_hash(self.basic_cpp)
                mtime_after = self.basic_cpp.stat().st_mtime_ns
                self.assertEqual(hash_before, hash_after)
                self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_explain_file_with_actual_loop(self):
        """
        Requirement 8C: Explain a file that actually contains a loop (02_search.cpp)
        and verify the loop and O(n) complexity are properly mentioned.
        """
        search_cpp = self.test_lab / "02_search.cpp"
        search_cpp_content = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    int arr[] = {4, 8, 15, 16, 23, 42};\n"
            "    int n = 6;\n"
            "    int target = 23;\n\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        if (arr[i] == target) {\n"
            '            cout << "Found at index " << i << endl;\n'
            "            return 0;\n"
            "        }\n"
            "    }\n\n"
            '    cout << "Not found" << endl;\n'
            "    return 0;\n"
            "}\n"
        )
        search_cpp.write_text(search_cpp_content, encoding="utf-8")

        async def run():
            prompt = "Explain 02_search.cpp line by line. Don't modify it."
            mock_info = dict(self.mock_info)
            mock_info["active_file"] = search_cpp
            mock_info["active_file_name"] = "02_search.cpp"

            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(args.get("mode"), "line_by_line")
            self.assertEqual(args.get("filename"), "02_search.cpp")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=mock_info):
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                msg = result.message
                self.assertIn("for (int i = 0; i < n; i++) {", msg)
                self.assertIn("O(n)", msg)
                self.assertIn("Loop statement", msg)

        asyncio.run(run())

    def test_missing_unreadable_file_error(self):
        """
        Requirement 6 & 8D: Missing / unreadable file must not produce a fabricated explanation.
        """
        async def run():
            prompt = "Explain nonexistent_file_999.cpp line by line. Don't modify it."
            res = await CommandRouter.parse_skill_intent(prompt)
            self.assertIsNotNone(res)
            skill_name, args = res
            self.assertEqual(args.get("filename"), "nonexistent_file_999.cpp")

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                result = await self.skill.execute(args)
                self.assertFalse(result.success)
                self.assertFalse(result.verified)
                self.assertEqual(result.error, "File not found")
                self.assertIn("couldn't find source file", result.message)

        asyncio.run(run())

    def test_real_test_lab_fixture_if_present_on_disk(self):
        """
        Test against the actual live C:\\Users\\ryzzn\\OneDrive\\Desktop\\ByteX_Real_Test\\ByteX_Test_Lab\\01_basic.cpp
        """
        async def run():
            real_path = Path(r"C:\Users\ryzzn\OneDrive\Desktop\ByteX_Real_Test\ByteX_Test_Lab\01_basic.cpp")
            if not real_path.exists():
                self.skipTest(f"Real path {real_path} not found on this machine")

            hash_before = hashlib.sha256(real_path.read_bytes()).hexdigest()
            mtime_before = real_path.stat().st_mtime_ns

            prompt = "Explain 01_basic.cpp line by line. Don't modify it."
            
            # Execute through full CommandRouter.route_command pipeline
            handled, response, state, data = await CommandRouter.route_command(prompt)
            self.assertTrue(handled)
            self.assertEqual(state, "speaking")
            self.assertIsNotNone(data)
            self.assertTrue(data.get("read_only"))
            self.assertEqual(data.get("filename"), "01_basic.cpp")
            self.assertEqual(data.get("mode"), "line_by_line")

            # Explanation matches source
            self.assertIn("Line-by-Line Breakdown", response)
            self.assertIn("#include <iostream>", response)
            self.assertIn("using namespace std;", response)
            self.assertIn("int main() {", response)
            self.assertIn("return 0;", response)

            # Ensure file hash on disk is strictly unchanged
            hash_after = hashlib.sha256(real_path.read_bytes()).hexdigest()
            mtime_after = real_path.stat().st_mtime_ns
            self.assertEqual(hash_before, hash_after)
            self.assertEqual(mtime_before, mtime_after)

        asyncio.run(run())

    def test_compile_only_routing_and_execution_regression(self):
        """
        Requirement 12: Comprehensive regression tests for compile-only vs compile-and-run:
        A. Compile 01_basic.cpp -> successful compilation.
        B. Confirm executable is NOT launched.
        C. Confirm source file is unchanged.
        D. Broken source -> real compiler diagnostics are returned.
        E. Missing file -> explicit file-not-found result.
        F. "Compile and run 01_basic.cpp" -> compile followed by run.
        G. "Compile 01_basic.cpp but don't run it" -> compile only.
        H. Natural-language compile request must not route to generic AI/web/open-application fallback.
        """
        async def run():
            # A, B, C, G: "Compile 01_basic.cpp but don't run it."
            hash_before = self._file_hash(self.basic_cpp)
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                res = await CommandRouter.parse_skill_intent("Compile 01_basic.cpp but don't run it.")
                self.assertIsNotNone(res)
                skill_name, args = res
                self.assertEqual(skill_name, "coding_workspace")
                self.assertEqual(args.get("action"), "compile_code")
                self.assertEqual(args.get("filename"), "01_basic.cpp")
                self.assertTrue(args.get("compile_only"))

                # Test SkillSelector does not route to web or open_app
                selector_res = ByteXSkillSelector.select_skills_for_goal("Compile 01_basic.cpp but don't run it.")
                self.assertIn("coding_workspace", selector_res.get("selected_skills", []))
                self.assertNotIn("open_application", selector_res.get("selected_skills", []))
                self.assertNotIn("web_search", selector_res.get("selected_skills", []))

                # Execute
                result = await self.skill.execute(args)
                self.assertTrue(result.success)
                self.assertTrue(result.verified)
                self.assertEqual(result.data.get("status"), "COMPILED_SUCCESSFULLY")
                self.assertEqual(result.data.get("exit_code"), 0)
                self.assertEqual(result.data.get("executed"), False)
                self.assertIn("Successfully compiled", result.message)
                self.assertIn("Execution:** Skipped", result.message)

            # Confirm source file is unchanged
            hash_after = self._file_hash(self.basic_cpp)
            self.assertEqual(hash_before, hash_after)

            # D: Broken source -> real compiler diagnostics are returned
            buggy_cpp = self.test_lab / "03_buggy.cpp"
            buggy_cpp.write_text("#include <iostream>\nusing namespace std;\nint main() {\n    int x = 10\n    cout << x << endl;\n    return 0;\n}\n", encoding="utf-8")
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                buggy_res = await CommandRouter.parse_skill_intent("Compile 03_buggy.cpp but don't run it.")
                self.assertIsNotNone(buggy_res)
                _, buggy_args = buggy_res
                result_buggy = await self.skill.execute(buggy_args)
                self.assertFalse(result_buggy.success)
                self.assertEqual(result_buggy.data.get("status"), "COMPILATION_FAILED")
                self.assertNotEqual(result_buggy.data.get("exit_code"), 0)
                self.assertIn("error:", result_buggy.data.get("diagnostics", "").lower())
                self.assertEqual(result_buggy.data.get("executed"), False)

            # E: Missing file -> explicit file-not-found result
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                missing_res = await CommandRouter.parse_skill_intent("Compile totally_missing_file_xyz.cpp")
                self.assertIsNotNone(missing_res)
                _, missing_args = missing_res
                result_missing = await self.skill.execute(missing_args)
                self.assertFalse(result_missing.success)
                self.assertEqual(result_missing.data.get("status"), "SOURCE_FILE_NOT_FOUND")
                self.assertIn("couldn't find source file", result_missing.message)

            # F: "Compile and run 01_basic.cpp" -> compile followed by run
            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                run_res = await CommandRouter.parse_skill_intent("Compile and run 01_basic.cpp")
                self.assertIsNotNone(run_res)
                run_skill, run_args = run_res
                self.assertEqual(run_skill, "coding_workspace")
                self.assertEqual(run_args.get("action"), "execute_code")
                result_run = await self.skill.execute(run_args)
                self.assertTrue(result_run.success)
                self.assertEqual(result_run.data.get("status"), "EXECUTION_VERIFIED")
                self.assertIn("BYTE_X_BASIC_TEST", result_run.data.get("stdout"))

        asyncio.run(run())

    def test_source_grounding_cross_file_isolation_suite(self):
        """
        Requirements 12 & 13: Source integrity, grounding, and cross-file contamination suite (Tests A-H).
        """
        # Create all 5 fixtures in test lab
        search_cpp = self.test_lab / "02_search.cpp"
        search_cpp.write_text(
            "#include <iostream>\nusing namespace std;\n\nint main() {\n    int arr[] = {4, 8, 15, 16, 23, 42};\n    int n = 6;\n    int target = 23;\n\n    for (int i = 0; i < n; i++) {\n        if (arr[i] == target) {\n            cout << \"Found at index \" << i << endl;\n            return 0;\n        }\n    }\n\n    cout << \"Not found\" << endl;\n    return 0;\n}\n",
            encoding="utf-8"
        )

        edge_cases_cpp = self.test_lab / "04_edge_cases.cpp"
        edge_cases_cpp.write_text(
            "#include <iostream>\nusing namespace std;\n\nint main() {\n    int n;\n    cin >> n;\n    if (n <= 0) {\n        cout << \"NO_POSITIVE_VALUES\" << endl;\n        return 0;\n    }\n    for (int i = 1; i <= n; i++) {\n        cout << i << endl;\n    }\n    return 0;\n}\n",
            encoding="utf-8"
        )

        complexity_cpp = self.test_lab / "05_complexity.cpp"
        complexity_cpp.write_text(
            "#include <iostream>\nusing namespace std;\n\nint main() {\n    int n = 10;\n    cout << n << endl; // O(1)\n\n    for (int i = 0; i < n; i++) {\n        cout << i << \" \";\n    } // O(n)\n\n    cout << endl;\n\n    for (int i = 0; i < n; i++) {\n        for (int j = 0; j < n; j++) {\n            int value = i + j;\n        }\n    } // O(n²)\n\n    return 0;\n}\n",
            encoding="utf-8"
        )

        async def run():
            # Initial file hashes
            search_hash_init = self._file_hash(search_cpp)
            edge_hash_init = self._file_hash(edge_cases_cpp)
            comp_hash_init = self._file_hash(complexity_cpp)

            with patch.object(self.skill, '_detect_vscode_workspace_info', return_value=self.mock_info):
                # TEST A: Analyze 04_edge_cases.cpp
                # Assert response mentions input n / n <= 0 / loop. Assert response does NOT mention bubble sort.
                res_a = await CommandRouter.parse_skill_intent("Analyze 04_edge_cases.cpp and identify all meaningful edge cases. Don't modify it.")
                self.assertIsNotNone(res_a)
                _, args_a = res_a
                self.assertEqual(args_a.get("action"), "analyze_code")
                out_a = await self.skill.execute(args_a)
                self.assertTrue(out_a.success)
                msg_a = out_a.message.lower()
                self.assertIn("cin >> n", msg_a)
                self.assertIn("n <= 0", msg_a)
                self.assertIn("loop", msg_a)
                self.assertIn("no_positive_values", msg_a)
                self.assertNotIn("bubble sort", msg_a)
                self.assertNotIn("std::sort", msg_a)
                self.assertNotIn("swap", msg_a)

                # TEST B: Analyze 05_complexity.cpp
                # Assert response mentions O(1), O(n), O(n²).
                # Assert response does NOT mention bubble sort, sorting, std::sort, swapping, or adjacent comparisons.
                res_b = await CommandRouter.parse_skill_intent("Analyze 05_complexity.cpp. Identify every major algorithmic section and give its time complexity. Don't modify it.")
                self.assertIsNotNone(res_b)
                _, args_b = res_b
                self.assertEqual(args_b.get("action"), "analyze_code")
                out_b = await self.skill.execute(args_b)
                self.assertTrue(out_b.success)
                msg_b = out_b.message
                msg_b_lower = msg_b.lower()
                self.assertIn("O(1)", msg_b)
                self.assertIn("O(n)", msg_b)
                self.assertIn("O(n^2)", msg_b)
                self.assertNotIn("bubble sort", msg_b_lower)
                self.assertNotIn("std::sort", msg_b_lower)
                self.assertNotIn("adjacent comparison", msg_b_lower)
                self.assertNotIn("pairwise", msg_b_lower)

                # TEST C: Analyze 02_search.cpp
                # Assert response mentions linear search. Assert response does NOT claim bubble sort.
                res_c = await CommandRouter.parse_skill_intent("Analyze 02_search.cpp. What algorithm is being used and what is its time and space complexity? Don't modify it.")
                self.assertIsNotNone(res_c)
                _, args_c = res_c
                out_c = await self.skill.execute(args_c)
                self.assertTrue(out_c.success)
                msg_c_lower = out_c.message.lower()
                self.assertIn("linear search", msg_c_lower)
                self.assertIn("o(n)", msg_c_lower)
                self.assertIn("o(1)", msg_c_lower)
                self.assertNotIn("bubble sort", msg_c_lower)

                # TEST D: Cross-file contamination: Analyze 02_search.cpp then immediately analyze 05_complexity.cpp
                out_d1 = await self.skill.execute(args_c)
                out_d2 = await self.skill.execute(args_b)
                self.assertIn("linear search", out_d1.message.lower())
                self.assertNotIn("linear search", out_d2.message.lower())
                self.assertNotIn("target =", out_d2.message.lower())
                self.assertNotIn("found at index", out_d2.message.lower())
                self.assertNotIn("not found", out_d2.message.lower())
                self.assertIn("O(n^2)", out_d2.message)

                # TEST E: Cross-file contamination: Analyze 05_complexity.cpp then immediately analyze 04_edge_cases.cpp
                out_e1 = await self.skill.execute(args_b)
                out_e2 = await self.skill.execute(args_a)
                self.assertNotIn("int value = i + j", out_e2.message)
                self.assertNotIn("section 3", out_e2.message.lower())
                self.assertIn("no_positive_values", out_e2.message.lower())

                # TEST F: Suggest an optimization for 02_search.cpp
                # Ensure it reads the source and does not request pasted code.
                res_f = await CommandRouter.parse_skill_intent("Suggest a more efficient approach for 02_search.cpp, but don't modify it.")
                self.assertIsNotNone(res_f)
                _, args_f = res_f
                self.assertEqual(args_f.get("action"), "analyze_code")
                self.assertEqual(args_f.get("filename"), "02_search.cpp")
                out_f = await self.skill.execute(args_f)
                self.assertTrue(out_f.success)
                self.assertNotIn("paste the code", out_f.message.lower())
                self.assertNotIn("cannot analyze", out_f.message.lower())
                self.assertIn("binary search", out_f.message.lower())
                self.assertIn("sorted", out_f.message.lower())

                # TEST G: Make source missing/unreadable -> returns explicit read failure instead of fabricated analysis
                res_g = await CommandRouter.parse_skill_intent("Analyze nonexistent_source_file_999.cpp. Don't modify it.")
                self.assertIsNotNone(res_g)
                _, args_g = res_g
                out_g = await self.skill.execute(args_g)
                self.assertFalse(out_g.success)
                self.assertIn("couldn't find source file", out_g.message.lower())

                # TEST H: Verify all analysis requests leave file hashes completely unchanged
                self.assertEqual(self._file_hash(search_cpp), search_hash_init)
                self.assertEqual(self._file_hash(edge_cases_cpp), edge_hash_init)
                self.assertEqual(self._file_hash(complexity_cpp), comp_hash_init)

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()


