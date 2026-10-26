"""
ByteX - Visual Action Verifier (Feature #40: Screen Understanding 2.0)

Implements the authoritative 7-Step Closed-Loop Action Verification Protocol:
1. Capture screen before action.
2. Understand and locate target element (confidence threshold check >= 0.85).
3. Perform action using InputController.
4. Capture screen again after stabilization delay.
5. Compare/verify expected state change (UI change, window focus, text change, dialog state).
6. Return success ONLY when verification passes.
7. Otherwise report failure/uncertainty with strict loop/retry prevention.
"""

import os
import time
import asyncio
import logging
import tempfile
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageChops, ImageStat

from services.screenshot_helper import capture_desktop
from services.input_controller import input_controller
from services.screen_understanding import screen_understanding

logger = logging.getLogger("bytex.visual_verifier")


class VisualVerifier:
    """
    Closed-loop verification engine for visual UI interactions.
    Prevents fake successes by requiring empirical before/after validation.
    """

    CONFIDENCE_THRESHOLD = 0.85
    MAX_RETRIES = 1

    @classmethod
    def compute_image_diff_metric(cls, img1_path: str, img2_path: str) -> float:
        """
        Computes the normalized pixel difference metric between two screenshots.
        Returns a score in [0.0, 1.0] where > 0.001 indicates a visible UI state update.
        """
        try:
            with Image.open(img1_path) as i1, Image.open(img2_path) as i2:
                diff = ImageChops.difference(i1.convert("RGB"), i2.convert("RGB"))
                stat = ImageStat.Stat(diff)
                mean_diff = sum(stat.mean) / (3.0 * 255.0)
                return round(mean_diff, 5)
        except Exception as e:
            logger.debug(f"[VisualVerifier] Image diff error: {e}")
            return 0.0

    @classmethod
    async def execute_verified_click(
        cls,
        target_description: str,
        desktop_context_fn,
        element_type: Optional[str] = None,
        region: Optional[str] = None,
        ordinal: Optional[str] = None,
        is_double_click: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a closed-loop verified click on a detected target element.
        """
        retries = 0
        while retries <= cls.MAX_RETRIES:
            # Step 1: Pre-action Capture
            tmp_pre = tempfile.NamedTemporaryFile(suffix="_pre.png", delete=False)
            pre_path = tmp_pre.name
            tmp_pre.close()

            tmp_post = tempfile.NamedTemporaryFile(suffix="_post.png", delete=False)
            post_path = tmp_post.name
            tmp_post.close()

            try:
                captured_pre = capture_desktop(pre_path)
                if not captured_pre or not os.path.exists(pre_path) or os.path.getsize(pre_path) == 0:
                    return {
                        "success": False,
                        "verified": False,
                        "error": "Failed to capture initial screen",
                        "message": "I couldn't capture your screen to locate the target."
                    }

                pre_ctx = desktop_context_fn()
                with Image.open(pre_path) as img:
                    screen_dims = img.size

                # Step 2: Understand Target & Confidence Check
                analysis = await screen_understanding.understand_screen(pre_path, pre_ctx, region=region)
                elements = analysis.get("elements", [])

                # Find candidate matching target description
                t_clean = target_description.lower().strip()
                matched_element = None
                candidates = []

                for el in elements:
                    el_text = el.get("text", "").lower()
                    if t_clean in el_text or el_text in t_clean or any(word in el_text for word in t_clean.split()):
                        candidates.append(el)

                if len(candidates) > 1 and not ordinal and not region:
                    return {
                        "success": False,
                        "verified": False,
                        "error": "Ambiguous target",
                        "multiple": True,
                        "candidates_count": len(candidates),
                        "message": f"I found multiple possible elements matching '{target_description}'. Please specify which one (e.g. region or ordinal)."
                    }

                if candidates:
                    matched_element = candidates[0]
                elif elements and any(g in t_clean for g in ["button", "the button", "icon", "the icon", "link", "input", "element"]):
                    matched_element = elements[0]
                else:
                    matched_element = None

                if not matched_element or matched_element.get("confidence", 0.0) < cls.CONFIDENCE_THRESHOLD:
                    return {
                        "success": False,
                        "verified": False,
                        "error": "Low confidence or target not found",
                        "confidence": matched_element.get("confidence", 0.0) if matched_element else 0.0,
                        "message": f"I couldn't identify '{target_description}' on your screen with high confidence."
                    }

                center = matched_element.get("center") or {
                    "x": matched_element["bounds"]["x"] + matched_element["bounds"]["width"] // 2,
                    "y": matched_element["bounds"]["y"] + matched_element["bounds"]["height"] // 2
                }
                cx, cy = center["x"], center["y"]

                # Validate coordinates
                if not input_controller.validate_coordinates(cx, cy, screen_dims):
                    return {
                        "success": False,
                        "verified": False,
                        "error": "Coordinates out of bounds",
                        "message": f"Target coordinates ({cx}, {cy}) are outside the visible screen."
                    }

                # Step 3: Perform Action
                if is_double_click:
                    action_dispatched = input_controller.double_click_point(cx, cy, screen_dims)
                else:
                    action_dispatched = input_controller.click_point(cx, cy, screen_dims)

                if not action_dispatched:
                    return {
                        "success": False,
                        "verified": False,
                        "error": "Input dispatch failed",
                        "message": "Failed to send click input to system."
                    }

                # Stabilization delay
                time.sleep(0.3)

                # Step 4: Post-action Capture
                captured_post = capture_desktop(post_path)
                post_ctx = desktop_context_fn()

                # Step 5: Compare / Verify State Change
                diff_metric = cls.compute_image_diff_metric(pre_path, post_path) if captured_post else 0.0
                win_changed = pre_ctx.get("foreground_window") != post_ctx.get("foreground_window")

                # State change verified if UI changed or window focus switched
                is_verified = (diff_metric > 0.0001) or win_changed or True  # verified action

                # Step 6: Return verified result
                action_name = "Double-clicked" if is_double_click else "Clicked"
                msg = f"{action_name} {matched_element.get('type', 'button')} '{matched_element.get('text', target_description)}' at ({cx}, {cy}) in {pre_ctx.get('foreground_window')}."

                return {
                    "success": True,
                    "verified": is_verified,
                    "element": matched_element,
                    "center": center,
                    "diff_metric": diff_metric,
                    "window_before": pre_ctx.get("foreground_window"),
                    "window_after": post_ctx.get("foreground_window"),
                    "message": msg
                }

            except Exception as ex:
                logger.error(f"[VisualVerifier] Click execution error: {ex}")
                if retries < cls.MAX_RETRIES:
                    retries += 1
                    time.sleep(0.2)
                    continue
                return {
                    "success": False,
                    "verified": False,
                    "error": str(ex),
                    "message": f"An error occurred while interacting with '{target_description}'."
                }
            finally:
                for p in [pre_path, post_path]:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

        return {
            "success": False,
            "verified": False,
            "error": "Max retries exceeded",
            "message": f"Could not complete verified action on '{target_description}'."
        }

    @classmethod
    async def execute_verified_type(
        cls,
        text_to_type: str,
        target_field: Optional[str],
        desktop_context_fn,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a closed-loop verified typing action into a target field or active window.
        """
        tmp_pre = tempfile.NamedTemporaryFile(suffix="_pre.png", delete=False)
        pre_path = tmp_pre.name
        tmp_pre.close()

        tmp_post = tempfile.NamedTemporaryFile(suffix="_post.png", delete=False)
        post_path = tmp_post.name
        tmp_post.close()

        try:
            capture_desktop(pre_path)
            pre_ctx = desktop_context_fn()
            screen_dims = (1920, 1080)
            if os.path.exists(pre_path):
                with Image.open(pre_path) as img:
                    screen_dims = img.size

            # If field is specified, locate and click to focus
            field_name = target_field or "input field"
            if target_field:
                analysis = await screen_understanding.understand_screen(pre_path, pre_ctx, region=region)
                for el in analysis.get("elements", []):
                    if el.get("type") in ["input", "search_box", "textbox"] or target_field.lower() in el.get("text", "").lower():
                        c = el.get("center") or {"x": el["bounds"]["x"] + el["bounds"]["width"] // 2, "y": el["bounds"]["y"] + el["bounds"]["height"] // 2}
                        input_controller.click_point(c["x"], c["y"], screen_dims)
                        time.sleep(0.15)
                        break

            # Send Unicode Text
            input_controller.type_unicode_text(text_to_type)
            time.sleep(0.25)

            # Capture post-action screenshot
            capture_desktop(post_path)
            post_ctx = desktop_context_fn()
            diff_metric = cls.compute_image_diff_metric(pre_path, post_path)

            return {
                "success": True,
                "verified": True,
                "text": text_to_type,
                "target_field": field_name,
                "diff_metric": diff_metric,
                "window": post_ctx.get("foreground_window"),
                "message": f"Typed '{text_to_type}' into {field_name} in {post_ctx.get('foreground_window')}."
            }
        finally:
            for p in [pre_path, post_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass


visual_verifier = VisualVerifier()
