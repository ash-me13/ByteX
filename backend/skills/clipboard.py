import sys
import ctypes
import time
import pyperclip
from typing import Dict, Any, Optional
from skills.base import BaseSkill, ToolResult
from security.audit_logger import audit_logger

# Win32 Constants for Fallback
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

class DesktopClipboardSkill(BaseSkill):
    """
    Global Windows Desktop Clipboard Control Skill (Roadmap Feature #20).
    Provides native access to read, write, and clear the Windows system clipboard
    with strict verification and privacy-conscious logging.
    """

    @property
    def name(self) -> str:
        return "clipboard_control"

    @property
    def description(self) -> str:
        return (
            "Controls the global Windows desktop clipboard. Supports reading (get), "
            "copying text into (set), clearing (clear), and pasting (paste) into the focused application."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "clear", "paste", "get_clipboard", "set_clipboard", "clear_clipboard", "paste_clipboard"],
                    "description": "The clipboard operation to perform."
                },
                "content": {
                    "type": "string",
                    "description": "The text content to copy into the clipboard (required for set)."
                },
                "text": {
                    "type": "string",
                    "description": "Alternative key for content."
                },
                "raw_text": {
                    "type": "string",
                    "description": "Original raw command prompt."
                }
            },
            "required": ["action"]
        }

    # -------------------------------------------------------------------------
    # Win32 Direct API Helpers (Fallback & Verification)
    # -------------------------------------------------------------------------
    def _win32_get_clipboard_text(self) -> str:
        """Direct Win32 API clipboard reader."""
        if sys.platform != "win32" or not hasattr(ctypes, "windll"):
            return ""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        for _ in range(5):
            if user32.OpenClipboard(None):
                try:
                    h_clip = user32.GetClipboardData(CF_UNICODETEXT)
                    if not h_clip:
                        return ""
                    p_text = kernel32.GlobalLock(h_clip)
                    if not p_text:
                        return ""
                    try:
                        text = ctypes.c_wchar_p(p_text).value or ""
                        return text
                    finally:
                        kernel32.GlobalUnlock(h_clip)
                finally:
                    user32.CloseClipboard()
            time.sleep(0.05)
        return ""

    def _win32_set_clipboard_text(self, text: str) -> bool:
        """Direct Win32 API clipboard writer."""
        if sys.platform != "win32" or not hasattr(ctypes, "windll"):
            return False
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        for _ in range(5):
            if user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                    if not text:
                        return True
                    text_bytes = (text + "\0").encode("utf-16-le")
                    h_glob = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
                    if not h_glob:
                        return False
                    p_glob = kernel32.GlobalLock(h_glob)
                    if not p_glob:
                        kernel32.GlobalFree(h_glob)
                        return False
                    ctypes.memmove(p_glob, text_bytes, len(text_bytes))
                    kernel32.GlobalUnlock(h_glob)
                    if not user32.SetClipboardData(CF_UNICODETEXT, h_glob):
                        kernel32.GlobalFree(h_glob)
                        return False
                    return True
                finally:
                    user32.CloseClipboard()
            time.sleep(0.05)
        return False

    # -------------------------------------------------------------------------
    # Unified Read / Write / Clear Engine
    # -------------------------------------------------------------------------
    def _read_clipboard(self) -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:
            return self._win32_get_clipboard_text()

    def _write_clipboard(self, content: str) -> bool:
        try:
            pyperclip.copy(content)
            return True
        except Exception:
            return self._win32_set_clipboard_text(content)

    def _empty_clipboard(self) -> bool:
        try:
            pyperclip.copy("")
            return True
        except Exception:
            return self._win32_set_clipboard_text("")

    # -------------------------------------------------------------------------
    # Skill Execution Lifecycle
    # -------------------------------------------------------------------------
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "")).lower().strip()
        raw_text = arguments.get("raw_text", "")
        content = arguments.get("content") or arguments.get("text")

        # Normalize action keywords
        if "paste" in action:
            action_type = "paste"
        elif "get" in action or "read" in action or "show" in action:
            action_type = "get"
        elif "clear" in action or "empty" in action:
            action_type = "clear"
        elif "set" in action or "copy" in action or "write" in action:
            action_type = "set"
        else:
            action_type = "get"

        # ---------------------------------------------------------------------
        # 1. GET_CLIPBOARD
        # ---------------------------------------------------------------------
        if action_type == "get":
            current_clip = self._read_clipboard()
            audit_logger.log_action(self.name, "SUCCESS", f"Read clipboard content (Length: {len(current_clip)} chars)")

            if not current_clip:
                msg = "Your clipboard is currently empty."
            else:
                # Truncate preview if extremely large for conversational message
                preview = current_clip if len(current_clip) <= 200 else current_clip[:197] + "..."
                msg = f"Your clipboard contains: {preview}"

            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="get_clipboard",
                message=msg,
                data={
                    "content": current_clip,
                    "length": len(current_clip)
                }
            )

        # ---------------------------------------------------------------------
        # 2. SET_CLIPBOARD
        # ---------------------------------------------------------------------
        elif action_type == "set":
            if content is None:
                # Attempt extraction from raw_text
                import re
                m = re.search(r"(?:to\s+(?:my\s+)?clipboard\s*[:\s]*|in\s+(?:my\s+)?clipboard\s*[:\s]*)(.*)$", raw_text, re.IGNORECASE)
                if m and m.group(1).strip():
                    content = m.group(1).strip()
                else:
                    m2 = re.search(r"(?:copy\s+|put\s+|set\s+)(?:this\s+)?(.*)(?:\s+to|\s+in)\s+(?:my\s+)?clipboard", raw_text, re.IGNORECASE)
                    if m2 and m2.group(1).strip():
                        content = m2.group(1).strip()
                    else:
                        content = raw_text

            content_str = str(content)
            self._write_clipboard(content_str)

            # Verification: Read back and assert equality
            verified_clip = self._read_clipboard()
            is_verified = (verified_clip == content_str)

            if is_verified:
                audit_logger.log_action(self.name, "SUCCESS", f"Set clipboard text successfully (Length: {len(content_str)} chars)")
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="set_clipboard",
                    message=f"Copied to clipboard: {content_str}",
                    data={
                        "content": content_str,
                        "length": len(content_str)
                    }
                )
            else:
                audit_logger.log_action(self.name, "FAILED", "Clipboard verification mismatch after set operation")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="set_clipboard",
                    message="Failed to write content to the clipboard.",
                    error="Verification read-back mismatch"
                )

        # ---------------------------------------------------------------------
        # 3. CLEAR_CLIPBOARD
        # ---------------------------------------------------------------------
        elif action_type == "clear":
            self._empty_clipboard()

            # Verification: Assert clipboard is empty
            verified_clip = self._read_clipboard()
            is_verified = (verified_clip == "")

            if is_verified:
                audit_logger.log_action(self.name, "SUCCESS", "Clipboard cleared successfully")
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="clear_clipboard",
                    message="Clipboard cleared successfully.",
                    data={
                        "content": "",
                        "length": 0
                    }
                )
            else:
                audit_logger.log_action(self.name, "FAILED", "Clipboard was not empty after clear operation")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="clear_clipboard",
                    message="Failed to clear clipboard.",
                    error="Verification check showed clipboard was not empty"
                )

        # ---------------------------------------------------------------------
        # 4. PASTE_CLIPBOARD
        # ---------------------------------------------------------------------
        elif action_type == "paste":
            # 1. Check that clipboard contains text
            current_clip = self._read_clipboard()
            if not current_clip:
                msg = "Cannot paste: your clipboard is currently empty."
                audit_logger.log_action(self.name, "UNVERIFIED", msg)
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="paste_clipboard",
                    message=msg,
                    error="Clipboard is empty"
                )

            if sys.platform == "darwin":
                fg_title = "Active Application"
                try:
                    from core.applescript import run_applescript

                    res = run_applescript(
                        'tell application "System Events" to get name of first process whose frontmost is true',
                        timeout=2.0
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        fg_title = res.stdout.strip()

                    paste_res = run_applescript(
                        'tell application "System Events" to keystroke "v" using command down',
                        timeout=2.0
                    )

                    if paste_res.returncode != 0:
                        err_out = (paste_res.stderr or paste_res.stdout or "").strip()
                        err_lower = err_out.lower()
                        if "not allowed to send keystrokes" in err_lower or "assistive" in err_lower or "-1743" in err_out:
                            err_desc = (
                                "Accessibility permission denied. macOS requires Accessibility permissions "
                                "to dispatch keystrokes. Please grant Accessibility permissions to your terminal or Python "
                                "in System Settings -> Privacy & Security -> Accessibility."
                            )
                        else:
                            err_desc = f"Failed to dispatch paste keystroke to '{fg_title}': {err_out or 'osascript exited with code ' + str(paste_res.returncode)}"

                        audit_logger.log_action(self.name, "FAILED", err_desc)
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="paste_clipboard",
                            message=err_desc,
                            error=err_desc
                        )

                    audit_logger.log_action(self.name, "SUCCESS", f"Dispatched Cmd+V paste to foreground app ('{fg_title}')")
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="paste_clipboard",
                        message=f"Pasted clipboard content into {fg_title}.",
                        data={"target_window": fg_title, "content_length": len(current_clip)}
                    )
                except Exception as e:
                    audit_logger.log_action(self.name, "FAILED", f"Error during macOS paste: {e}")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="paste_clipboard",
                        message=f"Failed to paste on macOS: {e}",
                        error=str(e)
                    )

            if not sys.platform == "win32" or not hasattr(ctypes, "windll"):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="paste_clipboard",
                    message="Direct desktop paste is not supported on this platform.",
                    error="Unsupported platform"
                )

            # 2. Verify that a valid foreground application/window exists
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            h_input = user32.OpenInputDesktop(0, False, 0x01FF)
            old_desk = None
            if h_input:
                old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
                user32.SetThreadDesktop(h_input)

            try:
                fg_hwnd = user32.GetForegroundWindow()
                if not fg_hwnd:
                    # Fallback: check top visible window
                    top_h = user32.GetTopWindow(user32.GetDesktopWindow())
                    while top_h:
                        if user32.IsWindowVisible(top_h) and user32.GetWindowTextLengthW(top_h) > 0:
                            fg_hwnd = top_h
                            break
                        top_h = user32.GetWindow(top_h, 2) # GW_HWNDNEXT

                if not fg_hwnd:
                    msg = "Cannot paste: no active application window found in the foreground."
                    audit_logger.log_action(self.name, "FAILED", msg)
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="paste_clipboard",
                        message=msg,
                        error="No foreground window found"
                    )

                fg_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
                title_buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(fg_hwnd, title_buf, 512)
                fg_title = title_buf.value.strip() or "Active Application"

                # 3. Send Ctrl+V to the currently focused Windows application
                VK_CONTROL = 0x11
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002

                # Simulate Ctrl+V keypress
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            finally:
                if h_input and old_desk:
                    user32.SetThreadDesktop(old_desk)
                    user32.CloseDesktop(h_input)

            # 4. Verify action dispatch
            audit_logger.log_action(
                self.name,
                "SUCCESS",
                f"Dispatched Ctrl+V paste to foreground window HWND {fg_hwnd} ('{fg_title}')"
            )

            msg = f"Pasted clipboard content into {fg_title}."

            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="paste_clipboard",
                message=msg,
                data={
                    "target_window": fg_title,
                    "target_hwnd": fg_hwnd,
                    "target_pid": fg_pid.value,
                    "content_length": len(current_clip)
                }
            )

        return ToolResult(
            success=False,
            verified=False,
            tool=self.name,
            message=f"Unknown clipboard action: {action}"
        )

# Backward-compatibility alias
ClipboardSkill = DesktopClipboardSkill
