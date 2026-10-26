from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class HealthResponse(BaseModel):
    status: str = "online"
    assistant: str = "ByteX"
    version: str = "0.1.0"

class ChatRequest(BaseModel):
    message: str = Field(..., description="User prompt message")

class ChatResponse(BaseModel):
    message: str = Field(..., description="Assistant response message")
    state: str = Field("speaking", description="Orb visual state")

class WSEvent(BaseModel):
    type: str = Field(..., description="Event type: USER_MESSAGE, ASSISTANT_MESSAGE, ASSISTANT_DELTA, ASSISTANT_COMPLETE, STATE_CHANGE, ERROR, SYSTEM_STATUS")
    message: Optional[str] = None
    content: Optional[str] = None
    state: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
