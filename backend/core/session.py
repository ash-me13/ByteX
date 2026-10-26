import time
import os
import re
import logging
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import sys
import subprocess
import psutil

logger = logging.getLogger("bytex.session")

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

user32 = None
if IS_WINDOWS and hasattr(ctypes, "windll"):
    try:
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.IsWindow.restype = ctypes.c_bool
    except Exception as e:
        logger.warning(f"Failed to initialize user32 on Windows: {e}")

DEFAULT_SESSION_TIMEOUT_SECONDS = 15.0

class ConversationalSessionManager:
    """
    Feature #24: Context Awareness & Conversational Session Manager for ByteX.

    Maintains volatile, structured session working context allowing natural conversational
    references across turns ("it", "this", "that", "there", "the app", "the window",
    "the document", "the file", "the button", "the search box", "the first result",
    "same app", "same window", "do it again", "continue").

    Security & Structural Invariants:
    1. Volatile & Session-Scoped: Never pollutes permanent ByteX Memory store.
    2. Strict Timeout: Automatically expires after inactivity (default 15s) and requires wake word.
    3. Strict Context Validation: Verifies HWND existence, file existence, and media session before resolving.
    4. Stale-Context Protection: Refuses to interact with closed windows/documents safely with clear notice.
    5. Ambiguity Guard: If multiple referents exist or referent is missing, asks for clarification.
    6. Context Priority: Explicit user targets > Current active app > Recent actions > Elements > Session history.
    7. Zero LLM Overhead: Fully deterministic, fast rule-based resolver executed BEFORE command dispatch.
    8. Security Invariant: Context resolution never bypasses permission checks or risk classification.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self._is_active: bool = False
        self._last_activity_time: float = 0.0
        self._turn_count: int = 0

        # Structured Working Context Model
        self._working_context: Dict[str, Any] = {
            "active_application": None,     # {"name": str, "pid": int, "hwnd": int, "title": str, "status": str}
            "active_window": None,          # {"title": str, "hwnd": int, "pid": int}
            "active_document": None,        # {"name": str, "path": str, "type": str, "content": str}
            "active_url": None,             # str (e.g. "https://www.w3schools.com/cpp/")
            "active_browser": None,         # {"browser": str, "url": str, "domain": str, "title": str}
            "active_element": None,         # {"element": str, "type": str, "bbox": dict, "center": dict, "confidence": float, "window": str}
            "candidate_elements": [],       # list of candidate elements (for ambiguity detection)
            "last_search": None,            # {"query": str, "service": str, "results": list, "selected_result": str}
            "active_media": None,           # {"title": str, "status": str, "service": str, "session_active": bool}
            "last_screenshot": None,        # {"path": str, "timestamp": float, "exists": bool}
            "last_action": None,            # {"skill": str, "action": str, "target": str, "result": str, "arguments": dict}
            "last_successful_target": None, # str
            "last_location": None,          # str
            "conversation_references": []   # list of recent entity references
        }

    # Backward compatibility properties
    @property
    def _last_target(self) -> Optional[str]:
        return self._working_context.get("last_successful_target")

    @_last_target.setter
    def _last_target(self, val: Optional[str]):
        self._working_context["last_successful_target"] = val

    @property
    def _last_action(self) -> Optional[str]:
        la = self._working_context.get("last_action")
        return la.get("skill") if isinstance(la, dict) else la

    @_last_action.setter
    def _last_action(self, val: Optional[str]):
        if isinstance(self._working_context.get("last_action"), dict):
            self._working_context["last_action"]["skill"] = val
        else:
            self._working_context["last_action"] = {"skill": val, "action": val, "target": None, "result": None, "arguments": {}}

    @property
    def _last_location(self) -> Optional[str]:
        return self._working_context.get("last_location")

    @_last_location.setter
    def _last_location(self, val: Optional[str]):
        self._working_context["last_location"] = val

    @property
    def _last_window_context(self) -> Optional[Dict[str, Any]]:
        return self._working_context.get("active_window")

    @_last_window_context.setter
    def _last_window_context(self, val: Optional[Dict[str, Any]]):
        self._working_context["active_window"] = val

    def is_session_active(self) -> bool:
        """Checks if current conversational session is active and unexpired."""
        if not self._is_active:
            return False

        elapsed = time.time() - self._last_activity_time
        if elapsed > self.timeout_seconds:
            print(f"[ByteX Session] Session expired after {elapsed:.1f}s of inactivity. Returning to normal wake-word mode.")
            self.end_session()
            return False
        return True

    def end_session(self):
        """Ends active conversation session and resets volatile working context."""
        self._is_active = False
        self._turn_count = 0
        self._last_activity_time = 0.0
        self._working_context = {
            "active_application": None,
            "active_window": None,
            "active_document": None,
            "active_url": None,
            "active_browser": None,
            "active_element": None,
            "candidate_elements": [],
            "last_search": None,
            "active_media": None,
            "last_screenshot": None,
            "last_action": None,
            "last_successful_target": None,
            "last_location": None,
            "conversation_references": []
        }

    def reset(self):
        """Resets conversational session manager state."""
        self.end_session()

    def start_or_renew_session(
        self,
        target: Optional[str] = None,
        action: Optional[str] = None,
        location: Optional[str] = None,
        window_context: Optional[Dict[str, Any]] = None
    ):
        """Starts or extends active conversation session window."""
        self._is_active = True
        self._last_activity_time = time.time()
        self._turn_count += 1
        if target:
            self._working_context["last_successful_target"] = target
        if location:
            self._working_context["last_location"] = location
        if window_context:
            self._working_context["active_window"] = window_context
            app_name = window_context.get("application", "")
            self._working_context["active_application"] = {
                "name": app_name,
                "pid": window_context.get("pid", 0),
                "hwnd": window_context.get("hwnd", 0),
                "title": window_context.get("title", ""),
                "status": "running"
            }
        print(f"[ByteX Session] Session active (Turn {self._turn_count}, Target: {self._working_context.get('last_successful_target')}, Timeout: {self.timeout_seconds}s)")

    def record_action_result(self, action_name: str, arguments: Dict[str, Any], result: Any):
        """
        Authoritatively updates working context based on executed tool and verified result.
        """
        self.start_or_renew_session(action=action_name)
        data = result.data if hasattr(result, "data") and isinstance(result.data, dict) else {}
        target_str = arguments.get("application") or arguments.get("target") or arguments.get("query") or arguments.get("filename") or arguments.get("url") or (data.get("url") if isinstance(data, dict) else None)

        # Update last_action record
        self._working_context["last_action"] = {
            "skill": action_name,
            "action": arguments.get("action", action_name),
            "target": str(target_str) if target_str else None,
            "result": getattr(result, "message", ""),
            "arguments": dict(arguments)
        }
        if target_str:
            self._working_context["last_successful_target"] = str(target_str)

        # 1. Application & Window Context
        if action_name in ["open_application", "open_app"]:
            app_name = data.get("application") or arguments.get("application", "")
            pid = data.get("pid", 0)
            hwnd = data.get("hwnd", 0)
            title = data.get("title", "")
            if app_name or hwnd:
                app_info = {
                    "name": app_name,
                    "pid": pid,
                    "hwnd": hwnd,
                    "title": title,
                    "status": "running"
                }
                win_info = {
                    "title": title,
                    "hwnd": hwnd,
                    "pid": pid
                }
                self._working_context["active_application"] = app_info
                self._working_context["active_window"] = win_info
                self._working_context["last_successful_target"] = app_name
                self._add_conversation_reference("application", app_name, app_info)

        elif action_name in ["close_application", "close_app"]:
            closed_app = data.get("application") or arguments.get("application", "")
            if self._working_context.get("active_application") and self._working_context["active_application"].get("name", "").lower() == str(closed_app).lower():
                self._working_context["active_application"] = None
                self._working_context["active_window"] = None

        # 2. Browser & Web Navigation Context (Feature #32)
        elif action_name in ["browser_control", "browser"]:
            browser_name = data.get("browser") or arguments.get("browser", "edge")
            url = data.get("url") or arguments.get("url", "")
            title = data.get("title") or data.get("destination", "")
            tab_id = data.get("tab_id")
            tab_idx = data.get("index", 0)
            pid = data.get("pid")
            hwnd = data.get("hwnd")
            cdp_port = data.get("cdp_port", 9222)
            query = arguments.get("query", "")
            action_type = data.get("action") or arguments.get("action", "")

            # Set active_browser model
            b_info = {
                "browser": browser_name,
                "pid": pid,
                "hwnd": hwnd,
                "cdp_port": cdp_port,
                "url": url,
                "title": title,
                "tab_id": tab_id,
                "index": tab_idx
            }
            self._working_context["active_browser"] = b_info
            self._working_context["active_application"] = {
                "name": browser_name,
                "pid": pid,
                "hwnd": hwnd,
                "title": title
            }

            # Set active_tab model
            if tab_id or url:
                t_info = {
                    "tab_id": tab_id,
                    "title": title,
                    "url": url,
                    "index": tab_idx
                }
                self._working_context["active_tab"] = t_info

            if url:
                self._working_context["active_url"] = url
                self._working_context["last_successful_target"] = url
                self._add_conversation_reference("url", url, b_info)

            self._working_context["last_browser_action"] = action_type

            if action_type == "search" and query:
                s_info = {
                    "query": query,
                    "engine": arguments.get("engine", "google"),
                    "service": arguments.get("engine", "google"),
                    "results": data.get("results", [
                        {"index": 1, "title": f"{query} Top Result", "url": f"https://www.google.com/search?q={query}", "domain": "google.com", "snippet": ""}
                    ]),
                    "selected_result": None
                }
                self._working_context["last_search"] = s_info
                self._working_context["last_successful_target"] = query
                self._add_conversation_reference("search", query, s_info)

        # 2.5. Dedicated Web Search Context (Feature #31)
        elif action_name in ["web_search", "search_web", "search"]:
            query = arguments.get("query") or data.get("query") or ""
            results_list = data.get("results", [])
            engine = arguments.get("engine") or data.get("engine", "google")
            s_info = {
                "query": query,
                "engine": engine,
                "service": engine,
                "provider": data.get("provider", "duckduckgo"),
                "timestamp": data.get("timestamp") or time.time(),
                "results": results_list,
                "selected_result": None
            }
            self._working_context["last_search"] = s_info
            self._working_context["last_successful_target"] = query
            self._add_conversation_reference("search", query, s_info)

        # 3. Read Webpage Context
        elif action_name in ["read_webpage", "reader"]:
            url = data.get("url") or arguments.get("url", "")
            if url:
                self._working_context["active_url"] = url
                doc_info = {
                    "name": data.get("title") or url,
                    "path": url,
                    "type": "webpage",
                    "content": data.get("content", "")
                }
                self._working_context["active_document"] = doc_info
                self._working_context["last_successful_target"] = url
                self._add_conversation_reference("document", url, doc_info)

        # 4. Screenshot Context
        elif action_name in ["take_screenshot", "screenshot"]:
            path = data.get("path") or arguments.get("path")
            sc_info = {
                "path": path,
                "timestamp": time.time(),
                "exists": True
            }
            self._working_context["last_screenshot"] = sc_info
            self._working_context["last_successful_target"] = path
            self._add_conversation_reference("screenshot", path, sc_info)

        # 4.5. Coding Workspace Context (Feature #33.1)
        elif action_name in ["coding_workspace", "coding", "code"]:
            proj_name = data.get("project_name") or arguments.get("project_name")
            proj_path = data.get("project_path") or data.get("path")
            lang = data.get("language") or data.get("primary_language")
            filename = data.get("filename") or arguments.get("filename")

            if proj_name or proj_path:
                p_info = {
                    "name": proj_name,
                    "path": proj_path,
                    "language": lang,
                    "entry_point": data.get("entry_point")
                }
                self._working_context["active_project"] = p_info
                self._add_conversation_reference("project", proj_name or proj_path, p_info)

            if filename:
                doc_info = {
                    "name": filename,
                    "path": data.get("path") or filename,
                    "type": "code",
                    "language": data.get("language") or lang,
                    "content": data.get("content", "")
                }
                self._working_context["active_document"] = doc_info
                self._working_context["last_successful_target"] = filename
                self._add_conversation_reference("document", filename, doc_info)

            # Record execution result context for #33.3 and #33.4 diagnosis
            act_type = arguments.get("action", "")
            if act_type in ["execute_code", "run_code", "compile_and_run", "execute", "run"] or "exit_code" in data or "timed_out" in data:
                exec_info = {
                    "file": filename or data.get("file"),
                    "path": data.get("path") or filename,
                    "language": lang or data.get("language"),
                    "stage": data.get("stage", "runtime"),
                    "exit_code": data.get("exit_code"),
                    "stdout": data.get("stdout", ""),
                    "stderr": data.get("stderr", ""),
                    "timed_out": data.get("timed_out", False),
                    "compiled": data.get("compiled", False),
                    "success": data.get("success", False),
                    "duration_seconds": data.get("duration_seconds", 0.0),
                    "timestamp": time.time()
                }
                self._working_context["last_execution"] = exec_info
                self._add_conversation_reference("execution", filename or "code_execution", exec_info)

        # 5. Screen Vision & UI Element Context
        elif action_name in ["screen_vision", "vision"]:
            sub_action = arguments.get("action")
            if sub_action == "detect_element" and (data.get("found") or data.get("element") or getattr(result, "success", False)):
                elem_info = {
                    "element": data.get("element", arguments.get("target")),
                    "type": data.get("type", "button"),
                    "center": data.get("center", {}),
                    "bbox": data.get("bbox", {}),
                    "confidence": data.get("confidence", 0.9),
                    "window": data.get("window", "")
                }
                self._working_context["active_element"] = elem_info
                self._working_context["candidate_elements"] = [elem_info]
                self._working_context["last_successful_target"] = elem_info["element"]
                self._add_conversation_reference("element", elem_info["element"], elem_info)
            elif sub_action == "detect_element" and data.get("multiple"):
                self._working_context["candidate_elements"] = data.get("elements", [])
                self._working_context["active_element"] = None
            elif sub_action == "click":
                target_elem = arguments.get("target") or "element"
                self._working_context["last_successful_target"] = target_elem
            elif sub_action == "type":
                typed_text = arguments.get("text", "")
                self._working_context["last_successful_target"] = typed_text

        # 6. Media Playback Context
        elif action_name in ["play_media", "media"]:
            media_action = arguments.get("action", "play")
            title = arguments.get("query") or data.get("title") or "media"
            if media_action == "play":
                m_info = {
                    "title": title,
                    "status": "playing",
                    "service": "youtube",
                    "session_active": True
                }
                self._working_context["active_media"] = m_info
                self._working_context["last_successful_target"] = title
                self._add_conversation_reference("media", title, m_info)
            elif media_action == "pause":
                if self._working_context.get("active_media"):
                    self._working_context["active_media"]["status"] = "paused"
            elif media_action in ["resume", "play"]:
                if self._working_context.get("active_media"):
                    self._working_context["active_media"]["status"] = "playing"
            elif media_action == "stop":
                if self._working_context.get("active_media"):
                    self._working_context["active_media"]["session_active"] = False

        # 7. File & Document Context
        elif action_name in ["file_search", "list_files", "file_operations", "create_folder"]:
            fn = arguments.get("filename") or data.get("filename")
            folder_name = arguments.get("folder") or arguments.get("folder_name") or data.get("folder")
            path = data.get("path") or arguments.get("path")
            if fn:
                ext = Path(fn).suffix.lstrip(".").lower() if fn else "txt"
                doc_info = {
                    "name": fn,
                    "path": path or fn,
                    "type": ext,
                    "content": arguments.get("content", "")
                }
                self._working_context["active_document"] = doc_info
                self._working_context["last_successful_target"] = fn
                self._add_conversation_reference("document", fn, doc_info)
            if folder_name or action_name == "create_folder":
                self._working_context["last_location"] = folder_name or "folder"
                self._working_context["last_successful_target"] = folder_name or "folder"

    def _add_conversation_reference(self, ref_type: str, name: str, details: Any):
        """Maintains chronologically ordered volatile reference history."""
        refs = self._working_context.get("conversation_references", [])
        refs.append({
            "type": ref_type,
            "name": name,
            "details": details,
            "timestamp": time.time()
        })
        # Keep recent 10 references
        self._working_context["conversation_references"] = refs[-10:]

    # Context Validation Methods
    def validate_active_window(self) -> Tuple[bool, Optional[str]]:
        """
        Verifies that the stored active window still physically exists on Windows.
        Returns: (is_valid, failure_reason)
        """
        win_ctx = self._working_context.get("active_window")
        app_ctx = self._working_context.get("active_application")

        if not win_ctx and not app_ctx:
            return False, "no_window"

        hwnd = (win_ctx or {}).get("hwnd", 0) or (app_ctx or {}).get("hwnd", 0)
        pid = (win_ctx or {}).get("pid", 0) or (app_ctx or {}).get("pid", 0)
        app_name = ((app_ctx or {}).get("name") or (win_ctx or {}).get("application") or "").lower()

        if not hwnd and not pid:
            return False, "no_hwnd"

        if not IS_WINDOWS or user32 is None:
            # On macOS / non-Windows, validate via PID or process name
            if pid and psutil.pid_exists(pid):
                return True, None
            if app_name:
                for proc in psutil.process_iter(["name", "pid"]):
                    try:
                        pname = (proc.info["name"] or "").lower()
                        if app_name in pname:
                            if self._working_context.get("active_window"):
                                self._working_context["active_window"]["pid"] = proc.info["pid"]
                            if self._working_context.get("active_application"):
                                self._working_context["active_application"]["pid"] = proc.info["pid"]
                            return True, None
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            display_name = (app_ctx or {}).get("name") or (win_ctx or {}).get("application") or "target"
            print(f"[ByteX ContextResolver] Stale context: Process for '{display_name}' no longer exists.")
            self._working_context["active_window"] = None
            self._working_context["active_application"] = None
            return False, f"The {display_name} application I was working with is no longer running."

        # Check with interactive default desktop context on Windows
        h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not h_default:
            h_default = user32.OpenInputDesktop(0, False, 0x01FF)

        old_desk = None
        if h_default:
            old_desk = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
            user32.SetThreadDesktop(h_default)

        try:
            if hwnd and user32.IsWindow(hwnd):
                return True, None
            # Check if process is still running with matching windows
            from skills.apps import find_visible_windows_on_default_desktop
            matching = find_visible_windows_on_default_desktop([app_name] if app_name else ["notepad"])
            if matching:
                new_hwnd, new_pid, proc, title = matching[0]
                if self._working_context.get("active_window"):
                    self._working_context["active_window"]["hwnd"] = new_hwnd
                    self._working_context["active_window"]["pid"] = new_pid
                    self._working_context["active_window"]["title"] = title
                if self._working_context.get("active_application"):
                    self._working_context["active_application"]["hwnd"] = new_hwnd
                    self._working_context["active_application"]["pid"] = new_pid
                    self._working_context["active_application"]["title"] = title
                return True, None
        finally:
            if h_default and old_desk:
                user32.SetThreadDesktop(old_desk)
                user32.CloseDesktop(h_default)

        display_name = (app_ctx or {}).get("name") or (win_ctx or {}).get("application") or "target"
        print(f"[ByteX ContextResolver] Stale context: Window HWND {hwnd} ('{display_name}') no longer exists.")
        self._working_context["active_window"] = None
        self._working_context["active_application"] = None
        return False, f"The {display_name} window I was working with is no longer open."

    def ensure_active_window_focused(self) -> bool:
        """
        Verifies that the tracked window HWND still exists and restores/focuses it.
        """
        win_ctx = self._working_context.get("active_window") or self._working_context.get("active_application")
        if not win_ctx:
            return False
        hwnd = win_ctx.get("hwnd", 0)
        if not hwnd:
            return False

        is_valid, _ = self.validate_active_window()
        if not is_valid:
            return False

        hwnd = (self._working_context.get("active_window") or {}).get("hwnd", 0)
        app_name = ((self._working_context.get("active_application") or {}).get("name") or
                    (self._working_context.get("active_window") or {}).get("application") or "").strip()

        if not IS_WINDOWS or user32 is None:
            if IS_MACOS and app_name:
                try:
                    from core.applescript import activate_application
                    ok, _ = activate_application(app_name, timeout=2.0)
                    time.sleep(0.08)
                    return ok
                except Exception as e:
                    logger.warning(f"Failed to activate application {app_name} on macOS: {e}")
                    return False
            return True

        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9) # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SwitchToThisWindow(hwnd, True)
            time.sleep(0.08)
            title = (self._working_context.get("active_window") or {}).get("title", "")
            print(f"[ByteX Session] Verified & activated target HWND {hwnd} ('{title}')")
            return True
        except Exception as e:
            logger.warning(f"Failed to activate target HWND {hwnd}: {e}")
            return False

    def get_last_window_context(self) -> Optional[Dict[str, Any]]:
        """Returns the most recent application window context if valid."""
        if not self.is_session_active():
            return None
        is_valid, _ = self.validate_active_window()
        if not is_valid:
            return None
        return self._working_context.get("active_window")

    def get_working_context(self) -> Dict[str, Any]:
        """Returns read-only copy of current working context."""
        return dict(self._working_context)

    def set_working_context(self, context_dict: Dict[str, Any]):
        """Sets or updates working context entries."""
        self._is_active = True
        self._last_activity_time = time.time()
        self._working_context.update(context_dict)

    def end_session(self):
        """Cleanly wipes temporary conversational session working context."""
        self._is_active = False
        self._last_activity_time = 0.0
        self._turn_count = 0
        for k in self._working_context:
            if isinstance(self._working_context[k], list):
                self._working_context[k] = []
            else:
                self._working_context[k] = None
        print("[ByteX Session] Conversational session reset to IDLE.")

    def reset_session(self):
        """Alias for end_session."""
        self.end_session()

    def get_turn_count(self) -> int:
        """Returns the current session turn count."""
        return self._turn_count

    def record_interaction(self, message: str):
        """Records a user interaction in the active session."""
        self.start_or_renew_session()
        self._working_context["last_successful_target"] = message

    def resolve_follow_up(self, message: str) -> str:
        """
        Feature #24 Context Resolver:
        Resolves conversational follow-up prefixes, pronouns ("it", "this", "that", "there",
        "the app", "the window", "the document", "the file", "the button", "the search box",
        "the first result", "same app", "same window", "do it again", "continue")
        against active working context BEFORE execution.
        """
        clean = message.strip()
        clean_lower = clean.lower()

        # 1. Strip leading conversational connectors
        clean = re.sub(r"^(?:and\s+|then\s+|now\s+|also\s+|after\s+that\s+|next\s+)", "", clean, flags=re.IGNORECASE).strip()
        clean_lower = clean.lower()
        clean_nopunct = re.sub(r"[.!?,\"\']+$", "", clean_lower).strip()

        # -------------------------------------------------------------
        # PATTERN 1: REPEAT ACTION ("do it again", "again", "repeat that")
        # -------------------------------------------------------------
        if clean_nopunct in ["do it again", "again", "repeat", "repeat that", "repeat it", "do that again", "one more time"]:
            last_act = self._working_context.get("last_action")
            if last_act and isinstance(last_act, dict) and last_act.get("skill"):
                skill_name = last_act["skill"]
                args = last_act.get("arguments", {})
                print(f"[ByteX ContextResolver] Resolved 'do it again' -> Repeating {skill_name}")
                if skill_name == "open_application":
                    app = args.get("application", "")
                    return f"open {app}"
                elif skill_name == "screen_vision" and args.get("action") == "type":
                    txt = args.get("text", "")
                    return f"type {txt}"
                elif skill_name == "screen_vision" and args.get("action") == "click":
                    tgt = args.get("target", "element")
                    return f"click {tgt}"
                elif skill_name == "take_screenshot":
                    return "take a screenshot"
                elif skill_name == "system_status":
                    return "check system status"
                elif skill_name == "play_media":
                    act = args.get("action", "play")
                    return f"{act} media"
                elif skill_name == "browser_control" and args.get("action") == "search":
                    q = args.get("query", "")
                    return f"search google for {q}"
                elif skill_name == "file_operations" and args.get("operation") == "create_file":
                    fn = args.get("filename", "file.txt")
                    floc = args.get("folder", "desktop")
                    cnt = args.get("content", "")
                    return f"create a file named {fn} on the {floc} containing {cnt}"
            return "AMBIGUOUS_FOLLOWUP: There is no previous action to repeat."

        # -------------------------------------------------------------
        # PATTERN 2: TYPE IN IT / WRITE IN IT / ADD TEXT (Conversational Continuity)
        # E.g. "Type Hello ByteX.", "Add world.", "Type my username.", "Type 123."
        # -------------------------------------------------------------
        m_type_it = re.match(
            r"^(?:type|write|enter|input|add)\s+(.+?)(?:\s+(?:in|into|on|to)\s+(?:it|this|that|the\s+app|the\s+window|the\s+file|the\s+document|the\s+search\s+box|same\s+app|same\s+window))?$",
            clean_nopunct,
            flags=re.IGNORECASE
        )
        if m_type_it:
            text_to_type = m_type_it.group(1).strip()
            # If user explicitly used "in it" or follow-up typing:
            is_explicit_it = bool(re.search(r"\s+(?:in|into|on|to)\s+(?:it|this|that|the\s+app|the\s+window|the\s+file|the\s+document|the\s+search\s+box|same\s+app|same\s+window)$", clean_nopunct))

            # Context Priority: Current active application/window
            app_ctx = self._working_context.get("active_application")
            win_ctx = self._working_context.get("active_window")

            if app_ctx or win_ctx:
                is_valid, reason = self.validate_active_window()
                if not is_valid:
                    return f"STALE_CONTEXT: {reason} Please specify where you would like me to type."
                else:
                    self.ensure_active_window_focused()
                    app_name = (app_ctx or {}).get("name") or (win_ctx or {}).get("application") or "Application"
                    print(f"[ByteX ContextResolver] Resolved typing '{text_to_type}' into active {app_name}")
                    return f"type {text_to_type}"
            elif is_explicit_it:
                return "AMBIGUOUS_FOLLOWUP: Which application or window would you like me to type into?"

        # -------------------------------------------------------------
        # PATTERN 3: SAVE IT / SAVE IT AS <filename> (Document Context)
        # E.g. "Save it as notes.txt.", "Save it.", "Save the document."
        # -------------------------------------------------------------
        m_save = re.match(r"^(?:save|save\s+it|save\s+the\s+document|save\s+the\s+file)(?:\s+as\s+([a-zA-Z0-9_\-\.\s]+))?(?:\s+(?:on|in)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+))?$", clean_nopunct)
        if m_save:
            fn = m_save.group(1)
            loc = m_save.group(2) or "desktop"
            if fn:
                fn_clean = fn.strip()
                print(f"[ByteX ContextResolver] Resolved 'save it as {fn_clean}' on {loc}")
                return f"save document as {fn_clean} on {loc}"
            else:
                return "AMBIGUOUS_FOLLOWUP: What filename should I use to save it?"

        # -------------------------------------------------------------
        # PATTERN 4: CLICK IT / SELECT IT / PRESS IT (UI Element Context)
        # E.g. "Click it.", "Click that button.", "Click the button."
        # -------------------------------------------------------------
        if re.match(r"^(?:click|press|tap|select)\s+(?:on\s+)?(?:it|this|that|the\s+button|that\s+button|the\s+element|that\s+element)$", clean_nopunct):
            # 4.1. Check for ambiguity (multiple candidate elements)
            if len(self._working_context.get("candidate_elements", [])) > 1:
                return "AMBIGUOUS_FOLLOWUP: I found multiple possible buttons. Which one do you mean?"

            # 4.2. Resolved single detected element
            active_elem = self._working_context.get("active_element")
            if active_elem and active_elem.get("element"):
                elem_name = active_elem["element"]
                elem_type = active_elem.get("type", "button")
                print(f"[ByteX ContextResolver] Resolved 'click it' -> previously detected {elem_type} '{elem_name}'")
                return f"click the {elem_name} {elem_type}" if not elem_name.lower().endswith(elem_type.lower()) else f"click the {elem_name}"

            # 4.3. Search results / Media
            if self._working_context.get("last_search"):
                query = self._working_context["last_search"].get("query")
                print(f"[ByteX ContextResolver] Resolved 'click it' -> search result '{query}'")
                return f"play {query}"

            return "AMBIGUOUS_FOLLOWUP: Which element would you like me to click?"

        # -------------------------------------------------------------
        # PATTERN 5: OPEN SEARCH RESULT (Browser & Search Context - Feature #31)
        # E.g. "Open the first result.", "Open the third result.", "Open result 2.", "Open the result from W3Schools."
        # -------------------------------------------------------------
        ORDINAL_MAP = {
            "first": 1, "1st": 1, "top": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
            "sixth": 6, "6th": 6,
            "seventh": 7, "7th": 7,
            "eighth": 8, "8th": 8,
            "ninth": 9, "9th": 9,
            "tenth": 10, "10th": 10
        }

        m_ord = re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?|top)\s+(?:result|one|link)$", clean_nopunct)
        m_num = re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?result\s+(?:number\s+|#)?(\d+)$", clean_nopunct)
        m_dom = re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?result\s+from\s+(.+)$", clean_nopunct)
        m_dom2 = re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]+)\s+result$", clean_nopunct)

        if m_ord or m_num or m_dom or m_dom2:
            last_srch = self._working_context.get("last_search")
            if not last_srch or not last_srch.get("results"):
                return "AMBIGUOUS_FOLLOWUP: I don't have a recent search result to open."

            results_list = last_srch.get("results", [])

            # Case A: Ordinal / Numbered Index
            target_idx = None
            if m_ord:
                word = m_ord.group(1).lower()
                target_idx = ORDINAL_MAP.get(word)
                if not target_idx:
                    num_match = re.match(r"^(\d+)", word)
                    if num_match:
                        target_idx = int(num_match.group(1))
            elif m_num:
                target_idx = int(m_num.group(1))

            if target_idx is not None:
                if 1 <= target_idx <= len(results_list):
                    selected = results_list[target_idx - 1]
                    url = selected.get("url") if isinstance(selected, dict) else str(selected)
                    self._working_context["active_url"] = url
                    self._working_context["last_search"]["selected_result"] = url
                    print(f"[ByteX ContextResolver] Resolved 'open result #{target_idx}' -> '{url}'")
                    return f"navigate to {url}"
                else:
                    return f"AMBIGUOUS_FOLLOWUP: I only have {len(results_list)} search result(s). Please choose a valid result number."

            # Case B: Domain / Source Matching
            domain_query = ""
            if m_dom:
                domain_query = m_dom.group(1).strip().lower()
            elif m_dom2:
                domain_query = m_dom2.group(1).strip().lower()

            if domain_query:
                # Discard generic noise words
                domain_query = re.sub(r"^(?:the\s+|website\s+)", "", domain_query).strip()
                matches = []
                for res in results_list:
                    if isinstance(res, dict):
                        d_name = res.get("domain", "").lower()
                        src_name = res.get("source", "").lower()
                        title_name = res.get("title", "").lower()
                        url_name = res.get("url", "").lower()
                        if (
                            domain_query in d_name
                            or domain_query in src_name
                            or domain_query in title_name
                            or domain_query in url_name
                        ):
                            matches.append(res)

                if len(matches) == 1:
                    matched_res = matches[0]
                    url = matched_res.get("url")
                    self._working_context["active_url"] = url
                    self._working_context["last_search"]["selected_result"] = url
                    print(f"[ByteX ContextResolver] Resolved 'open result from {domain_query}' -> '{url}'")
                    return f"navigate to {url}"
                elif len(matches) > 1:
                    return f"AMBIGUOUS_FOLLOWUP: I found {len(matches)} results matching '{domain_query}'. Which one would you like to open?"
                else:
                    return f"AMBIGUOUS_FOLLOWUP: I couldn't find a search result from '{domain_query}'."

        # -------------------------------------------------------------
        # PATTERN 6: SUMMARIZE IT / SUMMARIZE THIS (Webpage / Document Context)
        # E.g. "Summarize it.", "Summarize this.", "Summarize the page."
        # -------------------------------------------------------------
        if re.match(r"^(?:summarize|summarise|give\s+me\s+a\s+summary\s+of)\s+(?:it|this|that|the\s+page|the\s+webpage|the\s+article|the\s+document|the\s+file)$", clean_nopunct):
            # Priority 1: Active URL
            active_url = self._working_context.get("active_url")
            if active_url:
                print(f"[ByteX ContextResolver] Resolved 'summarize it' -> active URL '{active_url}'")
                return f"summarize {active_url}"

            # Priority 2: Active Document
            active_doc = self._working_context.get("active_document")
            if active_doc and active_doc.get("path"):
                doc_path = active_doc["path"]
                print(f"[ByteX ContextResolver] Resolved 'summarize it' -> active document '{doc_path}'")
                return f"summarize file {doc_path}"

            # Priority 3: Last Search
            if self._working_context.get("last_search"):
                q = self._working_context["last_search"].get("query")
                return f"search the web for {q} and summarize"

            return "AMBIGUOUS_FOLLOWUP: What would you like me to summarize? Please provide a URL, document, or topic."

        # -------------------------------------------------------------
        # PATTERN 7: READ THIS / READ IT (File / Document / Webpage Context)
        # E.g. "Read this.", "Read it.", "Read the document."
        # -------------------------------------------------------------
        if re.match(r"^(?:read|read\s+out|what\s+does\s+(?:this|it|the\s+file|the\s+document)\s+say)\s*(?:this|it|that|the\s+document|the\s+file)?$", clean_nopunct):
            active_doc = self._working_context.get("active_document")
            if active_doc and active_doc.get("path"):
                doc_path = active_doc["path"]
                print(f"[ByteX ContextResolver] Resolved 'read this' -> active document '{doc_path}'")
                return f"read file {doc_path}"

            active_url = self._working_context.get("active_url")
            if active_url:
                print(f"[ByteX ContextResolver] Resolved 'read this' -> active URL '{active_url}'")
                return f"read webpage {active_url}"

            return "AMBIGUOUS_FOLLOWUP: Which document or webpage would you like me to read?"

        # -------------------------------------------------------------
        # PATTERN 8: MEDIA PLAYBACK (Pause it, Resume it, Play it)
        # -------------------------------------------------------------
        if re.match(r"^(?:pause|pause\s+it|pause\s+(?:the\s+)?(?:song|video|music|playback|media))$", clean_nopunct):
            from skills.media import media_session_manager
            if self._working_context.get("active_media") or media_session_manager.get_session():
                print(f"[ByteX ContextResolver] Resolved 'pause it' -> active media session")
                return "pause media"
            return "AMBIGUOUS_FOLLOWUP: There is no active media playback to pause."

        if re.match(r"^(?:resume|resume\s+it|unpause|unpause\s+it|continue\s+(?:playing|playback)|play\s+it)$", clean_nopunct):
            from skills.media import media_session_manager
            if self._working_context.get("active_media") or media_session_manager.get_session():
                print(f"[ByteX ContextResolver] Resolved 'resume it' -> active media session")
                return "resume media"
            elif self._working_context.get("last_search"):
                query = self._working_context["last_search"].get("query")
                return f"play {query}"
            return "AMBIGUOUS_FOLLOWUP: There is no active media playback to resume."

        # -------------------------------------------------------------
        # PATTERN 9: CLOSE IT / QUIT IT (Application Context)
        # E.g. "Close it.", "Close the app.", "Close the window."
        # -------------------------------------------------------------
        if re.match(r"^(?:close|quit|exit|kill|stop)\s+(?:it|this|that|the\s+app|the\s+window|same\s+app|same\s+window)$", clean_nopunct):
            app_ctx = self._working_context.get("active_application")
            win_ctx = self._working_context.get("active_window")
            if app_ctx and app_ctx.get("name"):
                app_name = app_ctx["name"]
                print(f"[ByteX ContextResolver] Resolved 'close it' -> active application '{app_name}'")
                return f"close {app_name}"
            elif win_ctx and win_ctx.get("title"):
                title = win_ctx["title"]
                print(f"[ByteX ContextResolver] Resolved 'close it' -> active window '{title}'")
                return f"close {title}"
            elif self._working_context.get("last_successful_target"):
                target = self._working_context["last_successful_target"]
                print(f"[ByteX ContextResolver] Resolved 'close it' -> '{target}'")
                return f"close {target}"
            elif self._working_context.get("active_media"):
                return "stop media"
            else:
                return "AMBIGUOUS_FOLLOWUP: Which application would you like me to close?"

        # -------------------------------------------------------------
        # PATTERN 10: OPEN IT (Folder, File, Document)
        # -------------------------------------------------------------
        if re.match(r"^(?:open|show|explore)\s+(?:it|this|that|the\s+folder|the\s+file|the\s+directory|the\s+document)$", clean_nopunct):
            if self._working_context.get("active_document"):
                doc_path = self._working_context["active_document"].get("path") or self._working_context["active_document"].get("name")
                print(f"[ByteX ContextResolver] Resolved 'open it' -> document '{doc_path}'")
                return f"open file {doc_path}"
            elif self._working_context.get("last_location"):
                fld = self._working_context["last_location"]
                print(f"[ByteX ContextResolver] Resolved 'open it' -> folder '{fld}'")
                return f"open folder {fld}"
            elif self._working_context.get("last_successful_target"):
                target = self._working_context["last_successful_target"]
                print(f"[ByteX ContextResolver] Resolved 'open it' -> target '{target}'")
                return f"open {target}"
            else:
                return "AMBIGUOUS_FOLLOWUP: Which item would you like me to open?"

        # -------------------------------------------------------------
        # PATTERN 11: SCREENSHOT & ANALYZE IT / DESCRIBE IT
        # -------------------------------------------------------------
        if re.match(r"^(?:analyze|describe|inspect|examine|read|what\s+is\s+(?:in|on))\s+(?:it|this|that|the\s+screenshot|the\s+image|the\s+screen)$", clean_nopunct):
            print(f"[ByteX ContextResolver] Resolved 'analyze it' -> Screen Understanding")
            return "What is on my screen?"

        # -------------------------------------------------------------
        # PATTERN 12: CREATE ANOTHER ONE / THERE / IN THERE
        # -------------------------------------------------------------
        m_another = re.search(r"^(?:create|make)\s+(?:another\s+one|another\s+folder)\s+(?:called|named)?\s*([a-zA-Z0-9_\-]+)", clean_nopunct)
        if m_another:
            new_name = m_another.group(1).strip()
            loc = self._working_context.get("last_location") or "desktop"
            print(f"[ByteX ContextResolver] Resolved 'create another one' -> folder '{new_name}' on {loc}")
            return f"create a folder called {new_name} on my {loc}"

        return clean

session_manager = ConversationalSessionManager()
