"""
ByteX — Feature #33.2: Natural-Language Code Generation Test Suite

Comprehensive automated test suite covering:
1. C++ prime-number generation
2. Python palindrome generation
3. JavaScript calculator generation
4. C++ binary-search generation
5. Language detection
6. Filename detection
7. Default filename selection
8. Existing-file overwrite protection
9. Explicit overwrite confirmation
10. New-file creation
11. Generated-code persistence
12. Generated-code verification
13. Project-context integration
14. Planner compound generation
15. CommandRouter generation routing
16. Risk classification
17. Secret/credential protection
18. No shell/subprocess execution (execution notice guard)
19. Task History integration
20. #33.1 regression
21. #32 Browser regression
22. #31 Search regression
23. #30 Automation regression
24. #29 History regression
25. #28 Recovery regression
26. #27 Suggestions regression
27. #26 Preference regression
28. #25 Memory regression
29. #24 Context regression
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
from agent.recovery import ErrorRecoveryEngine, ErrorCategory
from agent.automation import NaturalLanguageAutomationParser
from skills.base import ToolResult

TOTAL_TESTS = 29
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
    print("STARTING FULL TEST SUITE: FEATURE #33.2 NATURAL-LANGUAGE CODE GENERATION")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    test_project_dir = desktop / "ByteXCodeGenApp"
    if test_project_dir.exists():
        shutil.rmtree(test_project_dir, ignore_errors=True)

    skill = CodingWorkspaceSkill()

    # -------------------------------------------------------------
    # Setup Workspace
    # -------------------------------------------------------------
    await skill.execute({
        "action": "create_project",
        "project_name": "ByteXCodeGenApp",
        "language": "cpp"
    })

    # -------------------------------------------------------------
    # TEST 01: C++ Prime Number Generation
    # -------------------------------------------------------------
    res1 = await skill.execute({
        "action": "generate_code",
        "prompt": "Print prime numbers from 1 to 100 in C++",
        "filename": "primes.cpp",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        1, "C++ Prime Number Generation",
        res1.success and res1.verified and "isPrime" in res1.data.get("code", "") and res1.data.get("language") == "C++",
        f"(Generated {res1.data.get('language')} solution in {res1.data.get('filename')})"
    )

    # -------------------------------------------------------------
    # TEST 02: Python Palindrome Generation
    # -------------------------------------------------------------
    res2 = await skill.execute({
        "action": "generate_code",
        "prompt": "Create a Python program to check palindrome",
        "filename": "palindrome.py",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        2, "Python Palindrome Generation",
        res2.success and res2.verified and "is_palindrome" in res2.data.get("code", "") and res2.data.get("language") == "Python",
        f"(Generated {res2.data.get('language')} palindrome checker in {res2.data.get('filename')})"
    )

    # -------------------------------------------------------------
    # TEST 03: JavaScript Calculator Generation
    # -------------------------------------------------------------
    res3 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write a JavaScript calculator",
        "filename": "calc.js",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        3, "JavaScript Calculator Generation",
        res3.success and res3.verified and "Calculator" in res3.data.get("code", "") and res3.data.get("language") == "JavaScript",
        f"(Generated {res3.data.get('language')} calculator in {res3.data.get('filename')})"
    )

    # -------------------------------------------------------------
    # TEST 04: C++ Binary Search Generation
    # -------------------------------------------------------------
    res4 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write a binary search program in C++",
        "filename": "binary_search.cpp",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        4, "C++ Binary Search Generation",
        res4.success and res4.verified and "binarySearch" in res4.data.get("code", "") and res4.data.get("language") == "C++",
        f"(Generated binary search in {res4.data.get('filename')})"
    )

    # -------------------------------------------------------------
    # TEST 05: Language Detection
    # -------------------------------------------------------------
    norm_cpp, display_cpp, _, _ = skill._resolve_target_language("Implement merge sort in C++")
    norm_py, display_py, _, _ = skill._resolve_target_language("Create a palindrome script in Python")
    norm_js, display_js, _, _ = skill._resolve_target_language("Write calculator in JS")
    log_test(
        5, "Language Detection",
        norm_cpp == "cpp" and norm_py == "python" and norm_js == "javascript",
        f"(Detected languages: {display_cpp}, {display_py}, {display_js})"
    )

    # -------------------------------------------------------------
    # TEST 06: Filename Detection
    # -------------------------------------------------------------
    res6 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write merge sort in C++ and save it as merge.cpp",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        6, "Filename Detection",
        res6.success and res6.data.get("filename") == "merge.cpp",
        f"(Extracted embedded filename '{res6.data.get('filename')}')"
    )

    # -------------------------------------------------------------
    # TEST 07: Default Filename Selection
    # -------------------------------------------------------------
    res7 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write a program in Python to calculate factorial",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        7, "Default Filename Selection",
        res7.success and res7.data.get("filename") == "main.py",
        f"(Selected default filename '{res7.data.get('filename')}' for Python)"
    )

    # -------------------------------------------------------------
    # TEST 08: Existing-File Overwrite Protection
    # -------------------------------------------------------------
    res8 = await skill.execute({
        "action": "generate_code",
        "prompt": "Print prime numbers from 1 to 100 in C++",
        "filename": "main.cpp",
        "project_name": "ByteXCodeGenApp",
        "overwrite": False
    })
    log_test(
        8, "Existing-File Overwrite Protection",
        not res8.success and res8.confirmation_required and res8.data.get("already_exists") is True,
        f"(Blocked silent overwrite and requested confirmation: '{res8.message[:60]}...')"
    )

    # -------------------------------------------------------------
    # TEST 09: Explicit Overwrite Confirmation
    # -------------------------------------------------------------
    res9 = await skill.execute({
        "action": "generate_code",
        "prompt": "Print prime numbers from 1 to 100 in C++",
        "filename": "main.cpp",
        "project_name": "ByteXCodeGenApp",
        "overwrite": True
    })
    log_test(
        9, "Explicit Overwrite Confirmation",
        res9.success and res9.verified and res9.data.get("written") is True,
        f"(Replaced main.cpp successfully after explicit confirmation)"
    )

    # -------------------------------------------------------------
    # TEST 10: New-File Creation
    # -------------------------------------------------------------
    res10 = await skill.execute({
        "action": "generate_code",
        "prompt": "Create a Python program to reverse a string",
        "filename": "reverse.py",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        10, "New-File Creation",
        res10.success and (test_project_dir / "reverse.py").exists(),
        f"(Created new file {res10.data.get('filename')} on disk)"
    )

    # -------------------------------------------------------------
    # TEST 11: Generated-Code Persistence
    # -------------------------------------------------------------
    persisted_content = (test_project_dir / "primes.cpp").read_text(encoding="utf-8")
    log_test(
        11, "Generated-Code Persistence",
        "isPrime" in persisted_content and len(persisted_content) > 50,
        f"(Persisted on disk with length {len(persisted_content)} chars)"
    )

    # -------------------------------------------------------------
    # TEST 12: Generated-Code Verification
    # -------------------------------------------------------------
    ver_ok, ver_data, _ = ActionVerifier.verify_file_creation(test_project_dir / "primes.cpp")
    log_test(
        12, "Generated-Code Verification",
        ver_ok and ver_data.get("size_bytes", 0) > 0,
        f"(ActionVerifier confirmed physical disk existence and size)"
    )

    # -------------------------------------------------------------
    # TEST 13: Project-Context Integration
    # -------------------------------------------------------------
    res13 = await skill.execute({
        "action": "generate_code",
        "prompt": "Write merge sort in C++",
        "filename": "merge_ctx.cpp"
    })
    log_test(
        13, "Project-Context Integration",
        res13.success and (test_project_dir / "merge_ctx.cpp").exists(),
        f"(Saved into active project directory '{test_project_dir.name}')"
    )

    # -------------------------------------------------------------
    # TEST 14: Planner Compound Generation
    # -------------------------------------------------------------
    plan = ByteXPlanner.generate_plan(
        "Open my ByteXCodeGenApp project and write a binary search program in C++"
    )
    plan_ok = (
        plan is not None
        and len(plan.steps) >= 2
        and plan.steps[0].suggested_skill == "coding_workspace"
        and plan.steps[0].arguments.get("action") == "open_project"
        and plan.steps[1].suggested_skill == "coding_workspace"
        and plan.steps[1].arguments.get("action") == "generate_code"
    )
    log_test(
        14, "Planner Compound Generation",
        plan_ok,
        f"(Decomposed into steps: {[s.description for s in plan.steps] if plan else []})"
    )

    # -------------------------------------------------------------
    # TEST 15: CommandRouter Generation Routing
    # -------------------------------------------------------------
    test_queries = [
        "Print prime numbers from 1 to 100 in C++",
        "Write a binary search program in C++",
        "Create a Python program to check palindrome",
        "Write a JavaScript calculator",
        "Implement merge sort in C++",
        "Write merge sort in C++ and save it as merge.cpp"
    ]
    routed_count = 0
    for q in test_queries:
        cr_res = await CommandRouter.classify_request(q)
        if cr_res.get("skill") == "coding_workspace" and cr_res.get("arguments", {}).get("action") == "generate_code":
            routed_count += 1
    log_test(
        15, "CommandRouter Generation Routing",
        routed_count == len(test_queries),
        f"({routed_count}/{len(test_queries)} programming intents routed to generate_code)"
    )

    # -------------------------------------------------------------
    # TEST 16: Risk Classification
    # -------------------------------------------------------------
    risk_gen_safe = ActionRiskClassifier.classify_action("coding_workspace", {"action": "generate_code", "overwrite": False})
    risk_gen_sens = ActionRiskClassifier.classify_action("coding_workspace", {"action": "generate_code", "overwrite": True, "filename": "main.cpp"})
    log_test(
        16, "Risk Classification",
        risk_gen_safe.risk_level == RiskLevel.SAFE and not risk_gen_safe.requires_confirmation
        and risk_gen_sens.risk_level == RiskLevel.SENSITIVE and risk_gen_sens.requires_confirmation,
        f"(Safe generation: {risk_gen_safe.risk_level.value}, Overwrite generation: {risk_gen_sens.risk_level.value})"
    )

    # -------------------------------------------------------------
    # TEST 17: Secret / Credential Protection
    # -------------------------------------------------------------
    res17 = await skill.execute({
        "action": "generate_code",
        "prompt": "Create a Python program with hardcoded AWS_SECRET_ACCESS_KEY = 'AKIA1234567890'",
        "filename": "secrets.py",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        17, "Secret / Credential Protection",
        res17.success and "AKIA1234567890" not in res17.data.get("code", ""),
        f"(Sanitized output without leaking secret credentials)"
    )

    # -------------------------------------------------------------
    # TEST 18: No Shell / Subprocess Execution (Execution Notice Guard)
    # -------------------------------------------------------------
    res18 = await skill.execute({
        "action": "generate_code",
        "prompt": "Run the prime-number program",
        "execution_request": True
    })
    log_test(
        18, "No Shell / Execution Notice Guard",
        not res18.success and "Feature #33.3" in res18.message,
        f"(Enforced #33.2 boundary: '{res18.message}')"
    )

    # -------------------------------------------------------------
    # TEST 19: Task History Integration
    # -------------------------------------------------------------
    task_history_manager.clear_history()
    h_ok, r_msg, s_stat, d_out = await CommandRouter.route_command("Print prime numbers in C++ and save it as history_primes.cpp")
    hist_records = task_history_manager.get_recent_tasks(limit=5)
    hist_ok = any("Print prime numbers" in getattr(r, "command", "") for r in hist_records)
    h_file = desktop / "history_primes.cpp"
    if h_file.exists():
        h_file.unlink(missing_ok=True)
    log_test(
        19, "Task History Integration",
        hist_ok,
        f"(Recorded code generation task in #29 Task History)"
    )

    # -------------------------------------------------------------
    # TEST 20: #33.1 Coding Workspace Regression
    # -------------------------------------------------------------
    res20 = await skill.execute({
        "action": "inspect_project",
        "project_name": "ByteXCodeGenApp"
    })
    log_test(
        20, "#33.1 Workspace Regression",
        res20.success and res20.data.get("project_name") == "ByteXCodeGenApp",
        f"(Inspected project successfully: {len(res20.data.get('files', []))} files)"
    )

    # -------------------------------------------------------------
    # TEST 21: #32 Browser Control Regression
    # -------------------------------------------------------------
    b_cr = await CommandRouter.classify_request("Open GitHub in a new tab")
    log_test(
        21, "#32 Browser Control Regression",
        b_cr.get("skill") == "browser_control" and b_cr.get("arguments", {}).get("action") == "new_tab",
        f"(Browser new_tab route intact)"
    )

    # -------------------------------------------------------------
    # TEST 22: #31 Web Search Regression
    # -------------------------------------------------------------
    s_cr = await CommandRouter.classify_request("Search the web for C++ tutorials")
    log_test(
        22, "#31 Web Search Regression",
        s_cr.get("skill") == "web_search",
        f"(Web search intent routed: {s_cr.get('skill')})"
    )

    # -------------------------------------------------------------
    # TEST 23: #30 Automation Regression
    # -------------------------------------------------------------
    is_auto, auto_obj, _ = NaturalLanguageAutomationParser.parse_creation_request(
        "Create an automation called Code Routine that opens Edge and creates main.py"
    )
    log_test(
        23, "#30 Automation Regression",
        is_auto and auto_obj is not None and len(auto_obj.steps) == 2,
        f"(Parsed automation with {len(auto_obj.steps) if auto_obj else 0} steps)"
    )

    # -------------------------------------------------------------
    # TEST 24: #29 Task History Regression
    # -------------------------------------------------------------
    recent = task_history_manager.get_recent_tasks(limit=3)
    log_test(
        24, "#29 Task History Regression",
        isinstance(recent, list) and len(recent) > 0,
        f"(Found {len(recent)} recent task records)"
    )

    # -------------------------------------------------------------
    # TEST 25: #28 Error Recovery Regression
    # -------------------------------------------------------------
    mock_res = ToolResult(success=False, tool="coding_workspace", message="File not found on disk: main.py", error="File not found")
    err_cat = ErrorRecoveryEngine.classify_error("coding_workspace", {"action": "read_code_file"}, mock_res)
    log_test(
        25, "#28 Error Recovery Regression",
        err_cat == ErrorCategory.FILE_NOT_FOUND,
        f"(Classified error correctly: {err_cat})"
    )

    # -------------------------------------------------------------
    # TEST 26: #27 Proactive Suggestions Regression
    # -------------------------------------------------------------
    is_safe = suggestion_engine.is_safe_action("Open Visual Studio Code")
    log_test(
        26, "#27 Suggestions Regression",
        is_safe is True,
        f"(Safe proactive action validated)"
    )

    # -------------------------------------------------------------
    # TEST 27: #26 Preference Learning Regression
    # -------------------------------------------------------------
    pref_mgr = preference_manager
    pref_mgr.set_explicit_preference("preferred_browser", "edge")
    pref = pref_mgr.get_preference("preferred_browser")
    log_test(
        27, "#26 Preference Learning Regression",
        pref is not None and pref.value == "edge",
        f"(Preferred browser: {pref.value if pref else None})"
    )

    # -------------------------------------------------------------
    # TEST 28: #25 Long-Term Memory Regression
    # -------------------------------------------------------------
    mem_mgr = memory_manager
    ok_mem, _, item = mem_mgr.add_memory("I always use VS Code for coding")
    all_mems = mem_mgr.get_all_memories()
    has_mem = any("VS Code" in m.content for m in all_mems)
    log_test(
        28, "#25 Long-Term Memory Regression",
        ok_mem and has_mem,
        f"(Memory saved & retrieved successfully)"
    )

    # -------------------------------------------------------------
    # TEST 29: #24 Context Awareness Regression
    # -------------------------------------------------------------
    ctx = session_manager.get_working_context()
    log_test(
        29, "#24 Context Awareness Regression",
        isinstance(ctx, dict),
        f"(Context active and tracked)"
    )

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    print("=" * 80)
    pct = (passed_tests / TOTAL_TESTS) * 100
    print(f"RESULTS: {passed_tests}/{TOTAL_TESTS} TESTS PASSED ({pct:.1f}%)")
    print("=" * 80)

    # Cleanup test project
    if test_project_dir.exists():
        shutil.rmtree(test_project_dir, ignore_errors=True)

    if failed_tests > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
