import sys
import ctypes
import time
import logging
from typing import Dict, Any, List, Optional
from agent.models import AgentContext, AgentPlan, PlanStep, StepState

logger = logging.getLogger("bytex.agent.context")

class ByteXAgentContextManager:
    """
    Temporary Task Context Manager for ByteX Agent.
    
    Maintains volatile, task-scoped execution state for the currently executing Agent task.
    
    Security & Lifecycle Invariants:
    1. Task-Scoped Volatility: Belongs strictly to the active task and is wiped on COMPLETE/FAILED/CANCELLED.
    2. Strict Memory Isolation: NEVER touches or pollutes the permanent ByteX Memory store.
    3. Zero Tool Execution: Pure state management; executes no tools or commands.
    4. Stale State Prevention: On startup/restart and new task initialization, resets active context.
    5. Zero LLM Overhead: Fully in-memory deterministic state tracker.
    """

    def __init__(self):
        self._active_context: Optional[AgentContext] = None

    def start_task(self, goal: str, plan: Optional[AgentPlan] = None, relevant_memory: Optional[List[str]] = None) -> AgentContext:
        """
        Initializes fresh context for a new Agent task, resetting any prior state.
        """
        steps = plan.steps if plan else []
        self._active_context = AgentContext(
            goal=goal,
            status=StepState.RUNNING,
            current_step=1,
            steps=steps,
            completed_steps=[],
            failed_steps=[],
            observations=[],
            pending_confirmation=None,
            replan_count=0,
            relevant_memory=relevant_memory or [],
            created_at=time.time(),
            updated_at=time.time()
        )
        print(f"[ByteX ContextManager] Started fresh task context (Task ID: {self._active_context.task_id}) for goal: '{goal}'")
        if relevant_memory:
            print(f"[ByteX ContextManager] Injected {len(relevant_memory)} relevant read-only memory item(s).")
        return self._active_context

    def get_active_context(self) -> Optional[AgentContext]:
        """Returns the currently active Agent task context, or None."""
        return self._active_context

    def update_step_completed(self, step_id: int, observation: str):
        """Records a step completion, updates observations, and advances step counter."""
        if not self._active_context:
            return
        if step_id not in self._active_context.completed_steps:
            self._active_context.completed_steps.append(step_id)
        if observation and observation not in self._active_context.observations:
            self._active_context.observations.append(observation)
        self._active_context.current_step = step_id + 1
        self._active_context.updated_at = time.time()
        print(f"[ByteX ContextManager] Step {step_id} COMPLETED. Current Step advanced to {self._active_context.current_step}")

    def update_step_failed(self, step_id: int, observation: str):
        """Records a step failure and updates observations."""
        if not self._active_context:
            return
        if step_id not in self._active_context.failed_steps:
            self._active_context.failed_steps.append(step_id)
        if observation and observation not in self._active_context.observations:
            self._active_context.observations.append(observation)
        self._active_context.status = StepState.FAILED
        self._active_context.updated_at = time.time()
        print(f"[ByteX ContextManager] Step {step_id} FAILED. Context status marked FAILED.")

    def set_pending_confirmation(self, confirmation_data: Optional[Dict[str, Any]]):
        """Sets or clears pending confirmation data."""
        if not self._active_context:
            return
        self._active_context.pending_confirmation = confirmation_data
        if confirmation_data:
            self._active_context.status = StepState.WAITING_CONFIRMATION
        self._active_context.updated_at = time.time()

    def record_replan(self):
        """Increments replan count for active task."""
        if not self._active_context:
            return
        self._active_context.replan_count += 1
        self._active_context.updated_at = time.time()
        print(f"[ByteX ContextManager] Replan recorded. Total replans: {self._active_context.replan_count}")

    def record_recovery_attempt(self, step_id: int, original_action: str, failure: str, recovery: str, attempt: int, result: str):
        """Tracks recovery attempt details inside current active task context."""
        if not self._active_context:
            return
        from agent.models import RecoveryAttemptRecord
        rec = RecoveryAttemptRecord(
            step_id=step_id,
            original_action=original_action,
            failure=failure,
            recovery=recovery,
            attempt=attempt,
            result=result,
            timestamp=time.time()
        )
        self._active_context.recovery_history.append(rec)
        self._active_context.updated_at = time.time()
        print(f"[ByteX ContextManager] Recorded Recovery: Step {step_id} ({failure} -> {recovery}) [Attempt {attempt}, Result: {result}]")

    def set_active_window(self, window_data: Optional[Dict[str, Any]]):
        """Stores or updates active application window context for the task."""
        if not self._active_context or not window_data:
            return
        self._active_context.active_window = {
            "application": window_data.get("application", ""),
            "pid": window_data.get("pid", 0),
            "hwnd": window_data.get("hwnd", 0),
            "title": window_data.get("title", "")
        }
        self._active_context.updated_at = time.time()
        print(f"[ByteX ContextManager] Active window tracked: {self._active_context.active_window}")

    def get_active_window(self) -> Optional[Dict[str, Any]]:
        """Returns the currently tracked active window context, or None."""
        if not self._active_context:
            return None
        return self._active_context.active_window

    def ensure_active_window_focused(self) -> bool:
        """
        Verifies that the tracked window HWND still exists and restores/focuses it.
        Returns True if window was verified and activated, False otherwise.
        """
        win_ctx = self.get_active_window()
        if not win_ctx:
            return False
        hwnd = win_ctx.get("hwnd", 0)
        if not hwnd:
            return False
        if sys.platform != "win32" or not hasattr(ctypes, "windll"):
            app_title = win_ctx.get("title") or ""
            if sys.platform == "darwin" and app_title:
                try:
                    from core.applescript import activate_application
                    ok, _ = activate_application(app_title, timeout=2.0)
                    return ok
                except Exception:
                    pass
            return True

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            print(f"[ByteX ContextManager] Tracked window HWND {hwnd} is invalid or closed.")
            return False
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9) # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SwitchToThisWindow(hwnd, True)
            time.sleep(0.05)
            print(f"[ByteX ContextManager] Verified & activated target HWND {hwnd} ('{win_ctx.get('title')}')")
            return True
        except Exception as e:
            logger.warning(f"Failed to activate target HWND {hwnd}: {e}")
            return False

    def clear_context(self, final_status: StepState = StepState.COMPLETED) -> Optional[AgentContext]:
        """
        Finalizes and clears active task context to prevent stale residue.
        """
        if not self._active_context:
            return None
        finished_context = self._active_context
        finished_context.status = final_status
        finished_context.updated_at = time.time()
        self._active_context = None
        print(f"[ByteX ContextManager] Cleared active task context (Final Status: {final_status}).")
        return finished_context

    def cancel_active_task(self) -> Optional[AgentContext]:
        """Cancels and immediately clears active task context."""
        return self.clear_context(final_status=StepState.CANCELLED)

agent_context_manager = ByteXAgentContextManager()
