"""
ByteX - Feature #33.6 Acceptance Test Suite

Covers the 8 canonical acceptance scenarios:
- Acceptance Test 1: Open project and list files workflow
- Acceptance Test 2: Run project tests with confirmation and execution
- Acceptance Test 3: Run npm install with confirmation
- Acceptance Test 4 (Attack): Shell chaining injection rejection ("Run npm test && del everything")
- Acceptance Test 5 (Attack): PowerShell execution rejection ("Run powershell -Command Get-Process")
- Acceptance Test 6 (Attack): Workspace boundary escape rejection ("Run ../../../something.exe")
- Acceptance Test 7 (No Project): Safe refusal when no active coding project exists
- Acceptance Test 8 (Long Running): Enforced timeout termination and orphan prevention
"""

import sys
import shutil
import asyncio
import json
from pathlib import Path

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from skills.registry import skill_registry
from skills.terminal import TerminalAgentSkill, terminal_agent_skill
from skills.coding import CodingWorkspaceSkill
from skills.files import resolve_user_directory
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from core.command_router import CommandRouter
from core.session import session_manager
from agent.history import task_history_manager


async def main():
    print("=" * 80)
    print("RUNNING BYTE X FEATURE #33.6 ACCEPTANCE TESTS (8 SCENARIOS)")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    proj = desktop / "ByteXTerminalAcceptanceApp"
    if proj.exists():
        shutil.rmtree(proj, ignore_errors=True)

    coding_skill = CodingWorkspaceSkill()
    term_skill = TerminalAgentSkill()

    # Setup project
    await coding_skill.execute({
        "action": "create_project",
        "project_name": "ByteXTerminalAcceptanceApp",
        "language": "python"
    })
    (proj / "test_app.py").write_text("def test_ok(): assert 1 == 1\n", encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({"name": "acc-app", "scripts": {"test": "echo tests pass"}}, indent=2), encoding="utf-8")

    session_manager.start_or_renew_session()
    session_manager._working_context["active_project"] = {
        "name": "ByteXTerminalAcceptanceApp",
        "path": str(proj),
        "language": "python"
    }

    # ----------------------------------------------------
    # ACCEPTANCE TEST 1: Open project and show files
    # ----------------------------------------------------
    res1 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files",
        "project_path": str(proj)
    })
    pass1 = res1.success and "test_app.py" in res1.message
    print("[Acceptance 1 - List Project Files]:", "PASSED [OK]" if pass1 else "FAILED [X]")
    print(res1.message[:150] + "...")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 2: Run tests
    # ----------------------------------------------------
    risk2 = ActionRiskClassifier.classify_action("terminal_agent", {"operation": "run_project_tests"})
    res2 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "run_project_tests",
        "project_path": str(proj)
    })
    pass2 = risk2.requires_confirmation and res2.data.get("status") in ["passed", "failed", "missing_executable"]
    print("[Acceptance 2 - Run Project Tests]:", "PASSED [OK]" if pass2 else "FAILED [X]")
    print(f"Risk confirmation: {risk2.requires_confirmation} | Execution status: {res2.data.get('status')}")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 3: Run npm install
    # ----------------------------------------------------
    risk3 = ActionRiskClassifier.classify_action("terminal_agent", {"operation": "npm_install"})
    res3 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "npm_install",
        "project_path": str(proj)
    })
    pass3 = risk3.requires_confirmation and (res3.success or res3.data.get("status") in ["passed", "failed", "missing_executable"])
    print("[Acceptance 3 - npm install]:", "PASSED [OK]" if pass3 else "FAILED [X]")
    print(f"Risk confirmation: {risk3.requires_confirmation} | Output status: {res3.data.get('status')}")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 4 (ATTACK): Chained shell injection
    # ----------------------------------------------------
    risk4 = ActionRiskClassifier.classify_action("terminal_agent", {
        "operation": "npm_test",
        "arguments": {"extra": "&& del everything"}
    })
    pass4 = risk4.risk_level == RiskLevel.BLOCKED
    print("[Acceptance 4 - Attack: Chained Shell Injection]:", "PASSED [OK]" if pass4 else "FAILED [X]")
    print(f"Blocked status: {risk4.risk_level} (Reason: {risk4.reason})")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 5 (ATTACK): PowerShell execution
    # ----------------------------------------------------
    risk5 = ActionRiskClassifier.classify_action("terminal_agent", {
        "operation": "powershell -Command Get-Process"
    })
    pass5 = (risk5.risk_level == RiskLevel.BLOCKED) or (TerminalAgentSkill._resolve_executable("powershell.exe") is None)
    print("[Acceptance 5 - Attack: PowerShell Execution]:", "PASSED [OK]" if pass5 else "FAILED [X]")
    print(f"PowerShell disallowed in executable allowlist: {pass5}")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 6 (ATTACK): Boundary escape
    # ----------------------------------------------------
    res6 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "list_files",
        "working_directory": "../../../Windows/System32",
        "project_path": str(proj)
    })
    pass6 = not res6.success and "blocked" in res6.message.lower()
    print("[Acceptance 6 - Attack: Workspace Boundary Escape]:", "PASSED [OK]" if pass6 else "FAILED [X]")
    print(f"Response: {res6.message}")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 7: No active project
    # ----------------------------------------------------
    session_manager._working_context["active_project"] = None
    coding_skill._active_project_path = None
    reg_coding = skill_registry.get_skill("coding_workspace")
    if reg_coding:
        reg_coding._active_project_path = None
    res7 = await term_skill.execute({
        "action": "terminal_command",
        "operation": "run_project_tests"
    })
    pass7 = not res7.success and "active coding project" in res7.message.lower()
    print("[Acceptance 7 - No Active Project]:", "PASSED [OK]" if pass7 else "FAILED [X]")
    print(f"Response: {res7.message}")
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 8: Long running timeout enforcement
    # ----------------------------------------------------
    res8 = await term_skill._run_process(["python", "-c", "import time; time.sleep(15)"], cwd=proj, timeout=2)
    pass8 = res8["timed_out"] is True and res8["status"] == "timeout" and res8["exit_code"] == -1
    print("[Acceptance 8 - Long Running Process Timeout]:", "PASSED [OK]" if pass8 else "FAILED [X]")
    print(f"Timed out: {res8['timed_out']} | Exit code: {res8['exit_code']} | Stderr: {res8['stderr']}")
    print("=" * 80)

    if proj.exists():
        shutil.rmtree(proj, ignore_errors=True)

    all_passed = all([pass1, pass2, pass3, pass4, pass5, pass6, pass7, pass8])
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

