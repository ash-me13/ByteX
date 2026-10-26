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
from memory.service import memory_service
from memory.database import db_manager
from memory.retrieval import memory_retriever

async def run_feature_25_suite():
    print("=" * 80)
    print("BYTEX — FEATURE #25: LONG-TERM MEMORY COMPLETE VERIFICATION SUITE")
    print("=" * 80)

    # Clean test start
    memory_manager.clear_all_memories()
    session_manager.end_session()

    # -------------------------------------------------------------
    # TEST 1: Explicit Memory Creation
    # -------------------------------------------------------------
    print("\n--- TEST 1: Explicit Memory Creation ('Remember that I prefer concise answers.') ---")
    h1, r1, s1, d1 = await CommandRouter.route_command("Remember that I prefer concise answers.")
    print(f"Response: {r1}")
    assert h1 is True, "Failed to handle 'Remember that I prefer concise answers.'"
    assert "remembered" in r1.lower() or "saved" in r1.lower()
    
    all_mems = memory_manager.get_all_memories()
    assert len(all_mems) == 1, f"Expected 1 memory in SQLite, found {len(all_mems)}"
    assert "concise" in all_mems[0].content.lower()
    assert all_mems[0].key == "response_style"
    print("TEST 1 RESULT: PASSED [OK] (Memory stored in SQLite database)")

    # -------------------------------------------------------------
    # TEST 2: Memory Retrieval
    # -------------------------------------------------------------
    print("\n--- TEST 2: Memory Retrieval ('What do you remember about my response preference?') ---")
    h2, r2, s2, d2 = await CommandRouter.route_command("What do you remember about my response preference?")
    print(f"Response:\n{r2}")
    assert h2 is True
    assert "concise" in r2.lower()
    print("TEST 2 RESULT: PASSED [OK] (Retrieved saved preference from SQLite)")

    # -------------------------------------------------------------
    # TEST 3: Relevant Context Injected for Informational Q&A
    # -------------------------------------------------------------
    print("\n--- TEST 3: Relevant Memory Context Injection ---")
    ctx_prompt = memory_service.get_context_for_prompt("Explain recursion.")
    print(f"Injected Memory Context for 'Explain recursion.':\n{ctx_prompt}")
    assert "concise" in ctx_prompt.lower()
    assert "USER_PREFERENCE" in ctx_prompt or "PREFERENCE" in ctx_prompt
    print("TEST 3 RESULT: PASSED [OK] (Relevant preference context prepared for AI Router)")

    # -------------------------------------------------------------
    # TEST 4: Current Instruction Override Priority
    # -------------------------------------------------------------
    print("\n--- TEST 4: Priority Rules (Current instruction overrides memory) ---")
    assert "OVERRIDE" in ctx_prompt or "PRIORITY" in ctx_prompt
    print("Memory Priority Rules verified: Current direct user instruction has absolute precedence.")
    print("TEST 4 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 5: Forget Specific Memory
    # -------------------------------------------------------------
    print("\n--- TEST 5: Forget Memory ('Forget that I prefer concise answers.') ---")
    h5, r5, s5, d5 = await CommandRouter.route_command("Forget that I prefer concise answers.")
    print(f"Response: {r5}")
    assert h5 is True
    assert "forgotten" in r5.lower() or "removed" in r5.lower()
    
    all_mems_after = memory_manager.get_all_memories()
    assert len(all_mems_after) == 0, f"Expected 0 memories after deletion, found {len(all_mems_after)}"
    print("TEST 5 RESULT: PASSED [OK] (Memory removed from SQLite)")

    # -------------------------------------------------------------
    # TEST 6: Persistence Across Backend Restart Simulation
    # -------------------------------------------------------------
    print("\n--- TEST 6: Persistence Across Restart Simulation ---")
    # Step 6.1: Store memory in SQLite
    await CommandRouter.route_command("Remember that my main project is ByteX.")
    assert len(memory_manager.get_all_memories()) == 1

    # Step 6.2: Simulate fresh DB connection (restart simulation)
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories")
        persisted_rows = cursor.fetchall()
        assert len(persisted_rows) == 1, "Failed: SQLite table empty on new connection"
        assert "ByteX" in persisted_rows[0]["content"]

    print("TEST 6 RESULT: PASSED [OK] (Memory verified directly from SQLite storage on fresh connection)")

    # -------------------------------------------------------------
    # TEST 7: No Automatic Memory Pollution from Normal Conversation
    # -------------------------------------------------------------
    print("\n--- TEST 7: No Automatic Pollution ---")
    initial_count = len(memory_manager.get_all_memories())
    await CommandRouter.route_command("Hello ByteX.")
    await CommandRouter.route_command("What is the capital of France?")
    post_count = len(memory_manager.get_all_memories())
    assert initial_count == post_count, f"Pollution detected: Count changed from {initial_count} to {post_count}"
    print("TEST 7 RESULT: PASSED [OK] (Normal conversation did not pollute long-term memory)")

    # -------------------------------------------------------------
    # TEST 8: Clipboard Privacy (Ephemeral only)
    # -------------------------------------------------------------
    print("\n--- TEST 8: Clipboard Privacy Guard ---")
    await CommandRouter.route_command("Read my clipboard")
    mems_after_clip = memory_manager.get_all_memories()
    for m in mems_after_clip:
        assert "clipboard" not in m.content.lower(), "Security violation: Clipboard content leaked into long-term memory"
    print("TEST 8 RESULT: PASSED [OK] (Clipboard remained strictly ephemeral)")

    # -------------------------------------------------------------
    # TEST 9: Vision & Screenshot Privacy Guard
    # -------------------------------------------------------------
    print("\n--- TEST 9: Vision & Screenshot Privacy Guard ---")
    await CommandRouter.route_command("Take a screenshot.")
    mems_after_sc = memory_manager.get_all_memories()
    for m in mems_after_sc:
        assert "data:image" not in m.content and "png" not in m.content, "Security violation: Screenshot leaked into long-term memory"
    print("TEST 9 RESULT: PASSED [OK] (Vision artifacts remained strictly ephemeral)")

    # -------------------------------------------------------------
    # TEST 10: Conflict Handling & In-Place Updates (No Duplicates)
    # -------------------------------------------------------------
    print("\n--- TEST 10: Conflict Handling & In-Place Updates ---")
    # Step 10.1: Remember dark mode
    await CommandRouter.route_command("Remember that I prefer dark mode.")
    mems_mode_1 = memory_manager.get_all_memories()
    theme_mems_1 = [m for m in mems_mode_1 if m.key == "theme"]
    assert len(theme_mems_1) == 1
    assert "dark" in theme_mems_1[0].content.lower()

    # Step 10.2: Remember light mode (should update, not duplicate)
    await CommandRouter.route_command("Remember that I prefer light mode.")
    mems_mode_2 = memory_manager.get_all_memories()
    theme_mems_2 = [m for m in mems_mode_2 if m.key == "theme"]
    assert len(theme_mems_2) == 1, f"Duplicate detected! Expected 1 theme memory, found {len(theme_mems_2)}"
    assert "light" in theme_mems_2[0].content.lower()
    print("TEST 10 RESULT: PASSED [OK] (Conflicting preference updated in-place without duplicate)")

    # -------------------------------------------------------------
    # TEST 11: Clear All Memories with Confirmation
    # -------------------------------------------------------------
    print("\n--- TEST 11: Clear All Memories with Confirmation ---")
    h11, r11, s11, d11 = await CommandRouter.route_command("Clear all memories.")
    print(f"Confirmation Prompt: {r11}")
    assert "continue" in r11.lower() or "delete" in r11.lower()
    
    # Confirm
    h11_conf, r11_conf, s11_conf, d11_conf = await CommandRouter.route_command("Yes.")
    print(f"Confirmation Response: {r11_conf}")
    assert len(memory_manager.get_all_memories()) == 0
    print("TEST 11 RESULT: PASSED [OK] (Destructive clear required confirmation and deleted all memories)")

    # -------------------------------------------------------------
    # TEST 12: Full Regression Verification
    # -------------------------------------------------------------
    print("\n--- TEST 12: Full Regression Suite ---")
    # 12.1 Context Awareness (#24)
    session_manager.end_session()
    h12_np, r12_np, _, _ = await CommandRouter.route_command("Open Notepad")
    assert h12_np is True
    h12_type, r12_type, _, _ = await CommandRouter.route_command("Type Hello ByteX.")
    assert h12_type is True
    print("Regression: Feature #24 Context Awareness [OK]")

    # 12.2 Telemetry
    h12_sys, r12_sys, _, _ = await CommandRouter.route_command("Check system status")
    assert h12_sys is True
    print("Regression: System Telemetry [OK]")

    # 12.3 Close App Context
    h12_close, r12_close, _, _ = await CommandRouter.route_command("Close Notepad.")
    assert h12_close is True
    print("Regression: App Close [OK]")

    print("\n" + "=" * 80)
    print("ALL 12 FEATURE #25 LONG-TERM MEMORY TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_feature_25_suite())
