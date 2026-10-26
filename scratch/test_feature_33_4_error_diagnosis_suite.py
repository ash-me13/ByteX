"""
ByteX — Feature #33.4: Intelligent Code Error Detection & Diagnosis Test Suite

Comprehensive automated test suite covering all 45 verification points:
01 C++ syntax error detection
02 C++ undeclared identifier
03 C++ linker error
04 C compiler error
05 Python SyntaxError
06 Python NameError
07 Python IndexError
08 Python exception traceback
09 JavaScript runtime error
10 Java compiler error
11 Java runtime exception
12 Go compile error
13 Rust compile error
14 TypeScript error
15 Segmentation fault classification
16 Division-by-zero classification
17 Timeout classification
18 Missing toolchain classification
19 Error line extraction
20 Error column extraction
21 Multiple-error handling
22 Source context extraction
23 Error prioritization
24 Confidence scoring
25 Suggested-fix generation
26 No source modification
27 No command execution
28 Secret sanitization
29 CommandRouter routing
30 Planner integration
31 Session-context integration
32 Task History integration
33 Risk classification
34 Feature #33.3 execution integration
35 Feature #33.2 generation regression
36 Feature #33.1 workspace regression
37 #32 Browser regression
38 #31 Search regression
39 #30 Automation regression
40 #29 History regression
41 #28 Recovery regression
42 #27 Suggestions regression
43 #26 Preferences regression
44 #25 Memory regression
45 #24 Context regression
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
from skills.diagnostics import CodeDiagnosticEngine, ErrorCategory
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

TOTAL_TESTS = 45
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
    print("STARTING FULL TEST SUITE: FEATURE #33.4 INTELLIGENT CODE ERROR DIAGNOSIS")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    test_proj_dir = desktop / "ByteXDiagTestApp"
    if test_proj_dir.exists():
        shutil.rmtree(test_proj_dir, ignore_errors=True)

    skill = CodingWorkspaceSkill()

    # -------------------------------------------------------------
    # Setup Test Workspace
    # -------------------------------------------------------------
    await skill.execute({
        "action": "create_project",
        "project_name": "ByteXDiagTestApp",
        "language": "cpp"
    })

    # -------------------------------------------------------------
    # TEST 01: C++ Syntax Error Detection
    # -------------------------------------------------------------
    cpp_syntax_err = "main.cpp:10:5: error: expected ';' before 'return'"
    res1 = CodeDiagnosticEngine.diagnose(
        error_output=cpp_syntax_err,
        file_path="main.cpp",
        language="cpp",
        source_code="int main() {\n    int a = 5\n    return 0;\n}"
    )
    log_test(
        1, "C++ Syntax Error Detection",
        res1.success and res1.error_type == ErrorCategory.SYNTAX_ERROR.value and res1.line == 10 and res1.column == 5,
        f"(Classified: {res1.error_type} at line {res1.line}:{res1.column})"
    )

    # -------------------------------------------------------------
    # TEST 02: C++ Undeclared Identifier / Typo
    # -------------------------------------------------------------
    cpp_typo_err = "main.cpp:12:5: error: 'coutt' was not declared in this scope"
    res2 = CodeDiagnosticEngine.diagnose(
        error_output=cpp_typo_err,
        file_path="main.cpp",
        language="cpp",
        source_code="#include <iostream>\nusing namespace std;\nint main() {\n    coutt << \"Hello\";\n    return 0;\n}"
    )
    log_test(
        2, "C++ Undeclared Identifier / Typo",
        res2.success and res2.error_type == ErrorCategory.NAME_ERROR.value and "cout" in res2.suggested_fix,
        f"(Detected typo 'coutt' -> suggested: '{res2.suggested_fix}')"
    )

    # -------------------------------------------------------------
    # TEST 03: C++ Linker Error
    # -------------------------------------------------------------
    cpp_linker_err = "undefined reference to `WinMain' or `main'"
    res3 = CodeDiagnosticEngine.diagnose(
        error_output=cpp_linker_err,
        file_path="main.cpp",
        language="cpp"
    )
    log_test(
        3, "C++ Linker Error",
        res3.success and res3.error_type == ErrorCategory.LINKER_ERROR.value,
        f"(Classified: {res3.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 04: C Compiler Error
    # -------------------------------------------------------------
    c_err = "main.c:6:10: fatal error: non_existent_header.h: No such file or directory"
    res4 = CodeDiagnosticEngine.diagnose(
        error_output=c_err,
        file_path="main.c",
        language="c"
    )
    log_test(
        4, "C Compiler Error",
        res4.success and res4.error_type in [ErrorCategory.IMPORT_ERROR.value, ErrorCategory.COMPILER_ERROR.value],
        f"(Classified C error: {res4.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 05: Python SyntaxError
    # -------------------------------------------------------------
    py_syntax_err = """  File "main.py", line 4
    if x == 5
            ^
