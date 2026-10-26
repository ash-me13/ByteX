import time
import logging
from typing import Dict, Any, Optional
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from skills.registry import skill_registry
from agent.models import AgentPlan, PlanStep, StepState, PlanState, ExecutionLogEntry

logger = logging.getLogger("bytex.agent.executor")

class ByteXAgentExecutor:
    """
    ByteX Agent Executor
    Executes a structured task plan ONE STEP AT A TIME using existing registered ByteX skills.
    
    Security Constraints:
    1. May ONLY execute registered ByteX skills.
    2. Never executes arbitrary CMD, PowerShell, shell, or Python code.
    3. Respects step, risk classification, and tool confirmation requirements.
    4. Records an immutable execution log for auditing.
    """

    @classmethod
    async def execute_plan(cls, plan: AgentPlan, approvals: Optional[Dict[int, Any]] = None) -> AgentPlan:
        """
        Sequentially executes pending steps in the provided plan.
        Pauses if a step requires confirmation or encounters a failure.

        ``approvals`` maps step_id -> ApprovalGrant and is supplied only by resume_step after a human approved
        that exact step. A plan cannot approve itself via step status or step arguments, and every call still
        passes the registry's risk policy (origin is untrusted).
        """
        approvals = dict(approvals or {})
        print(f"[ByteX AgentExecutor] Starting execution for Plan: '{plan.goal}' (ID: {plan.plan_id})")
        plan.status = PlanState.IN_PROGRESS

        for step in plan.steps:
            # Skip steps already completed or cancelled
            if step.status == StepState.COMPLETED:
                continue

            # 1. Action Risk Classification (Authoritative)
            assessment = ActionRiskClassifier.classify_action(step.suggested_skill, step.arguments)
            if assessment.is_blocked:
                err_msg = assessment.reason
                step.status = StepState.FAILED
                step.error = err_msg
                plan.status = PlanState.FAILED
                plan.execution_log.append(ExecutionLogEntry(
                    step_id=step.step_id,
                    skill=step.suggested_skill,
                    status=StepState.FAILED,
                    message="Action blocked by Risk Classifier.",
                    error=err_msg
                ))
                print(f"[ByteX AgentExecutor] BLOCKED: {err_msg}")
                return plan

            # 2. Risk Confirmation Enforcement (Non-Overridable by Plan/LLM)
            effective_confirmation = step.requires_confirmation or assessment.requires_confirmation
            if effective_confirmation and step.step_id not in approvals:
                step.status = StepState.WAITING_CONFIRMATION
                plan.status = PlanState.WAITING_CONFIRMATION
                msg = f"Step {step.step_id} ('{step.description}') [{assessment.risk_level}] requires confirmation: {assessment.reason}"
                plan.execution_log.append(ExecutionLogEntry(
                    step_id=step.step_id,
                    skill=step.suggested_skill,
                    status=StepState.WAITING_CONFIRMATION,
                    message=msg
                ))
                print(f"[ByteX AgentExecutor] Paused for confirmation [{assessment.risk_level}]: {msg}")
                return plan

            # 3. Mark step as RUNNING
            step.status = StepState.RUNNING
            print(f"[ByteX AgentExecutor] Running Step {step.step_id}: '{step.description}' using '{step.suggested_skill}'")

            # 4. Check Skill Registration
            skill = skill_registry.get_skill(step.suggested_skill)
            if not skill:
                err_msg = f"Skill '{step.suggested_skill}' is not registered in ByteX Skill Registry."
                step.status = StepState.FAILED
                step.error = err_msg
                plan.status = PlanState.FAILED
                plan.execution_log.append(ExecutionLogEntry(
                    step_id=step.step_id,
                    skill=step.suggested_skill,
                    status=StepState.FAILED,
                    message="Skill lookup failed.",
                    error=err_msg
                ))
                print(f"[ByteX AgentExecutor] Step {step.step_id} FAILED: {err_msg}")
                return plan

            # 4. Execute the registered skill safely
            try:
                result = await skill_registry.execute_tool(
                    step.suggested_skill,
                    step.arguments,
                    approval=approvals.get(step.step_id),
                )

                # 5. Check if the tool itself demanded confirmation
                if result.confirmation_required:
                    step.status = StepState.WAITING_CONFIRMATION
                    plan.status = PlanState.WAITING_CONFIRMATION
                    plan.execution_log.append(ExecutionLogEntry(
                        step_id=step.step_id,
                        skill=step.suggested_skill,
                        status=StepState.WAITING_CONFIRMATION,
                        message=result.message
                    ))
                    print(f"[ByteX AgentExecutor] Tool requested confirmation for Step {step.step_id}.")
                    return plan

                # 6. Check Execution Success & Verification
                if result.success and result.verified:
                    step.status = StepState.COMPLETED
                    step.result = result.message
                    plan.execution_log.append(ExecutionLogEntry(
                        step_id=step.step_id,
                        skill=step.suggested_skill,
                        status=StepState.COMPLETED,
                        message=result.message
                    ))
                    print(f"[ByteX AgentExecutor] Step {step.step_id} COMPLETED (Verified): {result.message}")
                else:
                    step.status = StepState.FAILED
                    step.error = result.error or result.message or "Action verification failed."
                    plan.status = PlanState.FAILED
                    plan.execution_log.append(ExecutionLogEntry(
                        step_id=step.step_id,
                        skill=step.suggested_skill,
                        status=StepState.FAILED,
                        message=result.message,
                        error=step.error
                    ))
                    print(f"[ByteX AgentExecutor] Step {step.step_id} FAILED (Verification Failed / Error): {step.error}")
                    return plan

            except Exception as e:
                err_msg = f"Unexpected execution exception: {str(e)}"
                step.status = StepState.FAILED
                step.error = err_msg
                plan.status = PlanState.FAILED
                plan.execution_log.append(ExecutionLogEntry(
                    step_id=step.step_id,
                    skill=step.suggested_skill,
                    status=StepState.FAILED,
                    message="Exception during step execution.",
                    error=err_msg
                ))
                print(f"[ByteX AgentExecutor] Step {step.step_id} EXCEPTION: {err_msg}")
                return plan

        # If all steps succeeded
        all_completed = all(s.status == StepState.COMPLETED for s in plan.steps)
        if all_completed:
            plan.status = PlanState.COMPLETED
            print(f"[ByteX AgentExecutor] Plan '{plan.goal}' successfully COMPLETED.")

        return plan

    @classmethod
    async def resume_step(cls, plan: AgentPlan, step_id: int, confirmed: bool) -> AgentPlan:
        """
        Resumes execution of a plan step that was waiting for confirmation.
        """
        target_step = next((s for s in plan.steps if s.step_id == step_id), None)
        if not target_step:
            print(f"[ByteX AgentExecutor] Cannot resume: Step {step_id} not found in plan.")
            return plan

        if not confirmed:
            target_step.status = StepState.CANCELLED
            target_step.error = "User cancelled execution."
            plan.status = PlanState.CANCELLED
            plan.execution_log.append(ExecutionLogEntry(
                step_id=target_step.step_id,
                skill=target_step.suggested_skill,
                status=StepState.CANCELLED,
                message="Execution cancelled by user."
            ))
            print(f"[ByteX AgentExecutor] Step {step_id} CANCELLED by user.")
            return plan

        # Mark step as running with confirmation flag and resume
        target_step.status = StepState.RUNNING
        from core.confirmation import confirmation_manager
        grant = confirmation_manager.issue_user_approval(target_step.suggested_skill, target_step.arguments)
        return await cls.execute_plan(plan, approvals={target_step.step_id: grant})

agent_executor = ByteXAgentExecutor()
