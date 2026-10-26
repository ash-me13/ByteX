import time
import logging
from typing import Dict, Any, List, Optional
from agent.models import AgentPlan, PlanStep, StepState, GoalStatus, GoalEvaluation, StepObservation

logger = logging.getLogger("bytex.agent.evaluator")

class ByteXGoalEvaluator:
    """
    ByteX Goal Completion Evaluator.
    
    Determines whether a user's original goal has actually been achieved based on:
    1. Original user goal
    2. Executed steps
    3. Actual execution results
    4. Physical verification results
    5. Agent observations
    
    Invariants & Security Constraints:
    - Zero tool execution: Purely evaluates state evidence.
    - Zero LLM overhead: Deterministic evaluation logic.
    - 'COMPLETE' strictly requires passed verification on all required steps.
    - Any verification failure or unrecoverable error yields FAILED or INCOMPLETE.
    """

    @classmethod
    def evaluate_goal(cls, plan: AgentPlan) -> GoalEvaluation:
        """
        Evaluates the plan's current state and produces a structured GoalEvaluation.
        """
        total_steps = len(plan.steps)
        if total_steps == 0:
            return GoalEvaluation(
                status=GoalStatus.FAILED,
                reason="Plan contains no steps.",
                remaining_requirements=["Define executable steps"]
            )

        completed_steps = [s for s in plan.steps if s.status == StepState.COMPLETED]
        failed_steps = [s for s in plan.steps if s.status == StepState.FAILED]
        pending_steps = [s for s in plan.steps if s.status in (StepState.PENDING, StepState.RUNNING, StepState.WAITING_CONFIRMATION)]

        completed_ids = [s.step_id for s in completed_steps]
        failed_ids = [s.step_id for s in failed_steps]

        # 1. Check for Verification Integrity
        # Map step_id to latest observation
        obs_map = {obs.step_id: obs for obs in plan.observations}
        unverified_completions = []
        for s in completed_steps:
            obs = obs_map.get(s.step_id)
            if not obs or obs.verification_status != "passed":
                unverified_completions.append(s.step_id)

        # If any step claimed to be completed lacks passed verification, reject COMPLETE
        if unverified_completions:
            reason = f"Step(s) {unverified_completions} claimed completion but failed physical action verification."
            print(f"[ByteX GoalEvaluator] Evaluation FAILED: {reason}")
            return GoalEvaluation(
                status=GoalStatus.FAILED,
                reason=reason,
                remaining_requirements=[f"Verify physical state for step {sid}" for sid in unverified_completions],
                completed_step_ids=[sid for sid in completed_ids if sid not in unverified_completions],
                failed_step_ids=failed_ids + unverified_completions
            )

        # 2. Check for Unrecoverable Failures
        if failed_steps:
            failed_descriptions = [f"Step {s.step_id} ('{s.description}'): {s.error or 'Failed'}" for s in failed_steps]
            reason = f"Goal cannot be completed due to failure in: {'; '.join(failed_descriptions)}"
            print(f"[ByteX GoalEvaluator] Evaluation FAILED: {reason}")
            return GoalEvaluation(
                status=GoalStatus.FAILED,
                reason=reason,
                remaining_requirements=[s.description for s in pending_steps],
                completed_step_ids=completed_ids,
                failed_step_ids=failed_ids
            )

        # 3. Check for Remaining Pending Steps
        if pending_steps:
            remaining = [f"Step {s.step_id}: {s.description}" for s in pending_steps]
            reason = f"{len(completed_steps)}/{total_steps} steps completed. {len(pending_steps)} step(s) remaining."
            print(f"[ByteX GoalEvaluator] Evaluation INCOMPLETE: {reason}")
            return GoalEvaluation(
                status=GoalStatus.INCOMPLETE,
                reason=reason,
                remaining_requirements=remaining,
                completed_step_ids=completed_ids,
                failed_step_ids=failed_ids
            )

        # 4. All Steps Completed & Verified
        if len(completed_steps) == total_steps:
            reason = f"All {total_steps} step(s) completed successfully with physical verification passed."
            print(f"[ByteX GoalEvaluator] Evaluation COMPLETE for goal '{plan.goal}': {reason}")
            return GoalEvaluation(
                status=GoalStatus.COMPLETE,
                reason=reason,
                remaining_requirements=[],
                completed_step_ids=completed_ids,
                failed_step_ids=[]
            )

        return GoalEvaluation(
            status=GoalStatus.INCOMPLETE,
            reason="Goal evaluation inconclusive.",
            remaining_requirements=[s.description for s in plan.steps if s.status != StepState.COMPLETED],
            completed_step_ids=completed_ids,
            failed_step_ids=failed_ids
        )

goal_evaluator = ByteXGoalEvaluator()
