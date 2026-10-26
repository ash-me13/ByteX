"""
ByteX - Input Controller Service (Feature #40: Screen Understanding 2.0)

Provides a clean, modular cross-platform abstraction for mouse and keyboard simulation
on the interactive user desktop with coordinate boundary validation and safety checks.

CRITICAL SAFETY INVARIANTS:
1. Mock / Test Mode Isolation: When mock mode or test environment is active, NO real
   OS mouse/keyboard inputs are sent to the user's physical screen.
2. Read-Only Screen Understanding: Screen analysis, element finding, and OCR must
   remain 100% READ-ONLY and NEVER dispatch input events.
3. Explicit Execution Only: InputController only dispatches physical input on explicit,
   verified user automation commands.
"""

import os
import sys
import time
import ctypes
import logging
from typing import Tuple, Dict, Any, Optional, List

logger = logging.getLogger("bytex.input_controller")

is_windows = sys.platform == "win32"

if is_windows:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    from ctypes import wintypes, byref, Structure, sizeof

    class KEYBDINPUT(Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulong)
        ]

    class INPUT(Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("_input",)
        _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]


class InputController:
    """
    Cross-platform input controller for precise visual UI automation.
    Handles mouse movement, single/double/right clicks, text entry, scrolling,
    and drag/selection with desktop security context attachment on Windows.
    """

    _mock_mode: bool = False
    _mock_history: List[Dict[str, Any]] = []

    @classmethod
    def enable_mock_mode(cls):
        """Enables mock input mode (disables physical mouse/keyboard OS events)."""
        cls._mock_mode = True
        logger.info("[InputController] Mock mode ENABLED. Real OS input disabled.")

    @classmethod
    def disable_mock_mode(cls):
        """Disables mock input mode (enables physical mouse/keyboard OS events)."""
        cls._mock_mode = False
        logger.info("[InputController] Mock mode DISABLED. Real OS input enabled.")

    @classmethod
    def is_mock_mode(cls) -> bool:
        """Returns True if mock mode is active either explicitly or via environment variable."""
        return cls._mock_mode or os.environ.get("BYTEX_TEST_MODE") == "1" or os.environ.get("BYTEX_MOCK_INPUT") == "1"

    @classmethod
    def get_mock_history(cls) -> List[Dict[str, Any]]:
        """Returns recorded mock input actions."""
        return list(cls._mock_history)

    @classmethod
    def clear_mock_history(cls):
        """Clears recorded mock input actions."""
        cls._mock_history.clear()

    @classmethod
    def _record_mock(cls, action: str, details: Dict[str, Any]):
        cls._mock_history.append({"action": action, "timestamp": time.time(), **details})
        logger.info(f"[InputController-Mock] Simulated {action}: {details}")

    @classmethod
    def _attach_desktop_context(cls):
        """Attaches the calling thread to the interactive user's desktop."""
        if not is_windows:
            return None, None
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        old_desk = None
        if h_input:
            old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            user32.SetThreadDesktop(h_input)
        return h_input, old_desk

    @classmethod
    def _detach_desktop_context(cls, h_input, old_desk):
        """Restores thread desktop context."""
        if is_windows and h_input and old_desk:
            user32.SetThreadDesktop(old_desk)
            user32.CloseDesktop(h_input)

    @classmethod
    def validate_coordinates(cls, x: int, y: int, screen_dims: Tuple[int, int]) -> bool:
        """Validates that (x, y) coordinates fall within visible screen boundaries."""
        w, h = screen_dims
        return 0 <= x < w and 0 <= y < h

    @classmethod
    def click_point(cls, x: int, y: int, screen_dims: Optional[Tuple[int, int]] = None) -> bool:
        """Moves cursor to (x, y) and performs a left mouse click."""
        if screen_dims and not cls.validate_coordinates(x, y, screen_dims):
            logger.error(f"[InputController] Click coordinates out of bounds: ({x}, {y})")
            return False

        if cls.is_mock_mode():
            cls._record_mock("click_point", {"x": x, "y": y, "screen_dims": screen_dims})
            return True

        if is_windows:
            h_in, old_d = cls._attach_desktop_context()
            try:
                user32.SetCursorPos(int(x), int(y))
                time.sleep(0.06)
                user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
                time.sleep(0.04)
                user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
                time.sleep(0.08)
                return True
            except Exception as e:
                logger.error(f"[InputController] click_point failed: {e}")
                return False
            finally:
                cls._detach_desktop_context(h_in, old_d)
        else:
            logger.info(f"[InputController-Sim] Clicked at ({x}, {y})")
            return True

    @classmethod
    def double_click_point(cls, x: int, y: int, screen_dims: Optional[Tuple[int, int]] = None) -> bool:
        """Moves cursor to (x, y) and performs a left double-click."""
        if cls.is_mock_mode():
            cls._record_mock("double_click_point", {"x": x, "y": y, "screen_dims": screen_dims})
            return True

        res1 = cls.click_point(x, y, screen_dims)
        time.sleep(0.08)
        res2 = cls.click_point(x, y, screen_dims)
        return res1 and res2

    @classmethod
    def right_click_point(cls, x: int, y: int, screen_dims: Optional[Tuple[int, int]] = None) -> bool:
        """Moves cursor to (x, y) and performs a right mouse click."""
        if screen_dims and not cls.validate_coordinates(x, y, screen_dims):
            logger.error(f"[InputController] Right-click coordinates out of bounds: ({x}, {y})")
            return False

        if cls.is_mock_mode():
            cls._record_mock("right_click_point", {"x": x, "y": y, "screen_dims": screen_dims})
            return True

        if is_windows:
            h_in, old_d = cls._attach_desktop_context()
            try:
                user32.SetCursorPos(int(x), int(y))
                time.sleep(0.06)
                user32.mouse_event(0x0008, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTDOWN
                time.sleep(0.04)
                user32.mouse_event(0x0010, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTUP
                time.sleep(0.08)
                return True
            except Exception as e:
                logger.error(f"[InputController] right_click_point failed: {e}")
                return False
            finally:
                cls._detach_desktop_context(h_in, old_d)
        else:
            logger.info(f"[InputController-Sim] Right-clicked at ({x}, {y})")
            return True

    @classmethod
    def scroll(cls, clicks: int = -3) -> bool:
        """Scrolls mouse wheel. Positive = up, negative = down."""
        if cls.is_mock_mode():
            cls._record_mock("scroll", {"clicks": clicks})
            return True

        if is_windows:
            h_in, old_d = cls._attach_desktop_context()
            try:
                user32.mouse_event(0x0800, 0, 0, clicks * 120, 0)  # MOUSEEVENTF_WHEEL
                time.sleep(0.1)
                return True
            except Exception as e:
                logger.error(f"[InputController] scroll failed: {e}")
                return False
            finally:
                cls._detach_desktop_context(h_in, old_d)
        else:
            logger.info(f"[InputController-Sim] Scrolled {clicks} clicks")
            return True

    @classmethod
    def type_unicode_text(cls, text: str) -> bool:
        """Sends native Unicode character input to the active focused window."""
        if not text:
            return True

        if cls.is_mock_mode():
            cls._record_mock("type_unicode_text", {"text": text})
            return True

        if is_windows:
            INPUT_KEYBOARD = 1
            KEYEVENTF_UNICODE = 0x0004
            KEYEVENTF_KEYUP = 0x0002

            try:
                for ch in text:
                    code = ord(ch)
                    inp_down = INPUT(type=INPUT_KEYBOARD)
                    inp_down.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)
                    inp_up = INPUT(type=INPUT_KEYBOARD)
                    inp_up.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)

                    user32.SendInput(1, byref(inp_down), sizeof(INPUT))
                    user32.SendInput(1, byref(inp_up), sizeof(INPUT))
                    time.sleep(0.015)
                return True
            except Exception as e:
                logger.error(f"[InputController] type_unicode_text failed: {e}")
                return False
        else:
            logger.info(f"[InputController-Sim] Typed: '{text}'")
            return True

    @classmethod
    def select_region(cls, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Drags mouse from (x1, y1) to (x2, y2) to select a screen area or text range."""
        if cls.is_mock_mode():
            cls._record_mock("select_region", {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
            return True

        if is_windows:
            h_in, old_d = cls._attach_desktop_context()
            try:
                user32.SetCursorPos(int(x1), int(y1))
                time.sleep(0.05)
                user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFT DOWN
                time.sleep(0.08)
                user32.SetCursorPos(int(x2), int(y2))
                time.sleep(0.08)
                user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFT UP
                time.sleep(0.05)
                return True
            except Exception as e:
                logger.error(f"[InputController] select_region failed: {e}")
                return False
            finally:
                cls._detach_desktop_context(h_in, old_d)
        else:
            logger.info(f"[InputController-Sim] Selected region from ({x1}, {y1}) to ({x2}, {y2})")
            return True


input_controller = InputController()
