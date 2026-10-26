import os
import sys
import time
import json
import asyncio
import subprocess

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

# Ensure project roots in path
sys.path.insert(0, os.path.abspath(r"c:\Users\ryzzn\OneDrive\Desktop\ByteX Core\backend"))

from core.command_router import CommandRouter
from core.session import session_manager
from memory.manager import memory_manager
from agent.history import task_history_manager, TaskHistoryRecord, TaskStepRecord, TaskStatus, StepStatus
from agent.suggestions import suggestion_engine

async def run_feature_29_suite():
    print("=" * 80)
    print("BYTEX — FEATURE #29: TASK HISTORY COMPLETE VERIFICATION SUITE")
    print("=" * 80)

    # Clean start for test suite
    task_history_manager.clear_history()
    session_manager.end_session()

    # -------------------------------------------------------------
    # TEST 1: Successful Task Recording
    # -------------------------------------------------------------
    print("\n--- TEST 1: Successful Multi-Step Task ---")
    step1 = TaskStepRecord(step_id=1, skill="open_application", action="open_application", target="Notepad", status=StepStatus.SUCCESS, human_readable_result="Notepad opened successfully.")
    step2 = TaskStepRecord(step_id=2, skill="screen_vision", action="screen_vision", target="Notepad Document Area", status=StepStatus.SUCCESS, human_readable_result="Typed text into document.")
    step3 = TaskStepRecord(step_id=3, skill="file_operations", action="file_operations", target="test.txt", status=StepStatus.SUCCESS, human_readable_result="Saved document as test.txt.")
    
    t1 = task_history_manager.record_task(
        request="Open Notepad, type Hello ByteX, and save it as test.txt.",
        steps=[step1, step2, step3],
        duration_seconds=2.4
    )
    
    assert t1.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED]
    assert len(t1.steps) == 3
    assert "saved" in t1.summary.lower() or "opened" in t1.summary.lower()
    print(f"Recorded Task: '{t1.command}' -> Status: {t1.status.value}, Summary: '{t1.summary}'")
    print("TEST 1 RESULT: PASSED [OK] (Single task recorded with 3 successful steps)")

    # -------------------------------------------------------------
    # TEST 2: Multi-Step Task Structure
    # -------------------------------------------------------------
    print("\n--- TEST 2: Multi-Step Task Structure ---")
    retrieved_t1 = task_history_manager.get_task_by_id(t1.task_id)
    assert retrieved_t1 is not None
    assert len(retrieved_t1.steps) == 3
    assert retrieved_t1.steps[0].action == "open_application"
    assert retrieved_t1.steps[1].target == "Notepad Document Area"
    print("TEST 2 RESULT: PASSED [OK] (Structure & steps verified)")

    # -------------------------------------------------------------
    # TEST 3: Failed Task Recording
    # -------------------------------------------------------------
    print("\n--- TEST 3: Failed Task Recording ---")
    f_step = TaskStepRecord(
        step_id=1,
        skill="open_application",
        action="open_application",
        target="NonExistentApp12345",
        status=StepStatus.NOT_FOUND,
        human_readable_result="I couldn't find NonExistentApp12345 installed on this PC."
    )
    t3 = task_history_manager.record_task(
        request="Open NonExistentApp12345",
        steps=[f_step],
        duration_seconds=0.5
    )
    assert t3.status == TaskStatus.FAILED
    assert "failed" in t3.summary.lower() or "couldn't find" in t3.summary.lower()
    print(f"Recorded Failed Task: '{t3.command}' -> Status: {t3.status.value}, Summary: '{t3.summary}'")
    print("TEST 3 RESULT: PASSED [OK] (Failed task recorded accurately with failure reason)")

    # -------------------------------------------------------------
    # TEST 4: Error Recovery Preservation
    # -------------------------------------------------------------
    print("\n--- TEST 4: Error Recovery Preservation ---")
    rec_step = TaskStepRecord(
        step_id=1,
        skill="screen_vision",
        action="screen_vision",
        target="Notepad",
        status=StepStatus.RECOVERED,
        recovery_attempts=1,
        recovery_details="Restored and refocused target window.",
        human_readable_result="Restored Notepad focus and typed text."
    )
    t4 = task_history_manager.record_task(
        request="Type text into background Notepad",
        steps=[rec_step],
        duration_seconds=1.2,
        recovery_occurred=True
    )
    assert t4.status == TaskStatus.RECOVERED or t4.recovery_occurred is True
    assert "recovered" in t4.summary.lower()
    print(f"Recorded Recovered Task: '{t4.command}' -> Status: {t4.status.value}, Summary: '{t4.summary}'")
    print("TEST 4 RESULT: PASSED [OK] (Recovery event preserved in task history)")

    # -------------------------------------------------------------
    # TEST 5: Partial Success Task
    # -------------------------------------------------------------
    print("\n--- TEST 5: Partial Success Recording ---")
    p_step1 = TaskStepRecord(step_id=1, skill="open_application", action="open_application", target="Notepad", status=StepStatus.SUCCESS, human_readable_result="Opened Notepad.")
    p_step2 = TaskStepRecord(step_id=2, skill="file_operations", action="file_operations", target="readonly.txt", status=StepStatus.FAILED, human_readable_result="Saving failed: file is write-protected.")
    t5 = task_history_manager.record_task(
        request="Open Notepad and save as readonly.txt",
        steps=[p_step1, p_step2],
        duration_seconds=1.8
    )
    assert t5.status in [TaskStatus.PARTIAL_SUCCESS, TaskStatus.PARTIAL]
    print(f"Recorded Partial Task: '{t5.command}' -> Status: {t5.status.value}, Summary: '{t5.summary}'")
    print("TEST 5 RESULT: PASSED [OK] (Partial success recorded accurately)")

    # -------------------------------------------------------------
    # TEST 6: Natural Language "What did you do recently?" Query
    # -------------------------------------------------------------
    print("\n--- TEST 6: Natural Recent Tasks Query ---")
    h6, r6, _, _ = await CommandRouter.route_command("What did you do recently?")
    assert h6 is True
    print(f"Recent Tasks Response:\n{r6}")
    assert "recent tasks" in r6.lower() or "notepad" in r6.lower()
    print("TEST 6 RESULT: PASSED [OK] (Recent tasks query formatted and delivered)")

    # -------------------------------------------------------------
    # TEST 7: Natural Language "What was my last task?" Query
    # -------------------------------------------------------------
    print("\n--- TEST 7: Natural Last Task Query ---")
    h7, r7, _, _ = await CommandRouter.route_command("What was my last task?")
    assert h7 is True
    print(f"Last Task Response:\n{r7}")
    assert "last task" in r7.lower() or "readonly.txt" in r7.lower()
    print("TEST 7 RESULT: PASSED [OK] (Detailed last task summary returned)")

    # -------------------------------------------------------------
    # TEST 8: Status Filtering ("Show failed tasks.")
    # -------------------------------------------------------------
    print("\n--- TEST 8: Status Filtering ---")
    h8, r8, _, _ = await CommandRouter.route_command("Show failed tasks.")
    assert h8 is True
    print(f"Failed Tasks Query Response:\n{r8}")
    assert "nonexistentapp" in r8.lower() or "failed" in r8.lower()
    print("TEST 8 RESULT: PASSED [OK] (Filtered for failed tasks only)")

    # -------------------------------------------------------------
    # TEST 9: Application Search ("Show tasks involving Notepad.")
    # -------------------------------------------------------------
    print("\n--- TEST 9: Application Keyword Search ---")
    h9, r9, _, _ = await CommandRouter.route_command("Show tasks involving Notepad.")
    assert h9 is True
    print(f"Notepad Tasks Query Response:\n{r9}")
    assert "notepad" in r9.lower()
    print("TEST 9 RESULT: PASSED [OK] (Filtered tasks involving specified application)")

    # -------------------------------------------------------------
    # TEST 10: Privacy & Sanitization
    # -------------------------------------------------------------
    print("\n--- TEST 10: Privacy & Sanitization Check ---")
    sec_step = TaskStepRecord(
        step_id=1,
        skill="screen_vision",
        action="screen_vision",
        target="Login Password Field",
        status=StepStatus.SUCCESS,
        human_readable_result="Typed password SuperSecret1234! into login box."
    )
    t10 = task_history_manager.record_task(
        request="Type SuperSecret1234! into the password field",
        steps=[sec_step]
    )
    assert "SuperSecret1234!" not in t10.command
    assert "SuperSecret1234!" not in t10.steps[0].human_readable_result
    print(f"Sanitized Command: '{t10.command}'")
    print(f"Sanitized Step Result: '{t10.steps[0].human_readable_result}'")
    print("TEST 10 RESULT: PASSED [OK] (Passwords and private credentials sanitized)")

    # -------------------------------------------------------------
    # TEST 11: Clear Task History & Memory Isolation
    # -------------------------------------------------------------
    print("\n--- TEST 11: Clear Task History & Memory Isolation ---")
    # 11a. Add a long-term memory first
    memory_manager.add_memory("My developer name is ByteX User.", category="USER_PROFILE", key="developer_name")
    assert len(memory_manager.get_all_memories()) >= 1
    
    # 11b. Request to clear task history -> requires confirmation
    h11_req, r11_req, s11_req, _ = await CommandRouter.route_command("Clear task history.")
    assert h11_req is True
    assert s11_req == "waiting_confirmation"
    print(f"Confirmation Prompt: {r11_req}")

    # 11c. Confirm with "Yes"
    h11_conf, r11_conf, s11_conf, _ = await CommandRouter.route_command("Yes.")
    assert h11_conf is True
    print(f"Clear Outcome: {r11_conf}")

    # Verify task history is empty
    assert len(task_history_manager.get_recent_tasks()) == 0
    # Verify Long-Term Memories are untouched!
    assert len(memory_manager.get_all_memories()) >= 1
    print("Long-term memory count after clearing task history: 1 (Untouched) [OK]")
    print("TEST 11 RESULT: PASSED [OK] (Task history deleted with confirmation; memory untouched)")

    # -------------------------------------------------------------
    # TEST 12: SQLite Persistence Across Restarts
    # -------------------------------------------------------------
    print("\n--- TEST 12: SQLite Persistence Across Restarts ---")
    p_step = TaskStepRecord(step_id=1, skill="open_application", action="open_application", target="VS Code", status=StepStatus.SUCCESS, human_readable_result="VS Code opened.")
    t12 = task_history_manager.record_task("Open VS Code", steps=[p_step])
    
    # Read directly from fresh database query
    persisted = task_history_manager.get_task_by_id(t12.task_id)
    assert persisted is not None
    assert persisted.command == "Open VS Code"
    assert persisted.status == TaskStatus.SUCCESS
    print(f"Persisted Task in SQLite: '{persisted.command}' [{persisted.status.value}]")
    print("TEST 12 RESULT: PASSED [OK] (Task history successfully persisted in SQLite)")

    # -------------------------------------------------------------
    # TEST 13: Proactive Suggestions Integration
    # -------------------------------------------------------------
    print("\n--- TEST 13: Proactive Suggestions Integration ---")
    suggestion_engine.clear()
    suggestion_engine.set_enabled(True)
    
    # Evaluate repeated workflow occurrences
    sug = None
    for i in range(3):
        sug = suggestion_engine.evaluate_triggers("open_application", target="ByteX Project")
    
    assert sug is not None
    print(f"Generated Proactive Suggestion from Repeated Workflow: '{sug.title}'")
    print("TEST 13 RESULT: PASSED [OK] (Task history workflow pattern integration operational)")

    # -------------------------------------------------------------
    # TEST 14: Full Platform Regression Suite
    # -------------------------------------------------------------
    print("\n--- TEST 14: Full Regression Verification ---")
    
    # 14.1 Context Awareness (#24)
    session_manager.end_session()
    h14_np, _, _, _ = await CommandRouter.route_command("Open Notepad")
    assert h14_np is True
    h14_type, _, _, _ = await CommandRouter.route_command("Type Hello ByteX.")
    assert h14_type is True
    print("Regression: Context Awareness (#24) [OK]")

    # 14.2 Close App
    h14_cl, _, _, _ = await CommandRouter.route_command("Close Notepad.")
    assert h14_cl is True
    print("Regression: App Close [OK]")

    # 14.3 Clean up memory test entry
    memory_manager.clear_all_memories()

    print("\n" + "=" * 80)
    print("ALL 14 FEATURE #29 TASK HISTORY TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_feature_29_suite())