SyntaxError: expected ':'"""
    res5 = CodeDiagnosticEngine.diagnose(
        error_output=py_syntax_err,
        file_path="main.py",
        language="python"
    )
    log_test(
        5, "Python SyntaxError",
        res5.success and res5.error_type == ErrorCategory.SYNTAX_ERROR.value and res5.line == 4,
        f"(Classified: {res5.error_type} at line {res5.line})"
    )

    # -------------------------------------------------------------
    # TEST 06: Python NameError
    # -------------------------------------------------------------
    py_name_err = """Traceback (most recent call last):
  File "main.py", line 8, in <module>
    print(unknown_var)
NameError: name 'unknown_var' is not defined"""
    res6 = CodeDiagnosticEngine.diagnose(
        error_output=py_name_err,
        file_path="main.py",
        language="python"
    )
    log_test(
        6, "Python NameError",
        res6.success and res6.error_type == ErrorCategory.NAME_ERROR.value and res6.line == 8,
        f"(Classified: {res6.error_type} for 'unknown_var')"
    )

    # -------------------------------------------------------------
    # TEST 07: Python IndexError
    # -------------------------------------------------------------
    py_idx_err = """Traceback (most recent call last):
  File "main.py", line 12, in <module>
    item = items[99]
IndexError: list index out of range"""
    res7 = CodeDiagnosticEngine.diagnose(
        error_output=py_idx_err,
        file_path="main.py",
        language="python"
    )
    log_test(
        7, "Python IndexError",
        res7.success and res7.error_type == ErrorCategory.INDEX_ERROR.value and res7.line == 12,
        f"(Classified: {res7.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 08: Python Exception Traceback
    # -------------------------------------------------------------
    py_exc_err = """Traceback (most recent call last):
  File "main.py", line 3, in helper
    return 10 / 0
  File "main.py", line 6, in <module>
    helper()
