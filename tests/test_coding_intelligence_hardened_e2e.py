import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.coding import CodingWorkspaceSkill


class TestCodingIntelligenceHardenedE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="bytex_hardened_test_"))
        self.skill = CodingWorkspaceSkill()
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name

    async def asyncTearDown(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # 1. Insert after loop
    async def test_01_insert_after_loop(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "01_basic.cpp",
            "instruction": "Add a message after the loop that says HELLO_BYTE_X."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        
        # Verify statement is placed after closing brace of loop, not inside
        loop_close_idx = content.find("}")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertNotEqual(stmt_idx, -1)
        self.assertGreater(stmt_idx, loop_close_idx)
        self.assertIn("for (int i = 1; i <= 10; i++)", content)

    # 2. Insert inside loop
    async def test_02_insert_inside_loop(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "02_inside.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "02_inside.cpp",
            "instruction": "Add a message inside the loop saying INSIDE_LOOP."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        loop_close_idx = content.find("}")
        stmt_idx = content.find('cout << "INSIDE_LOOP" << endl;')
        self.assertNotEqual(stmt_idx, -1)
        self.assertLess(stmt_idx, loop_close_idx)

    # 3. Insert before loop
    async def test_03_insert_before_loop(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "03_before.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "03_before.cpp",
            "instruction": "Add a message before the loop that says STARTING_LOOP."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        loop_start_idx = content.find("for (int i = 1; i <= 10; i++)")
        stmt_idx = content.find('cout << "STARTING_LOOP" << endl;')
        self.assertNotEqual(stmt_idx, -1)
        self.assertLess(stmt_idx, loop_start_idx)

    # 4. Insert after existing output (Live Test 2)
    async def test_04_insert_after_existing_output(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "01_basic.cpp",
            "instruction": "Add a message after the existing output in 01_basic.cpp that says HELLO_BYTE_X."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        
        # Verify output is placed after the loop body
        loop_close_idx = content.find("}")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertNotEqual(stmt_idx, -1)
        self.assertGreater(stmt_idx, loop_close_idx)
        self.assertNotIn("cout << \"Executing:", content)

    # 5. Preserve unrelated code
    async def test_05_preserve_unrelated_code(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "// Critical helper function\n"
            "void helperUnrelated() {\n"
            "    cout << \"Helper invariant\" << endl;\n"
            "}\n\n"
            "int main() {\n"
            "    helperUnrelated();\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "05_preserve.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "05_preserve.cpp",
            "instruction": "Add a message after the existing output that says HELLO_BYTE_X. Don't change anything else."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        self.assertIn("void helperUnrelated()", content)
        self.assertIn("cout << \"Helper invariant\"", content)
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertIn('cout << "HELLO_BYTE_X" << endl;', content)

    # 6. Fix without rewriting (Live Test 3: Fix != Rewrite)
    async def test_06_fix_without_rewriting(self):
        # Misplaced code inside loop
        broken_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(broken_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "01_basic.cpp",
            "instruction": "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        
        # Invariant: loop structure MUST NOT be destroyed or converted to dummy cout
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertIn("cout << i << endl;", content)
        self.assertNotIn("cout << \"Executing:", content)
        
        # Verify HELLO_BYTE_X occurs exactly once and is outside the loop
        self.assertEqual(content.count('cout << "HELLO_BYTE_X" << endl;'), 1)
        loop_close_idx = content.find("}")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertGreater(stmt_idx, loop_close_idx)

    # 7. Exactly-once output verification
    async def test_07_exactly_once_output(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    cout << \"HELLO_BYTE_X\" << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "07_exec.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "execute_code",
            "filename": "07_exec.cpp"
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        stdout = res.data.get("stdout", "")
        self.assertEqual(stdout.count("HELLO_BYTE_X"), 1)

    # 8. Ordered output verification
    async def test_08_ordered_output(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    cout << \"HELLO_BYTE_X\" << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "08_order.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "execute_code",
            "filename": "08_order.cpp"
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        stdout = res.data.get("stdout", "")
        
        # Verify 10 is printed before HELLO_BYTE_X
        pos_10 = stdout.rfind("10")
        pos_hello = stdout.find("HELLO_BYTE_X")
        self.assertNotEqual(pos_10, -1)
        self.assertNotEqual(pos_hello, -1)
        self.assertGreater(pos_hello, pos_10)

    # 9. "Don't change anything else"
    async def test_09_dont_change_anything_else(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "const int MAX_LIMIT = 10;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= MAX_LIMIT; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "09_const.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "edit_code_file",
            "filename": "09_const.cpp",
            "instruction": "Add a message after the existing output that says HELLO_BYTE_X. Don't change anything else."
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")
        self.assertIn("const int MAX_LIMIT = 10;", content)
        self.assertIn("for (int i = 1; i <= MAX_LIMIT; i++)", content)

    # 10. Source-grounded line-by-line explanation
    async def test_10_source_grounded_line_by_line(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    cout << \"HELLO_BYTE_X\" << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        res = await self.skill.execute({
            "action": "explain_code",
            "filename": "01_basic.cpp",
            "mode": "line_by_line"
        })
        self.assertTrue(res.success, f"Failed: {res.message}")
        msg = res.message
        
        # Must describe cout << i << endl as printing current value of i followed by newline
        self.assertIn("Prints the current value of i followed by a newline", msg)
        self.assertNotIn("Outputs i << endl", msg)
        
        # Must describe loop bounds 1 through 10
        self.assertIn("from 1 through 10", msg)

    # 11. Source-grounded complexity analysis
    async def test_11_source_grounded_complexity_analysis(self):
        sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(sample_code, encoding="utf-8")

        analysis = self.skill._synthesize_code_analysis(sample_code, "cpp", "01_basic.cpp", "analyze complexity")
        report = analysis["report"]
        
        # Invariant: must NOT claim visiting elements of an array
        self.assertNotIn("visiting each element of an array", report)
        self.assertNotIn("unsorted elements", report)
        self.assertIn("1 through 10", report)

    # 12. Exact user prompt FIX test (Fix != Rewrite)
    async def test_12_exact_user_fix_command_e2e(self):
        from core.command_router import CommandRouter
        from core.session import session_manager
        
        # Misplaced code inside loop
        broken_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(broken_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name

        # Route exact user command
        cmd = "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers."
        res_intent = await CommandRouter.parse_skill_intent(cmd)
        self.assertIsNotNone(res_intent, f"CommandRouter failed to parse intent for: {cmd}")
        skill_name, args = res_intent
        self.assertEqual(skill_name, "coding_workspace")
        self.assertEqual(args.get("action"), "edit_code_file")

        # Execute
        res = await self.skill.execute(args)
        self.assertTrue(res.success, f"Execution failed: {res.message}")
        content = test_file.read_text(encoding="utf-8")

        # Invariants: MUST NOT destroy loop, MUST NOT introduce placeholder cout, MUST have HELLO_BYTE_X once outside loop
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertIn("cout << i << endl;", content)
        self.assertNotIn("cout << \"Executing:", content)
        loop_close_idx = content.find("}")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertGreater(stmt_idx, loop_close_idx)

    # 13. End-to-end route_command regression test for natural fix command
    async def test_13_route_command_natural_fix_pipeline_regression(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        # Initial source with bug (HELLO_BYTE_X printed inside loop on each iteration)
        broken_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 5; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(broken_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        # Register test skill instance in registry for route_command execution
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers."
        handled, response_text, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled, f"route_command failed to handle: {cmd}")
        self.assertEqual(state, "speaking")

        # Read modified content
        content = test_file.read_text(encoding="utf-8")

        # 1. Existing loop preserved
        self.assertIn("for (int i = 1; i <= 5; i++)", content)
        self.assertIn("cout << i << endl;", content)

        # 2. No dummy fallback sentence replacement
        self.assertNotIn("Executing:", content)
        self.assertNotIn("cout << \"Executing:", content)

        # 3. HELLO_BYTE_X executed once after the loop
        self.assertEqual(content.count('cout << "HELLO_BYTE_X" << endl;'), 1)
        loop_end_idx = content.find("}")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertGreater(stmt_idx, loop_end_idx)

    # 14. Exact RYznn fix command with loop preservation and execution verification (Cases A, F, G, H)
    async def test_14_exact_ryznn_fix_command_and_verification(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        broken_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(broken_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so RYznn is printed only once after all the numbers."
        handled, response_text, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled, f"route_command failed for: {cmd}")
        self.assertEqual(state, "speaking")

        content = test_file.read_text(encoding="utf-8")

        # Invariant 1: Source code contains cout << "RYznn" << endl; exactly once
        self.assertEqual(content.count('cout << "RYznn" << endl;'), 1)
        # Invariant 2: Stale HELLO_BYTE_X removed completely
        self.assertNotIn("HELLO_BYTE_X", content)
        # Invariant 3: Loop for 1 to 10 and cout << i << endl; preserved
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertIn("cout << i << endl;", content)
        # Invariant 4: RYznn statement is AFTER the loop closing brace
        loop_end = content.find("}")
        ryznn_pos = content.find('cout << "RYznn" << endl;')
        self.assertGreater(ryznn_pos, loop_end)

        # Invariant 5: Dynamic execution verification passed for RYznn
        if data:
            self.assertEqual(data.get("final_verification_state"), "EXECUTION_VERIFIED")
            stdout = data.get("stdout", "")
            self.assertEqual(stdout.count("RYznn"), 1)
            self.assertNotIn("HELLO_BYTE_X", stdout)
            # Numbers 1 through 10 in order
            for n in range(1, 11):
                self.assertIn(str(n), stdout)
            # RYznn is after number 10
            self.assertGreater(stdout.find("RYznn"), stdout.rfind("10"))

    # 15. Fix command with KUNAL_TEST (Case C)
    async def test_15_kunal_test_fix_command_and_verification(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        broken_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(broken_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so KUNAL_TEST is printed only once after all the numbers."
        handled, response_text, state, data = await CommandRouter.route_command(cmd)
        self.assertTrue(handled, f"route_command failed for: {cmd}")
        self.assertEqual(state, "speaking")

        content = test_file.read_text(encoding="utf-8")
        self.assertEqual(content.count('cout << "KUNAL_TEST" << endl;'), 1)
        self.assertNotIn("HELLO_BYTE_X", content)
        if data:
            self.assertEqual(data.get("final_verification_state"), "EXECUTION_VERIFIED")
            self.assertIn("KUNAL_TEST", data.get("stdout", ""))

    # 16. Mismatched target string causes OUTPUT_VERIFICATION_FAILED (Case D)
    async def test_16_mismatched_target_string_verification_fails(self):
        # Code that prints HELLO_BYTE_X instead of requested RYznn
        wrong_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "    }\n"
            "    cout << \"HELLO_BYTE_X\" << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_wrong.cpp"
        test_file.write_text(wrong_code, encoding="utf-8")

        # Request requires RYznn
        reqs = self.skill._extract_semantic_requirements(
            "Fix 01_wrong.cpp so RYznn is printed only once after all the numbers."
        )
        self.assertEqual(reqs.get("target_string"), "RYznn")

        # Verify execution semantics against wrong_code
        ok, stdout, summary, info = self.skill._verify_execution_semantics(test_file, reqs)
        self.assertFalse(ok)
        self.assertEqual(info.get("verification_state"), "OUTPUT_VERIFICATION_FAILED")
        self.assertIn("OUTPUT_VERIFICATION_FAILED", summary)

    # 17. Two consecutive requests with different strings (Case E)
    async def test_17_consecutive_requests_independent_targets(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        initial_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(initial_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        # Request 1: RYznn
        cmd1 = "Fix 01_basic.cpp so RYznn is printed only once after all the numbers."
        h1, r1, s1, d1 = await CommandRouter.route_command(cmd1)
        self.assertTrue(h1)
        c1 = test_file.read_text(encoding="utf-8")
        self.assertEqual(c1.count('cout << "RYznn" << endl;'), 1)
        self.assertNotIn("HELLO_BYTE_X", c1)

        # Request 2: KUNAL_TEST (consecutive on the modified file)
        cmd2 = "Fix 01_basic.cpp so KUNAL_TEST is printed only once after all the numbers."
        h2, r2, s2, d2 = await CommandRouter.route_command(cmd2)
        self.assertTrue(h2)
        c2 = test_file.read_text(encoding="utf-8")
        self.assertEqual(c2.count('cout << "KUNAL_TEST" << endl;'), 1)
        # Invariant: Must NOT retain previous target RYznn or HELLO_BYTE_X
        self.assertNotIn("RYznn", c2)
        self.assertNotIn("HELLO_BYTE_X", c2)
        self.assertIn("for (int i = 1; i <= 10; i++)", c2)


    # 18. Exact hellow_world Fix Command & Verification
    async def test_18_exact_hellow_world_fix_command_and_verification(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        initial_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(initial_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so hellow_world is printed only once after all the numbers."
        handled, response, state, data = await CommandRouter.route_command(cmd)

        self.assertTrue(handled)
        content = test_file.read_text(encoding="utf-8")
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertNotIn("HELLO_BYTE_X", content)
        self.assertEqual(content.count('cout << "hellow_world" << endl;'), 1)
        self.assertIn("hellow_world", response)
        self.assertNotIn("HELLO_BYTE_X", response)
        if data:
            self.assertEqual(data.get("output_verification"), "EXECUTION_VERIFIED")

    # 19. Exact HELLO_BYTE_X Fix Command & Verification
    async def test_19_exact_hello_byte_x_fix_command_and_verification(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        initial_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(initial_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers."
        handled, response, state, data = await CommandRouter.route_command(cmd)

        self.assertTrue(handled)
        content = test_file.read_text(encoding="utf-8")
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertEqual(content.count('cout << "HELLO_BYTE_X" << endl;'), 1)
        loop_idx = content.find("for (int i = 1; i <= 10; i++)")
        stmt_idx = content.find('cout << "HELLO_BYTE_X" << endl;')
        self.assertGreater(stmt_idx, loop_idx)
        if data:
            self.assertEqual(data.get("output_verification"), "EXECUTION_VERIFIED")

    # 20. Exact RYznn Fix Command & Verification
    async def test_20_exact_ryznn_fix_command_and_verification(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        initial_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(initial_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        cmd = "Fix 01_basic.cpp so RYznn is printed only once after all the numbers."
        handled, response, state, data = await CommandRouter.route_command(cmd)

        self.assertTrue(handled)
        content = test_file.read_text(encoding="utf-8")
        self.assertIn("for (int i = 1; i <= 10; i++)", content)
        self.assertNotIn("HELLO_BYTE_X", content)
        self.assertEqual(content.count('cout << "RYznn" << endl;'), 1)
        self.assertIn("RYznn", response)
        self.assertNotIn("HELLO_BYTE_X", response)
        if data:
            self.assertEqual(data.get("output_verification"), "EXECUTION_VERIFIED")

    # 21. Multi-target consecutive requests (hellow_world -> RYznn -> HELLO_BYTE_X -> hellow_world)
    async def test_21_consecutive_multi_target_lifecycle(self):
        from core.command_router import CommandRouter
        from skills.registry import skill_registry

        initial_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        cout << i << endl;\n"
            "        cout << \"HELLO_BYTE_X\" << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        test_file = self.temp_dir / "01_basic.cpp"
        test_file.write_text(initial_code, encoding="utf-8")
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        seq = [
            ("hellow_world", ["HELLO_BYTE_X", "RYznn"]),
            ("RYznn", ["HELLO_BYTE_X", "hellow_world"]),
            ("HELLO_BYTE_X", ["RYznn", "hellow_world"]),
            ("hellow_world", ["HELLO_BYTE_X", "RYznn"])
        ]

        for target, forbidden in seq:
            cmd = f"Fix 01_basic.cpp so {target} is printed only once after all the numbers."
            handled, response, state, data = await CommandRouter.route_command(cmd)
            self.assertTrue(handled)
            c = test_file.read_text(encoding="utf-8")
            self.assertEqual(c.count(f'cout << "{target}" << endl;'), 1)
            self.assertIn("for (int i = 1; i <= 10; i++)", c)
            for f in forbidden:
                self.assertNotIn(f, c, f"Found forbidden stale target '{f}' after setting '{target}'")
            if data:
                self.assertEqual(data.get("output_verification"), "EXECUTION_VERIFIED")


if __name__ == "__main__":
    unittest.main()



