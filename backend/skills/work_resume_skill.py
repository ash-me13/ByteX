"""
ByteX — Feature #42 Skill: Work Resume Skill

Registers actions:
- resume_my_work: Safely identifies and resumes the most relevant unfinished work.
- get_work_context: Returns the structured WorkContext of recent work.
- summarize_last_work: Returns concise explanation of where the user left off.
- find_resumable_tasks: Lists all unfinished tasks eligible for resumption.
"""

from typing import Dict, Any, Optional
from skills.base import BaseSkill, ToolResult
from core.verifier import ActionVerifier


class WorkResumeSkill(BaseSkill):
    name = "resume_my_work"
    description = "Understands previous user work context and safely resumes interrupted or unfinished tasks."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'resume_my_work', 'get_work_context', 'summarize_last_work', 'find_resumable_tasks'",
                    "enum": ["resume_my_work", "get_work_context", "summarize_last_work", "find_resumable_tasks"]
                },
                "query": {
                    "type": "string",
                    "description": "Optional search or task query to disambiguate resume target"
                }
            }
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        from agent.work_resume import work_resume_engine
        action = arguments.get("action", "resume_my_work")
        query = arguments.get("query", "")

        if action == "get_work_context":
            ctx = work_resume_engine.reconstruct_work_context()
            if not ctx:
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action=action,
                    message="No previous task history found.",
                    data={"work_context": None}
                )
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message=f"Reconstructed work context for '{ctx.task_objective}' [{ctx.work_state.value}].",
                data={"work_context": ctx.model_dump()}
            )

        elif action == "summarize_last_work":
            summary = work_resume_engine.summarize_last_work()
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message=summary,
                data={"summary": summary}
            )

        elif action == "find_resumable_tasks":
            candidates = work_resume_engine.find_resumable_tasks(limit=arguments.get("limit", 5))
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message=f"Found {len(candidates)} resumable task(s).",
                data={"candidates": [c.model_dump() for c in candidates]}
            )

        else:
            # Default action: resume_my_work
            success, msg, state, data = await work_resume_engine.resume_work(user_query=query)
            return ToolResult(
                success=success,
                verified=success,
                tool=self.name,
                action="resume_my_work",
                message=msg,
                data=data or {}
            )


work_resume_skill = WorkResumeSkill()
