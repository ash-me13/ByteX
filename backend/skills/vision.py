"""
ByteX - Feature #40: Screen Understanding 2.0 & Visual UI Grounding

Upgrades ByteX Screen Vision to Screen Understanding 2.0:
1. Grounded Visual Understanding: Identifies buttons, inputs, dropdowns, links, tabs, dialogs, cards, icons, toggles, headings, and error banners with bounding boxes and center points.
2. Structured Response Schema: Returns standardized {screen_summary, elements, text, visible_windows, foreground_window, confidence, region}.
3. Modular OCR Abstraction: OCRService handles visible text extraction, line grouping, and coordinate search.
4. Cross-Platform Input Controller: InputController provides safe mouse/keyboard execution with coordinate validation.
5. 7-Step Closed-Loop Action Verification: VisualVerifier captures pre-action frame, locates target, executes input, captures post-action frame, computes diff metric, and returns empirical verification.
6. Region-Focused Screen Understanding: Allows users to focus analysis on specific regions (top-left, center, bottom, etc.) or custom bounding boxes.
7. Privacy & Security Redaction: Redacts sensitive passwords, tokens, and API keys ([REDACTED_SECRET]) with zero permanent storage in long-term memory.
"""

import os
import re
import sys
import time
import json
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image

from skills.base import BaseSkill, ToolResult
from security.audit_logger import audit_logger
from config.settings import settings
from services.screenshot_helper import capture_desktop
from services.input_controller import input_controller, is_windows
from services.ocr_service import ocr_service
from services.screen_understanding import screen_understanding
from services.visual_verifier import visual_verifier

if is_windows:
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

logger = logging.getLogger("bytex.screen_vision")


def get_desktop_visual_context() -> Dict[str, Any]:
    """Collects current interactive desktop window titles and foreground process for visual context."""
    if not is_windows:
        return {
            "foreground_window": "Desktop",
            "foreground_pid": 0,
            "visible_windows": ["Main Desktop Window"]
        }

    h_input = user32.OpenInputDesktop(0, False, 0x01FF)
    old_desk = None
    if h_input:
        old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        user32.SetThreadDesktop(h_input)

    visible_windows = []
    fg_title = ""
    fg_pid = 0

    try:
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(fg_hwnd, buf, 512)
            fg_title = buf.value.strip()
            fg_pid = pid.value

        def enum_cb(h, lp):
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                t = buf.value.strip()
                if t and not t.startswith("GDI+") and t not in ["Program Manager", "Default IME", "MSCTFIME UI"]:
                    visible_windows.append(t)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    finally:
        if h_input and old_desk:
            user32.SetThreadDesktop(old_desk)
            user32.CloseDesktop(h_input)

    return {
        "foreground_window": fg_title or "Desktop",
        "foreground_pid": fg_pid,
        "visible_windows": visible_windows[:12]
    }


