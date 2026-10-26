import re
import time
import logging
from typing import Dict, Any, Tuple, Optional
from agent.models import AgentPlan, PlanStep, StepState, PlanState, AgentDecision, GoalStatus, GoalEvaluation
from agent.executor import ByteXAgentExecutor
from agent.observer import ByteXAgentObserver
from agent.evaluator import ByteXGoalEvaluator
from agent.selector import ByteXSkillSelector
from agent.planner import ByteXPlanner
from agent.context import agent_context_manager
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from memory.retrieval import memory_retriever
from skills.registry import skill_registry
from skills.base import ToolResult

logger = logging.getLogger("bytex.agent.pipeline")

def format_natural_agent_response(step_outcomes: List[Tuple[PlanStep, ToolResult]]) -> str:
    """
    Synthesizes discrete verified step execution outcomes into a clean, human-friendly response.
    Never exposes 'Step X', skill names, tool names, or internal metadata to the user.
    """
    if not step_outcomes:
        return "I was unable to complete the requested actions."

    if len(step_outcomes) == 1:
        return step_outcomes[0][1].message

    # Check if all steps are application opening tasks
    all_app_steps = all(step.suggested_skill == "open_application" for step, _ in step_outcomes)
    
    if all_app_steps:
        opened_apps = []
        already_open_apps = []
        not_found_apps = []
        unsupported_apps = []
        failed_apps = []

        for step, res in step_outcomes:
            app_name = (step.arguments.get("application") or "Application").strip().capitalize()
            
            if res.success and res.verified:
                if res.data and res.data.get("status") == "already_visible":
                    already_open_apps.append(app_name)
                elif "already open" in res.message.lower():
                    already_open_apps.append(app_name)
                else:
                    opened_apps.append(app_name)
            else:
                if "couldn't find" in res.message.lower() or "not found" in (res.error or "").lower():
                    not_found_apps.append(app_name)
                elif "don't have a supported way" in res.message.lower() or "unsupported" in (res.error or "").lower():
                    unsupported_apps.append(app_name)
                else:
                    failed_apps.append(app_name)

        sentences = []
        
        success_part = ""
        all_successful = opened_apps + already_open_apps
        if len(all_successful) == 1:
            success_part = f"{all_successful[0]} opened successfully" if all_successful[0] in opened_apps else f"{all_successful[0]} is already open"
        elif len(all_successful) == 2:
            success_part = f"{all_successful[0]} and {all_successful[1]} opened successfully"
        elif len(all_successful) > 2:
            formatted = ", ".join(all_successful[:-1]) + f", and {all_successful[-1]}"
            success_part = f"{formatted} opened successfully"

        failure_parts = []
        if not_found_apps:
            if len(not_found_apps) == 1:
                failure_parts.append(f"{not_found_apps[0]} could not be found")
            else:
                formatted = " and ".join(not_found_apps)
                failure_parts.append(f"{formatted} could not be found")

        if unsupported_apps:
            if len(unsupported_apps) == 1:
                failure_parts.append(f"I don't have a supported way to open {unsupported_apps[0]}")
            else:
                formatted = " and ".join(unsupported_apps)
                failure_parts.append(f"I don't have a supported way to open {formatted}")

        if failed_apps:
            if len(failed_apps) == 1:
                failure_parts.append(f"{failed_apps[0]} couldn't be opened")
            else:
                formatted = " and ".join(failed_apps)
                failure_parts.append(f"{formatted} couldn't be opened")

        if success_part and failure_parts:
            return f"{success_part}, but {', and '.join(failure_parts)}."
        elif success_part:
            return f"{success_part}."
        elif failure_parts:
            if not_found_apps and not failed_apps and not unsupported_apps:
                if len(not_found_apps) == 1:
                    return f"I couldn't find {not_found_apps[0]} installed on this PC."
                return f"I couldn't find {' and '.join(not_found_apps)} installed on this PC."
            return f"{', and '.join(failure_parts)}."

        return "Action completed."

    # Check if all steps are application closing tasks
    all_close_steps = all(step.suggested_skill == "close_application" for step, _ in step_outcomes)
    if all_close_steps:
        closed_apps = []
        already_closed_apps = []
        not_found_apps = []
        failed_apps = []

        for step, res in step_outcomes:
            app_name = (step.arguments.get("application") or "Application").strip().capitalize()
            if res.success and res.verified:
                if res.data and res.data.get("status") == "already_closed":
                    already_closed_apps.append(app_name)
                elif "already closed" in res.message.lower():
                    already_closed_apps.append(app_name)
                else:
                    closed_apps.append(app_name)
            else:
                if "couldn't find" in res.message.lower() or "not found" in (res.error or "").lower():
                    not_found_apps.append(app_name)
                else:
                    failed_apps.append(app_name)

        sentences = []

        # 1. Closed successfully
        if closed_apps and already_closed_apps:
            all_successful = closed_apps + already_closed_apps
            if len(all_successful) == 2:
                sentences.append(f"{all_successful[0]} and {all_successful[1]} were closed successfully.")
            else:
                formatted = ", ".join(all_successful[:-1]) + f", and {all_successful[-1]}"
                sentences.append(f"{formatted} were closed successfully.")
        elif closed_apps:
            if len(closed_apps) == 1:
                sentences.append(f"{closed_apps[0]} closed successfully.")
            elif len(closed_apps) == 2:
                sentences.append(f"{closed_apps[0]} and {closed_apps[1]} were closed successfully.")
            else:
                formatted = ", ".join(closed_apps[:-1]) + f", and {closed_apps[-1]}"
                sentences.append(f"{formatted} were closed successfully.")
        elif already_closed_apps:
            if len(already_closed_apps) == 1:
                sentences.append(f"{already_closed_apps[0]} is already closed.")
            elif len(already_closed_apps) == 2:
                sentences.append(f"{already_closed_apps[0]} and {already_closed_apps[1]} are already closed.")
            else:
                formatted = ", ".join(already_closed_apps[:-1]) + f", and {already_closed_apps[-1]}"
                sentences.append(f"{formatted} are already closed.")

        # 2. Failed / Unconfirmed
        if failed_apps:
            if len(failed_apps) == 1:
                sentences.append(f"{failed_apps[0]} could not be confirmed as closed.")
            else:
                formatted = " and ".join(failed_apps)
                sentences.append(f"{formatted} could not be confirmed as closed.")

        # 3. Not found
        if not_found_apps:
            if len(not_found_apps) == 1:
                sentences.append(f"I couldn't find {not_found_apps[0]} installed on this PC.")
            else:
                formatted = " and ".join(not_found_apps)
                sentences.append(f"I couldn't find {formatted} installed on this PC.")

        return " ".join(sentences)

    # General multi-step heterogeneous workflow:
    has_failure = any(not (r.success and r.verified) for _, r in step_outcomes)
    if has_failure:
        successful_steps = [s for s, r in step_outcomes if r.success and r.verified]
        failed_step, failed_res = next(((s, r) for s, r in step_outcomes if not (r.success and r.verified)), (None, None))
        
        def _describe_step(s: PlanStep) -> str:
            if s.suggested_skill == "open_application":
                return f"opened {s.arguments.get('application', 'the application')}"
            elif s.suggested_skill == "close_application":
                return f"closed {s.arguments.get('application', 'the application')}"
            elif s.suggested_skill == "screen_vision" and s.arguments.get("action") == "type":
                return f"typed '{s.arguments.get('text', '')}'"
            elif s.suggested_skill == "screen_vision" and s.arguments.get("action") == "click":
                return f"clicked {s.arguments.get('target', 'the element')}"
            elif s.suggested_skill == "take_screenshot":
                return "captured the screen"
            return s.description

        if successful_steps and failed_res:
            succ_str = " and ".join([_describe_step(s) for s in successful_steps])
            return f"I {succ_str} successfully, but {failed_res.message} I stopped execution."
        elif failed_res:
            return failed_res.message
        return "The requested multi-step action could not be completed."

    # All steps succeeded
    def _describe_success_step(s: PlanStep) -> str:
        if s.suggested_skill == "open_application":
            return f"opened {s.arguments.get('application', 'the application')}"
        elif s.suggested_skill == "close_application":
            return f"closed {s.arguments.get('application', 'the application')}"
        elif s.suggested_skill == "screen_vision" and s.arguments.get("action") == "type":
            return f"typed '{s.arguments.get('text', '')}'"
        elif s.suggested_skill == "screen_vision" and s.arguments.get("action") == "click":
            target = s.arguments.get('target', 'the element')
            return f"saved the document" if str(target).lower() == "save" else f"clicked {target}"
        elif s.suggested_skill == "file_operations":
            fname = s.arguments.get("filename", "file")
            floc = s.arguments.get("folder", "desktop")
            return f"saved it as {fname} on the {floc}"
        elif s.suggested_skill == "take_screenshot":
            return "captured the screen"
        return s.description

    if len(step_outcomes) == 1:
        return step_outcomes[0][1].message

    # If any steps produced rich coding / terminal output, synthesize informative output
    has_rich_coding_results = any(
        s.suggested_skill in ["coding_workspace", "terminal_agent"]
        and res.message
        and ("Output:" in res.message or "**Output:**" in res.message or "```" in res.message or "Fixed" in res.message)
        for s, res in step_outcomes
    )
    if has_rich_coding_results:
        distinct_msgs = []
        for s, res in step_outcomes:
            if res.message and res.message not in distinct_msgs:
                distinct_msgs.append(res.message)
        if distinct_msgs:
            return "\n\n".join(distinct_msgs)

    actions_str = ", ".join([_describe_success_step(s) for s, _ in step_outcomes[:-1]])
    if actions_str:
        actions_str += f", and {_describe_success_step(step_outcomes[-1][0])}"
    else:
        actions_str = _describe_success_step(step_outcomes[0][0])

    return f"I {actions_str} successfully."

