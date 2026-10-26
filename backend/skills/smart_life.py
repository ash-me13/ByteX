"""SMART LIFE skill: reminders, tasks, birthdays, bills, deadlines. A thin adapter over smartlife.service."""
from typing import Any, Dict

from skills.base import BaseSkill, ToolResult
from smartlife.service import READ_ACTIONS, WRITE_ACTIONS, SmartLifeService, default_service


class SmartLifeSkill(BaseSkill):
    def __init__(self, service: SmartLifeService = None):
        self._service = service

    @property
    def service(self) -> SmartLifeService:
        return self._service or default_service()

    @property
    def name(self) -> str:
        return "smart_life"

    @property
    def description(self) -> str:
        return ("Manage the user's reminders, tasks, deadlines, birthdays, bills, subscriptions and document expiries. "
                "Changes always need the user's explicit approval; the user is shown an exact preview first.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "action": f"one of: {', '.join(READ_ACTIONS + WRITE_ACTIONS)}",
            "kind": "reminder|task|birthday|event|bill|subscription|trial_end|document_expiry|assignment|exam",
            "title": "short title", "due_local": "YYYY-MM-DDTHH:MM (local time) or YYYY-MM-DD",
            "recurrence": '{"freq": "daily|weekly|monthly|yearly", "interval": 1}', "item_id": "exact id from a previous search/list",
        }

    def confirmation_message(self, args: Dict[str, Any]) -> str:
        """The exact text the user is asked to approve (built by trusted code from validated arguments)."""
        plan = self.service.plan(str(args.get("action", "")), args)
        return plan.preview

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        args = dict(arguments or {})
        confirmed = args.pop("confirmed", False) is True  # set only by SkillRegistry after a verified user approval
        action = str(args.pop("action", "")).strip().lower()
        try:
            res = self.service.execute(action, args, confirmed=confirmed)
        except Exception as exc:  # never let a tool error take the chat down
            return ToolResult(success=False, tool=self.name, action=action, message="SMART LIFE could not complete that request.", error=type(exc).__name__)
        if res["status"] == "confirm":
            return ToolResult(success=True, verified=False, tool=self.name, action=action, message=res["message"],
                              confirmation_required=True, pending_action={"action": action, **args})
        if res["status"] == "clarify":
            return ToolResult(success=True, verified=False, tool=self.name, action=action, message=res["message"], data={"needs_clarification": True})
        if res["status"] == "error":
            return ToolResult(success=False, tool=self.name, action=action, message=res["message"], error="SmartLifeError")
        return ToolResult(success=True, verified=bool(res["verified"]), tool=self.name, action=action, message=res["message"], data=res["data"])