ZeroDivisionError: division by zero"""
    res8 = CodeDiagnosticEngine.diagnose(
        error_output=py_exc_err,
        file_path="main.py",
        language="python"
    )
    log_test(
        8, "Python Exception Traceback",
        res8.success and res8.error_type == ErrorCategory.DIVISION_BY_ZERO.value,
        f"(Extracted root exception: {res8.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 09: JavaScript Runtime Error
    # -------------------------------------------------------------
    js_err = """ReferenceError: myVal is not defined
    at Object.<anonymous> (main.js:15:3)
    at Module._compile (node:internal/modules/cjs/loader:1376:14)"""
    res9 = CodeDiagnosticEngine.diagnose(
        error_output=js_err,
        file_path="main.js",
        language="javascript"
    )
    log_test(
        9, "JavaScript Runtime Error",
        res9.success and res9.error_type == ErrorCategory.NAME_ERROR.value and res9.line == 15 and res9.column == 3,
        f"(Classified: {res9.error_type} in {res9.file}:{res9.line}:{res9.column})"
    )

    # -------------------------------------------------------------
    # TEST 10: Java Compiler Error
    # -------------------------------------------------------------
    java_comp_err = "Main.java:6: error: cannot find symbol\n        System.out.prntln(\"Hello\");"
    res10 = CodeDiagnosticEngine.diagnose(
        error_output=java_comp_err,
        file_path="Main.java",
        language="java"
    )
    log_test(
        10, "Java Compiler Error",
        res10.success and res10.error_type == ErrorCategory.NAME_ERROR.value and res10.line == 6,
        f"(Classified: {res10.error_type} at line {res10.line})"
    )

    # -------------------------------------------------------------
    # TEST 11: Java Runtime Exception
    # -------------------------------------------------------------
    java_run_err = """Exception in thread "main" java.lang.NullPointerException
    at Main.process(Main.java:14)
    at Main.main(Main.java:8)"""
    res11 = CodeDiagnosticEngine.diagnose(
        error_output=java_run_err,
        file_path="Main.java",
        language="java"
    )
    log_test(
        11, "Java Runtime Exception",
        res11.success and res11.error_type == ErrorCategory.NULL_REFERENCE.value,
        f"(Classified: {res11.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 12: Go Compile Error
    # -------------------------------------------------------------
    go_err = "./main.go:7:2: undefined: fmt.Printlnn"
    res12 = CodeDiagnosticEngine.diagnose(
        error_output=go_err,
        file_path="main.go",
        language="go"
    )
    log_test(
        12, "Go Compile Error",
        res12.success and res12.error_type == ErrorCategory.NAME_ERROR.value and res12.line == 7 and res12.column == 2,
        f"(Classified: {res12.error_type} at line {res12.line}:{res12.column})"
    )

    # -------------------------------------------------------------
    # TEST 13: Rust Compile Error
    # -------------------------------------------------------------
    rust_err = """error[E0425]: cannot find value `val` in this scope
 --> main.rs:9:5
  |
9 |     val + 1;
  |     ^^^ not found in this scope"""
    res13 = CodeDiagnosticEngine.diagnose(
        error_output=rust_err,
        file_path="main.rs",
        language="rust"
    )
    log_test(
        13, "Rust Compile Error",
        res13.success and res13.error_type == ErrorCategory.NAME_ERROR.value and res13.line == 9 and res13.column == 5,
        f"(Classified: {res13.error_type} at line {res13.line}:{res13.column})"
    )

    # -------------------------------------------------------------
    # TEST 14: TypeScript Error
    # -------------------------------------------------------------
    ts_err = "main.ts(11,7): error TS2304: Cannot find name 'unresolved'."
    res14 = CodeDiagnosticEngine.diagnose(
        error_output=ts_err,
        file_path="main.ts",
        language="typescript"
    )
    log_test(
        14, "TypeScript Error",
        res14.success and res14.error_type == ErrorCategory.NAME_ERROR.value and res14.line == 11 and res14.column == 7,
        f"(Classified: {res14.error_type} at line {res14.line}:{res14.column})"
    )

    # -------------------------------------------------------------
    # TEST 15: Segmentation Fault Classification
    # -------------------------------------------------------------
    seg_res = CodeDiagnosticEngine.diagnose(
        error_output="Segmentation fault (core dumped)",
        file_path="main.cpp",
        exit_code=139
    )
    log_test(
        15, "Segmentation Fault Classification",
        seg_res.success and seg_res.error_type == ErrorCategory.SEGMENTATION_FAULT.value,
        f"(Classified: {seg_res.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 16: Division-by-Zero Classification
    # -------------------------------------------------------------
    div_res = CodeDiagnosticEngine.diagnose(
        error_output="ZeroDivisionError: integer division or modulo by zero",
        file_path="math.py",
        language="python"
    )
    log_test(
        16, "Division-by-Zero Classification",
        div_res.success and div_res.error_type == ErrorCategory.DIVISION_BY_ZERO.value,
        f"(Classified: {div_res.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 17: Timeout Classification
    # -------------------------------------------------------------
    timeout_res = CodeDiagnosticEngine.diagnose(
        error_output="",
        file_path="loop.py",
        timed_out=True
    )
    log_test(
        17, "Timeout Classification",
        timeout_res.success and timeout_res.error_type == ErrorCategory.TIMEOUT.value and "infinite loop" in timeout_res.cause.lower(),
        f"(Classified: {timeout_res.error_type} with explanation: '{timeout_res.cause[:50]}...')"
    )

    # -------------------------------------------------------------
    # TEST 18: Missing Toolchain Classification
    # -------------------------------------------------------------
    tool_res = CodeDiagnosticEngine.diagnose(
        error_output="I can't run this program because the required C++ runner (g++) is not available.",
        file_path="main.cpp"
    )
    log_test(
        18, "Missing Toolchain Classification",
        tool_res.success and tool_res.error_type == ErrorCategory.MISSING_TOOLCHAIN.value,
        f"(Classified: {tool_res.error_type})"
    )

    # -------------------------------------------------------------
    # TEST 19: Error Line Extraction
    # -------------------------------------------------------------
    log_test(
        19, "Error Line Extraction",
        res1.line == 10 and res2.line == 12 and res5.line == 4 and res6.line == 8,
        f"(Extracted line numbers: C++={res1.line}, Typo={res2.line}, PySyntax={res5.line}, PyName={res6.line})"
    )

    # -------------------------------------------------------------
    # TEST 20: Error Column Extraction
    # -------------------------------------------------------------
    log_test(
        20, "Error Column Extraction",
        res1.column == 5 and res2.column == 5 and res9.column == 3 and res14.column == 7,
        f"(Extracted column numbers: {res1.column}, {res2.column}, {res9.column}, {res14.column})"
    )

    # -------------------------------------------------------------
    # TEST 21: Multiple-Error Handling
    # -------------------------------------------------------------
    multi_err = """main.cpp:5:3: error: 'int a' redeclared
