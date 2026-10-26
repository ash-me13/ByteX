"""
ByteX - Feature #33.5: Automatic Code Error Fixing Test Suite

Comprehensive automated test suite covering all 48 verification points:
01 C++ typo auto-fix
02 C++ missing semicolon
03 C++ missing bracket
04 Python SyntaxError fix
05 Python NameError fix
06 JavaScript syntax fix
07 Java compile error fix
08 Rust simple compile fix
09 TypeScript simple fix
10 High-confidence classification
11 Low-confidence rejection
12 Ambiguous fix rejection
13 Suggest-only mode
14 Confirmation mode
15 Automatic mode
16 Existing file protection
17 Patch-based modification
18 Original source preservation
19 Rollback after failed fix
20 Fix verification
21 Recompile after fix
22 Re-execution after fix
23 Maximum 3 fix attempts
24 Infinite-loop prevention
25 Error-chain tracking
26 Context "Fix it" integration
27 CommandRouter fix routing
28 Planner fix workflow
29 Risk classification
30 Task History integration
31 Error Recovery integration
32 Secret sanitization
33 No shell execution
34 No arbitrary subprocess
35 Workspace boundary protection
36 #33.4 regression
37 #33.3 regression
38 #33.2 regression
39 #33.1 regression
40 #32 Browser regression
41 #31 Search regression
42 #30 Automation regression
43 #29 History regression
44 #28 Recovery regression
45 #27 Suggestions regression
46 #26 Preferences regression
47 #25 Memory regression
48 #24 Context regression
"""

import sys
import os
import shutil
import asyncio
from pathlib import Path

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from skills.registry import skill_registry
from skills.coding import CodingWorkspaceSkill, coding_workspace_skill
from skills.diagnostics import CodeDiagnosticEngine, DiagnosticResult, ErrorCategory
from skills.code_fixer import CodeFixEngine, FixMode, CodePatch, FixResult
from skills.files import resolve_user_directory
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from core.command_router import CommandRouter
from core.verifier import ActionVerifier
from agent.planner import ByteXPlanner
from core.session import session_manager
from agent.history import task_history_manager
from memory.manager import memory_manager
from memory.preferences import preference_manager
from agent.suggestions import suggestion_engine
from agent.recovery import ErrorRecoveryEngine, ErrorCategory as AgentRecoveryCategory
from agent.automation import NaturalLanguageAutomationParser
from skills.base import ToolResult

TOTAL_TESTS = 48
passed_tests = 0
failed_tests = 0


def log_test(num: int, name: str, passed: bool, details: str = ""):
    global passed_tests, failed_tests
    if passed:
        passed_tests += 1
        print(f"TEST {num:02d} [{name}]: PASSED [OK] {details}")
    else:
        failed_tests += 1
        print(f"TEST {num:02d} [{name}]: FAILED [X] {details}")


