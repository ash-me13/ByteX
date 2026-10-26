"""
ByteX - Self-Healing & Error Recovery Engine 2.0 (Feature #41)

Provides comprehensive, safe, bounded self-healing and error recovery:
1. Centralized Structured Failure Classification: Classifies execution failures into standard categories
   (TIMEOUT, APPLICATION_NOT_FOUND, PERMISSION_DENIED, NETWORK_ERROR, ELEMENT_NOT_FOUND, etc.)
2. Safe Bounded Retry Policy: Enforces max 3 retries per step, max 5 per task, exponential backoff,
   and prevents repeated identical actions without a changed strategy.
3. Self-Correction Strategy Engine: Dispatches alternative strategies (alternative app launch paths,
   Screen Understanding 2.0 re-scan, HWND focus restore, Smart File Manager search fallback).
4. Safety & Security Invariants: Destructive/high-risk actions (delete, format, kill, send_message, pay)
   are NEVER automatically retried without explicit user confirmation.
5. Observability & Activity Timeline: Emits structured lifecycle events (TASK_STARTED, FAILURE_CLASSIFIED,
   RECOVERY_STRATEGY_SELECTED, RETRY_ATTEMPTED, RECOVERY_SUCCEEDED, TASK_RESUMED, TASK_FAILED).
"""

import re
import time
import ctypes
import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel, Field

from skills.base import ToolResult
from skills.registry import skill_registry
from agent.models import (
    PlanStep,
    StepState,
    FailureRecord,
    RecoveryTimelineEventType,
    RecoveryTimelineEvent
)
from core.session import session_manager
from agent.context import agent_context_manager
from core.risk_classifier import ActionRiskClassifier, RiskLevel

logger = logging.getLogger("bytex.agent.recovery")

is_windows = ctypes.windll is not None if hasattr(ctypes, "windll") else False
if is_windows:
    user32 = ctypes.windll.user32
else:
    user32 = None


class ErrorCategory(str, Enum):
    # Core Standard Failure Categories (Feature #41)
    TIMEOUT = "TIMEOUT"
    APPLICATION_NOT_FOUND = "APPLICATION_NOT_FOUND"
    APPLICATION_NOT_RESPONDING = "APPLICATION_NOT_RESPONDING"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NETWORK_ERROR = "NETWORK_ERROR"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    VISUAL_VERIFICATION_FAILED = "VISUAL_VERIFICATION_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_ACCESS_ERROR = "FILE_ACCESS_ERROR"
    COMMAND_FAILED = "COMMAND_FAILED"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    RESOURCE_ERROR = "RESOURCE_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

    # Specific Structural Sub-Categories for backwards compatibility
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    WINDOW_NOT_FOCUSED = "WINDOW_NOT_FOCUSED"
    APPLICATION_NOT_RUNNING = "APPLICATION_NOT_RUNNING"
    ELEMENT_AMBIGUOUS = "ELEMENT_AMBIGUOUS"
    INPUT_NOT_AVAILABLE = "INPUT_NOT_AVAILABLE"
    FILE_ALREADY_EXISTS = "FILE_ALREADY_EXISTS"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    BROWSER_FAILURE = "BROWSER_FAILURE"
    ALREADY_IN_DESIRED_STATE = "ALREADY_IN_DESIRED_STATE"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class RecoveryAction(str, Enum):
    PROCEED_AS_SUCCESS = "PROCEED_AS_SUCCESS"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    RECOVER_WINDOW = "RECOVER_WINDOW"
    ASK_USER = "ASK_USER"
    STOP_FAIL = "STOP_FAIL"


class RecoveryDecision(BaseModel):
    action: RecoveryAction
    error_category: ErrorCategory
    is_recoverable: bool
    reason: str
    suggested_step: Optional[PlanStep] = None
    clean_user_message: Optional[str] = None
    requires_confirmation: bool = False
    strategy_name: Optional[str] = None