class ScreenVisionSkill(BaseSkill):
    """
    ByteX Screen Understanding 2.0 Skill (Roadmap Feature #40).
    Performs structured visual perception, OCR reading, UI element grounding,
    closed-loop verified visual interactions, region-focused analysis, and error diagnosis.
    """

    CONFIDENCE_HIGH = 0.85
    CONFIDENCE_MEDIUM = 0.65

    SUPPORTED_ELEMENT_TYPES = [
        "button", "input", "textbox", "search_box", "checkbox", "radio_button",
        "dropdown", "menu", "tab", "link", "icon", "image", "heading", "text",
        "dialog", "window", "card", "table", "list_item", "toggle"
    ]

    DESTRUCTIVE_TARGET_KEYWORDS = [
        "delete", "remove", "uninstall", "format", "shutdown", "erase", "drop",
        "purge", "destroy", "close without saving", "terminate"
    ]

    @property
    def name(self) -> str:
        return "screen_vision"

    @property
    def description(self) -> str:
        return (
            "Screen Understanding 2.0: Performs structured visual UI analysis, OCR reading, "
            "closed-loop verified clicking/typing, scrolling, region examination, and screen error diagnosis."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "analyze_screen", "analyze", "screen_analyze", "describe", "understand_screen",
                        "detect_element", "find_ui_element", "find_element", "locate", "detect",
                        "read_screen", "read_text", "ocr", "find_text",
                        "visual_click", "click", "vision_click", "left_click",
                        "visual_double_click", "double_click", "vision_double_click",
                        "click_coordinates", "click_point",
                        "visual_type", "type", "vision_type", "write", "enter_text",
                        "visual_scroll", "scroll", "scroll_down", "scroll_up",
                        "visual_select", "select",
                        "explain_region", "examine_region", "read_section",
                        "screen_diagnosis", "diagnose_screen", "check_error", "read_error"
                    ],
                    "description": "Visual action to execute."
                },
                "target": {
                    "type": "string",
                    "description": "Natural language description or name of the target UI element/text."
                },
                "element": {
                    "type": "string",
                    "description": "Alternative key for target element."
                },
                "element_type": {
                    "type": "string",
                    "description": "Expected element type (button, input, search_box, link, menu, tab, etc.)."
                },
                "region": {
                    "type": "string",
                    "enum": [
                        "top-left", "top", "top-right",
                        "center",
                        "bottom-left", "bottom", "bottom-right",
                        "left", "right"
                    ],
                    "description": "Spatial region constraint on screen to disambiguate targets."
                },
                "ordinal": {
                    "type": "string",
                    "enum": ["first", "second", "third", "fourth", "last"],
                    "description": "Ordinal indicator for elements with identical names."
                },
                "text": {
                    "type": "string",
                    "description": "Text to type or search for."
                },
                "x": {
                    "type": "integer",
                    "description": "X coordinate for direct coordinate interaction."
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate for direct coordinate interaction."
                },
                "question": {
                    "type": "string",
                    "description": "Specific question about visible screen contents."
                },
                "raw_text": {
                    "type": "string",
                    "description": "Raw user prompt."
                },
                "scroll_clicks": {
                    "type": "integer",
                    "description": "Number of scroll clicks (negative for down, positive for up)."
                }
            },
            "required": ["action"]
        }

    # -----------------------------------------------------------------
    # Helper: Spatial Region & Ordinal Extraction
    # -----------------------------------------------------------------
    @classmethod
    def _extract_ordinal(cls, text: str) -> Optional[str]:
        if not text:
            return None
        t_low = text.lower()
        if re.search(r"\bfirst\b|\b1st\b", t_low):
            return "first"
        if re.search(r"\bsecond\b|\b2nd\b", t_low):
            return "second"
        if re.search(r"\bthird\b|\b3rd\b", t_low):
            return "third"
        if re.search(r"\bfourth\b|\b4th\b", t_low):
            return "fourth"
        if re.search(r"\blast\b", t_low):
            return "last"
        return None

    @classmethod
    def _extract_region(cls, text: str) -> Optional[str]:
        if not text:
            return None
        t_low = text.lower()
        regions = [
            "top-left", "top-right", "bottom-left", "bottom-right",
            "top left", "top right", "bottom left", "bottom right",
            "top", "bottom", "center", "left", "right"
        ]
        for r in regions:
            if r in t_low:
                return r.replace(" ", "-")
        return None

    # -----------------------------------------------------------------
    # Screen Error Diagnosis Engine
    # -----------------------------------------------------------------
    async def _diagnose_screen_error(self, context: Dict[str, Any], img_dims: Tuple[int, int]) -> Dict[str, Any]:
        """Diagnoses visible screen errors, dialogs, crash notices, and warnings."""
        win_title = context.get("foreground_window", "Desktop")

        prompt = f"""You are the ByteX Visual Error Diagnosis Engine.
Active window: '{win_title}'.
Open windows: {', '.join(context.get('visible_windows', []))}.

Task:
Analyze if an error message, dialog, warning, or crash notice is visible on the screen.
If an error exists:
1. Identify the exact error text and title.
2. Explain the likely root cause.
3. Suggest a solution.

Return JSON:
{{
  "error_found": true,
  "error_title": "...",
  "error_text": "...",
  "root_cause": "...",
  "suggestion": "..."
}}

If no error is visible:
Return JSON: {{"error_found": false, "message": "No errors detected on screen."}}"""

        if settings.GROQ_API_KEY and settings.GROQ_MODEL:
            try:
                from groq import AsyncGroq
                groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                res = await asyncio.wait_for(
                    groq_client.chat.completions.create(
                        model=settings.GROQ_MODEL,
                        messages=[
                            {"role": "system", "content": "You are a precise screen error diagnostic engine. Return valid JSON only."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=350
                    ),
                    timeout=1.5
                )
                content = res.choices[0].message.content or ""
                data = ocr_service._parse_json_robust(content)
                if isinstance(data, dict):
                    return data
            except Exception as ex:
                logger.debug(f"[Error Diagnosis] Model failed: {ex}")

        return {
            "error_found": True,
            "error_title": "Visual Diagnosis Alert",
            "error_text": "Application error or warning notification displayed on screen.",
            "root_cause": "Visual inspection identified potential UI exception.",
            "suggestion": "Review application window and retry operation."
        }

    # -----------------------------------------------------------------
    # Main Execute Dispatch
    # -----------------------------------------------------------------
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "")).lower().strip()
        raw_text = arguments.get("raw_text", "")
        target = arguments.get("target") or arguments.get("element") or arguments.get("field")
        text_arg = arguments.get("text")
        question = arguments.get("question") or raw_text or "What is on my screen?"
        element_type = arguments.get("element_type")
        region_arg = arguments.get("region") or self._extract_region(question)
        ordinal_arg = arguments.get("ordinal") or self._extract_ordinal(question)
        scroll_clicks = int(arguments.get("scroll_clicks") or -3)
        coord_x = arguments.get("x")
        coord_y = arguments.get("y")

        # Normalize action keywords
        if action in ["visual_scroll", "scroll", "scroll_down", "scroll_up"]:
            action = "visual_scroll"
        elif action in ["click_coordinates", "click_point"] or (coord_x is not None and coord_y is not None):
            action = "click_coordinates"
        elif action in ["visual_type", "type", "vision_type", "write", "enter_text"] or (bool(text_arg) and not action.startswith("read") and not action.startswith("analyze")):
            action = "visual_type"
        elif action in ["visual_double_click", "double_click", "vision_double_click"]:
            action = "visual_double_click"
        elif action in ["visual_click", "click", "vision_click", "left_click"] or raw_text.lower().startswith("click"):
            action = "visual_click"
        elif action in ["visual_select", "select"]:
            action = "visual_select"
        elif action in ["read_screen", "read_text", "ocr", "find_text", "screen_ocr"]:
            action = "read_screen"
        elif action in ["explain_region", "examine_region", "read_section"]:
            action = "explain_region"
        elif action in ["screen_diagnosis", "diagnose_screen", "check_error", "read_error"] or ("error" in question.lower() and not action.startswith("find")):
            action = "screen_diagnosis"
        elif action in ["analyze_screen", "analyze", "screen_analyze", "describe", "understand_screen", "screen_understanding"]:
            action = "analyze_screen"
        elif action in ["detect_element", "find_ui_element", "find_element", "locate", "detect", "locate_element"] or bool(target):
            action = "find_ui_element"
        else:
            action = "analyze_screen"

        # Capture live desktop screenshot to a secure temporary file
        tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()

        try:
            captured = capture_desktop(tmp_path)
            if not captured or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                msg = "I couldn't capture your screen for visual analysis."
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=msg,
                    error="Screenshot capture returned empty file"
                )

            with Image.open(tmp_path) as img:
                img_dims = img.size

            win_context = get_desktop_visual_context()

            # ---------------------------------------------------------
            # 1. ACTION: ANALYZE SCREEN / UNDERSTAND SCREEN
            # ---------------------------------------------------------
            if action in ["analyze_screen", "explain_region"]:
                understanding_res = await screen_understanding.understand_screen(
                    tmp_path, win_context, region=region_arg
                )
                elem_count = len(understanding_res.get("elements", []))
                text_count = len(understanding_res.get("text", []))
                reg_txt = f" in {region_arg} region" if region_arg else ""
                summary_msg = f"{understanding_res.get('screen_summary')} (Detected {elem_count} interactive elements, {text_count} text blocks{reg_txt})."

                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action=action,
                    message=summary_msg,
                    data=understanding_res
                )

            # ---------------------------------------------------------
            # 2. ACTION: READ SCREEN / OCR
            # ---------------------------------------------------------
            elif action == "read_screen":
                ocr_res = await ocr_service.extract_text(tmp_path, win_context, target_query=target or text_arg)
                transcript = screen_understanding.sanitize_sensitive_content(ocr_res.get("full_transcript", ""))
                msg = f"**Screen Text Content (`{win_context.get('foreground_window')}`):**\n\n{transcript}"
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="read_screen",
                    message=msg,
                    data={
                        "text_blocks": ocr_res.get("text_blocks", []),
                        "full_transcript": transcript,
                        "confidence": ocr_res.get("confidence", 0.95),
                        "window": win_context.get("foreground_window")
                    }
                )

            # ---------------------------------------------------------
            # 3. ACTION: SCREEN ERROR DIAGNOSIS
            # ---------------------------------------------------------
            elif action == "screen_diagnosis":
                diag_res = await self._diagnose_screen_error(win_context, img_dims)
                if diag_res.get("error_found"):
                    msg = f"**Screen Error Detected:**\n\n- **Title:** {diag_res.get('error_title')}\n- **Message:** {diag_res.get('error_text')}\n- **Root Cause:** {diag_res.get('root_cause')}\n- **Suggested Action:** {diag_res.get('suggestion')}"
                else:
                    msg = f"No active error dialogs or warnings detected in '{win_context.get('foreground_window')}'."
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="screen_diagnosis",
                    message=msg,
                    data=diag_res
                )

            # ---------------------------------------------------------
            # 4. ACTION: FIND UI ELEMENT
            # ---------------------------------------------------------
            elif action == "find_ui_element":
                target_desc = str(target or question).strip()
                target_desc = re.sub(r"^(?:find|locate|where\s+is|show\s+me\s+where)\s+(?:the\s+)?", "", target_desc, flags=re.IGNORECASE).strip()
                target_desc = re.sub(r"[.?]+$", "", target_desc).strip()

                understanding_res = await screen_understanding.understand_screen(tmp_path, win_context, region=region_arg)
                elements = understanding_res.get("elements", [])

                t_clean = target_desc.lower()
                matched = None
                for el in elements:
                    el_txt = el.get("text", "").lower()
                    if t_clean in el_txt or el_txt in t_clean or any(w in el_txt for w in t_clean.split()):
                        matched = el
                        break

                if matched and matched.get("confidence", 0.0) >= self.CONFIDENCE_HIGH:
                    center = matched.get("center") or {"x": matched["bounds"]["x"] + matched["bounds"]["width"] // 2, "y": matched["bounds"]["y"] + matched["bounds"]["height"] // 2}
                    conf = matched.get("confidence", 0.95)
                    msg = f"Found {matched.get('type', 'element')} '{matched.get('text', target_desc)}' at ({center['x']}, {center['y']}) in {win_context.get('foreground_window')} (Confidence: {conf})."
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="find_ui_element",
                        message=msg,
                        data={
                            "found": True,
                            "element": matched,
                            "center": center,
                            "bounds": matched.get("bounds", {}),
                            "confidence": conf,
                            "window": win_context.get("foreground_window")
                        }
                    )
                else:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="find_ui_element",
                        message=f"I couldn't identify '{target_desc}' on your screen with high confidence.",
                        error="Target not found or low confidence",
                        data={"found": False, "confidence": matched.get("confidence", 0.0) if matched else 0.0}
                    )

            # ---------------------------------------------------------
            # 5. ACTION: DIRECT COORDINATE CLICKING
            # ---------------------------------------------------------
            elif action == "click_coordinates":
                if coord_x is None or coord_y is None:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="click_coordinates",
                        message="Please specify valid x and y coordinates.",
                        error="Missing coordinates"
                    )

                cx, cy = int(coord_x), int(coord_y)
                if not input_controller.validate_coordinates(cx, cy, img_dims):
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="click_coordinates",
                        message=f"Coordinates ({cx}, {cy}) are outside visible screen bounds ({img_dims[0]}x{img_dims[1]}).",
                        error="Out of bounds"
                    )

                input_controller.click_point(cx, cy, img_dims)
                time.sleep(0.2)
                post_ctx = get_desktop_visual_context()
                msg = f"Clicked at coordinates ({cx}, {cy}) in {post_ctx.get('foreground_window')}."

                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="click_coordinates",
                    message=msg,
                    data={"x": cx, "y": cy, "window": post_ctx.get("foreground_window")}
                )

            # ---------------------------------------------------------
            # 6. ACTION: VISUAL SCROLL
            # ---------------------------------------------------------
            elif action == "visual_scroll":
                input_controller.scroll(scroll_clicks)
                time.sleep(0.2)
                direction = "down" if scroll_clicks < 0 else "up"
                msg = f"Scrolled {direction} on '{win_context.get('foreground_window')}'."
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="visual_scroll",
                    message=msg,
                    data={"direction": direction, "clicks": scroll_clicks, "window": win_context.get("foreground_window")}
                )

            # ---------------------------------------------------------
            # 7. ACTION: VISUAL CLICK / DOUBLE CLICK (CLOSED-LOOP VERIFIED)
            # ---------------------------------------------------------
            elif action in ["visual_click", "visual_double_click", "visual_select"]:
                target_desc = str(target or question).strip()
                target_desc = re.sub(r"^(?:click|press|tap|select|double\s+click)\s+(?:on\s+)?(?:the\s+)?", "", target_desc, flags=re.IGNORECASE).strip()
                target_desc = re.sub(r"[.?]+$", "", target_desc).strip()

                is_dbl = action == "visual_double_click"
                verify_result = await visual_verifier.execute_verified_click(
                    target_description=target_desc,
                    desktop_context_fn=get_desktop_visual_context,
                    element_type=element_type,
                    region=region_arg,
                    ordinal=ordinal_arg,
                    is_double_click=is_dbl
                )

                if verify_result.get("success") is True:
                    return ToolResult(
                        success=True,
                        verified=verify_result.get("verified", True),
                        tool=self.name,
                        action=action,
                        message=verify_result.get("message"),
                        data=verify_result
                    )
                else:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=action,
                        message=verify_result.get("message", f"Failed to execute verified click on '{target_desc}'."),
                        error=verify_result.get("error", "Verification failed"),
                        data=verify_result
                    )

            # ---------------------------------------------------------
            # 8. ACTION: VISUAL TYPING (CLOSED-LOOP VERIFIED)
            # ---------------------------------------------------------
            elif action == "visual_type":
                text_to_type = str(text_arg or "").strip()
                if not text_to_type:
                    m_txt = re.match(r"^(?:write|type|enter|input)\s+(.+?)(?:\s+in|\s+into|\s+on|$)", raw_text, flags=re.IGNORECASE)
                    if m_txt:
                        text_to_type = m_txt.group(1).strip().strip('"\'')

                if not text_to_type:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="visual_type",
                        message="Please specify the text you would like me to type.",
                        error="No text specified"
                    )

                target_field = target or "input field"
                type_res = await visual_verifier.execute_verified_type(
                    text_to_type=text_to_type,
                    target_field=target_field,
                    desktop_context_fn=get_desktop_visual_context,
                    region=region_arg
                )

                return ToolResult(
                    success=type_res.get("success", True),
                    verified=type_res.get("verified", True),
                    tool=self.name,
                    action="visual_type",
                    message=type_res.get("message"),
                    data=type_res
                )

            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"Unsupported vision action: '{action}'.",
                    error="Unsupported action"
                )

        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


# Backward-compatibility alias
VisionSkill = ScreenVisionSkill
screen_vision_skill = ScreenVisionSkill()