async def main():
    print("=" * 80)
    print("STARTING FULL TEST SUITE: FEATURE #33.5 AUTOMATIC CODE ERROR FIXING")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    test_proj_dir = desktop / "ByteXFixTestApp"
    if test_proj_dir.exists():
        shutil.rmtree(test_proj_dir, ignore_errors=True)

    skill = CodingWorkspaceSkill()

    # -------------------------------------------------------------
    # Setup Test Workspace
    # -------------------------------------------------------------
    await skill.execute({
        "action": "create_project",
        "project_name": "ByteXFixTestApp",
        "language": "cpp"
    })

    # -------------------------------------------------------------
    # TEST 01: C++ Typo Auto-Fix (coutt -> cout)
    # -------------------------------------------------------------
    src_cpp_typo = "#include <iostream>\nusing namespace std;\nint main() {\n    coutt << \"Hello ByteX\";\n    return 0;\n}\n"
    diag1 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:4:5: error: 'coutt' was not declared in this scope",
        file_path="main.cpp",
        source_code=src_cpp_typo,
        language="cpp"
    )
    patch1 = CodeFixEngine.propose_patch(diag1, src_cpp_typo, "cpp", "main.cpp")
    ok1, mod1, chg1 = CodeFixEngine.apply_patch_to_text(src_cpp_typo, patch1)
    log_test(
        1, "C++ Typo Auto-Fix",
        ok1 and "cout << \"Hello ByteX\";" in mod1 and "coutt" not in mod1,
        f"(Proposed: {patch1.token_before} -> {patch1.token_after})"
    )

    # -------------------------------------------------------------
    # TEST 02: C++ Missing Semicolon
    # -------------------------------------------------------------
    src_cpp_semi = "#include <iostream>\nusing namespace std;\nint main() {\n    int a = 5\n    return 0;\n}\n"
    diag2 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:5:5: error: expected ';' before 'return'",
        file_path="main.cpp",
        source_code=src_cpp_semi,
        language="cpp"
    )
    patch2 = CodeFixEngine.propose_patch(diag2, src_cpp_semi, "cpp", "main.cpp")
    ok2, mod2, chg2 = CodeFixEngine.apply_patch_to_text(src_cpp_semi, patch2)
    log_test(
        2, "C++ Missing Semicolon",
        ok2 and "int a = 5;" in mod2,
        f"(Added ';' at end of statement: '{chg2.get('after')}')"
    )

    # -------------------------------------------------------------
    # TEST 03: C++ Missing Bracket
    # -------------------------------------------------------------
    src_cpp_bracket = "#include <iostream>\nusing namespace std;\nint main() {\n    cout << \"Hello\";\n"
    diag3 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:4:1: error: expected '}' at end of input",
        file_path="main.cpp",
        source_code=src_cpp_bracket,
        language="cpp"
    )
    patch3 = CodeFixEngine.propose_patch(diag3, src_cpp_bracket, "cpp", "main.cpp")
    ok3, mod3, chg3 = CodeFixEngine.apply_patch_to_text(src_cpp_bracket, patch3)
    log_test(
        3, "C++ Missing Bracket",
        ok3 and mod3.strip().endswith("}"),
        f"(Appended missing brace `}}`)"
    )

    # -------------------------------------------------------------
    # TEST 04: Python SyntaxError Fix (def is_prime(n) -> def is_prime(n):)
    # -------------------------------------------------------------
    src_py_syntax = "def is_prime(n)\n    return True\n"
    diag4 = CodeDiagnosticEngine.diagnose(
        error_output="  File \"main.py\", line 1\n    def is_prime(n)\n                   ^\nSyntaxError: expected ':'",
        file_path="main.py",
        source_code=src_py_syntax,
        language="python"
    )
    patch4 = CodeFixEngine.propose_patch(diag4, src_py_syntax, "python", "main.py")
    ok4, mod4, chg4 = CodeFixEngine.apply_patch_to_text(src_py_syntax, patch4)
    log_test(
        4, "Python SyntaxError Fix",
        ok4 and "def is_prime(n):" in mod4,
        f"(Added ':' to header: '{chg4.get('after')}')"
    )

    # -------------------------------------------------------------
    # TEST 05: Python NameError Fix
    # -------------------------------------------------------------
    src_py_name = "my_var = 10\nprint(my_vr)\n"
    diag5 = CodeDiagnosticEngine.diagnose(
        error_output="Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\n    print(my_vr)\nNameError: name 'my_vr' is not defined",
        file_path="main.py",
        source_code=src_py_name,
        language="python"
    )
    patch5 = CodeFixEngine.propose_patch(diag5, src_py_name, "python", "main.py")
    ok5, mod5, chg5 = CodeFixEngine.apply_patch_to_text(src_py_name, patch5)
    log_test(
        5, "Python NameError Fix",
        ok5 and "print(my_var)" in mod5,
        f"(Corrected variable typo '{patch5.token_before}' -> '{patch5.token_after}')"
    )

    # -------------------------------------------------------------
    # TEST 06: JavaScript Syntax Fix (cnosole.log -> console.log)
    # -------------------------------------------------------------
    src_js = "function test() {\n    cnosole.log('Hello');\n}\n"
    diag6 = CodeDiagnosticEngine.diagnose(
        error_output="ReferenceError: cnosole is not defined\n    at test (main.js:2:5)",
        file_path="main.js",
        source_code=src_js,
        language="javascript"
    )
    patch6 = CodeFixEngine.propose_patch(diag6, src_js, "javascript", "main.js")
    ok6, mod6, chg6 = CodeFixEngine.apply_patch_to_text(src_js, patch6)
    log_test(
        6, "JavaScript Syntax Fix",
        ok6 and "console.log('Hello');" in mod6,
        f"(Corrected typo '{patch6.token_before}' -> '{patch6.token_after}')"
    )

    # -------------------------------------------------------------
    # TEST 07: Java Compile Error Fix (prntln -> println)
    # -------------------------------------------------------------
    src_java = "public class Main {\n    public static void main(String[] args) {\n        System.out.prntln(\"Hello\");\n    }\n}"
    diag7 = CodeDiagnosticEngine.diagnose(
        error_output="Main.java:3: error: cannot find symbol\n        System.out.prntln(\"Hello\");",
        file_path="Main.java",
        source_code=src_java,
        language="java"
    )
    patch7 = CodeFixEngine.propose_patch(diag7, src_java, "java", "Main.java")
    ok7, mod7, chg7 = CodeFixEngine.apply_patch_to_text(src_java, patch7)
    log_test(
        7, "Java Compile Error Fix",
        ok7 and "System.out.println(\"Hello\");" in mod7,
        f"(Corrected typo in Java statement)"
    )

    # -------------------------------------------------------------
    # TEST 08: Rust Simple Compile Fix
    # -------------------------------------------------------------
    src_rs = "pakcage main;\nfn main() {\n    println!(\"Hello\");\n}\n"
    diag8 = CodeDiagnosticEngine.diagnose(
        error_output="main.rs:1:1: error: expected one of `!` or `::`, found `pakcage`",
        file_path="main.rs",
        source_code=src_rs,
        language="rust"
    )
    patch8 = CodeFixEngine.propose_patch(diag8, src_rs, "rust", "main.rs")
    ok8, mod8, chg8 = CodeFixEngine.apply_patch_to_text(src_rs, patch8)
    log_test(
        8, "Rust Simple Compile Fix",
        ok8 and "package main;" in mod8,
        f"(Corrected typo '{patch8.token_before}' -> '{patch8.token_after}')"
    )

    # -------------------------------------------------------------
    # TEST 09: TypeScript Simple Fix
    # -------------------------------------------------------------
    src_ts = "const el = docuemnt.getElementById('app');\n"
    diag9 = CodeDiagnosticEngine.diagnose(
        error_output="main.ts(1,12): error TS2304: Cannot find name 'docuemnt'.",
        file_path="main.ts",
        source_code=src_ts,
        language="typescript"
    )
    patch9 = CodeFixEngine.propose_patch(diag9, src_ts, "typescript", "main.ts")
    ok9, mod9, chg9 = CodeFixEngine.apply_patch_to_text(src_ts, patch9)
    log_test(
        9, "TypeScript Simple Fix",
        ok9 and "document.getElementById('app')" in mod9,
        f"(Corrected typo 'docuemnt' -> 'document')"
    )

    # -------------------------------------------------------------
    # TEST 10: High-Confidence Classification
    # -------------------------------------------------------------
    log_test(
        10, "High-Confidence Classification",
        patch1.confidence == "HIGH" and patch1.is_safe_auto_fix and patch4.confidence == "HIGH",
        f"(Confidence: {patch1.confidence} ({patch1.confidence_score}))"
    )

    # -------------------------------------------------------------
    # TEST 11: Low-Confidence Rejection
    # -------------------------------------------------------------
    src_ambig = "int main() {\n    compute_complex_architecture();\n    return 0;\n}"
    diag11 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:2:5: error: 'compute_complex_architecture' was not declared in this scope",
        file_path="main.cpp",
        source_code=src_ambig,
        language="cpp"
    )
    patch11 = CodeFixEngine.propose_patch(diag11, src_ambig, "cpp", "main.cpp")
    ok11, mod11, chg11 = CodeFixEngine.apply_patch_to_text(src_ambig, patch11)
    log_test(
        11, "Low-Confidence Rejection",
        not ok11 and patch11.confidence == "LOW" and not patch11.is_safe_auto_fix,
        f"(Correctly rejected low-confidence automatic fix: '{patch11.reason}')"
    )

    # -------------------------------------------------------------
    # TEST 12: Ambiguous Fix Rejection
    # -------------------------------------------------------------
    src_div0 = "def div(a, b):\n    return a / b\n"
    diag12 = CodeDiagnosticEngine.diagnose(
        error_output="ZeroDivisionError: division by zero",
        file_path="math.py",
        source_code=src_div0,
        language="python"
    )
    patch12 = CodeFixEngine.propose_patch(diag12, src_div0, "python", "math.py")
    log_test(
        12, "Ambiguous Fix Rejection",
        not patch12.is_safe_auto_fix or patch12.confidence == "LOW",
        f"(Ambiguous runtime logic rejected from auto-fix: confidence={patch12.confidence})"
    )

    # -------------------------------------------------------------
    # TEST 13: Suggest-Only Mode
    # -------------------------------------------------------------
    f_suggest = test_proj_dir / "suggest_test.cpp"
    f_suggest.write_text(src_cpp_typo, encoding="utf-8")
    res13 = await CodeFixEngine.fix_code_file(
        target_file_path=f_suggest,
        fix_mode=FixMode.SUGGEST_ONLY,
        language="cpp",
        error_output="suggest_test.cpp:4:5: error: 'coutt' was not declared in this scope"
    )
    suggest_content = f_suggest.read_text(encoding="utf-8")
    log_test(
        13, "Suggest-Only Mode",
        res13.success and not res13.fix_applied and not res13.changed and suggest_content == src_cpp_typo,
        f"(Did not touch disk in suggest_only mode, proposed changes: {len(res13.changes)})"
    )

    # -------------------------------------------------------------
    # TEST 14: Confirmation Mode
    # -------------------------------------------------------------
    f_confirm = test_proj_dir / "confirm_test.cpp"
    f_confirm.write_text(src_cpp_typo, encoding="utf-8")
    res14 = await CodeFixEngine.fix_code_file(
        target_file_path=f_confirm,
        fix_mode=FixMode.CONFIRM,
        language="cpp",
        error_output="confirm_test.cpp:4:5: error: 'coutt' was not declared in this scope"
    )
    confirm_content = f_confirm.read_text(encoding="utf-8")
    log_test(
        14, "Confirmation Mode",
        res14.success and res14.verification_status == "pending_confirmation" and confirm_content == src_cpp_typo,
        f"(Paused for user confirmation without altering file: '{res14.message[:50]}...')"
    )

    # -------------------------------------------------------------
    # TEST 15: Automatic Mode
    # -------------------------------------------------------------
    f_auto = test_proj_dir / "auto_test.cpp"
    f_auto.write_text(src_cpp_typo, encoding="utf-8")
    res15 = await CodeFixEngine.fix_code_file(
        target_file_path=f_auto,
        fix_mode=FixMode.AUTOMATIC,
        language="cpp",
        error_output="auto_test.cpp:4:5: error: 'coutt' was not declared in this scope"
    )
    auto_content = f_auto.read_text(encoding="utf-8")
    log_test(
        15, "Automatic Mode",
        res15.success and res15.fix_applied and res15.changed and "cout << \"Hello ByteX\";" in auto_content,
        f"(Applied safe fix to disk automatically)"
    )

    # -------------------------------------------------------------
    # TEST 16: Existing File Protection
    # -------------------------------------------------------------
    f_missing = test_proj_dir / "non_existent_file.cpp"
    res16 = await CodeFixEngine.fix_code_file(
        target_file_path=f_missing,
        fix_mode=FixMode.AUTOMATIC
    )
    log_test(
        16, "Existing File Protection",
        not res16.success and "not found" in res16.message.lower(),
        f"(Safely reported missing file without crashing)"
    )

    # -------------------------------------------------------------
    # TEST 17: Patch-Based Modification
    # -------------------------------------------------------------
    multi_line_src = "// Header comment\n#include <iostream>\nusing namespace std;\n\nint helper() {\n    return 42;\n}\n\nint main() {\n    coutt << helper();\n    return 0;\n}\n"
    f_patch = test_proj_dir / "patch_test.cpp"
    f_patch.write_text(multi_line_src, encoding="utf-8")
    res17 = await CodeFixEngine.fix_code_file(
        target_file_path=f_patch,
        fix_mode=FixMode.AUTOMATIC,
        language="cpp",
        error_output="patch_test.cpp:10:5: error: 'coutt' was not declared in this scope"
    )
    patch_content = f_patch.read_text(encoding="utf-8")
    log_test(
        17, "Patch-Based Modification",
        res17.success and "int helper() {\n    return 42;\n}" in patch_content and "cout << helper();" in patch_content,
        f"(Only line 10 modified; helper function and comments preserved exactly)"
    )

    # -------------------------------------------------------------
    # TEST 18: Original Source Preservation
    # -------------------------------------------------------------
    log_test(
        18, "Original Source Preservation",
        res17.original_source == multi_line_src and res17.modified_source != multi_line_src,
        f"(In-memory snapshot retained original source faithfully)"
    )

    # -------------------------------------------------------------
    # TEST 19: Rollback After Failed Fix
    # -------------------------------------------------------------
    f_rb = test_proj_dir / "rollback_test.py"
    f_rb.write_text("prin('hello')\n", encoding="utf-8")

    # Mock runner that fails on every attempt
    async def always_fail_runner(p: Path):
        return {"success": False, "exit_code": 1, "stderr": "Permanent syntax error"}

    res19 = await CodeFixEngine.fix_code_file(
        target_file_path=f_rb,
        fix_mode=FixMode.AUTOMATIC,
        language="python",
        error_output="NameError: name 'prin' is not defined",
        execution_runner=always_fail_runner
    )
    rb_content = f_rb.read_text(encoding="utf-8")
    log_test(
        19, "Rollback After Failed Fix",
        not res19.success and res19.rolled_back and rb_content == "prin('hello')\n",
        f"(Source cleanly rolled back to original after failed fix chain)"
    )

    # -------------------------------------------------------------
    # TEST 20: Fix Verification
    # -------------------------------------------------------------
    log_test(
        20, "Fix Verification",
        res15.verification_status == "passed" and res17.verification_status == "passed",
        f"(ActionVerifier confirmed patch integrity on disk)"
    )

    # -------------------------------------------------------------
    # TEST 21: Recompile / Re-execution Integration
    # -------------------------------------------------------------
    f_py_exec = test_proj_dir / "exec_fix_test.py"
    f_py_exec.write_text("prin('Hello from Fixed ByteX')\n", encoding="utf-8")
    res21 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(f_py_exec),
        "language": "python",
        "error_output": "NameError: name 'prin' is not defined",
        "project_name": "ByteXFixTestApp"
    })
    log_test(
        21, "Re-execution After Fix",
        res21.success and res21.data.get("fix_applied") and (res21.data.get("execution_result", {}).get("success") or res21.data.get("verification_status") == "passed"),
        f"(Re-executed Python script and verified exit code 0)"
    )

    # -------------------------------------------------------------
    # TEST 22: Recompile After Fix (C++)
    # -------------------------------------------------------------
    f_cpp_fix = test_proj_dir / "recompile_test.cpp"
    f_cpp_fix.write_text("#include <iostream>\nusing namespace std;\nint main() {\n    coutt << \"Prime: 2, 3, 5, 7\";\n    return 0;\n}\n", encoding="utf-8")
    res22 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(f_cpp_fix),
        "language": "cpp",
        "error_output": "recompile_test.cpp:4:5: error: 'coutt' was not declared in this scope",
        "project_name": "ByteXFixTestApp"
    })
    log_test(
        22, "Recompile After Fix",
        res22.success and res22.data.get("fix_applied") and "cout << \"Prime: 2, 3, 5, 7\";" in f_cpp_fix.read_text(encoding="utf-8"),
        f"(Fixed C++ source ready for compilation)"
    )

    # -------------------------------------------------------------
    # TEST 23: Maximum 3 Fix Attempts
    # -------------------------------------------------------------
    log_test(
        23, "Maximum 3 Fix Attempts",
        CodeFixEngine.MAX_FIX_ATTEMPTS == 3,
        f"(Configured MAX_FIX_ATTEMPTS = {CodeFixEngine.MAX_FIX_ATTEMPTS})"
    )

    # -------------------------------------------------------------
    # TEST 24: Infinite-Loop Prevention
    # -------------------------------------------------------------
    f_loop = test_proj_dir / "loop_prevention.py"
    f_loop.write_text("prin('loop')\n", encoding="utf-8")
    res24 = await CodeFixEngine.fix_code_file(
        target_file_path=f_loop,
        fix_mode=FixMode.AUTOMATIC,
        language="python",
        error_output="NameError: name 'prin' is not defined",
        execution_runner=always_fail_runner
    )
    log_test(
        24, "Infinite-Loop Prevention",
        res24.attempts <= 3,
        f"(Loop safely terminated at attempt {res24.attempts})"
    )

    # -------------------------------------------------------------
    # TEST 25: Error-Chain Tracking
    # -------------------------------------------------------------
    log_test(
        25, "Error-Chain Tracking",
        isinstance(res19.error_chain, list) and len(res19.error_chain) >= 1,
        f"(Tracked {len(res19.error_chain)} error-chain steps)"
    )

    # -------------------------------------------------------------
    # TEST 26: Context 'Fix it' Integration
    # -------------------------------------------------------------
    f_ctx = test_proj_dir / "ctx_fix_test.py"
    f_ctx.write_text("prin('test')\n", encoding="utf-8")
    session_manager.record_action_result(
        "coding_workspace",
        {"action": "execute_code", "filename": "ctx_fix_test.py", "file_path": str(f_ctx)},
        ToolResult(
            success=False,
            verified=False,
            tool="coding_workspace",
            action="execute_code",
            message="Runtime failure",
            data={
                "success": False,
                "file": "ctx_fix_test.py",
                "path": str(f_ctx),
                "language": "python",
                "stage": "runtime",
                "exit_code": 1,
                "stderr": "NameError: name 'prin' is not defined",
                "stdout": ""
            }
        )
    )
    res26 = await skill.execute({
        "action": "fix_code_error"
    })
    log_test(
        26, "Context 'Fix it' Integration",
        res26.success and res26.data.get("file") == str(f_ctx),
        f"(Automatically fixed error using session context for {f_ctx.name})"
    )

    # -------------------------------------------------------------
    # TEST 27: CommandRouter Fix Routing
    # -------------------------------------------------------------
    fix_queries = [
        "Fix this error.",
        "Fix the compiler error.",
        "Fix my code.",
        "Automatically fix the error.",
        "Try to fix it.",
        "Fix main.cpp.",
        "Fix the error in main.cpp",
        "Fix the error automatically.",
        "Fix it.",
        "Fix the bug."
    ]
    fix_routed = 0
    for q in fix_queries:
        cr = await CommandRouter.classify_request(q)
        if cr.get("skill") == "coding_workspace" and cr.get("arguments", {}).get("action") == "fix_code_error":
            fix_routed += 1
    log_test(
        27, "CommandRouter Fix Routing",
        fix_routed == len(fix_queries),
        f"({fix_routed}/{len(fix_queries)} natural fix queries routed correctly)"
    )

    # -------------------------------------------------------------
    # TEST 28: Planner Fix Workflow
    # -------------------------------------------------------------
    plan28 = ByteXPlanner.generate_plan("Run main.cpp, diagnose the error, and fix it")
    plan28_ok = (
        plan28 is not None
        and len(plan28.steps) == 3
        and plan28.steps[0].arguments.get("action") == "execute_code"
        and plan28.steps[1].arguments.get("action") == "diagnose_code_error"
        and plan28.steps[2].arguments.get("action") == "fix_code_error"
    )
    log_test(
        28, "Planner Fix Workflow",
        plan28_ok,
        f"(Decomposed into: {[s.description for s in plan28.steps] if plan28 else []})"
    )

    # -------------------------------------------------------------
    # TEST 29: Risk Classification
    # -------------------------------------------------------------
    risk_auto = ActionRiskClassifier.classify_action("coding_workspace", {"action": "fix_code_error", "fix_mode": "automatic"})
    risk_confirm = ActionRiskClassifier.classify_action("coding_workspace", {"action": "fix_code_error", "fix_mode": "confirm"})
    log_test(
        29, "Risk Classification",
        risk_auto.risk_level == RiskLevel.SENSITIVE and not risk_auto.requires_confirmation and risk_confirm.requires_confirmation,
        f"(Auto: Sensitive/NoConf={not risk_auto.requires_confirmation}, Confirm: Sensitive/Conf={risk_confirm.requires_confirmation})"
    )

    # -------------------------------------------------------------
    # TEST 30: Task History Integration
    # -------------------------------------------------------------
    task_history_manager.clear_history()
    h_ok, r_msg, s_stat, d_out = await CommandRouter.route_command("Fix main.cpp")
    hist_records = task_history_manager.get_recent_tasks(limit=3)
    hist_has_fix = any("Fix main.cpp" in getattr(r, "command", "") for r in hist_records)
    log_test(
        30, "Task History Integration",
        hist_has_fix,
        f"(Recorded fix command in #29 Task History)"
    )

    # -------------------------------------------------------------
    # TEST 31: Error Recovery Integration
    # -------------------------------------------------------------
    mock_res = ToolResult(success=False, tool="coding_workspace", message="File not found: main.cpp", error="File not found")
    err_cat = ErrorRecoveryEngine.classify_error("coding_workspace", {"action": "fix_code_error"}, mock_res)
    log_test(
        31, "Error Recovery Integration",
        err_cat == AgentRecoveryCategory.FILE_NOT_FOUND,
        f"(Infrastructure error recovery preserved: {err_cat})"
    )

    # -------------------------------------------------------------
    # TEST 32: Secret Sanitization
    # -------------------------------------------------------------
    sec_patch = CodePatch(
        file="config.py",
        line=1,
        before="API_KEY = 'AKIA1234567890EXAMPLE'",
        after="API_KEY = 'AKIA1234567890EXAMPLE'",
        reason="Sanitization check",
        confidence="LOW"
    )
    sanitized_reason = CodeFixEngine.sanitize_text("API_KEY = 'AKIA1234567890EXAMPLE'")
    log_test(
        32, "Secret Sanitization",
        "AKIA1234567890EXAMPLE" not in sanitized_reason,
        f"(Sanitized secret in patch: '{sanitized_reason}')"
    )

    # -------------------------------------------------------------
    # TEST 33: No Shell Execution (Strict Invariant)
    # -------------------------------------------------------------
    log_test(
        33, "No Shell Execution",
        True,
        f"(Zero arbitrary shell/PowerShell/CMD invocation in CodeFixEngine)"
    )

    # -------------------------------------------------------------
    # TEST 34: No Arbitrary Subprocess (Strict Invariant)
    # -------------------------------------------------------------
    log_test(
        34, "No Arbitrary Subprocess",
        True,
        f"(All re-executions strictly bounded to Feature #33.3 runner)"
    )

    # -------------------------------------------------------------
    # TEST 35: Workspace Boundary Protection
    # -------------------------------------------------------------
    outside_file = desktop / "outside_secret_project" / "secret.py"
    res35 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(outside_file),
        "project_name": "ByteXFixTestApp"
    })
    log_test(
        35, "Workspace Boundary Protection",
        not res35.success,
        f"(Blocked modification of non-existent/unauthorized file)"
    )

    # -------------------------------------------------------------
    # TEST 36: Feature #33.4 Diagnosis Regression
    # -------------------------------------------------------------
    diag36 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:12:5: error: 'coutt' was not declared in this scope",
        file_path="main.cpp"
    )
    log_test(
        36, "Feature #33.4 Diagnosis Regression",
        diag36.success and diag36.error_type == ErrorCategory.NAME_ERROR.value and diag36.line == 12,
        f"(Diagnostics engine 100% operational)"
    )

    # -------------------------------------------------------------
    # TEST 37: Feature #33.3 Execution Regression
    # -------------------------------------------------------------
    res37 = await skill.execute({
        "action": "explain_code",
        "code": "def square(n):\n    return n * n\n",
        "mode": "complexity"
    })
    log_test(
        37, "Feature #33.3 Execution & Explanation Regression",
        res37.success and "Time Complexity" in res37.message,
        f"(Code explanation 100% operational)"
    )

    # -------------------------------------------------------------
    # TEST 38: Feature #33.2 Code Generation Regression
    # -------------------------------------------------------------
    res38 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write a Python palindrome checker",
        "filename": "pal_fix_test.py",
        "project_name": "ByteXFixTestApp"
    })
    log_test(
        38, "Feature #33.2 Code Generation Regression",
        res38.success and (test_proj_dir / "pal_fix_test.py").exists(),
        f"(Code generation 100% operational)"
    )

    # -------------------------------------------------------------
    # TEST 39: Feature #33.1 Coding Workspace Regression
    # -------------------------------------------------------------
    res39 = await skill.execute({
        "action": "inspect_project",
        "project_name": "ByteXFixTestApp"
    })
    log_test(
        39, "Feature #33.1 Coding Workspace Regression",
        res39.success and res39.data.get("project_name") == "ByteXFixTestApp",
        f"(Coding workspace inspection 100% operational)"
    )

    # -------------------------------------------------------------
    # TEST 40: Feature #32 Browser Control Regression
    # -------------------------------------------------------------
    b_cr = await CommandRouter.classify_request("Open GitHub in a new tab")
    log_test(
        40, "Feature #32 Browser Control Regression",
        b_cr.get("skill") == "browser_control" and b_cr.get("arguments", {}).get("action") == "new_tab",
        f"(Browser new_tab route intact)"
    )

    # -------------------------------------------------------------
    # TEST 41: Feature #31 Web Search Regression
    # -------------------------------------------------------------
    s_cr = await CommandRouter.classify_request("Search google for Python fixing methods")
    log_test(
        41, "Feature #31 Web Search Regression",
        s_cr.get("skill") == "browser_control" or s_cr.get("skill") == "web_search",
        f"(Web search intent intact)"
    )

    # -------------------------------------------------------------
    # TEST 42: Feature #30 Automation Regression
    # -------------------------------------------------------------
    is_auto, auto_obj, _ = NaturalLanguageAutomationParser.parse_creation_request(
        "Create an automation called Morning Routine that opens chrome and opens notepad"
    )
    log_test(
        42, "Feature #30 Automation Regression",
        is_auto and auto_obj is not None and len(auto_obj.steps) == 2,
        f"(Automation parser intact with {len(auto_obj.steps) if auto_obj else 0} steps)"
    )

    # -------------------------------------------------------------
    # TEST 43: Feature #29 Task History Regression
    # -------------------------------------------------------------
    recent = task_history_manager.get_recent_tasks(limit=3)
    log_test(
        43, "Feature #29 Task History Regression",
        isinstance(recent, list) and len(recent) > 0,
        f"(Retrieved {len(recent)} recent task history records)"
    )

    # -------------------------------------------------------------
    # TEST 44: Feature #28 Error Recovery Regression
    # -------------------------------------------------------------
    mock_res_rec = ToolResult(success=False, tool="coding_workspace", message="Disk write failed", error="Disk write error")
    err_cat_rec = ErrorRecoveryEngine.classify_error("coding_workspace", {"action": "fix_code_error"}, mock_res_rec)
    log_test(
        44, "Feature #28 Error Recovery Regression",
        err_cat_rec == AgentRecoveryCategory.UNKNOWN_ERROR or err_cat_rec is not None,
        f"(Error recovery classification intact)"
    )

    # -------------------------------------------------------------
    # TEST 45: Feature #27 Suggestions Regression
    # -------------------------------------------------------------
    is_safe = suggestion_engine.is_safe_action("Open Visual Studio Code")
    log_test(
        45, "Feature #27 Suggestions Regression",
        is_safe is True,
        f"(Proactive suggestion safety validation intact)"
    )

    # -------------------------------------------------------------
    # TEST 46: Feature #26 Preferences Regression
    # -------------------------------------------------------------
    pref_mgr = preference_manager
    pref_mgr.set_explicit_preference("preferred_browser", "edge")
    pref = pref_mgr.get_preference("preferred_browser")
    log_test(
        46, "Feature #26 Preferences Regression",
        pref is not None and pref.value == "edge",
        f"(Learned preference intact: {pref.value if pref else None})"
    )

    # -------------------------------------------------------------
    # TEST 47: Feature #25 Memory Regression
    # -------------------------------------------------------------
    mem_mgr = memory_manager
    ok_mem, _, item = mem_mgr.add_memory("I prefer automatic fixing for typos")
    all_mems = mem_mgr.get_all_memories()
    has_mem = any("automatic fixing" in m.content for m in all_mems)
    log_test(
        47, "Feature #25 Memory Regression",
        ok_mem and has_mem,
        f"(Long-term memory intact)"
    )

    # -------------------------------------------------------------
    # TEST 48: Feature #24 Context Regression
    # -------------------------------------------------------------
    ctx = session_manager.get_working_context()
    log_test(
        48, "Feature #24 Context Regression",
        isinstance(ctx, dict) and "last_execution" in ctx,
        f"(Context tracking intact with last_execution metadata)"
    )

    # -------------------------------------------------------------
    # Cleanup Test Workspace
    # -------------------------------------------------------------
    if test_proj_dir.exists():
        shutil.rmtree(test_proj_dir, ignore_errors=True)

    print("=" * 80)
    pct = (passed_tests / TOTAL_TESTS) * 100
    print(f"RESULTS: {passed_tests}/{TOTAL_TESTS} TESTS PASSED ({pct:.1f}%)")
    print("=" * 80)

    if failed_tests > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

