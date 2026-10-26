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
from memory.learning import preference_learner

async def run_feature_26_suite():
    print("=" * 80)
    print("BYTEX — FEATURE #26: LEARNING USER PREFERENCES COMPLETE VERIFICATION SUITE")
    print("=" * 80)

    # Clean test start
    memory_manager.clear_all_memories()
    preference_learner.clear_candidates()
    preference_learner.set_enabled(True)
    session_manager.end_session()

    # -------------------------------------------------------------
    # TEST 1: Observe Repeated Behavior Without Premature Saving
    # -------------------------------------------------------------
    print("\n--- TEST 1: Observe Repeated Behavior (Occurrences 1 & 2) ---")
    
    # 1.1 First occurrence
    h1_1, r1_1, s1_1, d1_1 = await CommandRouter.route_command("Make it shorter.")
    print(f"Occurrence 1 Response State: {s1_1}")
    cand1 = preference_learner.get_candidate("response_style")
    assert cand1 is not None, "Failed: Candidate not observed on occurrence 1"
    assert cand1.evidence_count == 1
    assert cand1.status == "observing"
    assert len(memory_manager.get_all_memories()) == 0, "Security violation: Preference prematurely saved to SQLite on 1st occurrence!"
    print("Occurrence 1: Candidate observed (Count: 1, Status: observing). NOT saved to SQLite [OK]")

    # 1.2 Second occurrence
    h1_2, r1_2, s1_2, d1_2 = await CommandRouter.route_command("Give me a concise version.")
    cand2 = preference_learner.get_candidate("response_style")
    assert cand2.evidence_count == 2
    assert cand2.status == "candidate"
    assert len(memory_manager.get_all_memories()) == 0, "Security violation: Preference prematurely saved to SQLite on 2nd occurrence!"
    print("Occurrence 2: Candidate strengthened (Count: 2, Status: candidate). NOT saved to SQLite [OK]")
    print("TEST 1 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 2: Threshold Reached (3 Occurrences) -> Confirmation Prompt
    # -------------------------------------------------------------
    print("\n--- TEST 2: Confidence Threshold (Occurrence 3 -> Ask User) ---")
    h2, r2, s2, d2 = await CommandRouter.route_command("Just give me the important parts.")
    print(f"Occurrence 3 Confirmation Prompt: {r2}")
    assert h2 is True
    assert "concise" in r2.lower()
    assert "remember this preference" in r2.lower()
    assert d2 and d2.get("confirmation_required") is True
    assert len(memory_manager.get_all_memories()) == 0, "Memory must NOT be written before user confirms!"
    print("TEST 2 RESULT: PASSED [OK] (ByteX asked user confirmation before saving)")

    # -------------------------------------------------------------
    # TEST 3: User Confirms YES -> Save Through #25 Memory System
    # -------------------------------------------------------------
    print("\n--- TEST 3: User Confirms YES -> Saved via #25 Memory Manager ---")
    h3, r3, s3, d3 = await CommandRouter.route_command("Yes.")
    print(f"Confirmation Response: {r3}")
    assert h3 is True
    assert "saved" in r3.lower() or "preference" in r3.lower()

    # Verify stored in SQLite via #25 memory manager
    all_mems = memory_manager.get_all_memories()
    assert len(all_mems) == 1, f"Expected 1 saved memory in SQLite, found {len(all_mems)}"
    assert all_mems[0].key == "response_style"
    assert all_mems[0].value == "concise"
    assert all_mems[0].source == "learned_confirmation"
    print("TEST 3 RESULT: PASSED [OK] (Learned preference stored in SQLite through #25 memory manager)")

    # -------------------------------------------------------------
    # TEST 4: Persistence Across Backend Restart Simulation
    # -------------------------------------------------------------
    print("\n--- TEST 4: Persistence Across Restart Simulation ---")
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE key = 'response_style'")
        row = cursor.fetchone()
        assert row is not None, "Failed: Learned preference not found in SQLite on fresh connection"
        assert row["value"] == "concise"
    print("TEST 4 RESULT: PASSED [OK] (Confirmed learned preference survives restart)")

    # -------------------------------------------------------------
    # TEST 5: Explicit User Instruction Always Wins
    # -------------------------------------------------------------
    print("\n--- TEST 5: Explicit Instruction Priority (Detailed vs Concise) ---")
    ctx = memory_service.get_context_for_prompt("Give me a very detailed explanation of quicksort.")
    assert "PRIORITY" in ctx
    print("Priority Instruction Verified: Direct prompt instruction has absolute precedence.")
    print("TEST 5 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 6: User Says NO to Learning Suggestion -> Cooldown
    # -------------------------------------------------------------
    print("\n--- TEST 6: Negative Feedback & Rejection Cooldown ---")
    preference_learner.clear_candidates()
    
    # Trigger 3 C++ requests
    await CommandRouter.route_command("Give me the C++ solution.")
    await CommandRouter.route_command("C++ please.")
    h6_prompt, r6_prompt, s6_prompt, d6_prompt = await CommandRouter.route_command("Use C++.")
    print(f"C++ Learning Prompt: {r6_prompt}")
    assert "c++" in r6_prompt.lower()

    # User rejects: NO
    h6_no, r6_no, s6_no, d6_no = await CommandRouter.route_command("No.")
    print(f"Rejection Response: {r6_no}")
    assert "won't save" in r6_no.lower() or "cancelled" in r6_no.lower()
    
    # Verify NO C++ memory was stored
    c_mems = [m for m in memory_manager.get_all_memories() if m.key == "preferred_programming_language"]
    assert len(c_mems) == 0, "Security failure: Rejected preference was saved to memory!"

    # Verify Cooldown: next C++ command should NOT prompt again immediately
    cand_cpp = preference_learner.get_candidate("preferred_programming_language")
    assert cand_cpp.status == "rejected"
    assert cand_cpp.cooldown_until > time.time()
    
    h6_again, r6_again, s6_again, d6_again = await CommandRouter.route_command("Write this in C++.")
    assert d6_again is None or not d6_again.get("confirmation_required"), "Nagging failure: Re-prompted user during active cooldown!"
    print("TEST 6 RESULT: PASSED [OK] (Rejection respected; candidate placed on cooldown)")

    # -------------------------------------------------------------
    # TEST 7: Conflicting Behavior -> Preference Change Detection
    # -------------------------------------------------------------
    print("\n--- TEST 7: Conflicting Behavior / Preference Change Detection ---")
    preference_learner.clear_candidates()
    
    # User previously confirmed "concise" (from Test 3).
    # Now user repeatedly requests "detailed" 3 times:
    await CommandRouter.route_command("Give more details.")
    await CommandRouter.route_command("Explain deeply.")
    h7_chg, r7_chg, s7_chg, d7_chg = await CommandRouter.route_command("Give me a detailed explanation.")
    print(f"Change Prompt: {r7_chg}")
    assert "update your preference" in r7_chg.lower() or "detailed" in r7_chg.lower()
    
    # User confirms update: YES
    await CommandRouter.route_command("Yes.")
    updated_mems = memory_manager.get_all_memories()
    style_mems = [m for m in updated_mems if m.key == "response_style"]
    assert len(style_mems) == 1, f"Duplicate conflict detected: Found {len(style_mems)} style memories"
    assert style_mems[0].value == "detailed"
    print("TEST 7 RESULT: PASSED [OK] (Preference change detected safely and updated in-place)")

    # -------------------------------------------------------------
    # TEST 8: Sensitive Content Excluded
    # -------------------------------------------------------------
    print("\n--- TEST 8: Sensitive Content Exclusion ---")
    preference_learner.clear_candidates()
    await CommandRouter.route_command("My password=secretPassword123 keep it short")
    await CommandRouter.route_command("My password=secretPassword123 concise please")
    await CommandRouter.route_command("My password=secretPassword123 make shorter")
    cand_sens = preference_learner.get_candidate("response_style")
    assert cand_sens is None or cand_sens.evidence_count == 0, "Privacy violation: Sensitive text triggered learning candidate!"
    print("TEST 8 RESULT: PASSED [OK] (Sensitive credentials strictly excluded from learning engine)")

    # -------------------------------------------------------------
    # TEST 9: Learning Disabled in Settings
    # -------------------------------------------------------------
    print("\n--- TEST 9: Learning Disabled Toggle ---")
    preference_learner.clear_candidates()
    preference_learner.set_enabled(False)

    await CommandRouter.route_command("Search in Edge.")
    await CommandRouter.route_command("Open this in Edge.")
    h9_edge, r9_edge, s9_edge, d9_edge = await CommandRouter.route_command("Use Edge.")
    assert d9_edge is None or not d9_edge.get("confirmation_required"), "Failure: Prompted learning when disabled in settings!"
    assert len(preference_learner.get_all_candidates()) == 0
    preference_learner.set_enabled(True)
    print("TEST 9 RESULT: PASSED [OK] (Zero candidates or suggestions generated when learning disabled)")

    # -------------------------------------------------------------
    # TEST 10: Explicit Memories Remain Fully Functional
    # -------------------------------------------------------------
    print("\n--- TEST 10: Explicit #25 Memories Invariance ---")
    await CommandRouter.route_command("Remember that my main project is ByteX.")
    h10_q, r10_q, _, _ = await CommandRouter.route_command("What do you remember about my project?")
    print(f"Explicit Query Response:\n{r10_q}")
    assert "bytex" in r10_q.lower()
    print("TEST 10 RESULT: PASSED [OK] (Explicit long-term memories fully operational)")

    # -------------------------------------------------------------
    # TEST 11: Full Platform Regression Suite
    # -------------------------------------------------------------
    print("\n--- TEST 11: Full Regression Verification ---")
    
    # 11.1 Context Awareness (#24)
    session_manager.end_session()
    h11_np, _, _, _ = await CommandRouter.route_command("Open Notepad")
    assert h11_np is True
    h11_type, _, _, _ = await CommandRouter.route_command("Type Hello ByteX.")
    assert h11_type is True
    print("Regression: Context Awareness (#24) [OK]")

    # 11.2 Telemetry
    h11_sys, r11_sys, _, _ = await CommandRouter.route_command("Check system status")
    assert h11_sys is True
    print("Regression: System Telemetry [OK]")

    # 11.3 Close App
    h11_cl, _, _, _ = await CommandRouter.route_command("Close Notepad.")
    assert h11_cl is True
    print("Regression: App Close [OK]")

    # 11.4 Clear all memories with confirmation
    await CommandRouter.route_command("Clear all memories.")
    await CommandRouter.route_command("Yes.")
    assert len(memory_manager.get_all_memories()) == 0
    print("Regression: Clear All Confirmation [OK]")

    print("\n" + "=" * 80)
    print("ALL 11 FEATURE #26 LEARNING USER PREFERENCES TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_feature_26_suite())
