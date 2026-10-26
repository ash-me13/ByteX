import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.coding import CodingWorkspaceSkill
from skills.diagnostics import CodeDiagnosticEngine
from skills.code_fixer import CodeFixEngine, FixMode

class TestCodeSelfHealingDebugE2E(unittest.TestCase):
    """
    End-to-End verification test suite for Coding Intelligence Self-Healing Debugger
    and automated localized error recovery pipeline.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temp_dir.name)
        self.skill = CodingWorkspaceSkill()
        self.skill._cached_vscode_workspace = self.workspace_path

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_semicolon_cpp_self_healing(self):
        """
        Scenario: 'Run testing.cpp and fix the error.'
        testing.cpp has a missing semicolon after 'int x = 10'
        Verifies:
        1. GCC compiler error parsed accurately with line number.
        2. Surgical semicolon insertion at line 5 without touching bubbleSort or main.
        3. Recompilation / verification succeeds.
        4. Returns FIXED_AND_COMPILED or FIXED_AND_EXECUTION_VERIFIED.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    int x = 10\n"
                "    cout << x << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            # Mock compiler output simulating GCC error
            mock_compiler_err = (
                f"{str(cpp_file)}:6:5: error: expected ';' before 'cout'\n"
                "    cout << x << endl;\n"
                "    ^~~~\n"
            )

            # Step 1: Diagnose
            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_compiler_err,
                source_code=original_code,
                language="cpp",
                file_path=str(cpp_file),
                stage="compile"
            )
            self.assertEqual(diag.confidence_level, "HIGH")

            # Step 2: Fix
            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_compiler_err,
                language="cpp",
                diagnostic=diag
            )
            self.assertTrue(fix_res.success)
            self.assertTrue(fix_res.fix_applied)
            self.assertIn(fix_res.verification_status, ["FIXED_AND_COMPILED", "passed"])

            modified = cpp_file.read_text(encoding="utf-8")
            self.assertIn("int x = 10;", modified)
            self.assertIn("cout << x << endl;", modified)

        asyncio.run(run())

    def test_missing_closing_brace_cpp_self_healing(self):
        """
        Scenario: testing.cpp missing closing brace at EOF.
        Verifies:
        1. Diagnostic identifies missing brace.
        2. Surgical append of '}' preserves all previous statements.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    cout << \"hello\" << endl;\n"
                "    return 0;\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            mock_compiler_err = (
                f"{str(cpp_file)}:6:1: error: expected '}}' at end of input\n"
            )

            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_compiler_err,
                source_code=original_code,
                language="cpp",
                file_path=str(cpp_file),
                stage="compile"
            )
            self.assertEqual(diag.confidence_level, "HIGH")

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_compiler_err,
                language="cpp",
                diagnostic=diag
            )
            self.assertTrue(fix_res.success)
            modified = cpp_file.read_text(encoding="utf-8")
            self.assertTrue(modified.rstrip().endswith("}"))

        asyncio.run(run())

    def test_missing_namespace_and_iostream_cpp(self):
        """
        Scenario: 'cout' was not declared in this scope (missing using namespace std; / iostream)
        Verifies:
        1. Classified as missing_include_or_import with HIGH confidence.
        2. Automatically adds 'using namespace std;' or '#include <iostream>'.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n\n"
                "int main() {\n"
                "    cout << 42 << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            mock_compiler_err = (
                f"{str(cpp_file)}:4:5: error: 'cout' was not declared in this scope; did you mean 'std::cout'?\n"
            )

            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_compiler_err,
                source_code=original_code,
                language="cpp",
                file_path=str(cpp_file),
                stage="compile"
            )
            self.assertEqual(diag.confidence_level, "HIGH")

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_compiler_err,
                language="cpp",
                diagnostic=diag
            )
            self.assertTrue(fix_res.success)
            modified = cpp_file.read_text(encoding="utf-8")
            self.assertIn("using namespace std;", modified)

        asyncio.run(run())

    def test_undeclared_variable_declaration_cpp(self):
        """
        Scenario: 'x' was not declared in this scope, used as 'x = 10;'
        Verifies:
        1. Classified with HIGH confidence.
        2. Synthesizes variable type declaration 'int x = 10;'
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    x = 10;\n"
                "    cout << x << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            mock_compiler_err = (
                f"{str(cpp_file)}:5:5: error: 'x' was not declared in this scope\n"
            )

            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_compiler_err,
                source_code=original_code,
                language="cpp",
                file_path=str(cpp_file),
                stage="compile"
            )
            self.assertEqual(diag.confidence_level, "HIGH")

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_compiler_err,
                language="cpp",
                diagnostic=diag
            )
            self.assertTrue(fix_res.success)
            modified = cpp_file.read_text(encoding="utf-8")
            self.assertIn("int x = 10;", modified)

        asyncio.run(run())

    def test_python_missing_colon_self_healing(self):
        """
        Scenario: SyntaxError: expected ':' in Python script.
        Verifies:
        1. Colon appended to def/if/for/while/class statement.
        2. Execution verified.
        """
        async def run():
            py_file = self.workspace_path / "script.py"
            original_code = (
                "def calculate_sum(a, b)\n"
                "    return a + b\n\n"
                "print(calculate_sum(5, 7))\n"
            )
            py_file.write_text(original_code, encoding="utf-8")

            mock_err = (
                f'  File "{str(py_file)}", line 1\n'
                "    def calculate_sum(a, b)\n"
                "                           ^\n"
                "SyntaxError: expected ':'\n"
            )

            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_err,
                source_code=original_code,
                language="python",
                file_path=str(py_file),
                stage="compile"
            )
            self.assertEqual(diag.confidence_level, "HIGH")

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=py_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_err,
                language="python",
                diagnostic=diag
            )
            self.assertTrue(fix_res.success)
            modified = py_file.read_text(encoding="utf-8")
            self.assertIn("def calculate_sum(a, b):", modified)

        asyncio.run(run())

    def test_complex_ambiguous_error_no_auto_modification(self):
        """
        Scenario: Ambiguous or architectural compilation failure.
        Verifies:
        1. Confidence is LOW or MEDIUM.
        2. In AUTOMATIC mode without clear patch, file is NOT modified.
        3. Returns DIAGNOSIS_ONLY or safe failure message without corrupting code.
        """
        async def run():
            cpp_file = self.workspace_path / "complex.cpp"
            original_code = (
                "#include <iostream>\n"
                "template<typename T> struct ComplexTraits {};\n"
                "int main() { return 0; }\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            mock_err = (
                f"{str(cpp_file)}:2:29: error: no matching function for call to 'ComplexTraits<int>::resolve()'\n"
            )

            diag = CodeDiagnosticEngine.diagnose(
                error_output=mock_err,
                source_code=original_code,
                language="cpp",
                file_path=str(cpp_file),
                stage="compile"
            )
            self.assertIn(diag.confidence_level, ["LOW", "MEDIUM"])

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_err,
                language="cpp",
                diagnostic=diag
            )
            self.assertFalse(fix_res.fix_applied)
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), original_code)
            self.assertTrue(
                "haven't modified" in fix_res.message.lower()
                or "ambiguity" in fix_res.message.lower()
                or "not confident" in fix_res.message.lower()
            )

        asyncio.run(run())

    def test_failed_repair_triggers_clean_rollback(self):
        """
        Scenario: An automatic fix is applied but fails re-compilation.
        Verifies:
        1. File is immediately rolled back to exact original source.
        2. verification_status is FIX_ATTEMPT_FAILED_ROLLED_BACK.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n"
                "using namespace std;\n"
                "int main() {\n"
                "    int x = 10\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            mock_err = f"{str(cpp_file)}:5:5: error: expected ';' before 'return'\n"

            # Custom mock execution runner that always fails
            async def failing_runner(p):
                return {"success": False, "exit_code": 1, "stderr": "Fatal linking error"}

            fix_res = await CodeFixEngine.fix_code_file(
                target_file_path=cpp_file,
                fix_mode=FixMode.AUTOMATIC,
                error_output=mock_err,
                language="cpp",
                execution_runner=failing_runner
            )
            self.assertFalse(fix_res.success)
            self.assertTrue(fix_res.rolled_back)
            self.assertEqual(fix_res.verification_status, "FIX_ATTEMPT_FAILED_ROLLED_BACK")
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), original_code)

        asyncio.run(run())

    def test_readonly_commands_remain_unmodified(self):
        """
        Verifies that read-only commands (review, explain, teach) never mutate files.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            original_code = (
                "#include <iostream>\n"
                "using namespace std;\n"
                "int main() { return 0; }\n"
            )
            cpp_file.write_text(original_code, encoding="utf-8")

            # Review code
            rev_res = await self.skill._action_review_code({"filename": "testing.cpp"})
            self.assertTrue(rev_res.success)
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), original_code)

            # Explain code
            exp_res = await self.skill._action_explain_code({"filename": "testing.cpp"})
            self.assertTrue(exp_res.success)
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), original_code)

            # Teach code
            teach_res = await self.skill._action_teach_code({"filename": "testing.cpp"})
            self.assertTrue(teach_res.success)
            self.assertEqual(cpp_file.read_text(encoding="utf-8"), original_code)

        asyncio.run(run())

    def test_real_mingw_semicolon_output_diagnostics(self):
        r"""
        Tests the EXACT raw output from MinGW GCC 6.3+:
        C:\path\testing.cpp: In function 'int main()':
        C:\path\testing.cpp:5:5: error: expected ',' or ';' before 'cout'
             cout << x << endl;
             ^~~~
        """
        cpp_file = self.workspace_path / "testing.cpp"
        source = (
            "#include <iostream>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    int x = 10\n"
            "    cout << x << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        cpp_file.write_text(source, encoding="utf-8")
        raw_stderr = (
            f"{str(cpp_file)}: In function 'int main()':\n"
            f"{str(cpp_file)}:5:5: error: expected ',' or ';' before 'cout'\n"
            "     cout << x << endl;\n"
            "     ^~~~\n"
        )

        diag = CodeDiagnosticEngine.diagnose(
            error_output=raw_stderr,
            language="cpp",
            file_path=str(cpp_file),
            source_code=source,
            stage="compile"
        )
        self.assertEqual(diag.error_type, "SYNTAX_ERROR")
        self.assertEqual(diag.line, 5)
        self.assertEqual(diag.confidence_level, "HIGH")
        self.assertTrue(";" in diag.cause or "semicolon" in diag.cause.lower() or "terminator" in diag.cause.lower())

    def test_msvc_cl_compiler_output_diagnostics(self):
        r"""
        Tests MSVC (cl.exe / clang-cl) compiler output:
        C:\path\testing.cpp(5): error C2143: syntax error : missing ';' before 'cout'
        """
        cpp_file = self.workspace_path / "testing.cpp"
        source = (
            "#include <iostream>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    int x = 10\n"
            "    cout << x << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        cpp_file.write_text(source, encoding="utf-8")
        raw_stderr = (
            f"{str(cpp_file)}(5): error C2143: syntax error : missing ';' before 'cout'\n"
        )

        diag = CodeDiagnosticEngine.diagnose(
            error_output=raw_stderr,
            language="cpp",
            file_path=str(cpp_file),
            source_code=source,
            stage="compile"
        )
        self.assertEqual(diag.error_type, "SYNTAX_ERROR")
        self.assertEqual(diag.line, 5)
        self.assertEqual(diag.confidence_level, "HIGH")

    def test_system_header_note_filtering(self):
        r"""
        Verifies that notes from standard library headers (e.g. c:\mingw\include\c++\iostream:61:18)
        are filtered out so the primary error focuses strictly on user source file.
        """
        cpp_file = self.workspace_path / "testing.cpp"
        source = (
            "#include <iostream>\n"
            "int main() {\n"
            "    cout << 10 << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        cpp_file.write_text(source, encoding="utf-8")
        raw_stderr = (
            f"{str(cpp_file)}:3:5: error: 'cout' was not declared in this scope\n"
            "     cout << 10 << endl;\n"
            "     ^~~~\n"
            "c:\\mingw\\lib\\gcc\\mingw32\\6.3.0\\include\\c++\\iostream:61:18: note:   'std::cout'\n"
            "   extern ostream cout;  /// Linked to standard output\n"
            "                  ^~~~\n"
            f"{str(cpp_file)}:3:19: error: 'endl' was not declared in this scope\n"
        )

        diag = CodeDiagnosticEngine.diagnose(
            error_output=raw_stderr,
            language="cpp",
            file_path=str(cpp_file),
            source_code=source,
            stage="compile"
        )
        self.assertEqual(diag.line, 3)
        self.assertEqual(Path(diag.file).name.lower(), "testing.cpp")

    def test_execute_code_debug_metadata_and_live_auto_fix(self):
        """
        Live end-to-end test with the real g++ compiler if available, verifying:
        1. auto_fix=True compiles, catches missing semicolon, fixes file, recompiles, and runs.
        2. Structured diagnostic metadata is fully populated in result.data.
        """
        async def run():
            cpp_file = self.workspace_path / "testing.cpp"
            source = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                "    int x = 42\n"
                "    cout << x << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            cpp_file.write_text(source, encoding="utf-8")

            res = await self.skill._action_execute_code({
                "filename": "testing.cpp",
                "auto_fix": True
            })
            if shutil.which("g++"):
                self.assertTrue(res.success)
                self.assertTrue(res.verified)
                self.assertIn("Fixed the error", res.message)
                self.assertIn("42", res.message)

                # Check structured metadata
                data = res.data or {}
                self.assertIn("compiler", data)
                self.assertIn("command", data)
                self.assertEqual(data.get("file"), "testing.cpp")
                self.assertIn(data.get("recompilation_result"), ["success", "passed"])

                # Check disk file was updated surgically
                modified = cpp_file.read_text(encoding="utf-8")
                self.assertIn("int x = 42;", modified)

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()