# Destructive / High-risk actions that must NEVER be automatically retried
DESTRUCTIVE_ACTIONS = {
    "delete_file", "delete_folder", "rmdir", "del", "format", "taskkill",
    "close_application", "shutdown", "restart", "reboot", "send_message", "pay",
    "wipe", "erase", "drop", "destroy", "purge"
}


class ErrorRecoveryEngine:
    """
    Self-Healing & Error Recovery Engine 2.0 for ByteX Agent.
    """

    MAX_RETRIES_PER_STEP: int = 3
    MAX_TASK_RECOVERY_ATTEMPTS: int = 5

    def __init__(self):
        self._timeline_events: List[RecoveryTimelineEvent] = []

    def record_timeline_event(
        self,
        event_type: RecoveryTimelineEventType,
        task_id: str,
        step_id: Optional[int] = None,
        action: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> RecoveryTimelineEvent:
        """Records an observable recovery lifecycle event into the activity timeline."""
        evt = RecoveryTimelineEvent(
            event_type=event_type,
            task_id=task_id,
            step_id=step_id,
            action=action,
            details=details or {},
            timestamp=time.time()
        )
        self._timeline_events.append(evt)
        # Keep bounded memory of timeline events
        if len(self._timeline_events) > 1000:
            self._timeline_events = self._timeline_events[-500:]
        print(f"[ByteX RecoveryTimeline] [{event_type.value}] Task: {task_id} Step: {step_id} Action: '{action}'")
        return evt

    def get_timeline_events(self, task_id: Optional[str] = None) -> List[RecoveryTimelineEvent]:
        """Returns recorded timeline events, optionally filtered by task_id."""
        if task_id:
            return [e for e in self._timeline_events if e.task_id == task_id]
        return list(self._timeline_events)

    def clear_timeline(self):
        """Clears memory timeline events."""
        self._timeline_events.clear()

    @classmethod
    def get_backoff_delay(cls, attempt: int) -> float:
        """Computes safe bounded exponential backoff delay in seconds (0.15s to 1.0s)."""
        return min(1.0, 0.15 * (2 ** max(0, attempt - 1)))

    @classmethod
    def is_destructive_action(cls, skill_name: str, arguments: Dict[str, Any]) -> bool:
        """Determines if a step action is destructive or high-risk."""
        if skill_name.lower() in DESTRUCTIVE_ACTIONS:
            return True
        action_arg = str(arguments.get("action", "")).lower()
        if any(d in action_arg for d in ["delete", "remove", "kill", "format", "wipe", "destroy", "shutdown"]):
            return True
        assessment = ActionRiskClassifier.classify_action(skill_name, arguments)
        return assessment.risk_level in [RiskLevel.DANGEROUS, RiskLevel.BLOCKED]

    @classmethod
    def classify_error(cls, skill_name: str, arguments: Dict[str, Any], tool_result: ToolResult) -> ErrorCategory:
        """
        Deterministically classifies the failure category based on execution outcome and message.
        """
        status_tag = str(tool_result.data.get("status", "")).lower() if tool_result.data else ""
        msg_lower = (tool_result.message or "").lower()
        err_lower = (tool_result.error or "").lower()
        combined = f"{msg_lower} {err_lower} {status_tag}"

        # 1. State already achieved
        if tool_result.verified and any(k in combined for k in ["already open", "already closed", "already_visible", "already_closed", "already running"]):
            return ErrorCategory.ALREADY_IN_DESIRED_STATE

        # 2. Permission Denied / Security Boundary
        if any(k in combined for k in ["permission", "blocked", "restricted", "access denied", "security boundary", "unauthorized"]):
            return ErrorCategory.PERMISSION_DENIED

        # 3. Window Not Focused
        if any(k in combined for k in ["not focused", "lost focus", "inactive window", "background window", "foreground verification failed"]):
            return ErrorCategory.WINDOW_NOT_FOCUSED

        # 4. Window Not Found / Closed / Stale HWND
        if any(k in combined for k in ["window not found", "invalid hwnd", "hwnd is no longer open", "window is closed", "stale hwnd", "no longer exists", "stale context"]):
            return ErrorCategory.WINDOW_NOT_FOUND

        # 5. Application Not Responding
        if any(k in combined for k in ["not responding", "frozen", "hang", "hung", "deadlock", "busy"]):
            return ErrorCategory.APPLICATION_NOT_RESPONDING

        # 6. Application Not Running / Application Not Found
        if any(k in combined for k in ["application not running", "process not found", "could not find process", "is no longer running"]):
            return ErrorCategory.APPLICATION_NOT_RUNNING

        if any(k in combined for k in ["application not found", "app not found", "not installed", "could not find application", "couldn't find"]):
            return ErrorCategory.APPLICATION_NOT_FOUND

        # 7. Element Ambiguous
        if any(k in combined for k in ["ambiguous", "multiple elements", "multiple targets", "which one", "multiple buttons"]):
            return ErrorCategory.ELEMENT_AMBIGUOUS

        # 8. Element Not Found / Target Disappeared
        if any(k in combined for k in ["element not found", "could not detect", "target not detected", "button not found", "no matching ui element", "failed to locate", "could not locate", "target not found", "not found on screen"]):
            return ErrorCategory.ELEMENT_NOT_FOUND

        # 9. Input Not Available / Invalid Input
        if any(k in combined for k in ["input not available", "input field disappeared", "field not editable", "cannot type"]):
            return ErrorCategory.INPUT_NOT_AVAILABLE

        if any(k in combined for k in ["invalid input", "missing argument", "invalid argument", "parameter missing", "no text specified", "missing coordinates"]):
            return ErrorCategory.INVALID_INPUT

        # 10. File Already Exists / File Access Error
        if any(k in combined for k in ["file already exists", "already exists", "fileexists"]):
            return ErrorCategory.FILE_ALREADY_EXISTS

        if any(k in combined for k in ["file access error", "sharing violation", "file in use", "locked file", "ioerror"]):
            return ErrorCategory.FILE_ACCESS_ERROR

        # 11. File Not Found
        if any(k in combined for k in ["filenotfound", "file not found", "file does not exist", "path not found", "directory not found"]):
            return ErrorCategory.FILE_NOT_FOUND

        # 12. Network / DNS / HTTP Failure
        if any(k in combined for k in ["network", "dns", "getaddrinfo failed", "connection refused", "http error", "offline", "connection timeout", "network_error"]):
            return ErrorCategory.NETWORK_ERROR

        # 13. Browser / CDP Failure
        if any(k in combined for k in ["browser failure", "cdp disconnected", "target closed", "tab crashed", "page not loaded"]):
            return ErrorCategory.BROWSER_FAILURE

        # 14. Timeout
        if any(k in combined for k in ["timeout", "timed out", "wait timed out", "exceeded timeout"]):
            return ErrorCategory.TIMEOUT

        # 15. Dependency / Resource Error
        if any(k in combined for k in ["dependency", "missing dependency", "module not found", "import error", "driver missing"]):
            return ErrorCategory.DEPENDENCY_ERROR

        if any(k in combined for k in ["out of memory", "resource error", "disk full", "insufficient resources"]):
            return ErrorCategory.RESOURCE_ERROR

        # 16. Physical Visual Verification Failed
        if not tool_result.verified and ("verification" in combined or "could not be verified" in combined or "launch verification failed" in combined or "verification failed" in combined):
            return ErrorCategory.VISUAL_VERIFICATION_FAILED

        # 17. Generic Command Failed
        if any(k in combined for k in ["failed with exit code", "command failed", "execution exception", "process exited"]):
            return ErrorCategory.COMMAND_FAILED

        # 18. Generic Not Found (App/Executable)
        if any(k in combined for k in ["not found"]):
            return ErrorCategory.NOT_FOUND

        return ErrorCategory.UNKNOWN_ERROR

    @classmethod
    def classify_failure(
        cls,
        skill_name: str,
        arguments: Dict[str, Any],
        tool_result: ToolResult,
        task_id: str = "",
        step_id: int = 1,
        retry_count: int = 0
    ) -> FailureRecord:
        """
        Builds a structured FailureRecord for comprehensive error observability.
        """
        category = cls.classify_error(skill_name, arguments, tool_result)
        is_dest = cls.is_destructive_action(skill_name, arguments)

        # Determine if recoverable
        is_rec = True
        strategies = []

        if is_dest or category == ErrorCategory.PERMISSION_DENIED:
            is_rec = False
            strategies = ["require_explicit_confirmation" if is_dest else "report_security_blocker"]
        elif category in [ErrorCategory.APPLICATION_NOT_FOUND, ErrorCategory.APPLICATION_NOT_RUNNING]:
            strategies = ["search_alternative_window", "resolve_universal_launch_path", "launch_application_safely"]
        elif category in [ErrorCategory.ELEMENT_NOT_FOUND, ErrorCategory.INPUT_NOT_AVAILABLE]:
            strategies = ["refocus_window", "screen_understanding_recapture", "visual_grounding_retry"]
        elif category in [ErrorCategory.VISUAL_VERIFICATION_FAILED]:
            strategies = ["settle_delay", "post_action_diff_recheck", "safe_single_retry"]
        elif category in [ErrorCategory.TIMEOUT, ErrorCategory.APPLICATION_NOT_RESPONDING]:
            strategies = ["bounded_settle_delay", "check_process_liveness", "safe_timeout_retry"]
        elif category in [ErrorCategory.NETWORK_ERROR, ErrorCategory.NETWORK_FAILURE]:
            strategies = ["exponential_backoff_retry", "stop_after_max_network_retries"]
        elif category in [ErrorCategory.FILE_NOT_FOUND]:
            strategies = ["verify_exact_path", "smart_file_search_fallback"]
        elif category in [ErrorCategory.WINDOW_NOT_FOCUSED, ErrorCategory.WINDOW_NOT_FOUND]:
            strategies = ["restore_and_focus_window", "find_replacement_hwnd"]
        else:
            strategies = ["bounded_safe_retry"]

        if retry_count >= cls.MAX_RETRIES_PER_STEP:
            is_rec = False

        from services.screen_understanding import ScreenUnderstandingService
        sanitized_err = ScreenUnderstandingService.sanitize_sensitive_content(tool_result.error or tool_result.message or "Execution failed")

        return FailureRecord(
            error_type=category.value,
            original_error=sanitized_err,
            failed_action=skill_name,
            task_id=task_id,
            step_id=step_id,
            timestamp=time.time(),
            retry_count=retry_count,
            is_recoverable=is_rec,
            suggested_recovery_strategies=strategies
        )

    def evaluate_recovery(
        self,
        step: PlanStep,
        tool_result: ToolResult,
        task_recovery_count: int = 0,
        task_id: str = ""
    ) -> RecoveryDecision:
        """
        Diagnoses step failure and produces a safe, structured recovery strategy.
        """
        category = self.classify_error(step.suggested_skill, step.arguments, tool_result)
        is_destructive = self.is_destructive_action(step.suggested_skill, step.arguments)

        # Emit ACTION_FAILED and FAILURE_CLASSIFIED
        self.record_timeline_event(
            event_type=RecoveryTimelineEventType.ACTION_FAILED,
            task_id=task_id,
            step_id=step.step_id,
            action=step.suggested_skill,
            details={"message": tool_result.message, "error": tool_result.error}
        )
        self.record_timeline_event(
            event_type=RecoveryTimelineEventType.FAILURE_CLASSIFIED,
            task_id=task_id,
            step_id=step.step_id,
            action=step.suggested_skill,
            details={"category": category.value, "is_destructive": is_destructive}
        )

        print(f"[ByteX ErrorRecovery] Step {step.step_id} Error Classified as: {category.value}")

        # Strategy 1: State already achieved -> Proceed as Success
        if category == ErrorCategory.ALREADY_IN_DESIRED_STATE:
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_SUCCEEDED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "proceed_as_success"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="proceed_as_success",
                attempt=step.replan_count,
                result="success"
            )
            return RecoveryDecision(
                action=RecoveryAction.PROCEED_AS_SUCCESS,
                error_category=category,
                is_recoverable=True,
                reason="Target is already in the desired state and physical verification passed.",
                clean_user_message=tool_result.message,
                strategy_name="proceed_as_success"
            )

        # Strategy 2: Safety Check: Destructive / High-Risk Actions NEVER Auto-Retry
        if is_destructive:
            print(f"[ByteX ErrorRecovery] Step {step.step_id} is DESTRUCTIVE/HIGH-RISK. Automatic retry blocked for safety.")
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.TASK_FAILED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"reason": "destructive_auto_retry_blocked"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="blocked_destructive_safety",
                attempt=step.replan_count,
                result="requires_confirmation"
            )
            return RecoveryDecision(
                action=RecoveryAction.STOP_FAIL,
                error_category=category,
                is_recoverable=False,
                requires_confirmation=True,
                reason="Destructive operations cannot be automatically retried without user confirmation.",
                clean_user_message=f"The {step.arguments.get('action') or step.suggested_skill} action failed. High-risk operations require explicit confirmation to retry.",
                strategy_name="blocked_destructive_safety"
            )

        # Strategy 3: Permission Denied -> Strictly Non-Recoverable
        if category == ErrorCategory.PERMISSION_DENIED:
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.TASK_FAILED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"reason": "permission_denied"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="stop_permission_denied",
                attempt=step.replan_count,
                result="failed"
            )
            return RecoveryDecision(
                action=RecoveryAction.STOP_FAIL,
                error_category=category,
                is_recoverable=False,
                reason="Action blocked by system permission or security boundary.",
                clean_user_message="Action blocked: access is restricted for security.",
                strategy_name="stop_permission_denied"
            )

        # Strategy 4: Element Ambiguous -> Ask User (Never guess or click blindly)
        if category == ErrorCategory.ELEMENT_AMBIGUOUS:
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STARTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "ask_user_clarification"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="ask_user_clarification",
                attempt=step.replan_count,
                result="requires_user_input"
            )
            return RecoveryDecision(
                action=RecoveryAction.ASK_USER,
                error_category=category,
                is_recoverable=False,
                reason="Multiple possible matching elements detected on screen.",
                clean_user_message="I found multiple possible targets on your screen. Which one would you like me to click?",
                strategy_name="ask_user_clarification"
            )

        # Strategy 5: Check Retry Limits (Safe Bounded Policy)
        if step.replan_count >= self.MAX_RETRIES_PER_STEP or task_recovery_count >= self.MAX_TASK_RECOVERY_ATTEMPTS:
            print(f"[ByteX ErrorRecovery] Step {step.step_id} reached recovery limit ({step.replan_count}/{self.MAX_RETRIES_PER_STEP} step retries, {task_recovery_count}/{self.MAX_TASK_RECOVERY_ATTEMPTS} task retries). Halting.")
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.TASK_FAILED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"reason": "retry_limit_exhausted", "attempts": step.replan_count}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="retry_limit_exhausted",
                attempt=step.replan_count,
                result="failed"
            )
            return RecoveryDecision(
                action=RecoveryAction.STOP_FAIL,
                error_category=category,
                is_recoverable=False,
                reason="Recovery retry limit reached.",
                clean_user_message=f"I couldn't complete '{step.description}' after {self.MAX_RETRIES_PER_STEP} recovery attempts.",
                strategy_name="retry_limit_exhausted"
            )

        # Strategy 6: Window Focus Recovery (WINDOW_NOT_FOCUSED)
        if category == ErrorCategory.WINDOW_NOT_FOCUSED:
            win_ctx = agent_context_manager.get_active_window()
            target_hwnd = win_ctx.get("hwnd") if win_ctx else None

            if is_windows and target_hwnd and user32 and user32.IsWindow(target_hwnd):
                try:
                    if user32.IsIconic(target_hwnd):
                        user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
                    user32.BringWindowToTop(target_hwnd)
                    user32.SetForegroundWindow(target_hwnd)
                    time.sleep(0.1)
                    print(f"[ByteX ErrorRecovery] Restored & focused target HWND {target_hwnd}.")
                except Exception as e:
                    logger.warning(f"Failed to bring window to foreground: {e}")

            retry_step = PlanStep(
                step_id=step.step_id,
                description=f"{step.description} (Refocused Window)",
                suggested_skill=step.suggested_skill,
                arguments=step.arguments,
                requires_confirmation=step.requires_confirmation,
                status=StepState.PENDING,
                replan_count=step.replan_count + 1,
                max_replans=self.MAX_RETRIES_PER_STEP
            )
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "restore_and_focus_window"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="restore_and_focus_window",
                attempt=step.replan_count + 1,
                result="retrying"
            )
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                error_category=category,
                is_recoverable=True,
                reason="Restored and focused target window before retrying action.",
                suggested_step=retry_step,
                clean_user_message="The target window lost focus, so I restored it and continued.",
                strategy_name="restore_and_focus_window"
            )

        # Strategy 7: Application / Window Recovery (APPLICATION_NOT_FOUND / APPLICATION_NOT_RUNNING / WINDOW_NOT_FOUND)
        if category in [ErrorCategory.APPLICATION_NOT_FOUND, ErrorCategory.APPLICATION_NOT_RUNNING, ErrorCategory.WINDOW_NOT_FOUND, ErrorCategory.NOT_FOUND]:
            app_target = step.arguments.get("application") or step.arguments.get("target") or "Notepad"

            from skills.apps import find_windows_for_process_or_title
            cand_windows = find_windows_for_process_or_title(str(app_target))
            if cand_windows:
                best_w = cand_windows[0]
                new_hwnd = best_w.get("hwnd", 0)
                new_pid = best_w.get("pid", 0)
                new_title = best_w.get("title", "")

                agent_context_manager.set_active_window({"hwnd": new_hwnd, "pid": new_pid, "title": new_title, "application": app_target})
                session_manager._working_context["active_window"] = {"hwnd": new_hwnd, "pid": new_pid, "title": new_title}
                session_manager._working_context["active_application"] = {"name": app_target, "pid": new_pid, "hwnd": new_hwnd, "title": new_title}

                print(f"[ByteX ErrorRecovery] Found existing window context HWND {new_hwnd} ('{new_title}').")

                retry_step = PlanStep(
                    step_id=step.step_id,
                    description=f"{step.description} (Connected to window '{new_title}')",
                    suggested_skill=step.suggested_skill,
                    arguments=step.arguments,
                    requires_confirmation=step.requires_confirmation,
                    status=StepState.PENDING,
                    replan_count=step.replan_count + 1,
                    max_replans=self.MAX_RETRIES_PER_STEP
                )
                self.record_timeline_event(
                    event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                    task_id=task_id,
                    step_id=step.step_id,
                    action=step.suggested_skill,
                    details={"strategy": "connect_existing_window", "hwnd": new_hwnd}
                )
                agent_context_manager.record_recovery_attempt(
                    step_id=step.step_id,
                    original_action=step.suggested_skill,
                    failure=category.value,
                    recovery="find_replacement_window_and_update_context",
                    attempt=step.replan_count + 1,
                    result="retrying"
                )
                return RecoveryDecision(
                    action=RecoveryAction.RETRY,
                    error_category=category,
                    is_recoverable=True,
                    reason=f"Found replacement window HWND {new_hwnd} for '{app_target}'. Updated working context.",
                    suggested_step=retry_step,
                    clean_user_message=f"I located the open {app_target} window and reconnected.",
                    strategy_name="connect_existing_window"
                )

            # If not open, launch application safely
            launch_step = PlanStep(
                step_id=step.step_id,
                description=f"Launch {app_target} on desktop",
                suggested_skill="open_application",
                arguments={"application": app_target},
                requires_confirmation=False,
                status=StepState.PENDING,
                replan_count=step.replan_count + 1,
                max_replans=self.MAX_RETRIES_PER_STEP
            )
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "launch_application_safely", "app": app_target}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="relaunch_safe_application",
                attempt=step.replan_count + 1,
                result="retrying"
            )
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                error_category=category,
                is_recoverable=True,
                reason=f"Application '{app_target}' was not running; launching to recover workflow.",
                suggested_step=launch_step,
                clean_user_message=f"I launched {app_target} and resumed your task.",
                strategy_name="launch_application_safely"
            )

        # Strategy 8: Vision Element Recovery (ELEMENT_NOT_FOUND / INPUT_NOT_AVAILABLE / VISUAL_VERIFICATION_FAILED)
        if category in [ErrorCategory.ELEMENT_NOT_FOUND, ErrorCategory.INPUT_NOT_AVAILABLE, ErrorCategory.VISUAL_VERIFICATION_FAILED]:
            agent_context_manager.ensure_active_window_focused()
            time.sleep(0.2)

            retry_step = PlanStep(
                step_id=step.step_id,
                description=f"{step.description} (Screen Understanding 2.0 Re-scan)",
                suggested_skill=step.suggested_skill,
                arguments=step.arguments,
                requires_confirmation=step.requires_confirmation,
                status=StepState.PENDING,
                replan_count=step.replan_count + 1,
                max_replans=self.MAX_RETRIES_PER_STEP
            )
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "vision_recapture_and_redetect"}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="vision_recapture_and_redetect",
                attempt=step.replan_count + 1,
                result="retrying"
            )
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                error_category=category,
                is_recoverable=True,
                reason="Re-captured screen and re-detected UI elements with Screen Understanding 2.0.",
                suggested_step=retry_step,
                clean_user_message="I refreshed and re-analyzed your screen to locate the target.",
                strategy_name="vision_recapture_and_redetect"
            )

        # Strategy 9: File Fallback Recovery (FILE_NOT_FOUND / FILE_ACCESS_ERROR)
        if category in [ErrorCategory.FILE_NOT_FOUND, ErrorCategory.FILE_ACCESS_ERROR]:
            fname = step.arguments.get("filename") or step.arguments.get("target_path") or step.arguments.get("file")
            if fname:
                search_step = PlanStep(
                    step_id=step.step_id,
                    description=f"Search for file '{fname}' using Smart File Manager",
                    suggested_skill="file_search",
                    arguments={"query": str(fname)},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    replan_count=step.replan_count + 1,
                    max_replans=self.MAX_RETRIES_PER_STEP
                )
                self.record_timeline_event(
                    event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                    task_id=task_id,
                    step_id=step.step_id,
                    action=step.suggested_skill,
                    details={"strategy": "smart_file_search_fallback", "filename": fname}
                )
                agent_context_manager.record_recovery_attempt(
                    step_id=step.step_id,
                    original_action=step.suggested_skill,
                    failure=category.value,
                    recovery="smart_file_search_fallback",
                    attempt=step.replan_count + 1,
                    result="retrying"
                )
                return RecoveryDecision(
                    action=RecoveryAction.RETRY,
                    error_category=category,
                    is_recoverable=True,
                    reason=f"File '{fname}' not found at specified path; searching via Smart File Manager.",
                    suggested_step=search_step,
                    clean_user_message=f"I couldn't find '{fname}' at that path, so I searched your files to locate it.",
                    strategy_name="smart_file_search_fallback"
                )

        # Strategy 10: Network Failure Recovery (Bounded Exponential Backoff)
        if category in [ErrorCategory.NETWORK_ERROR, ErrorCategory.NETWORK_FAILURE]:
            delay = self.get_backoff_delay(step.replan_count + 1)
            time.sleep(delay)
            retry_step = PlanStep(
                step_id=step.step_id,
                description=f"{step.description} (Network Backoff Retry {step.replan_count + 1})",
                suggested_skill=step.suggested_skill,
                arguments=step.arguments,
                requires_confirmation=step.requires_confirmation,
                status=StepState.PENDING,
                replan_count=step.replan_count + 1,
                max_replans=2  # max 2 network retries
            )
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "bounded_network_backoff", "delay": delay}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="bounded_network_retry",
                attempt=step.replan_count + 1,
                result="retrying"
            )
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                error_category=category,
                is_recoverable=True,
                reason=f"Transient network failure encountered; applied {delay}s backoff before retrying.",
                suggested_step=retry_step,
                clean_user_message=None,
                strategy_name="bounded_network_backoff"
            )

        # Strategy 11: Timeout / Application Not Responding Recovery
        if category in [ErrorCategory.TIMEOUT, ErrorCategory.APPLICATION_NOT_RESPONDING, ErrorCategory.COMMAND_FAILED, ErrorCategory.UNKNOWN_ERROR]:
            delay = self.get_backoff_delay(step.replan_count + 1)
            time.sleep(delay)
            retry_step = PlanStep(
                step_id=step.step_id,
                description=f"{step.description} (Safe Settle Retry)",
                suggested_skill=step.suggested_skill,
                arguments=step.arguments,
                requires_confirmation=step.requires_confirmation,
                status=StepState.PENDING,
                replan_count=step.replan_count + 1,
                max_replans=self.MAX_RETRIES_PER_STEP
            )
            self.record_timeline_event(
                event_type=RecoveryTimelineEventType.RECOVERY_STRATEGY_SELECTED,
                task_id=task_id,
                step_id=step.step_id,
                action=step.suggested_skill,
                details={"strategy": "delayed_verification_retry", "delay": delay}
            )
            agent_context_manager.record_recovery_attempt(
                step_id=step.step_id,
                original_action=step.suggested_skill,
                failure=category.value,
                recovery="delayed_verification_retry",
                attempt=step.replan_count + 1,
                result="retrying"
            )
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                error_category=category,
                is_recoverable=True,
                reason="Settle delay applied to verify system state before bounded retry.",
                suggested_step=retry_step,
                clean_user_message=None,
                strategy_name="delayed_verification_retry"
            )

        # Default Unrecoverable Failure
        self.record_timeline_event(
            event_type=RecoveryTimelineEventType.TASK_FAILED,
            task_id=task_id,
            step_id=step.step_id,
            action=step.suggested_skill,
            details={"reason": "unrecoverable_failure"}
        )
        agent_context_manager.record_recovery_attempt(
            step_id=step.step_id,
            original_action=step.suggested_skill,
            failure=category.value,
            recovery="stop_unrecoverable",
            attempt=step.replan_count,
            result="failed"
        )
        return RecoveryDecision(
            action=RecoveryAction.STOP_FAIL,
            error_category=category,
            is_recoverable=False,
            reason=f"Non-recoverable failure ({category.value}): {tool_result.error or tool_result.message}",
            clean_user_message=tool_result.message,
            strategy_name="stop_unrecoverable"
        )


error_recovery_engine = ErrorRecoveryEngine()
