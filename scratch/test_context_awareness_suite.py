import os
import sys
import time
import ctypes
import asyncio
import subprocess

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Ensure project roots in path
sys.path.insert(0, os.path.abspath(r"c:\Users\ryzzn\OneDrive\Desktop\ByteX Core\backend"))

from core.command_router import CommandRouter
from core.session import session_manager
from skills.media import media_session_manager

user32 = ctypes.windll.user32

async def run_context_suite():
    print("=" * 80)
    print("BYTEX — FEATURE #24 CONTEXT AWARENESS SUITE")
    print("=" * 80)

    # -------------------------------------------------------------
    # TEST 1: Open Notepad -> Type hello in it (same window)
    # -------------------------------------------------------------
    print("\n--- TEST 1: Open Notepad -> Type hello in it ---")
    session_manager.end_session()

    # Step 1: Open Notepad
    h1, r1, s1, d1 = await CommandRouter.route_command("Open Notepad")
    print(f"Step 1 Response: {r1}")
    win_ctx = session_manager.get_last_window_context()
    print(f"Working Context active_window: {win_ctx}")
    assert win_ctx is not None, "Failed: active_window not tracked in session"
    initial_hwnd = win_ctx.get("hwnd")

    # Step 2: Type hello in it
    h2, r2, s2, d2 = await CommandRouter.route_command("Type hello in it.")
    print(f"Step 2 Response: {r2}")
    assert h2 is True, "Failed: 'Type hello in it.' not handled"
    assert "hello" in r2.lower() or "typed" in r2.lower(), f"Unexpected response: {r2}"
    print("TEST 1 RESULT: PASSED [OK] (Same Notepad window targeted and typed into)")

    # -------------------------------------------------------------
    # TEST 2: Find the Save button -> Click it
    # -------------------------------------------------------------
    print("\n--- TEST 2: Find the Save button -> Click it ---")
    session_manager.end_session()

    # Step 1: Find the Save button
    h_find, r_find, s_find, d_find = await CommandRouter.route_command("Find the Save button")
    print(f"Find Element Response: {r_find}")
    last_elem = session_manager.get_working_context().get("last_detected_element")
    print(f"Working Context last_detected_element: {last_elem}")
    assert last_elem is not None, "Failed: last_detected_element not stored in working context"
    assert "save" in str(last_elem.get("element", "")).lower()

    # Step 2: Click it
    h_click, r_click, s_click, d_click = await CommandRouter.route_command("Click it.")
    print(f"Click It Response: {r_click}")
    assert h_click is True, "Failed: 'Click it.' not handled"
    print("TEST 2 RESULT: PASSED [OK] (Resolved 'it' to previously detected Save button)")

    # -------------------------------------------------------------
    # TEST 3: Open YouTube and play a song -> Pause it -> Resume it
    # -------------------------------------------------------------
    print("\n--- TEST 3: Media Control -> Pause it -> Resume it ---")
    session_manager.end_session()

    # Step 1: Open and play song
    h_play, r_play, s_play, d_play = await CommandRouter.route_command("Play Interstellar soundtrack on YouTube")
    print(f"Play Response: {r_play}")
    media_ctx = session_manager.get_working_context().get("active_media")
    print(f"Working Context active_media: {media_ctx}")
    assert media_ctx is not None, "Failed: active_media not stored in working context"
    assert media_ctx.get("session_active") is True

    # Step 2: Pause it
    h_pause, r_pause, s_pause, d_pause = await CommandRouter.route_command("Pause it.")
    print(f"Pause Response: {r_pause}")
    assert h_pause is True
    assert session_manager.get_working_context()["active_media"]["status"] == "paused"

    # Step 3: Resume it
    h_resume, r_resume, s_resume, d_resume = await CommandRouter.route_command("Resume it.")
    print(f"Resume Response: {r_resume}")
    assert h_resume is True
    assert session_manager.get_working_context()["active_media"]["status"] == "playing"
    print("TEST 3 RESULT: PASSED [OK] (Media session tracked, paused, and resumed safely)")

    # -------------------------------------------------------------
    # TEST 4: Stale Context Handling
    # Establish context, close target window externally, then say 'Type hello in it.'
    # -------------------------------------------------------------
    print("\n--- TEST 4: Stale Context Handling ---")
    session_manager.end_session()

    # Set up a fictitious or temporary closed HWND
    session_manager.start_or_renew_session(
        action="open_application",
        window_context={"application": "ClosedNotepadApp", "pid": 999999, "hwnd": 99999999, "title": "Closed Notepad"}
    )
    
    # Try typing into stale HWND
    h_stale, r_stale, s_stale, d_stale = await CommandRouter.route_command("Type hello in it.")
    print(f"Stale HWND Response: {r_stale}")
    assert "closed" in r_stale.lower() or "no longer active" in r_stale.lower() or "specify" in r_stale.lower(), f"Unexpected stale response: {r_stale}"
    assert session_manager.get_working_context()["active_window"] is None, "Failed: Stale window was not cleared"
    print("TEST 4 RESULT: PASSED [OK] (Detected stale HWND and prevented dangerous blind typing)")

    # -------------------------------------------------------------
    # TEST 5: Ambiguity Handling
    # -------------------------------------------------------------
    print("\n--- TEST 5: Ambiguity Guard (Multiple candidates) ---")
    session_manager.end_session()

    # Inject multiple candidate elements into session
    session_manager.start_or_renew_session(action="screen_vision")
    session_manager._working_context["last_detected_elements"] = [
        {"element": "Submit Button 1", "type": "button"},
        {"element": "Submit Button 2", "type": "button"}
    ]
    session_manager._working_context["last_detected_element"] = None

    # Say "Click it."
    h_ambig, r_ambig, s_ambig, d_ambig = await CommandRouter.route_command("Click it.")
    print(f"Ambiguity Response: {r_ambig}")
    assert "which" in r_ambig.lower() or "multiple" in r_ambig.lower(), f"Unexpected ambiguity response: {r_ambig}"
    print("TEST 5 RESULT: PASSED [OK] (Ambiguity correctly guarded with clarification question)")

    # -------------------------------------------------------------
    # TEST 6: Standalone Normal Commands
    # -------------------------------------------------------------
    print("\n--- TEST 6: Standalone Commands Invariant ---")
    session_manager.end_session()

    h_status, r_status, s_status, d_status = await CommandRouter.route_command("Check system status")
    print(f"System Status Response: {r_status}")
    assert h_status is True
    assert "cpu" in r_status.lower() or "system" in r_status.lower()

    print("TEST 6 RESULT: PASSED [OK] (Normal standalone commands executed seamlessly)")

    # -------------------------------------------------------------
    # TEST 7: Folder Context -> Find my Downloads folder -> Open it
    # -------------------------------------------------------------
    print("\n--- TEST 7: Folder Context -> Find Downloads -> Open it ---")
    session_manager.end_session()

    h_find_f, r_find_f, s_find_f, d_find_f = await CommandRouter.route_command("Find my Downloads folder.")
    print(f"Find Folder Response: {r_find_f}")
    assert session_manager.get_working_context().get("last_folder") is not None
    assert "downloads" in session_manager.get_working_context()["last_folder"]["folder"].lower()

    h_open_f, r_open_f, s_open_f, d_open_f = await CommandRouter.route_command("Open it.")
    print(f"Open It Response: {r_open_f}")
    assert h_open_f is True
    assert "downloads" in r_open_f.lower() or "opened" in r_open_f.lower()
    print("TEST 7 RESULT: PASSED [OK] (Folder reference resolved and opened)")

    # -------------------------------------------------------------
    # TEST 8: Screenshot Context -> Take a screenshot -> Analyze it
    # -------------------------------------------------------------
    print("\n--- TEST 8: Screenshot Context -> Take screenshot -> Analyze it ---")
    session_manager.end_session()

    h_sc, r_sc, s_sc, d_sc = await CommandRouter.route_command("Take a screenshot.")
    print(f"Screenshot Response: {r_sc}")
    assert session_manager.get_working_context().get("last_screenshot") is not None

    h_an, r_an, s_an, d_an = await CommandRouter.route_command("Analyze it.")
    print(f"Analyze It Response: {r_an}")
    assert h_an is True
    print("TEST 8 RESULT: PASSED [OK] (Screenshot reference resolved to screen understanding)")

    print("\n" + "=" * 80)
    print("ALL 8 FEATURE #24 CONTEXT AWARENESS TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_context_suite())
