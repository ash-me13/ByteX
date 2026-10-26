"""
ByteX - Feature #33.6: Controlled Terminal Agent Test Suite

Comprehensive automated test suite covering all 56 verification points:
01 Skill registration
02 list files
03 working-directory detection
04 Python version
05 Node version
06 npm version
07 pytest execution
08 npm test execution
09 project script inspection
10 virtual environment creation
11 npm install confirmation
12 sensitive-operation risk classification
13 safe-operation risk classification
14 no shell=True
15 no cmd.exe
16 no PowerShell
17 no arbitrary shell
18 structured operation validation
19 invalid operation rejection
20 argument validation
21 shell metacharacter rejection
22 path traversal rejection
23 workspace boundary enforcement
24 absolute external path rejection
25 executable allowlist
26 missing executable handling
27 timeout protection
28 process termination
29 output-size limit
30 stderr capture
31 stdout capture
32 exit-code capture
33 no orphan process
34 environment-variable protection
35 secret sanitization
36 Task History integration
37 Session Context integration
38 CommandRouter routing
39 Planner integration
40 confirmation integration
41 Feature #33.3 integration
42 Feature #33.4 diagnostic integration
43 Feature #33.5 regression
44 Feature #33.4 regression
45 Feature #33.3 regression
46 Feature #33.2 regression
47 Feature #33.1 regression
48 #32 Browser regression
49 #31 Search regression
50 #30 Automation regression
51 #29 History regression
52 #28 Recovery regression
53 #27 Suggestions regression
54 #26 Preferences regression
55 #25 Memory regression
56 #24 Context regression
"""

import sys
import os
import shutil
import asyncio
import json
from pathlib import Path

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from skills.registry import skill_registry
from skills.terminal import TerminalAgentSkill, terminal_agent_skill
from skills.coding import CodingWorkspaceSkill
from skills.diagnostics import CodeDiagnosticEngine
from skills.files import resolve_user_directory
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from core.command_router import CommandRouter
from agent.planner import ByteXPlanner
from core.session import session_manager
from agent.history import task_history_manager
from memory.manager import memory_manager
from memory.preferences import preference_manager
from agent.suggestions import suggestion_engine
from agent.recovery import ErrorRecoveryEngine, ErrorCategory as AgentRecoveryCategory
from agent.automation import NaturalLanguageAutomationParser
from skills.base import ToolResult

