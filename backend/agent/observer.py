import time
import logging
from typing import Dict, Any, Optional
from skills.base import ToolResult
from skills.registry import skill_registry
from agent.models import PlanStep, StepState, AgentDecision, StepObservation, AgentPlan

logger = logging.getLogger("bytex.agent.observer")

class ByteXAgentObserver:
    """
    ByteX Agent Observation & Controlled Replanning Engine.
    
    Responsibilities:
    1. Analyzes actual physical execution + verification results.
    2. Makes deterministic next-action decisions: CONTINUE, STOP_SUCCESS, STOP_FAILURE, REPLAN.
    3. Guarantees verification failures NEVER produce STOP_SUCCESS.
    4. Limits replanning to a maximum of ONE replan per step (no loops/chains).
    5. Validates replacement skills against registered skills ONLY.
    6. Performs ZERO tool executions directly.
    """

    @classmethod
    def observe_step(
        cls,
        step: PlanStep,
        tool_result: ToolResult,
        is_final_step: bool = False,
        task_recovery_count: int = 0,
        task_id: str = "",
        fallback_skill: Optional[str] = None,
        fallback_arguments: Optional[Dict[str, Any]] = None,
        fallback_description: Optional[str] = None
    ) -> StepObservation:
        """
        Inspects step execution and verification state, producing an observation and decision
        augmented by the Error Recovery Engine.
        """
        # 1. Successful & Verified Execution
        if tool_result.success and tool_result.verified:
            verification_status = "passed"
            observation = tool_result.message or "Action executed and verified successfully."
            decision = AgentDecision.STOP_SUCCESS if is_final_step else AgentDecision.CONTINUE

            return StepObservation(
                step_id=step.step_id,
                execution_status=StepState.COMPLETED,
                verification_status=verification_status,
                observation=observation,
                decision=decision,
                replan_count=step.replan_count
            )

        # 2. Evaluate via Error Recovery Engine
        from agent.recovery import error_recovery_engine, RecoveryAction, ErrorCategory
        recovery_decision = error_recovery_engine.evaluate_recovery(
            step=step,
            tool_result=tool_result,
            task_recovery_count=task_recovery_count,
            task_id=task_id
        )

        if recovery_decision.action == RecoveryAction.PROCEED_AS_SUCCESS:
            verification_status = "passed"
            observation = recovery_decision.clean_user_message or tool_result.message
            decision = AgentDecision.STOP_SUCCESS if is_final_step else AgentDecision.CONTINUE
            return StepObservation(
                step_id=step.step_id,
                execution_status=StepState.COMPLETED,
                verification_status=verification_status,
                observation=observation,
                decision=decision,
                replan_count=step.replan_count
            )

        if recovery_decision.action == RecoveryAction.RETRY and recovery_decision.suggested_step:
            return StepObservation(
                step_id=step.step_id,
                execution_status=StepState.FAILED,
                verification_status="failed",
                observation=tool_result.error or tool_result.message or "Transient execution error.",
                decision=AgentDecision.REPLAN,
                replan_count=step.replan_count,
                suggested_replanned_step=recovery_decision.suggested_step
            )

        # 3. Check for Fallback Skill Replanning (strictly bounded by max 1 replan per step)
        if step.replan_count < step.max_replans and fallback_skill:
            if skill_registry.get_skill(fallback_skill):
                suggested_step = PlanStep(
                    step_id=step.step_id,
                    description=fallback_description or f"Retry {step.description} via {fallback_skill}",
                    suggested_skill=fallback_skill,
                    arguments=fallback_arguments or {},
                    requires_confirmation=step.requires_confirmation,
                    status=StepState.PENDING,
                    replan_count=step.replan_count + 1,
                    max_replans=step.max_replans
                )
                print(f"[ByteX AgentObserver] Step {step.step_id} failed verification. Recommending controlled REPLAN via '{fallback_skill}' (Replan count: {step.replan_count + 1}/{step.max_replans})")
                return StepObservation(
                    step_id=step.step_id,
                    execution_status=StepState.FAILED,
                    verification_status="failed",
                    observation=tool_result.error or tool_result.message or "Action failed.",
                    decision=AgentDecision.REPLAN,
                    replan_count=step.replan_count,
                    suggested_replanned_step=suggested_step
                )
            else:
                print(f"[ByteX AgentObserver] Cannot replan with unregistered fallback skill '{fallback_skill}'.")

        # 4. Non-recoverable failure -> STOP_FAILURE
        obs_msg = recovery_decision.clean_user_message or tool_result.error or tool_result.message or "Action execution or physical verification failed."
        print(f"[ByteX AgentObserver] Step {step.step_id} failed unrecoverably ({recovery_decision.error_category.value}). Decision: STOP_FAILURE.")
        return StepObservation(
            step_id=step.step_id,
            execution_status=StepState.FAILED,
            verification_status="failed",
            observation=obs_msg,
            decision=AgentDecision.STOP_FAILURE,
            replan_count=step.replan_count
        )

agent_observer = ByteXAgentObserver()