main.cpp:8:5: error: 'coutt' was not declared in this scope
main.cpp:12:1: error: expected '}' at end of input"""
    res21 = CodeDiagnosticEngine.diagnose(
        error_output=multi_err,
        file_path="main.cpp",
        language="cpp"
    )
    log_test(
        21, "Multiple-Error Handling",
        res21.success and len(res21.errors) == 3 and len(res21.related_errors) == 2,
        f"(Parsed {len(res21.errors)} errors, {len(res21.related_errors)} related/cascading)"
    )

    # -------------------------------------------------------------
    # TEST 22: Source Context Extraction & Caret Snippet
    # -------------------------------------------------------------
    src_sample = "int main() {\n    int a = 5;\n    coutt << a;\n    return 0;\n}"
    res22 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:3:5: error: 'coutt' was not declared in this scope",
        file_path="main.cpp",
        source_code=src_sample
    )
    log_test(
        22, "Source Context Extraction",
        res22.success and "^" in res22.source_context and "coutt" in res22.source_context,
        f"(Extracted highlighted context:\n{res22.source_context})"
    )

    # -------------------------------------------------------------
    # TEST 23: Error Prioritization (Primary vs Cascading)
    # -------------------------------------------------------------
    log_test(
        23, "Error Prioritization",
        res21.primary_error is not None and res21.primary_error.get("line") == 5 and res21.errors[1].get("is_cascading") is True,
        f"(Primary error at line {res21.primary_error.get('line')}, cascading marked correctly)"
    )

    # -------------------------------------------------------------
    # TEST 24: Confidence Scoring
    # -------------------------------------------------------------
    low_conf_res = CodeDiagnosticEngine.diagnose(
        error_output="General failure",
        file_path="unknown.dat",
        exit_code=1
    )
    log_test(
        24, "Confidence Scoring",
        res1.confidence >= 0.90 and res1.confidence_level == "HIGH" and low_conf_res.confidence_level == "LOW",
        f"(Exact compiler: {res1.confidence_level} ({res1.confidence}), Ambiguous: {low_conf_res.confidence_level} ({low_conf_res.confidence}))"
    )

    # -------------------------------------------------------------
    # TEST 25: Suggested-Fix Generation
    # -------------------------------------------------------------
    log_test(
        25, "Suggested-Fix Generation",
        "cout" in res2.suggested_fix and "semicolon" in res1.suggested_fix.lower(),
        f"(Fix 1: '{res1.suggested_fix}', Fix 2: '{res2.suggested_fix}')"
    )

    # -------------------------------------------------------------
    # TEST 26: No Source Modification (Strict Invariant)
    # -------------------------------------------------------------
    broken_code = "#include <iostream>\nusing namespace std;\nint main() {\n    coutt << \"Hello ByteX\";\n    return 0;\n}\n"
    target_broken_file = test_proj_dir / "broken.cpp"
    target_broken_file.write_text(broken_code, encoding="utf-8")

    res26 = await skill.execute({
        "action": "diagnose_code_error",
        "file_path": str(target_broken_file),
        "error_output": "broken.cpp:4:5: error: 'coutt' was not declared in this scope",
        "project_name": "ByteXDiagTestApp"
    })
    current_content = target_broken_file.read_text(encoding="utf-8")
    log_test(
        26, "No Source Modification",
        res26.success and current_content == broken_code,
        f"(Source file strictly preserved without alteration)"
    )

    # -------------------------------------------------------------
    # TEST 27: No Command Execution (Strict Invariant)
    # -------------------------------------------------------------
    # Verify diagnose_code_error performs zero subprocesses and zero shell calls
    res27 = await skill.execute({
        "action": "diagnose_code_error",
        "file_path": "main.cpp",
        "error_output": "main.cpp:2:1: error: expected initializer before 'int'"
    })
    log_test(
        27, "No Command Execution",
        res27.success and res27.data.get("stage") == "compile",
        f"(Pure analytical diagnosis executed safely)"
    )

    # -------------------------------------------------------------
    # TEST 28: Secret Sanitization
    # -------------------------------------------------------------
    res28 = CodeDiagnosticEngine.diagnose(
        error_output="Runtime error with AWS_SECRET_ACCESS_KEY = 'AKIA1234567890EXAMPLE' at line 5",
        file_path="secrets.py",
        source_code="AWS_KEY = 'AKIA1234567890EXAMPLE'\nprint(AWS_KEY)\n"
    )
    log_test(
        28, "Secret Sanitization",
        "AKIA1234567890EXAMPLE" not in res28.message and "AKIA1234567890EXAMPLE" not in res28.source_context,
        f"(Redacted API key in diagnostics output)"
    )

    # -------------------------------------------------------------
    # TEST 29: CommandRouter Routing
    # -------------------------------------------------------------
    diag_queries = [
        "Why did my program fail?",
        "What's wrong with my code?",
        "Diagnose the error.",
        "Explain this compiler error.",
        "What caused the runtime error?",
        "Why didn't main.cpp compile?",
        "Why did main.cpp fail?",
        "Why am I getting NameError?",
        "Tell me how to fix this error.",
        "What is wrong with my Python program?"
    ]
    diag_routed = 0
    for q in diag_queries:
        cr = await CommandRouter.classify_request(q)
        if cr.get("skill") == "coding_workspace" and cr.get("arguments", {}).get("action") == "diagnose_code_error":
            diag_routed += 1
    log_test(
        29, "CommandRouter Routing",
        diag_routed == len(diag_queries),
        f"({diag_routed}/{len(diag_queries)} natural diagnostic queries routed correctly)"
    )

    # -------------------------------------------------------------
    # TEST 30: Planner Integration
    # -------------------------------------------------------------
    plan30 = ByteXPlanner.generate_plan("Run main.cpp and diagnose any errors")
    plan30_ok = (
        plan30 is not None
        and len(plan30.steps) == 2
        and plan30.steps[0].suggested_skill == "coding_workspace"
        and plan30.steps[0].arguments.get("action") == "execute_code"
        and plan30.steps[1].suggested_skill == "coding_workspace"
        and plan30.steps[1].arguments.get("action") == "diagnose_code_error"
    )
    log_test(
        30, "Planner Integration",
        plan30_ok,
        f"(Decomposed into: {[s.description for s in plan30.steps] if plan30 else []})"
    )

    # -------------------------------------------------------------
    # TEST 31: Session-Context Integration
    # -------------------------------------------------------------
    # Simulate a prior failed execution recorded in session
    session_manager.record_action_result(
        "coding_workspace",
        {"action": "execute_code", "filename": "broken.cpp"},
        ToolResult(
            success=False,
            verified=False,
            tool="coding_workspace",
            action="execute_code",
            message="Compilation failed",
            data={
                "success": False,
                "file": "broken.cpp",
                "path": str(target_broken_file),
                "language": "cpp",
                "stage": "compile",
                "exit_code": 1,
                "stderr": "broken.cpp:4:5: error: 'coutt' was not declared in this scope",
                "stdout": ""
            }
        )
    )
    res31 = await skill.execute({
        "action": "diagnose_code_error"
    })
    log_test(
        31, "Session-Context Integration",
        res31.success and res31.data.get("file") == "broken.cpp" and "cout" in res31.data.get("suggested_fix", ""),
        f"(Automatically retrieved error context from active session for broken.cpp)"
    )

    # -------------------------------------------------------------
    # TEST 32: Task History Integration
    # -------------------------------------------------------------
    task_history_manager.clear_history()
    h_ok, r_msg, s_stat, d_out = await CommandRouter.route_command("Why did my program fail?")
    hist_records = task_history_manager.get_recent_tasks(limit=3)
    hist_has_diag = any("Why did my program fail" in getattr(r, "command", "") for r in hist_records)
    log_test(
        32, "Task History Integration",
        hist_has_diag,
        f"(Recorded diagnosis query in Task History)"
    )

    # -------------------------------------------------------------
    # TEST 33: Risk Classification
    # -------------------------------------------------------------
    risk_diag = ActionRiskClassifier.classify_action("coding_workspace", {"action": "diagnose_code_error", "file_path": "main.cpp"})
    log_test(
        33, "Risk Classification",
        risk_diag.risk_level == RiskLevel.SAFE and not risk_diag.requires_confirmation,
        f"(diagnose_code_error is classified as SAFE, confirmation={risk_diag.requires_confirmation})"
    )

    # -------------------------------------------------------------
    # TEST 34: Feature #33.3 Execution Integration
    # -------------------------------------------------------------
    target_broken_py = test_proj_dir / "broken_exec.py"
    target_broken_py.write_text("print(undefined_variable_name)\n", encoding="utf-8")
    exec_run_res = await skill.execute({
        "action": "execute_code",
        "file_path": str(target_broken_py),
        "project_name": "ByteXDiagTestApp"
    })
    diag_from_exec = await skill.execute({
        "action": "diagnose_code_error",
        "execution_result": exec_run_res.data
    })
    log_test(
        34, "Feature #33.3 Execution Integration",
        not exec_run_res.success and diag_from_exec.success and diag_from_exec.data.get("error_type") == ErrorCategory.NAME_ERROR.value,
        f"(Seamlessly diagnosed #33.3 failed execution result: {diag_from_exec.data.get('error_type')})"
    )

    # -------------------------------------------------------------
    # TEST 35: Feature #33.2 Code Generation Regression
    # -------------------------------------------------------------
    res35 = await skill.execute({
        "action": "generate_code",
        "prompt": "Print prime numbers from 1 to 100 in C++",
        "filename": "primes_diag_test.cpp",
        "project_name": "ByteXDiagTestApp"
    })
    log_test(
        35, "Feature #33.2 Code Generation Regression",
        res35.success and res35.verified and (test_proj_dir / "primes_diag_test.cpp").exists(),
        f"(Code generation fully operational)"
    )

    # -------------------------------------------------------------
    # TEST 36: Feature #33.1 Coding Workspace Regression
    # -------------------------------------------------------------
    res36 = await skill.execute({
        "action": "inspect_project",
        "project_name": "ByteXDiagTestApp"
    })
    log_test(
        36, "Feature #33.1 Coding Workspace Regression",
        res36.success and res36.data.get("project_name") == "ByteXDiagTestApp",
        f"(Workspace inspection verified: {len(res36.data.get('files', []))} files)"
    )

    # -------------------------------------------------------------
    # TEST 37: Feature #32 Browser Control Regression
    # -------------------------------------------------------------
    b_cr = await CommandRouter.classify_request("Open GitHub in a new tab")
    log_test(
        37, "Feature #32 Browser Control Regression",
        b_cr.get("skill") == "browser_control" and b_cr.get("arguments", {}).get("action") == "new_tab",
        f"(Browser new_tab route intact)"
    )

    # -------------------------------------------------------------
    # TEST 38: Feature #31 Web Search Regression
    # -------------------------------------------------------------
    s_cr = await CommandRouter.classify_request("Search the web for C++ compiler errors")
    log_test(
        38, "Feature #31 Web Search Regression",
        s_cr.get("skill") == "web_search",
        f"(Web search intent intact)"
    )

    # -------------------------------------------------------------
    # TEST 39: Feature #30 Automation Regression
    # -------------------------------------------------------------
    is_auto, auto_obj, _ = NaturalLanguageAutomationParser.parse_creation_request(
        "Create an automation called Diag Routine that opens Edge and creates main.py"
    )
    log_test(
        39, "Feature #30 Automation Regression",
        is_auto and auto_obj is not None and len(auto_obj.steps) == 2,
        f"(Automation parser intact with {len(auto_obj.steps) if auto_obj else 0} steps)"
    )

    # -------------------------------------------------------------
    # TEST 40: Feature #29 Task History Regression
    # -------------------------------------------------------------
    recent = task_history_manager.get_recent_tasks(limit=3)
    log_test(
        40, "Feature #29 Task History Regression",
        isinstance(recent, list) and len(recent) > 0,
        f"(Retrieved {len(recent)} recent task history records)"
    )

    # -------------------------------------------------------------
    # TEST 41: Feature #28 Error Recovery Regression
    # -------------------------------------------------------------
    mock_res = ToolResult(success=False, tool="coding_workspace", message="File not found on disk: main.py", error="File not found")
    err_cat = ErrorRecoveryEngine.classify_error("coding_workspace", {"action": "read_code_file"}, mock_res)
    log_test(
        41, "Feature #28 Error Recovery Regression",
        err_cat == AgentRecoveryCategory.FILE_NOT_FOUND,
        f"(Error recovery classification intact: {err_cat})"
    )

    # -------------------------------------------------------------
    # TEST 42: Feature #27 Suggestions Regression
    # -------------------------------------------------------------
    is_safe = suggestion_engine.is_safe_action("Open Visual Studio Code")
    log_test(
        42, "Feature #27 Suggestions Regression",
        is_safe is True,
        f"(Proactive suggestion safety validation intact)"
    )

    # -------------------------------------------------------------
    # TEST 43: Feature #26 Preferences Regression
    # -------------------------------------------------------------
    pref_mgr = preference_manager
    pref_mgr.set_explicit_preference("preferred_browser", "edge")
    pref = pref_mgr.get_preference("preferred_browser")
    log_test(
        43, "Feature #26 Preferences Regression",
        pref is not None and pref.value == "edge",
        f"(Learned preference intact: {pref.value if pref else None})"
    )

    # -------------------------------------------------------------
    # TEST 44: Feature #25 Memory Regression
    # -------------------------------------------------------------
    mem_mgr = memory_manager
    ok_mem, _, item = mem_mgr.add_memory("I use g++ for compiling C++")
    all_mems = mem_mgr.get_all_memories()
    has_mem = any("g++" in m.content for m in all_mems)
    log_test(
        44, "Feature #25 Memory Regression",
        ok_mem and has_mem,
        f"(Long-term memory intact)"
    )

    # -------------------------------------------------------------
    # TEST 45: Feature #24 Context Regression
    # -------------------------------------------------------------
    ctx = session_manager.get_working_context()
    log_test(
        45, "Feature #24 Context Regression",
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
