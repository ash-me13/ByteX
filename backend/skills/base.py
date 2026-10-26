from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel

class ToolResult(BaseModel):
    success: bool
    verified: bool = False
    verification: Optional[Dict[str, Any]] = None
    tool: str
    action: Optional[str] = None
    message: str
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    confirmation_required: bool = False
    pending_action: Optional[Dict[str, Any]] = None

class BaseSkill(ABC):
    """Abstract Base Class for all ByteX Desktop Automation Skills."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        pass
