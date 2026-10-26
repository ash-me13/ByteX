"""
ByteX — Feature #42: Resume My Work Engine

Provides deterministic, safe, and context-aware work resumption:
1. Work Context Reconstruction: Reconstructs previous work state (task ID, objective, project, application,
   completed steps, failed step, remaining steps, resumability).
2. Work State Classification: Classifies previous work into COMPLETED, IN_PROGRESS, INTERRUPTED, FAILED,
   PAUSED, RECOVERABLE, NOT_RESUMABLE.
3. Natural "What was I doing?" Support: Concise, factual summaries of recent work based on real stored history.
4. Safe Multi-Step Resumption: Resumes tasks from the exact uncompleted/failed step without replaying already finished steps.
5. Current State Verification: Verifies physical environment (project directories, file paths, active windows) before resume.
6. Ambiguity Guard: Disambiguates between multiple unfinished tasks without guessing.
7. Security & Risk Invariants: Historical authorization is NEVER treated as current authorization; dangerous steps
   require fresh explicit confirmation.
8. Activity Timeline Logging: Emits WORK_CONTEXT_FOUND, RESUME_STATE_VERIFIED, TASK_RESUMED, RESUME_COMPLETED,
   RESUME_STATE_MISMATCH.
"""

import os
import re
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from agent.models import (
    WorkContext,
    WorkState,
    AgentPlan,
    PlanStep,
    StepState,
    RecoveryTimelineEventType
)
from agent.history import (
    task_history_manager,
    TaskHistoryRecord,
    TaskStepRecord,
    TaskStatus,
    StepStatus
)
from agent.recovery import error_recovery_engine
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from core.session import session_manager

logger = logging.getLogger("bytex.agent.work_resume")