class ByteXAgentPipeline:
    """
    Controlled End-to-End ByteX Agent Pipeline.
    
    Coordinates:
    Goal -> Dynamic Skill Selection -> Memory Retrieval -> Dynamic Plan Generation -> Agent Context -> Agent Executor -> Skill Execution -> Action Verification -> Agent Observation -> Goal Evaluation -> Decision -> Result.
    
    Security & Behavioral Constraints:
    1. Zero arbitrary tool selection or dynamic code execution.
    2. Only registered ByteX skills are executed.
    3. Strictly stops when STOP_SUCCESS or STOP_FAILURE is reached.
    4. Controlled replanning bounded by max 1 replan per step.
    5. Final response is strictly formatted from verified execution results.
    """

    @classmethod
    def create_plan_for_goal(cls, goal: str, relevant_memory: Optional[list] = None) -> Optional[AgentPlan]:
        """
        Dynamically constructs an AgentPlan for the validated multi-step goal using ByteXPlanner
        and optional read-only memory context.
        Zero LLM calls for deterministic matching.
        """
        return ByteXPlanner.generate_plan(goal, relevant_memory=relevant_memory)

    @classmethod
    async def run_pipeline(cls, goal: str, plan: Optional[AgentPlan] = None) -> Tuple[bool, str, str, Optional[Dict[str, Any]]]:
        """
        Executes an end-to-end multi-step Agent task using safe, verified skill primitives.
        Returns: (success, response_message, state, data)
        """
        print(f"[ByteX AgentPipeline] Activating pipeline for goal: '{goal}'")

        # 1. Retrieve Relevant Read-Only Memories and Preferences for Goal
        try:
            from memory.preferences import preference_manager
            rel_prefs = preference_manager.get_relevant_preferences(goal)
            rel_mems = memory_retriever.get_relevant_memories(goal, limit=3)
            memory_context = [f"[PREFERENCE] {p.key}: {p.value}" for p in rel_prefs] + [f"[{m.category.upper()}] {m.content}" for m in rel_mems]
        except Exception as e:
            logger.warning(f"Failed to retrieve memory context: {e}")
            memory_context = []
        
        if not plan:
            plan = cls.create_plan_for_goal(goal, relevant_memory=memory_context)
            if not plan:
                msg = f"Agent Mode received goal: '{goal}'. Identified multi-step task, but no registered safe pipeline matches."
                return False, msg, "speaking", None

        # Initialize fresh task context in Agent Context Manager with read-only memory
        agent_context_manager.start_task(goal, plan, relevant_memory=memory_context)

        from agent.recovery import error_recovery_engine, RecoveryTimelineEventType
        error_recovery_engine.record_timeline_event(
            event_type=RecoveryTimelineEventType.TASK_STARTED,
            task_id=plan.plan_id,
            details={"goal": goal, "total_steps": len(plan.steps)}
        )

        plan.status = PlanState.IN_PROGRESS
        last_observation = None
        final_message = ""
        completed_results = []
        step_outcomes: List[Tuple[PlanStep, ToolResult]] = []

        step_index = 0
        task_recovery_count = 0
        while step_index < len(plan.steps):
            step = plan.steps[step_index]
            is_final_step = (step_index == len(plan.steps) - 1)

            # 1. Authoritative Action Risk Classification Check
            assessment = ActionRiskClassifier.classify_action(step.suggested_skill, step.arguments)
            if assessment.is_blocked:
                step.status = StepState.FAILED
                step.error = assessment.reason
                plan.status = PlanState.FAILED
                final_message = assessment.reason
                agent_context_manager.update_step_failed(step.step_id, assessment.reason)
                error_recovery_engine.record_timeline_event(
                    event_type=RecoveryTimelineEventType.TASK_FAILED,
                    task_id=plan.plan_id,
                    step_id=step.step_id,
                    action=step.suggested_skill,
                    details={"reason": "blocked_by_safety"}
                )
                print(f"[ByteX AgentPipeline] Step {step.step_id} BLOCKED: {assessment.reason}")
                break

            # 2. Execute Step safely via Skill Registry
            skill = skill_registry.get_skill(step.suggested_skill)
            if not skill:
                step.status = StepState.FAILED
                step.error = f"Skill '{step.suggested_skill}' is not registered in ByteX Skill Registry."
                plan.status = PlanState.FAILED
                final_message = step.error
                agent_context_manager.update_step_failed(step.step_id, step.error)
                error_recovery_engine.record_timeline_event(
                    event_type=RecoveryTimelineEventType.TASK_FAILED,
                    task_id=plan.plan_id,
                    step_id=step.step_id,
                    action=step.suggested_skill,
                    details={"reason": "skill_not_registered"}
                )
                break

            step.status = StepState.RUNNING
            print(f"[ByteX AgentPipeline] Executing Step {step.step_id} [{assessment.risk_level}]: '{step.description}' via '{step.suggested_skill}'")

            # Ensure target application window is active and in foreground
            agent_context_manager.ensure_active_window_focused()

            try:
                # Steps come from the rule-based planner applied to the user's own typed request; skills keep their own prompts.
                tool_result = await skill_registry.execute_tool(step.suggested_skill, step.arguments, origin=skill_registry.ORIGIN_USER)
            except Exception as e:
                tool_result = ToolResult(
                    success=False,
                    verified=False,
                    tool=step.suggested_skill,
                    action=step.suggested_skill,
                    message=f"Execution exception: {e}",
                    error=str(e)
                )

            # Update active window context and session working context
            from core.session import session_manager
            session_manager.record_action_result(step.suggested_skill, step.arguments, tool_result)
            if isinstance(tool_result.data, dict) and ("hwnd" in tool_result.data or "pid" in tool_result.data):
                agent_context_manager.set_active_window(tool_result.data)

            # Record or update latest outcome for this step
            outcome_idx = next((i for i, (s, _) in enumerate(step_outcomes) if s.step_id == step.step_id), None)
            if outcome_idx is not None:
                step_outcomes[outcome_idx] = (step, tool_result)
            else:
                step_outcomes.append((step, tool_result))

            # 2. Observe & Decide via Agent Observer
            observation = ByteXAgentObserver.observe_step(
                step=step,
                tool_result=tool_result,
                is_final_step=is_final_step,
                task_recovery_count=task_recovery_count,
                task_id=plan.plan_id
            )
            obs_clean = observation.observation.encode("ascii", errors="replace").decode("ascii")
            print(f"[ByteX AgentPipeline] Step {step.step_id} Observation: {observation.decision} - {obs_clean}")

            # Record observation in plan
            obs_idx = next((i for i, o in enumerate(plan.observations) if o.step_id == step.step_id), None)
            if obs_idx is not None:
                plan.observations[obs_idx] = observation
            else:
                plan.observations.append(observation)

            # 3. Process Decision & Update Step State
            if observation.decision == AgentDecision.CONTINUE:
                if step.replan_count > 0:
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.RECOVERY_SUCCEEDED,
                        task_id=plan.plan_id,
                        step_id=step.step_id,
                        action=step.suggested_skill
                    )
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.TASK_RESUMED,
                        task_id=plan.plan_id,
                        step_id=step.step_id + 1
                    )
                step.status = StepState.COMPLETED
                step.result = tool_result.message
                completed_results.append(f"Step {step.step_id} ({step.suggested_skill}): {tool_result.message}")
                agent_context_manager.update_step_completed(step.step_id, observation.observation)
                step_index += 1

            elif observation.decision == AgentDecision.STOP_SUCCESS:
                if step.replan_count > 0:
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.RECOVERY_SUCCEEDED,
                        task_id=plan.plan_id,
                        step_id=step.step_id,
                        action=step.suggested_skill
                    )
                step.status = StepState.COMPLETED
                step.result = tool_result.message
                completed_results.append(f"Step {step.step_id} ({step.suggested_skill}): {tool_result.message}")
                agent_context_manager.update_step_completed(step.step_id, observation.observation)
                step_index += 1

            elif observation.decision == AgentDecision.REPLAN:
                task_recovery_count += 1
                if observation.suggested_replanned_step:
                    error_recovery_engine.record_timeline_event(
                        event_type=RecoveryTimelineEventType.RETRY_ATTEMPTED,
                        task_id=plan.plan_id,
                        step_id=step.step_id,
                        action=observation.suggested_replanned_step.suggested_skill,
                        details={"attempt": observation.suggested_replanned_step.replan_count}
                    )
                    plan.steps[step_index] = observation.suggested_replanned_step
                    agent_context_manager.record_replan()
                    print(f"[ByteX AgentPipeline] Replanning step {step.step_id} -> '{observation.suggested_replanned_step.suggested_skill}' (Task Recovery Attempt {task_recovery_count})")
                    continue
                else:
                    step.status = StepState.FAILED
                    final_message = observation.observation
                    agent_context_manager.update_step_failed(step.step_id, observation.observation)

            elif observation.decision == AgentDecision.STOP_FAILURE:
                step.status = StepState.FAILED
                step.error = observation.observation
                completed_results.append(f"Step {step.step_id} ({step.suggested_skill}): {tool_result.message}")
                agent_context_manager.update_step_failed(step.step_id, observation.observation)
                plan.status = PlanState.FAILED
                error_recovery_engine.record_timeline_event(
                    event_type=RecoveryTimelineEventType.TASK_FAILED,
                    task_id=plan.plan_id,
                    step_id=step.step_id,
                    action=step.suggested_skill,
                    details={"error": observation.observation}
                )
                print(f"[ByteX AgentPipeline] Step {step.step_id} failed. Halting sequential plan execution.")
                break

            # 4. Goal Completion Evaluator
            evaluation = ByteXGoalEvaluator.evaluate_goal(plan)
            plan.evaluations.append(evaluation)
            print(f"[ByteX AgentPipeline] Goal Evaluation: {evaluation.status} - {evaluation.reason}")

            if evaluation.status == GoalStatus.COMPLETE:
                plan.status = PlanState.COMPLETED
                print(f"[ByteX AgentPipeline] Pipeline Goal COMPLETE reached.")
                break

            elif evaluation.status == GoalStatus.FAILED:
                # If all attempted steps are done
                if step_index >= len(plan.steps):
                    plan.status = PlanState.FAILED
                    print(f"[ByteX AgentPipeline] Pipeline Goal FAILED.")
                    break

        completed_count = sum(1 for s in plan.steps if s.status == StepState.COMPLETED)
        natural_response = format_natural_agent_response(step_outcomes)

        # Record Multi-Step Task in Task History
        try:
            from agent.history import task_history_manager, TaskStepRecord, StepStatus, TaskStatus
            from agent.recovery import error_recovery_engine, ErrorCategory

            act_ctx = agent_context_manager.get_active_context()
            task_recov_occurred = bool(act_ctx and act_ctx.recovery_history)
            duration = round(time.time() - plan.created_at, 2)

            history_steps = []
            for step, res in step_outcomes:
                app_t = step.arguments.get("application") or step.arguments.get("target_path") or step.arguments.get("folder_name") or step.arguments.get("target") or step.arguments.get("text")
                if res.success and res.verified:
                    if step.replan_count > 0 or (act_ctx and any(r.step_id == step.step_id and r.result == "retrying" for r in act_ctx.recovery_history)):
                        step_st = StepStatus.RECOVERED
                    else:
                        step_st = StepStatus.SUCCESS
                else:
                    err_cat = error_recovery_engine.classify_error(step.suggested_skill, step.arguments, res)
                    if err_cat == ErrorCategory.NOT_FOUND:
                        step_st = StepStatus.NOT_FOUND
                    elif err_cat == ErrorCategory.UNSUPPORTED:
                        step_st = StepStatus.UNSUPPORTED
                    elif err_cat == ErrorCategory.PERMISSION_DENIED:
                        step_st = StepStatus.PERMISSION_DENIED
                    elif err_cat == ErrorCategory.VERIFICATION_FAILED:
                        step_st = StepStatus.VERIFICATION_FAILED
                    else:
                        step_st = StepStatus.FAILED

                history_steps.append(
                    TaskStepRecord(
                        step_id=step.step_id,
                        skill=step.suggested_skill,
                        action=step.suggested_skill,
                        target=str(app_t) if app_t else None,
                        status=step_st,
                        recovery_attempts=step.replan_count,
                        verification_status="passed" if (res.success and res.verified) else "failed",
                        human_readable_result=res.message
                    )
                )

            task_history_manager.record_task(
                request=goal,
                steps=history_steps,
                task_id=plan.plan_id,
                duration_seconds=duration,
                started_at=plan.created_at,
                completed_at=time.time(),
                recovery_occurred=task_recov_occurred
            )
        except Exception as e:
            logger.warning(f"Failed to record task history in pipeline: {e}")

        if completed_count > 0:
            plan.status = PlanState.COMPLETED
            agent_context_manager.clear_context(StepState.COMPLETED)
            return True, natural_response, "speaking", {"plan_id": plan.plan_id, "goal": plan.goal, "status": "completed"}
        else:
            plan.status = PlanState.FAILED
            agent_context_manager.clear_context(StepState.FAILED)
            err_resp = natural_response or (final_message or f"Agent pipeline failed during execution of '{goal}'.")
            return False, err_resp, "error", {"plan_id": plan.plan_id, "goal": plan.goal, "status": "failed"}

agent_pipeline = ByteXAgentPipeline()