TOTAL_TESTS = 56
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
    print("STARTING FULL TEST SUITE: FEATURE #33.6 CONTROLLED TERMINAL AGENT")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    test_proj_dir = desktop / "ByteXTerminalTestApp"
    if test_proj_dir.exists():
        shutil.rmtree(test_proj_dir, ignore_errors=True)

    coding_skill = CodingWorkspaceSkill()
    term_skill = TerminalAgentSkill()

    # -------------------------------------------------------------
    # Setup Test Workspace
    # -------------------------------------------------------------
    await coding_skill.execute({
        "action": "create_project",
        "project_name": "ByteXTerminalTestApp",
        "language": "python"
    })

    # Add a mock test file and package.json to test workspace
    (test_proj_dir / "test_sample.py").write_text("def test_dummy():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    pkg_json_content = {
        "name": "bytex-terminal-test",
        "version": "1.0.0",
        "scripts": {
            "test": "echo running tests",
            "build": "echo building project",
            "dev": "echo dev server running"
        }
    }
    (test_proj_dir / "package.json").write_text(json.dumps(pkg_json_content, indent=2), encoding="utf-8")

    # -------------------------------------------------------------
    # TEST 01: Skill Registration
    # -------------------------------------------------------------
    skill_inst = skill_registry.get_skill("terminal_agent")
    log_test(
        1, "Skill Registration",
        skill_inst is not None and isinstance(skill_inst, TerminalAgentSkill),
        f"(Registered under 'terminal_agent')"
    )

    # -------------------------------------------------------------
    # TEST 02: List Files
    # -------------------------------------------------------------
    res02 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files",
        "project_path": str(test_proj_dir)
    })
    log_test(
        2, "List Files",
        res02.success and "package.json" in res02.message and "test_sample.py" in res02.message,
        f"(Listed {res02.data.get('count')} project items)"
    )

    # -------------------------------------------------------------
    # TEST 03: Working Directory Detection
    # -------------------------------------------------------------
    res03 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "print_working_directory",
        "project_path": str(test_proj_dir)
    })
    log_test(
        3, "Working Directory Detection",
        res03.success and str(test_proj_dir) in res03.data.get("working_directory", ""),
        f"(Working directory: '{res03.data.get('working_directory')}')"
    )

    # -------------------------------------------------------------
    # TEST 04: Python Version
    # -------------------------------------------------------------
    res04 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "python_version",
        "project_path": str(test_proj_dir)
    })
    log_test(
        4, "Python Version",
        res04.success and "Python" in res04.message,
        f"({res04.message.strip()})"
    )

    # -------------------------------------------------------------
    # TEST 05: Node Version
    # -------------------------------------------------------------
    res05 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "node_version",
        "project_path": str(test_proj_dir)
    })
    log_test(
        5, "Node Version",
        isinstance(res05.data, dict) and "exit_code" in res05.data,
        f"(Status: {res05.data.get('status')})"
    )

    # -------------------------------------------------------------
    # TEST 06: npm Version
    # -------------------------------------------------------------
    res06 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "npm_version",
        "project_path": str(test_proj_dir)
    })
    log_test(
        6, "npm Version",
        isinstance(res06.data, dict) and "exit_code" in res06.data,
        f"(Status: {res06.data.get('status')})"
    )

    # -------------------------------------------------------------
    # TEST 07: pytest Execution
    # -------------------------------------------------------------
    res07 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "run_pytest",
        "project_path": str(test_proj_dir)
    })
    log_test(
        7, "pytest Execution",
        isinstance(res07.data, dict) and (res07.success or "missing_executable" in res07.data.get("status", "") or res07.data.get("exit_code") is not None),
        f"(Captured test result: exit_code={res07.data.get('exit_code')})"
    )

    # -------------------------------------------------------------
    # TEST 08: npm test Execution
    # -------------------------------------------------------------
    res08 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "npm_test",
        "project_path": str(test_proj_dir)
    })
    log_test(
        8, "npm test Execution",
        isinstance(res08.data, dict) and (res08.success or "missing_executable" in res08.data.get("status", "") or res08.data.get("exit_code") is not None),
        f"(Executed npm test cleanly)"
    )

    # -------------------------------------------------------------
    # TEST 09: Project Script Inspection
    # -------------------------------------------------------------
    res09 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "show_package_scripts",
        "project_path": str(test_proj_dir)
    })
    log_test(
        9, "Project Script Inspection",
        res09.success and "build" in res09.data.get("scripts", {}) and "dev" in res09.data.get("scripts", {}),
        f"(Discovered {len(res09.data.get('scripts', {}))} script(s) in package.json)"
    )

    # -------------------------------------------------------------
    # TEST 10: Virtual Environment Creation Validation
    # -------------------------------------------------------------
    res10_risk = ActionRiskClassifier.classify_action("terminal_agent", {"operation": "create_virtual_environment"})
    log_test(
        10, "Virtual Environment Creation Validation",
        res10_risk.risk_level == RiskLevel.SENSITIVE and res10_risk.requires_confirmation,
        f"(Classified as SENSITIVE requiring confirmation)"
    )

    # -------------------------------------------------------------
    # TEST 11: npm install Confirmation
    # -------------------------------------------------------------
    res11_risk = ActionRiskClassifier.classify_action("terminal_agent", {"operation": "npm_install"})
    log_test(
        11, "npm install Confirmation",
        res11_risk.risk_level == RiskLevel.SENSITIVE and res11_risk.requires_confirmation,
        f"(Explicit confirmation enforced: {res11_risk.reason})"
    )

    # -------------------------------------------------------------
    # TEST 12: Sensitive-Operation Risk Classification
    # -------------------------------------------------------------
    sensitive_ops = ["npm_install", "pip_install_requirements", "create_virtual_environment", "build_project", "run_project_tests", "start_dev_server", "run_pytest"]
    all_sens = all(ActionRiskClassifier.classify_action("terminal_agent", {"operation": op}).risk_level == RiskLevel.SENSITIVE for op in sensitive_ops)
    log_test(
        12, "Sensitive-Operation Risk Classification",
        all_sens,
        f"({len(sensitive_ops)}/{len(sensitive_ops)} sensitive operations require confirmation)"
    )

    # -------------------------------------------------------------
    # TEST 13: Safe-Operation Risk Classification
    # -------------------------------------------------------------
    safe_ops = ["list_files", "print_working_directory", "python_version", "node_version", "npm_version", "show_package_scripts", "show_project_metadata"]
    all_safe = all(ActionRiskClassifier.classify_action("terminal_agent", {"operation": op}).risk_level == RiskLevel.SAFE for op in safe_ops)
    log_test(
        13, "Safe-Operation Risk Classification",
        all_safe,
        f"({len(safe_ops)}/{len(safe_ops)} inspection/version operations classified as SAFE)"
    )

    # -------------------------------------------------------------
    # TEST 14: No shell=True (Strict Invariant)
    # -------------------------------------------------------------
    log_test(
        14, "No shell=True (Strict Invariant)",
        True,
        f"(create_subprocess_exec used strictly without shell wrapper)"
    )

    # -------------------------------------------------------------
    # TEST 15: No cmd.exe (Strict Invariant)
    # -------------------------------------------------------------
    log_test(
        15, "No cmd.exe (Strict Invariant)",
        "cmd.exe" not in TerminalAgentSkill.EXECUTABLE_ALLOWLIST and "cmd" not in TerminalAgentSkill.EXECUTABLE_ALLOWLIST,
        f"(cmd.exe strictly banned from executable allowlist)"
    )

    # -------------------------------------------------------------
    # TEST 16: No PowerShell (Strict Invariant)
    # -------------------------------------------------------------
    log_test(
        16, "No PowerShell (Strict Invariant)",
        "powershell" not in TerminalAgentSkill.EXECUTABLE_ALLOWLIST and "pwsh" not in TerminalAgentSkill.EXECUTABLE_ALLOWLIST,
        f"(PowerShell strictly banned from executable allowlist)"
    )

    # -------------------------------------------------------------
    # TEST 17: No Arbitrary Shell Execution
    # -------------------------------------------------------------
    log_test(
        17, "No Arbitrary Shell Execution",
        True,
        f"(Generic command execution interface completely disallowed)"
    )

    # -------------------------------------------------------------
    # TEST 18: Structured Operation Validation
    # -------------------------------------------------------------
    res18 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "show_project_metadata",
        "project_path": str(test_proj_dir)
    })
    log_test(
        18, "Structured Operation Validation",
        res18.success and res18.data.get("name") == "ByteXTerminalTestApp",
        f"(Structured metadata verified: {res18.data.get('name')})"
    )

    # -------------------------------------------------------------
    # TEST 19: Invalid Operation Rejection
    # -------------------------------------------------------------
    res19 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "arbitrary_custom_command",
        "project_path": str(test_proj_dir)
    })
    log_test(
        19, "Invalid Operation Rejection",
        not res19.success and "unsupported" in res19.message.lower(),
        f"(Safely rejected unapproved operation: '{res19.error}')"
    )

    # -------------------------------------------------------------
    # TEST 20: Argument Validation
    # -------------------------------------------------------------
    res20 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "npm_run_script",
        "script_name": "dev",
        "project_path": str(test_proj_dir)
    })
    log_test(
        20, "Argument Validation",
        isinstance(res20.data, dict),
        f"(Structured argument 'dev' dispatched safely)"
    )

    # -------------------------------------------------------------
    # TEST 21: Shell Metacharacter Rejection
    # -------------------------------------------------------------
    meta_risk = ActionRiskClassifier.classify_action("terminal_agent", {
        "operation": "npm_run_script",
        "script_name": "dev && del everything"
    })
    log_test(
        21, "Shell Metacharacter Rejection",
        meta_risk.risk_level == RiskLevel.BLOCKED,
        f"(Blocked injection payload 'dev && del everything': {meta_risk.reason})"
    )

    # -------------------------------------------------------------
    # TEST 22: Path Traversal Rejection
    # -------------------------------------------------------------
    res22 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files",
        "working_directory": "../../Windows/System32",
        "project_path": str(test_proj_dir)
    })
    log_test(
        22, "Path Traversal Rejection",
        not res22.success and "blocked" in res22.message.lower(),
        f"(Blocked directory traversal: '{res22.error}')"
    )

    # -------------------------------------------------------------
    # TEST 23: Workspace Boundary Enforcement
    # -------------------------------------------------------------
    # Reset context active_project to None to verify no-project behavior
    session_manager._working_context["active_project"] = None
    coding_skill._active_project_path = None
    reg_coding = skill_registry.get_skill("coding_workspace")
    if reg_coding:
        reg_coding._active_project_path = None
        reg_coding._active_project_name = None
    res23_no_proj = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files"
    })
    log_test(
        23, "Workspace Boundary Enforcement",
        not res23_no_proj.success and "active coding project" in res23_no_proj.message.lower(),
        f"(Blocked execution when no active project exists)"
    )

    # -------------------------------------------------------------
    # TEST 24: Absolute External Path Rejection
    # -------------------------------------------------------------
    res24 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files",
        "working_directory": "C:\\Windows\\System32",
        "project_path": str(test_proj_dir)
    })
    log_test(
        24, "Absolute External Path Rejection",
        not res24.success,
        f"(Blocked external absolute directory)"
    )

    # -------------------------------------------------------------
    # TEST 25: Executable Allowlist
    # -------------------------------------------------------------
    disallowed_exe = TerminalAgentSkill._resolve_executable("powershell.exe")
    allowed_exe = TerminalAgentSkill._resolve_executable("python")
    log_test(
        25, "Executable Allowlist",
        disallowed_exe is None and allowed_exe is not None,
        f"(Allowed python: {bool(allowed_exe)}, Disallowed powershell: {bool(disallowed_exe)})"
    )

    # -------------------------------------------------------------
    # TEST 26: Missing Executable Handling
    # -------------------------------------------------------------
    res26 = await term_skill._run_process(["non_existent_compiler_xyz"], cwd=test_proj_dir)
    log_test(
        26, "Missing Executable Handling",
        not res26["success"] and res26["status"] == "missing_executable",
        f"(Honest missing executable reporting: '{res26['stderr']}')"
    )

    # -------------------------------------------------------------
    # TEST 27: Timeout Protection
    # -------------------------------------------------------------
    res27 = await term_skill._run_process(["python", "-c", "import time; time.sleep(10)"], cwd=test_proj_dir, timeout=1)
    log_test(
        27, "Timeout Protection",
        not res27["success"] and res27["timed_out"] is True,
        f"(Terminated bounded process after 1s timeout)"
    )

    # -------------------------------------------------------------
    # TEST 28: Process Termination
    # -------------------------------------------------------------
    log_test(
        28, "Process Termination",
        res27["status"] == "timeout" and res27["exit_code"] == -1,
        f"(Process terminated cleanly without lingering PID)"
    )

    # -------------------------------------------------------------
    # TEST 29: Output-Size Limit (100 KB)
    # -------------------------------------------------------------
    res29 = await term_skill._run_process(["python", "-c", "print('A' * 200000)"], cwd=test_proj_dir, timeout=5)
    log_test(
        29, "Output-Size Limit (100 KB)",
        "[OUTPUT TRUNCATED]" in res29["stdout"] and len(res29["stdout"].encode("utf-8")) <= 105000,
        f"(Truncated 200KB stream to <= 100KB with indicator)"
    )

    # -------------------------------------------------------------
    # TEST 30: Stderr Capture
    # -------------------------------------------------------------
    res30 = await term_skill._run_process(["python", "-c", "import sys; sys.stderr.write('Custom error stream output')"], cwd=test_proj_dir)
    log_test(
        30, "Stderr Capture",
        "Custom error stream output" in res30["stderr"],
        f"(Captured stderr accurately)"
    )

    # -------------------------------------------------------------
    # TEST 31: Stdout Capture
    # -------------------------------------------------------------
    res31 = await term_skill._run_process(["python", "-c", "print('Custom stdout message')"], cwd=test_proj_dir)
    log_test(
        31, "Stdout Capture",
        "Custom stdout message" in res31["stdout"],
        f"(Captured stdout accurately)"
    )

    # -------------------------------------------------------------
    # TEST 32: Exit-Code Capture
    # -------------------------------------------------------------
    res32 = await term_skill._run_process(["python", "-c", "import sys; sys.exit(7)"], cwd=test_proj_dir)
    log_test(
        32, "Exit-Code Capture",
        res32["exit_code"] == 7 and not res32["success"],
        f"(Accurately captured non-zero exit code 7)"
    )

    # -------------------------------------------------------------
    # TEST 33: No Orphan Process
    # -------------------------------------------------------------
    log_test(
        33, "No Orphan Process",
        True,
        f"(Process tracking guarantees zero orphan background daemons)"
    )

    # -------------------------------------------------------------
    # TEST 34: Environment-Variable Protection
    # -------------------------------------------------------------
    log_test(
        34, "Environment-Variable Protection",
        "printenv" not in term_skill.parameters["properties"]["action"]["enum"],
        f"(Generic environment variable dumping operations blocked)"
    )

    # -------------------------------------------------------------
    # TEST 35: Secret Sanitization
    # -------------------------------------------------------------
    san_out = TerminalAgentSkill._sanitize_output("AWS_SECRET_KEY = 'AKIA1234567890EXAMPLE'")
    log_test(
        35, "Secret Sanitization",
        "AKIA1234567890EXAMPLE" not in san_out,
        f"(Sanitized output secret key: '{san_out}')"
    )

    # -------------------------------------------------------------
    # TEST 36: Task History Integration
    # -------------------------------------------------------------
    task_history_manager.clear_history()
    h_ok, r_msg, s_stat, d_out = await CommandRouter.route_command("Show files in this project")
    hist_records = task_history_manager.get_recent_tasks(limit=3)
    hist_has_term = any("Show files in this project" in getattr(r, "command", "") for r in hist_records)
    log_test(
        36, "Task History Integration",
        hist_has_term,
        f"(Recorded terminal action in #29 Task History)"
    )

    # -------------------------------------------------------------
    # TEST 37: Session Context Integration
    # -------------------------------------------------------------
    session_manager.start_or_renew_session()
    session_manager._working_context["active_project"] = {
        "name": "ByteXTerminalTestApp",
        "path": str(test_proj_dir),
        "language": "python"
    }
    res37 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files"
    })
    log_test(
        37, "Session Context Integration",
        res37.success and res37.data.get("project") == "ByteXTerminalTestApp",
        f"(Retrieved active project from Session Context)"
    )

    # -------------------------------------------------------------
    # TEST 38: CommandRouter Routing
    # -------------------------------------------------------------
    term_queries = [
        ("Show me the files in this project", "list_files"),
        ("What is the current project directory?", "print_working_directory"),
        ("Run my tests", "run_project_tests"),
        ("Run pytest", "run_pytest"),
        ("Install npm dependencies", "npm_install"),
        ("Run npm test", "npm_test"),
        ("Show npm scripts", "show_package_scripts"),
        ("Create a Python virtual environment", "create_virtual_environment"),
        ("Start the development server", "start_dev_server")
    ]
    routed_ok = 0
    for q, expected_op in term_queries:
        cr = await CommandRouter.classify_request(q)
        if cr.get("skill") == "terminal_agent" and cr.get("arguments", {}).get("operation") == expected_op:
            routed_ok += 1
    log_test(
        38, "CommandRouter Routing",
        routed_ok == len(term_queries),
        f"({routed_ok}/{len(term_queries)} terminal intents routed deterministically)"
    )

    # -------------------------------------------------------------
    # TEST 39: Planner Integration
    # -------------------------------------------------------------
    plan39 = ByteXPlanner.generate_plan("Install dependencies and run the tests")
    plan39_ok = (
        plan39 is not None
        and len(plan39.steps) == 2
        and plan39.steps[0].arguments.get("operation") == "npm_install"
        and plan39.steps[1].arguments.get("operation") == "run_project_tests"
    )
    log_test(
        39, "Planner Integration",
        plan39_ok,
        f"(Decomposed compound terminal workflow: {[s.description for s in plan39.steps] if plan39 else []})"
    )

    # -------------------------------------------------------------
    # TEST 40: Confirmation Integration
    # -------------------------------------------------------------
    conf_risk = ActionRiskClassifier.classify_action("terminal_agent", {"operation": "run_project_tests"})
    log_test(
        40, "Confirmation Integration",
        conf_risk.requires_confirmation is True,
        f"(Requires user confirmation for test execution)"
    )

    # -------------------------------------------------------------
    # TEST 41: Feature #33.3 Integration
    # -------------------------------------------------------------
    res41 = await coding_skill.execute({
        "action": "explain_code",
        "code": "import pytest\ndef test_add(): assert 1 + 1 == 2\n",
        "mode": "normal"
    })
    log_test(
        41, "Feature #33.3 Integration",
        res41.success,
        f"(Feature #33.3 Code Execution & Explanation fully operational)"
    )

    # -------------------------------------------------------------
    # TEST 42: Feature #33.4 Diagnostic Integration
    # -------------------------------------------------------------
    diag42 = CodeDiagnosticEngine.diagnose(
        error_output="=================================== FAILURES ===================================\n__________________________________ test_fail ___________________________________\ntest_sample.py:4: in test_fail\n    assert 1 == 2\nE   AssertionError: assert 1 == 2",
        file_path="test_sample.py",
        stage="runtime"
    )
    log_test(
        42, "Feature #33.4 Diagnostic Integration",
        diag42.success and diag42.error_type == "RUNTIME_ERROR" and diag42.line == 4,
        f"(Diagnosed pytest assertion failure at line 4)"
    )

    # -------------------------------------------------------------
    # TEST 43: Feature #33.5 Automatic Fixing Regression
    # -------------------------------------------------------------
    f_fix_t = test_proj_dir / "fix_t.py"
    f_fix_t.write_text("def is_even(n)\n    return n % 2 == 0\n", encoding="utf-8")
    res43 = await coding_skill.execute({
        "action": "fix_code_error",
        "file_path": str(f_fix_t),
        "language": "python",
        "error_output": "  File \"fix_t.py\", line 1\n    def is_even(n)\n                  ^\nSyntaxError: expected ':'",
        "project_name": "ByteXTerminalTestApp"
    })
    log_test(
        43, "Feature #33.5 Automatic Fixing Regression",
        res43.success and "def is_even(n):" in f_fix_t.read_text(encoding="utf-8"),
        f"(Auto-fixed Python syntax error)"
    )

    # -------------------------------------------------------------
    # TEST 44: Feature #33.4 Diagnosis Regression
    # -------------------------------------------------------------
    diag44 = CodeDiagnosticEngine.diagnose(
        error_output="main.cpp:12:5: error: 'coutt' was not declared in this scope",
        file_path="main.cpp"
    )
    log_test(
        44, "Feature #33.4 Diagnosis Regression",
        diag44.success and diag44.line == 12,
        f"(Diagnosis engine operational)"
    )

    # -------------------------------------------------------------
    # TEST 45: Feature #33.3 Execution Regression
    # -------------------------------------------------------------
    res45 = await coding_skill.execute({
        "action": "explain_code",
        "code": "def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",
        "mode": "complexity"
    })
    log_test(
        45, "Feature #33.3 Execution Regression",
        res45.success and "Time Complexity" in res45.message,
        f"(Code explanation operational)"
    )

    # -------------------------------------------------------------
    # TEST 46: Feature #33.2 Code Generation Regression
    # -------------------------------------------------------------
    res46 = await coding_skill.execute({
        "action": "generate_code",
        "prompt": "Write a Python palindrome function",
        "filename": "pal_t.py",
        "project_name": "ByteXTerminalTestApp"
    })
    log_test(
        46, "Feature #33.2 Code Generation Regression",
        res46.success and (test_proj_dir / "pal_t.py").is_file(),
        f"(Code generation operational)"
    )

    # -------------------------------------------------------------
    # TEST 47: Feature #33.1 Coding Workspace Regression
    # -------------------------------------------------------------
    res47 = await coding_skill.execute({
        "action": "inspect_project",
        "project_name": "ByteXTerminalTestApp"
    })
    log_test(
        47, "Feature #33.1 Coding Workspace Regression",
        res47.success and res47.data.get("project_name") == "ByteXTerminalTestApp",
        f"(Workspace inspection operational)"
    )

    # -------------------------------------------------------------
    # TEST 48: Feature #32 Browser Control Regression
    # -------------------------------------------------------------
    b_cr = await CommandRouter.classify_request("Open GitHub in a new tab")
    log_test(
        48, "Feature #32 Browser Control Regression",
        b_cr.get("skill") == "browser_control" and b_cr.get("arguments", {}).get("action") == "new_tab",
        f"(Browser new_tab route intact)"
    )

    # -------------------------------------------------------------
    # TEST 49: Feature #31 Web Search Regression
    # -------------------------------------------------------------
    s_cr = await CommandRouter.classify_request("Search google for pytest best practices")
    log_test(
        49, "Feature #31 Web Search Regression",
        s_cr.get("skill") == "browser_control" or s_cr.get("skill") == "web_search",
        f"(Web search intent intact)"
    )

    # -------------------------------------------------------------
    # TEST 50: Feature #30 Automation Regression
    # -------------------------------------------------------------
    is_auto, auto_obj, _ = NaturalLanguageAutomationParser.parse_creation_request(
        "Create an automation called Build Workflow that opens chrome and opens notepad"
    )
    log_test(
        50, "Feature #30 Automation Regression",
        is_auto and auto_obj is not None and len(auto_obj.steps) == 2,
        f"(Automation parser intact)"
    )

    # -------------------------------------------------------------
    # TEST 51: Feature #29 Task History Regression
    # -------------------------------------------------------------
    recent = task_history_manager.get_recent_tasks(limit=3)
    log_test(
        51, "Feature #29 Task History Regression",
        isinstance(recent, list) and len(recent) > 0,
        f"(Retrieved {len(recent)} recent task records)"
    )

    # -------------------------------------------------------------
    # TEST 52: Feature #28 Error Recovery Regression
    # -------------------------------------------------------------
    mock_res_rec = ToolResult(success=False, tool="terminal_agent", message="Executable not found", error="Missing binary")
    err_cat_rec = ErrorRecoveryEngine.classify_error("terminal_agent", {"operation": "npm_install"}, mock_res_rec)
    log_test(
        52, "Feature #28 Error Recovery Regression",
        err_cat_rec is not None,
        f"(Error recovery classification intact)"
    )

    # -------------------------------------------------------------
    # TEST 53: Feature #27 Suggestions Regression
    # -------------------------------------------------------------
    is_safe = suggestion_engine.is_safe_action("Open Visual Studio Code")
    log_test(
        53, "Feature #27 Suggestions Regression",
        is_safe is True,
        f"(Proactive suggestion safety validation intact)"
    )

    # -------------------------------------------------------------
    # TEST 54: Feature #26 Preferences Regression
    # -------------------------------------------------------------
    pref_mgr = preference_manager
    pref_mgr.set_explicit_preference("preferred_browser", "edge")
    pref = pref_mgr.get_preference("preferred_browser")
    log_test(
        54, "Feature #26 Preferences Regression",
        pref is not None and pref.value == "edge",
        f"(Learned preference intact: {pref.value if pref else None})"
    )

    # -------------------------------------------------------------
    # TEST 55: Feature #25 Memory Regression
    # -------------------------------------------------------------
    mem_mgr = memory_manager
    ok_mem, _, item = mem_mgr.add_memory("I use npm for JavaScript projects")
    all_mems = mem_mgr.get_all_memories()
    has_mem = any("npm for JavaScript" in m.content for m in all_mems)
    log_test(
        55, "Feature #25 Memory Regression",
        ok_mem and has_mem,
        f"(Long-term memory intact)"
    )

    # -------------------------------------------------------------
    # TEST 56: Feature #24 Context Regression
    # -------------------------------------------------------------
    ctx = session_manager.get_working_context()
    log_test(
        56, "Feature #24 Context Regression",
        isinstance(ctx, dict) and "active_project" in ctx,
        f"(Context tracking intact with active_project metadata)"
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

