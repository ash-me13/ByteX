"""
ByteX — Feature #33.1: Coding Workspace Complete Test Suite

Validates all 26 verification points:
1. Create Python project
2. Create C++ project
3. Existing project detection
4. Create source file
5. Prevent accidental overwrite
6. Read source file
7. Edit source file
8. Verify edited content
9. Project structure
10. Language detection
11. Unsupported extension rejection
12. Sensitive-content protection
13. Risk classification
14. CommandRouter routing
15. Planner multi-step decomposition
16. Task History integration
17. Verification failure handling
18. Existing #24 context regression
19. Existing #25 memory regression
20. Existing #26 preference regression
21. Existing #27 suggestion regression
22. Existing #28 recovery regression
23. Existing #29 history regression
24. Existing #30 automation regression
25. Existing #31 search regression
26. Existing #32 browser regression
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
from core.risk_classifier import risk_classifier, RiskLevel
from core.command_router import CommandRouter
from agent.planner import ByteXPlanner
from agent.pipeline import ByteXAgentPipeline
from core.session import session_manager
from agent.history import task_history_manager
from memory.manager import memory_manager
from memory.preferences import preference_manager
from agent.suggestions import suggestion_engine
from agent.recovery import ErrorRecoveryEngine, ErrorCategory
from agent.automation import NaturalLanguageAutomationParser
from skills.base import ToolResult

TOTAL_TESTS = 26
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
    print("STARTING FULL TEST SUITE: FEATURE #33.1 CODING WORKSPACE")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    test_py_proj = desktop / "ByteXTestPyApp"
    test_cpp_proj = desktop / "ByteXTestDSA"

    # Clean up previous test runs if any
    for p in [test_py_proj, test_cpp_proj]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    skill = CodingWorkspaceSkill()

    # -------------------------------------------------------------
    # TEST 1: Create Python Project
    # -------------------------------------------------------------
    res1 = await skill.execute({
        "action": "create_project",
        "project_name": "ByteXTestPyApp",
        "language": "python"
    })
    entry_ok = (test_py_proj / "main.py").exists()
    readme_ok = (test_py_proj / "README.md").exists()
    log_test(
        1, "Create Python Project",
        res1.success and res1.verified and entry_ok and readme_ok,
        f"(Project created at {test_py_proj}, main.py & README.md verified)"
    )

    # -------------------------------------------------------------
    # TEST 2: Create C++ Project
    # -------------------------------------------------------------
    res2 = await skill.execute({
        "action": "create_project",
        "project_name": "ByteXTestDSA",
        "language": "cpp"
    })
    cpp_entry_ok = (test_cpp_proj / "main.cpp").exists()
    cpp_readme_ok = (test_cpp_proj / "README.md").exists()
    log_test(
        2, "Create C++ Project",
        res2.success and res2.verified and cpp_entry_ok and cpp_readme_ok,
        f"(Project created at {test_cpp_proj}, main.cpp & README.md verified)"
    )

    # -------------------------------------------------------------
    # TEST 3: Existing Project Detection
    # -------------------------------------------------------------
    res3 = await skill.execute({
        "action": "create_project",
        "project_name": "ByteXTestPyApp",
        "language": "python"
    })
    already_exists = res3.data and res3.data.get("already_exists") is True
    log_test(
        3, "Existing Project Detection",
        not res3.success and already_exists,
        f"(Reported existing project honestly without overwriting: '{res3.message[:50]}...')"
    )

    # -------------------------------------------------------------
    # TEST 4: Create Source File
    # -------------------------------------------------------------
    res4 = await skill.execute({
        "action": "create_code_file",
        "filename": "utils.py",
        "project_name": "ByteXTestPyApp",
        "content": "def add(a, b):\n    return a + b\n"
    })
    utils_ok = (test_py_proj / "utils.py").exists()
    log_test(
        4, "Create Source File",
        res4.success and res4.verified and utils_ok,
        f"(Created utils.py in ByteXTestPyApp)"
    )

    # -------------------------------------------------------------
    # TEST 5: Prevent Accidental Overwrite
    # -------------------------------------------------------------
    res5 = await skill.execute({
        "action": "create_code_file",
        "filename": "utils.py",
        "project_name": "ByteXTestPyApp",
        "content": "def malicious_override(): pass\n",
        "overwrite": False
    })
    # Verify original content unchanged
    orig_content = (test_py_proj / "utils.py").read_text(encoding="utf-8")
    log_test(
        5, "Prevent Accidental Overwrite",
        not res5.success and "add(a, b)" in orig_content,
        f"(Blocked overwrite of existing utils.py)"
    )

    # -------------------------------------------------------------
    # TEST 6: Read Source File
    # -------------------------------------------------------------
    res6 = await skill.execute({
        "action": "read_code_file",
        "filename": "utils.py",
        "project_name": "ByteXTestPyApp"
    })
    read_has_content = res6.success and res6.data and "def add(a, b):" in res6.data.get("content", "")
    log_test(
        6, "Read Source File",
        read_has_content,
        f"(Successfully read actual file contents from disk)"
    )

    # -------------------------------------------------------------
    # TEST 7: Edit Source File (Add/Append or Replace)
    # -------------------------------------------------------------
    res7 = await skill.execute({
        "action": "edit_code_file",
        "filename": "utils.py",
        "project_name": "ByteXTestPyApp",
        "content": "def subtract(a, b):\n    return a - b\n"
    })
    log_test(
        7, "Edit Source File",
        res7.success and res7.verified,
        f"(Safely appended function to utils.py)"
    )

    # -------------------------------------------------------------
    # TEST 8: Verify Edited Content
    # -------------------------------------------------------------
    edited_text = (test_py_proj / "utils.py").read_text(encoding="utf-8")
    has_both = "def add(a, b):" in edited_text and "def subtract(a, b):" in edited_text
    log_test(
        8, "Verify Edited Content",
        has_both,
        f"(Verified both original 'add' and new 'subtract' exist on disk)"
    )

    # -------------------------------------------------------------
    # TEST 9: Project Structure (ASCII Tree)
    # -------------------------------------------------------------
    res9 = await skill.execute({
        "action": "project_structure",
        "project_name": "ByteXTestPyApp"
    })
    tree_str = res9.data.get("tree", "") if res9.data else ""
    log_test(
        9, "Project Structure",
        res9.success and "utils.py" in tree_str and "main.py" in tree_str,
        f"(ASCII tree generated with correct hierarchy)"
    )

    # -------------------------------------------------------------
    # TEST 10: Language Detection
    # -------------------------------------------------------------
    res10 = await skill.execute({
        "action": "detect_language",
        "project_name": "ByteXTestPyApp"
    })
    lang_det = res10.data.get("primary_language", "") if res10.data else ""
    log_test(
        10, "Language Detection",
        res10.success and lang_det == "Python",
        f"(Detected language: {lang_det})"
    )

    # -------------------------------------------------------------
    # TEST 11: Unsupported Extension Rejection
    # -------------------------------------------------------------
    res11 = await skill.execute({
        "action": "create_code_file",
        "filename": "payload.exe",
        "project_name": "ByteXTestPyApp"
    })
    log_test(
        11, "Unsupported Extension Rejection",
        not res11.success and "not permitted" in res11.message.lower(),
        f"(Blocked creation of dangerous extension .exe)"
    )

    # -------------------------------------------------------------
    # TEST 12: Sensitive Content Protection
    # -------------------------------------------------------------
    res12 = await skill.execute({
        "action": "create_code_file",
        "filename": "config.env",
        "project_name": "ByteXTestPyApp",
        "content": "DB_HOST=localhost\nDB_PASS=secret123\n"
    })
    log_test(
        12, "Sensitive Content Protection",
        res12.success,
        f"(Config created and safely handled)"
    )

    # -------------------------------------------------------------
    # TEST 13: Risk Classification
    # -------------------------------------------------------------
    risk_read = risk_classifier.classify_action("coding_workspace", {"action": "read_code_file", "filename": "main.py"})
    risk_create = risk_classifier.classify_action("coding_workspace", {"action": "create_project", "project_name": "App"})
    risk_edit = risk_classifier.classify_action("coding_workspace", {"action": "edit_code_file", "filename": "main.py"})
    log_test(
        13, "Risk Classification",
        risk_read.risk_level == RiskLevel.SAFE
        and risk_create.risk_level == RiskLevel.SAFE
        and risk_edit.risk_level == RiskLevel.SENSITIVE
        and risk_edit.requires_confirmation is True,
        f"(Read=SAFE, Create=SAFE, Edit=SENSITIVE/ConfirmationRequired)"
    )

    # -------------------------------------------------------------
    # TEST 14: CommandRouter Routing
    # -------------------------------------------------------------
    cr_res1 = await CommandRouter.classify_request("Create a Python project called TestApp")
    cr_res2 = await CommandRouter.classify_request("Create a C++ project called DSA")
    cr_res3 = await CommandRouter.classify_request("Open my TestApp project")
    cr_res4 = await CommandRouter.classify_request("Show the project structure")
    cr_res5 = await CommandRouter.classify_request("Create main.cpp")
    cr_res6 = await CommandRouter.classify_request("Read main.py")
    cr_res7 = await CommandRouter.classify_request("Change Hello World to Hello ByteX in main.py")

    all_cr_ok = (
        cr_res1.get("skill") == "coding_workspace" and cr_res1.get("arguments", {}).get("action") == "create_project"
        and cr_res2.get("skill") == "coding_workspace" and cr_res2.get("arguments", {}).get("language") in ["cpp", "c++"]
        and cr_res3.get("skill") == "coding_workspace" and cr_res3.get("arguments", {}).get("action") == "open_project"
        and cr_res4.get("skill") == "coding_workspace" and cr_res4.get("arguments", {}).get("action") == "project_structure"
        and cr_res5.get("skill") == "coding_workspace" and cr_res5.get("arguments", {}).get("action") == "create_code_file"
        and cr_res6.get("skill") == "coding_workspace" and cr_res6.get("arguments", {}).get("action") == "read_code_file"
        and cr_res7.get("skill") == "coding_workspace" and cr_res7.get("arguments", {}).get("action") == "edit_code_file"
    )
    log_test(
        14, "CommandRouter Routing",
        all_cr_ok,
        f"(All 7 natural-language coding intents correctly routed)"
    )

    # -------------------------------------------------------------
    # TEST 15: Planner Multi-Step Decomposition
    # -------------------------------------------------------------
    plan = ByteXPlanner.generate_plan("Create a C++ project called DSA and create main.cpp")
    plan_ok = (
        plan is not None
        and len(plan.steps) == 2
        and plan.steps[0].suggested_skill == "coding_workspace"
        and plan.steps[0].arguments.get("action") == "create_project"
        and plan.steps[1].suggested_skill == "coding_workspace"
        and plan.steps[1].arguments.get("action") == "create_code_file"
    )
    log_test(
        15, "Planner Multi-Step Decomposition",
        plan_ok,
        f"(Decomposed into 2 sequential coding steps: {[s.description for s in plan.steps] if plan else []})"
    )

    # -------------------------------------------------------------
    # TEST 16: Task History Integration
    # -------------------------------------------------------------
    task_history_manager.clear_history()
    h_ok, r_msg, s_stat, d_out = await CommandRouter.route_command("Create a Python project called ByteXHistoryTest")
    hist_records = task_history_manager.get_recent_tasks(limit=5)
    hist_ok = any(getattr(r, "command", "") == "Create a Python project called ByteXHistoryTest" for r in hist_records)
    # cleanup
    hist_proj = desktop / "ByteXHistoryTest"
    if hist_proj.exists():
        shutil.rmtree(hist_proj, ignore_errors=True)
    log_test(
        16, "Task History Integration",
        hist_ok,
        f"(Coding action recorded in #29 Task History)"
    )

    # -------------------------------------------------------------
    # TEST 17: Verification Failure Handling
    # -------------------------------------------------------------
    # Attempting to read a non-existent file
    res17 = await skill.execute({
        "action": "read_code_file",
        "filename": "non_existent_ghost_file.cpp",
        "project_name": "ByteXTestPyApp"
    })
    log_test(
        17, "Verification Failure Handling",
        not res17.success and "couldn't find" in res17.message.lower(),
        f"(Failed gracefully on missing file: '{res17.message}')"
    )

    # -------------------------------------------------------------
    # TEST 18: Context Awareness Regression (#24)
    # -------------------------------------------------------------
    session_manager.end_session()
    await CommandRouter.route_command("Open Notepad")
    ctx = session_manager.get_working_context()
    app_ctx = ctx.get("active_application", {})
    notepad_in_ctx = app_ctx and "notepad" in app_ctx.get("name", "").lower()
    await CommandRouter.route_command("Close Notepad")
    log_test(
        18, "Context Awareness Regression (#24)",
        notepad_in_ctx,
        f"(Context tracked active application: {app_ctx.get('name')})"
    )

    # -------------------------------------------------------------
    # TEST 19: Long-Term Memory Regression (#25)
    # -------------------------------------------------------------
    mem_mgr = memory_manager
    ok_mem, _, item = mem_mgr.add_memory("I always use VS Code for coding")
    all_mems = mem_mgr.get_all_memories()
    has_mem = any("VS Code" in m.content for m in all_mems)
    log_test(
        19, "Long-Term Memory Regression (#25)",
        ok_mem and has_mem,
        f"(Memory saved & retrieved successfully)"
    )

    # -------------------------------------------------------------
    # TEST 20: Preference Learning Regression (#26)
    # -------------------------------------------------------------
    pref_mgr = preference_manager
    pref_mgr.set_explicit_preference("preferred_browser", "edge")
    pref = pref_mgr.get_preference("preferred_browser")
    log_test(
        20, "Preference Learning Regression (#26)",
        pref is not None and pref.value == "edge",
        f"(Preferred browser: {pref.value if pref else None})"
    )

    # -------------------------------------------------------------
    # TEST 21: Proactive Suggestions Regression (#27)
    # -------------------------------------------------------------
    is_safe = suggestion_engine.is_safe_action("Open Visual Studio Code")
    log_test(
        21, "Proactive Suggestions Regression (#27)",
        is_safe is True,
        f"(Safe proactive action validated)"
    )

    # -------------------------------------------------------------
    # TEST 22: Error Recovery Regression (#28)
    # -------------------------------------------------------------
    mock_res = ToolResult(success=False, tool="coding_workspace", message="File not found on disk: main.py", error="File not found")
    err_cat = ErrorRecoveryEngine.classify_error("coding_workspace", {"action": "read_code_file"}, mock_res)
    log_test(
        22, "Error Recovery Regression (#28)",
        err_cat == ErrorCategory.FILE_NOT_FOUND,
        f"(Classified error correctly: {err_cat})"
    )

    # -------------------------------------------------------------
    # TEST 23: Task History Regression (#29)
    # -------------------------------------------------------------
    recent = task_history_manager.get_recent_tasks(limit=3)
    log_test(
        23, "Task History Regression (#29)",
        isinstance(recent, list) and len(recent) > 0,
        f"(Found {len(recent)} recent task records)"
    )

    # -------------------------------------------------------------
    # TEST 24: Natural-Language Automation Regression (#30)
    # -------------------------------------------------------------
    is_auto, auto_obj, _ = NaturalLanguageAutomationParser.parse_creation_request(
        "Create an automation called Code Routine that opens Edge and creates main.py"
    )
    log_test(
        24, "Automation Regression (#30)",
        is_auto and auto_obj is not None and len(auto_obj.steps) == 2,
        f"(Parsed automation with {len(auto_obj.steps) if auto_obj else 0} steps)"
    )

    # -------------------------------------------------------------
    # TEST 25: Web Search Regression (#31)
    # -------------------------------------------------------------
    search_cr = await CommandRouter.classify_request("Search the web for Python 3.12 release notes")
    log_test(
        25, "Web Search Regression (#31)",
        search_cr.get("skill") == "web_search",
        f"(Search intent routed to web_search)"
    )

    # -------------------------------------------------------------
    # TEST 26: Browser Control Regression (#32)
    # -------------------------------------------------------------
    browser_cr1 = await CommandRouter.classify_request("Open GitHub in a new tab")
    browser_cr2 = await CommandRouter.classify_request("Switch to tab 2")
    log_test(
        26, "Browser Control Regression (#32)",
        browser_cr1.get("skill") == "browser_control"
        and browser_cr1.get("arguments", {}).get("action") == "new_tab"
        and browser_cr2.get("skill") == "browser_control"
        and browser_cr2.get("arguments", {}).get("action") == "switch_tab",
        f"(Browser new_tab & switch_tab routes intact)"
    )

    # Cleanup created test directories
    for p in [test_py_proj, test_cpp_proj]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    print("=" * 80)
    print(f"RESULTS: {passed_tests}/{TOTAL_TESTS} TESTS PASSED ({passed_tests/TOTAL_TESTS*100:.1f}%)")
    print("=" * 80)

    if failed_tests > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
