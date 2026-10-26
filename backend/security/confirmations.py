from typing import Dict, Any, Optional

class ConfirmationManager:
    """Manages explicit user confirmation checks for potentially destructive actions."""
    
    DESTRUCTIVE_TOOLS = {"delete_file", "clear_all_memories", "force_close_process"}

    @classmethod
    def requires_confirmation(cls, tool_name: str, arguments: Dict[str, Any]) -> bool:
        if tool_name in cls.DESTRUCTIVE_TOOLS:
            return True
        return False

    @classmethod
    def format_confirmation_request(cls, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name == "delete_file":
            target = arguments.get("file_path", "specified file")
            return f"Do you want me to delete '{target}'? Please confirm."
        elif tool_name == "clear_all_memories":
            return "Are you sure you want me to erase all stored memories about you?"
        return f"Do you want me to execute '{tool_name}' with arguments {arguments}?"

confirmation_manager = ConfirmationManager()