class WorkResumeEngine:
    """
    Core Work Context Reconstruction & Safe Resumption Engine for ByteX.
    """

    @classmethod
    def classify_work_state(cls, task: TaskHistoryRecord) -> WorkState:
        """
        Deterministically classifies the work state of a previous task history record.
        """
        if not task.steps:
            if task.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED]:
                return WorkState.COMPLETED
            elif task.status == TaskStatus.CANCELLED:
                return WorkState.INTERRUPTED
            elif task.status == TaskStatus.RUNNING:
                return WorkState.IN_PROGRESS
            return WorkState.FAILED

        # Inspect steps
        failed_steps = [s for s in task.steps if s.status in [
            StepStatus.FAILED, StepStatus.VERIFICATION_FAILED, StepStatus.NOT_FOUND,
            StepStatus.UNSUPPORTED, StepStatus.PERMISSION_DENIED
        ]]
        completed_steps = [s for s in task.steps if s.status in [
            StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED
        ]]

        if task.status == TaskStatus.CANCELLED:
            return WorkState.INTERRUPTED

        if task.status == TaskStatus.RUNNING:
            return WorkState.IN_PROGRESS

        if len(completed_steps) == len(task.steps):
            return WorkState.COMPLETED

        if any(s.status == StepStatus.PERMISSION_DENIED for s in failed_steps):
            return WorkState.NOT_RESUMABLE

        if failed_steps:
            return WorkState.RECOVERABLE if len(completed_steps) > 0 else WorkState.FAILED

        return WorkState.IN_PROGRESS

    @classmethod
    def reconstruct_work_context(cls, task_record: Optional[TaskHistoryRecord] = None) -> Optional[WorkContext]:
        """
        Reconstructs a rich WorkContext object from a task record or the most recent task.
        """
        if task_record is None:
            task_record = task_history_manager.get_last_task()
            if not task_record:
                return None

        state = cls.classify_work_state(task_record)
        
        # Identify project, application, and active window
        proj_name = None
        app_name = None
        win_title = None

        # Try active session/coding context first
        try:
                from skills.coding import coding_workspace_skill
                if coding_workspace_skill._active_project_name:
                    proj_name = coding_workspace_skill._active_project_name
        except Exception:
            pass

        # Check command text for project or application references
        m_proj = re.search(r"project\s+(?:called|named\s+)?([a-zA-Z0-9_\-]+)", task_record.command, flags=re.IGNORECASE)
        if m_proj and not proj_name:
            proj_name = m_proj.group(1).strip()

        # Step analysis
        completed_list = []
        failed_dict = None
        remaining_list = []
        last_succ_action = None
        last_fail_action = None
        resumable_idx = 1

        for idx, s in enumerate(task_record.steps, 1):
            s_dict = {
                "step_id": s.step_id,
                "skill": s.skill or s.action,
                "action": s.action or s.skill,
                "target": s.target,
                "status": s.status.value,
                "human_readable_result": s.human_readable_result
            }

            if s.target and not app_name and ("open" in s.action.lower() or "app" in s.skill.lower()):
                app_name = s.target

            if s.status in [StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED]:
                completed_list.append(s_dict)
                last_succ_action = s.action or s.skill
            else:
                if failed_dict is None:
                    failed_dict = s_dict
                    last_fail_action = s.human_readable_result or s.action
                    resumable_idx = idx
                remaining_list.append(s_dict)

        # If no steps explicitly failed but task is in progress, remaining begins after completed
        if failed_dict is None and len(completed_list) < len(task_record.steps):
            resumable_idx = len(completed_list) + 1

        # Resumability classification
        if state == WorkState.COMPLETED:
            resumability = "NOT_RESUMABLE"
            reason = "Task already completed successfully."
        elif state == WorkState.NOT_RESUMABLE:
            resumability = "NOT_RESUMABLE"
            reason = "Task encountered a non-recoverable security boundary or permission error."
        else:
            resumability = "RESUMABLE"
            reason = f"Can resume from step {resumable_idx}."

        # Emit WORK_CONTEXT_FOUND
        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.WORK_CONTEXT_FOUND,
            task_id=task_record.task_id,
            action=task_record.command,
            details={"state": state.value, "resumability": resumability, "resumable_step_index": resumable_idx}
        )

        return WorkContext(
            task_id=task_record.task_id,
            task_objective=task_record.command,
            project=proj_name,
            application=app_name,
            active_window=win_title,
            task_status=task_record.status.value,
            work_state=state,
            completed_steps=completed_list,
            failed_step=failed_dict,
            remaining_steps=remaining_list,
            last_successful_action=last_succ_action,
            last_failure=last_fail_action,
            recovery_state="recovered" if task_record.recovery_occurred else "normal",
            relevant_project_context={"project": proj_name} if proj_name else None,
            timestamp=task_record.timestamp,
            resumability=resumability,
            resumable_step_index=resumable_idx,
            reason=reason
        )

    @classmethod
    def find_resumable_tasks(cls, limit: int = 5) -> List[WorkContext]:
        """
        Retrieves and ranks recent unfinished/interrupted/failed tasks that are candidates for resumption.
        """
        recent = task_history_manager.get_recent_tasks(limit=20)
        candidates = []

        for t in recent:
            ctx = cls.reconstruct_work_context(t)
            if ctx and ctx.resumability == "RESUMABLE" and ctx.work_state != WorkState.COMPLETED:
                candidates.append(ctx)
            if len(candidates) >= limit:
                break

        return candidates

    @classmethod
    def rank_resume_candidates(cls, candidates: List[WorkContext], query: str = "") -> List[WorkContext]:
        """
        Ranks candidate tasks based on state priority, project match, query relevance, and recency.
        """
        if not candidates:
            return []

        active_proj = None
        try:
            from skills.coding import coding_workspace_skill
            active_proj = coding_workspace_skill._active_project_name
        except Exception:
            pass

        scored_candidates = []
        now_ts = time.time()
        q_lower = query.lower()

        for c in candidates:
            score = 0.0

            # 1. State priority
            if c.work_state == WorkState.INTERRUPTED:
                score += 50.0
            elif c.work_state == WorkState.IN_PROGRESS:
                score += 40.0
            elif c.work_state == WorkState.RECOVERABLE:
                score += 35.0
            elif c.work_state == WorkState.FAILED:
                score += 25.0

            # 2. Active project alignment
            if active_proj and c.project and active_proj.lower() == c.project.lower():
                score += 30.0

            # 3. Query relevance
            if q_lower:
                if c.project and c.project.lower() in q_lower:
                    score += 40.0
                if c.application and c.application.lower() in q_lower:
                    score += 30.0
                if any(w in c.task_objective.lower() for w in q_lower.split() if len(w) > 3):
                    score += 25.0

            # 4. Recency decay (up to 20 points for tasks in the last 10 minutes)
            age_seconds = max(0.0, now_ts - c.timestamp)
            recency_score = max(0.0, 20.0 * (1.0 - (age_seconds / 3600.0)))
            score += recency_score

            scored_candidates.append((score, c))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored_candidates]

    @classmethod
    def verify_environment_for_resume(cls, work_context: WorkContext) -> Tuple[bool, str]:
        """
        Verifies current physical environment state before resuming.
        Checks active project paths, target files, and application states.
        """
        # 1. Project Verification
        if work_context.project:
            try:
                from skills.coding import coding_workspace_skill
                proj_path = coding_workspace_skill._active_project_path
                if proj_path and not proj_path.exists():
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.RESUME_STATE_MISMATCH,
                        task_id=work_context.task_id,
                        details={"mismatch": f"Project folder '{proj_path}' no longer exists."}
                    )
                    return False, f"Project directory '{proj_path}' no longer exists on disk."
            except Exception as e:
                logger.warning(f"Project verification error: {e}")

        # 2. File Verification for remaining steps
        for step in work_context.remaining_steps:
            target = step.get("target") or ""
            if target and ("." in target or "/" in target or "\\" in target):
                # Target resembles a file path
                p = Path(target)
                if p.is_absolute() and not p.exists() and "create" not in step.get("action", "").lower():
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.RESUME_STATE_MISMATCH,
                        task_id=work_context.task_id,
                        details={"mismatch": f"Target file '{target}' is missing."}
                    )
                    return False, f"The file '{target}' from the previous task was moved or deleted."

        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.RESUME_STATE_VERIFIED,
            task_id=work_context.task_id,
            details={"verified": True, "resumable_step_index": work_context.resumable_step_index}
        )
        return True, "Environment verified successfully."

    @classmethod
    def summarize_last_work(cls, task_record: Optional[TaskHistoryRecord] = None) -> str:
        """
        Generates a concise, high-clarity natural language response to "What was I doing?"
        """
        ctx = cls.reconstruct_work_context(task_record)
        if not ctx:
            return "You don't have any recent task history recorded."

        obj = ctx.task_objective
        proj_str = f" in project '{ctx.project}'" if ctx.project else ""

        if ctx.work_state == WorkState.COMPLETED:
            return f"You were working on '{obj}'{proj_str}. It completed all {len(ctx.completed_steps)} step(s) successfully."

        total_steps = len(ctx.completed_steps) + len(ctx.remaining_steps)
        comp_count = len(ctx.completed_steps)

        if comp_count > 0 and ctx.failed_step:
            fail_desc = ctx.failed_step.get('action') or ctx.failed_step.get('skill') or f"step {ctx.resumable_step_index}"
            return f"You were working on '{obj}'{proj_str}. Steps 1–{comp_count} completed successfully, and it stopped at step {ctx.resumable_step_index} ({fail_desc})."

        if ctx.work_state == WorkState.INTERRUPTED:
            return f"You were working on '{obj}'{proj_str}, which was paused/interrupted at step {ctx.resumable_step_index}."

        if ctx.failed_step:
            return f"You attempted '{obj}'{proj_str}, but it stopped at step {ctx.resumable_step_index} ({ctx.last_failure or 'execution error'})."

        return f"You were working on '{obj}'{proj_str} ({ctx.work_state.value.lower()})."

    @classmethod
    async def resume_work(
        cls,
        work_context: Optional[WorkContext] = None,
        user_query: str = ""
    ) -> Tuple[bool, str, str, Optional[Dict[str, Any]]]:
        """
        Safely identifies and resumes the most relevant unfinished work context.
        Returns: (success, response_message, state, data)
        """
        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.RESUME_ANALYSIS_STARTED,
            task_id="resume_analysis",
            details={"query": user_query}
        )

        # 1. Locate Candidate Context
        if work_context is None:
            candidates = cls.find_resumable_tasks(limit=5)
            if not candidates:
                last_task = task_history_manager.get_last_task()
                if last_task and last_task.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED]:
                    return True, f"Your previous task ('{last_task.command}') is already completed.", "speaking", {"completed_task": last_task.task_id}
                return True, "I couldn't find any unfinished tasks to resume.", "speaking", None

            ranked = cls.rank_resume_candidates(candidates, query=user_query)

            # Check Ambiguity (if top 2 candidates are very close and neither has clear match)
            if len(ranked) >= 2:
                c1, c2 = ranked[0], ranked[1]
                if abs(c1.timestamp - c2.timestamp) < 300 and not user_query:
                    # Ambiguous! Ask user for clarification
                    clarification = (
                        f"I found two unfinished tasks:\n"
                        f"1. **{c1.task_objective}** (stopped at step {c1.resumable_step_index})\n"
                        f"2. **{c2.task_objective}** (stopped at step {c2.resumable_step_index})\n"
                        f"Which one would you like me to resume?"
                    )
                    return True, clarification, "speaking", {"candidates": [c1.model_dump(), c2.model_dump()]}

            work_context = ranked[0]

        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.RESUME_CANDIDATE_SELECTED,
            task_id=work_context.task_id,
            details={"objective": work_context.task_objective, "step": work_context.resumable_step_index}
        )

        # 2. Verify Environment Before Resume
        is_valid_env, env_reason = cls.verify_environment_for_resume(work_context)
        if not is_valid_env:
            return True, f"I found your previous task ('{work_context.task_objective}'), but the environment has changed ({env_reason}). I didn't continue automatically.", "speaking", {"environment_mismatch": True}

        # 3. Check for Pending Confirmation Requirements on Resume Steps
        from core.confirmation import confirmation_manager
        plan_steps = []
        for s in work_context.remaining_steps:
            sk_name = s.get("skill") or s.get("action") or "open_application"
            args = {"target": s.get("target"), "action": s.get("action")}
            assessment = ActionRiskClassifier.classify_action(sk_name, args)
            
            if assessment.is_blocked:
                return False, f"Cannot resume task: {assessment.reason}", "error", None

            plan_steps.append(
                PlanStep(
                    step_id=s.get("step_id", 1),
                    description=s.get("human_readable_result") or f"Execute {sk_name}",
                    suggested_skill=sk_name,
                    arguments=args,
                    requires_confirmation=assessment.requires_confirmation,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )

        if not plan_steps:
            return True, f"Task '{work_context.task_objective}' has no remaining steps to execute.", "speaking", None

        # 4. Check if the immediate step requires confirmation
        first_step = plan_steps[0]
        if first_step.requires_confirmation:
            error_recovery_engine.record_timeline_event(
                event_type=RecoveryTimelineEventType.RESUME_CONFIRMATION_REQUIRED,
                task_id=work_context.task_id,
                step_id=first_step.step_id,
                action=first_step.suggested_skill
            )
            prompt = confirmation_manager.set_pending(
                tool=first_step.suggested_skill,
                action=first_step.suggested_skill,
                description=f"Resume '{work_context.task_objective}' at step {first_step.step_id}: {first_step.description}",
                arguments=first_step.arguments
            )
            return True, prompt, "speaking", {"confirmation_required": True}

        # 5. Execute Remaining Steps via Agent Pipeline
        from agent.pipeline import agent_pipeline
        resume_plan = AgentPlan(
            plan_id=f"resume_{work_context.task_id}_{int(time.time())}",
            goal=f"Resume: {work_context.task_objective}",
            steps=plan_steps
        )

        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.TASK_RESUMED,
            task_id=work_context.task_id,
            step_id=work_context.resumable_step_index,
            action=first_step.suggested_skill
        )

        print(f"[ByteX WorkResume] Resuming task '{work_context.task_objective}' from step {work_context.resumable_step_index} ({len(plan_steps)} remaining step(s))...")
        p_success, p_resp, p_state, p_data = await agent_pipeline.run_pipeline(
            goal=f"Resume: {work_context.task_objective}",
            plan=resume_plan
        )

        if p_success:
            error_recovery_engine.record_timeline_event(
                event_type=RecoveryTimelineEventType.RESUME_COMPLETED,
                task_id=work_context.task_id,
                details={"success": True}
            )
            msg = f"I resumed '{work_context.task_objective}' from step {work_context.resumable_step_index} and completed the remaining steps."
            return True, msg, "speaking", {"resumed_task_id": work_context.task_id, "pipeline_data": p_data}
        else:
            error_recovery_engine.record_timeline_event(
                event_type=RecoveryTimelineEventType.RESUME_FAILED,
                task_id=work_context.task_id,
                details={"error": p_resp}
            )
            return False, f"Attempted to resume '{work_context.task_objective}', but encountered an issue: {p_resp}", "speaking", p_data

    @classmethod
    async def handle_natural_resume_command(cls, message: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        Routes natural language queries and commands regarding resuming work or querying past work.
        """
        msg_norm = message.strip()
        msg_lower = msg_norm.lower()
        msg_clean = re.sub(r"[.!?,\"\']+$", "", msg_lower).strip()

        # 1. "What was I doing?" / "Where did I leave off?" / "What was I working on?"
        if msg_clean in [
            "what was i doing", "what was i doing?", "what was i doing earlier",
            "where did i leave off", "where did i leave off?", "where did we leave off", "where did we leave off?",
            "what was i working on", "what was i working on?", "what was my last task", "what was my last task?",
            "what task was i doing", "tell me what i was doing", "what was i doing today"
        ]:
            summary = cls.summarize_last_work()
            return True, summary, "speaking", {"action": "summarize_last_work"}

        # 2. "Resume my work" / "Continue what I was doing" / "Pick up where I left off"
        if msg_clean in [
            "resume my work", "resume my work.", "continue what i was doing", "continue what i was doing.",
            "resume my last task", "resume my last task.", "continue my last task", "continue last task",
            "resume last task", "pick up where i left off", "pick up where i left off.",
            "continue where i left off", "continue from where i left off", "resume previous task",
            "continue previous task", "resume unfinished task", "resume work",
            "resume my research", "resume my research.", "continue my research", "resume research", "continue research"
        ]:
            success, resp, state, data = await cls.resume_work(user_query=message)
            return True, resp, state, data

        # 3. Parameterized resume: "Resume project <Name>" or "Resume <App>"
        m_res_proj = re.match(r"^(?:resume|continue)\s+(?:work\s+on\s+)?(?:project\s+|the\s+project\s+)?([a-zA-Z0-9_\-]+)$", msg_clean)
        if m_res_proj:
            target_kw = m_res_proj.group(1).strip()
            if target_kw not in ["it", "this", "that", "work", "task", "job"]:
                success, resp, state, data = await cls.resume_work(user_query=target_kw)
                return True, resp, state, data

        return False, None, None, None


work_resume_engine = WorkResumeEngine()
