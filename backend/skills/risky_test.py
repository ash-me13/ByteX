"""TEST FIXTURES ONLY. These skills are never registered in the production registry; tests add them to their own
SkillRegistry(register_defaults=False) with register_fixture()."""
from typing import Dict, Any
from skills.base import BaseSkill, ToolResult

class RiskyTestActionSkill(BaseSkill):
    """Safe mock test skill demonstrating the ByteX confirmation system for risky actions."""

    @property
    def name(self) -> str:
        return "risky_test_action"

    @property
    def description(self) -> str:
        return "Safe mock test skill requiring confirmation before execution."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean", "description": "Whether user confirmed execution"}
            }
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        is_confirmed = arguments.get("confirmed", False)

        if not is_confirmed:
            # Request confirmation from user
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="risky_test_action",
                message="Mock sensitive operation requires confirmation.",
                confirmation_required=True,
                pending_action=arguments
            )

        # Executed ONLY after user explicit confirmation
        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="risky_test_action",
            message="Risky test action executed successfully after user confirmation.",
            data={"status": "executed_with_confirmation", "parameters": arguments}
        )

class MockVerificationFailureSkill(BaseSkill):
    """Mock skill designed to test action verification failure handling."""
    @property
    def name(self) -> str:
        return "mock_verification_failure"

    @property
    def description(self) -> str:
        return "Safe mock skill that executes but fails action verification."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        # Simulates a tool that claims execution succeeded but verification layer detects mismatch
        return ToolResult(
            success=False,
            verified=False,
            verification={"exists_after": True, "expected": False},
            tool=self.name,
            action="mock_delete",
            message="Verification failed: Target file still exists after deletion attempt.",
            error="Action verification failed."
        )
