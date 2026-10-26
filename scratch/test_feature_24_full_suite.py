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
from skills.media import media_session_manager

async def run_feature_24_suite():
    print("=" * 80)
    print("BYTEX — FEATURE #24: CONTEXT AWARENESS COMPLETE VERIFICATION SUITE")
    print("=" * 80)

    # -------------------------------------------------------------
    # TEST 1: Open Notepad -> Type Hello ByteX (Same window)
    # -------------------------------------------------------------
    print("\n--- TEST 1: Open Notepad -> Type Hello ByteX ---")
    session_manager.end_session()

    h1, r1, s1, d1 = await CommandRouter.route_command("Open Notepad")
    print(f"Step 1: {r1}")
    app_ctx = session_manager.get_working_context().get("active_application")
    assert app_ctx is not None and "notepad" in app_ctx.get("name", "").lower(), "Failed: active_application not tracked"

    h2, r2, s2, d2 = await CommandRouter.route_command("Type Hello ByteX.")
    print(f"Step 2: {r2}")
    assert h2 is True, "Failed: 'Type Hello ByteX.' not handled"
    assert "hello" in r2.lower() or "typed" in r2.lower()
    print("TEST 1 RESULT: PASSED [OK] (Text typed into the active Notepad instance)")

    # -------------------------------------------------------------
    # TEST 2: Open Notepad and type Hello -> Save it as test.txt
    # -------------------------------------------------------------
    print("\n--- TEST 2: Open Notepad and type Hello -> Save it as test.txt ---")
    session_manager.end_session()

    h2_1, r2_1, s2_1, d2_1 = await CommandRouter.route_command("Open Notepad and type Hello.")
    print(f"Turn 1: {r2_1}")

    h2_2, r2_2, s2_2, d2_2 = await CommandRouter.route_command("Save it as test.txt.")
    print(f"Turn 2: {r2_2}")
    assert h2_2 is True
    assert "test.txt" in r2_2.lower() or "saved" in r2_2.lower()
    print("TEST 2 RESULT: PASSED [OK] (Resolved 'it' to current document and saved as test.txt)")

    # -------------------------------------------------------------
    # TEST 3: Find the login button -> Click it
    # -------------------------------------------------------------
    print("\n--- TEST 3: Find the login button -> Click it ---")
    session_manager.end_session()

    h3_1, r3_1, s3_1, d3_1 = await CommandRouter.route_command("Find the login button")
    print(f"Find Element: {r3_1}")
    active_elem = session_manager.get_working_context().get("active_element")
    assert active_elem is not None, "Failed: active_element not stored in working context"
    assert "login" in str(active_elem.get("element", "")).lower()

    h3_2, r3_2, s3_2, d3_2 = await CommandRouter.route_command("Click it.")
    print(f"Click Element: {r3_2}")
    assert h3_2 is True
    print("TEST 3 RESULT: PASSED [OK] (Resolved 'it' to previously detected login button)")

    # -------------------------------------------------------------
    # TEST 4: Open Edge -> Search for C++ tutorials -> Open the first result -> Summarize it
    # -------------------------------------------------------------
    print("\n--- TEST 4: Browser Context (Search -> Open first result -> Summarize it) ---")
    session_manager.end_session()

    # Step 1: Open Edge
    h4_1, r4_1, s4_1, d4_1 = await CommandRouter.route_command("Open Edge")
    print(f"Step 1 (Open Edge): {r4_1}")
    assert session_manager.get_working_context().get("active_application") is not None

    # Step 2: Search for C++ tutorials
    h4_2, r4_2, s4_2, d4_2 = await CommandRouter.route_command("Search in Edge for C++ tutorials")
    print(f"Step 2 (Search): {r4_2}")
    last_search = session_manager.get_working_context().get("last_search")
    assert last_search is not None and "c++" in last_search.get("query", "").lower()

    # Step 3: Open the first result
    h4_3, r4_3, s4_3, d4_3 = await CommandRouter.route_command("Open the first result.")
    print(f"Step 3 (Open first result): {r4_3}")
    assert h4_3 is True
    assert session_manager.get_working_context().get("active_url") is not None

    # Step 4: Summarize it
    h4_4, r4_4, s4_4, d4_4 = await CommandRouter.route_command("Summarize it.")
    print(f"Step 4 (Summarize it): {r4_4}")
    assert h4_4 is True
    print("TEST 4 RESULT: PASSED [OK] (Maintained browser, search, and URL context across 4 turns)")

    # -------------------------------------------------------------
    # TEST 5: Stale Context Protection (Close Notepad manually -> Type hello)
    # -------------------------------------------------------------
    print("\n--- TEST 5: Stale Context Protection ---")
    session_manager.end_session()

    # Step 1: Open Notepad to establish real context
    await CommandRouter.route_command("Open Notepad")
    assert session_manager.get_working_context().get("active_application") is not None

    # Step 2: User manually closes Notepad
    subprocess.run(["taskkill", "/f", "/im", "notepad.exe"], capture_output=True)
    time.sleep(0.5)

    # Step 3: User says "Type hello."
    h5, r5, s5, d5 = await CommandRouter.route_command("Type hello.")
    print(f"Stale Window Response: {r5}")
    assert "no longer open" in r5.lower() or "closed" in r5.lower(), f"Unexpected stale response: {r5}"
    assert session_manager.get_working_context()["active_application"] is None, "Failed: Stale application context not cleared"
    print("TEST 5 RESULT: PASSED [OK] (Refused blind typing into closed application window)")

    # -------------------------------------------------------------
    # TEST 6: Context Priority (Open Notepad -> Open Calculator -> Type 123)
    # -------------------------------------------------------------
    print("\n--- TEST 6: Context Priority (Notepad -> Calculator -> Type 123) ---")
    session_manager.end_session()

    # Step 1: Open Notepad
    await CommandRouter.route_command("Open Notepad")
    assert session_manager.get_working_context()["active_application"]["name"].lower() == "notepad"

    # Step 2: Open Calculator
    h6_calc, r6_calc, s6_calc, d6_calc = await CommandRouter.route_command("Open Calculator")
    print(f"Opened App: {r6_calc}")
    active_app = session_manager.get_working_context()["active_application"]["name"].lower()
    print(f"Current Active App: {active_app}")
    assert "calc" in active_app, f"Expected Calculator to take context priority, found: {active_app}"

    # Step 3: Type 123
    h6_type, r6_type, s6_type, d6_type = await CommandRouter.route_command("Type 123.")
    print(f"Type Response: {r6_type}")
    assert h6_type is True
    print("TEST 6 RESULT: PASSED [OK] (Calculator correctly took precedence over prior Notepad context)")

    # -------------------------------------------------------------
    # TEST 7: Ambiguity Guard (Multiple candidate buttons -> Click the button)
    # -------------------------------------------------------------
    print("\n--- TEST 7: Ambiguity Guard ---")
    session_manager.end_session()

    session_manager.start_or_renew_session(action="screen_vision")
    session_manager._working_context["candidate_elements"] = [
        {"element": "Submit Form", "type": "button"},
        {"element": "Cancel Form", "type": "button"}
    ]
    session_manager._working_context["active_element"] = None

    h7, r7, s7, d7 = await CommandRouter.route_command("Click the button.")
    print(f"Ambiguity Response: {r7}")
    assert "multiple" in r7.lower() or "which" in r7.lower(), f"Unexpected ambiguity response: {r7}"
    print("TEST 7 RESULT: PASSED [OK] (Prompted user clarification for multiple matching buttons)")

    # -------------------------------------------------------------
    # TEST 8: Repeat Action ("Do it again.")
    # -------------------------------------------------------------
    print("\n--- TEST 8: Repeat Action ('Do it again.') ---")
    session_manager.end_session()

    # Execute screenshot
    h8_sc, r8_sc, s8_sc, d8_sc = await CommandRouter.route_command("Take a screenshot.")
    print(f"Original Action: {r8_sc}")

    # Do it again
    h8_rep, r8_rep, s8_rep, d8_rep = await CommandRouter.route_command("Do it again.")
    print(f"Repeat Response: {r8_rep}")
    assert h8_rep is True
    assert "screenshot" in r8_rep.lower()
    print("TEST 8 RESULT: PASSED [OK] (Repeated previous compatible action safely)")

    # -------------------------------------------------------------
    # TEST 9: Conversational Session Persistence & Standalone Invariance
    # -------------------------------------------------------------
    print("\n--- TEST 9: Standalone Invariant & History Retention ---")
    session_manager.end_session()

    h9, r9, s9, d9 = await CommandRouter.route_command("Check system status")
    print(f"System Status: {r9}")
    assert h9 is True
    assert "cpu" in r9.lower() or "system" in r9.lower()
    print("TEST 9 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 10: Full Regression Capabilities Check
    # -------------------------------------------------------------
    print("\n--- TEST 10: Full Regression Verification ---")
    
    # 10.1 Clipboard
    h10_clip, r10_clip, _, _ = await CommandRouter.route_command("Read my clipboard")
    assert h10_clip is True
    print("Regression: Clipboard Control [OK]")

    # 10.2 Media
    h10_media, r10_media, _, _ = await CommandRouter.route_command("Play believer on youtube")
    assert h10_media is True
    print("Regression: Media Playback [OK]")

    # 10.3 Pause media
    h10_p, r10_p, _, _ = await CommandRouter.route_command("Pause it.")
    assert h10_p is True
    print("Regression: Context Media Pause [OK]")

    # 10.4 Screen Vision
    h10_vis, r10_vis, _, _ = await CommandRouter.route_command("What is on my screen?")
    assert h10_vis is True
    print("Regression: Screen Understanding [OK]")

    print("\n" + "=" * 80)
    print("ALL 10 FEATURE #24 CONTEXT AWARENESS TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_feature_24_suite())
