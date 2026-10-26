from enum import Enum
from models.schemas import WSEvent

class EventType(str, Enum):
    USER_MESSAGE = "USER_MESSAGE"
    ASSISTANT_MESSAGE = "ASSISTANT_MESSAGE"
    ASSISTANT_DELTA = "ASSISTANT_DELTA"
    ASSISTANT_COMPLETE = "ASSISTANT_COMPLETE"
    STATE_CHANGE = "STATE_CHANGE"
    ERROR = "ERROR"
    SYSTEM_STATUS = "SYSTEM_STATUS"

def create_state_event(state: str) -> WSEvent:
    return WSEvent(type=EventType.STATE_CHANGE, state=state)

def create_assistant_event(message: str) -> WSEvent:
    return WSEvent(type=EventType.ASSISTANT_MESSAGE, message=message, state="speaking")

def create_delta_event(content: str) -> WSEvent:
    return WSEvent(type=EventType.ASSISTANT_DELTA, content=content, state="speaking")

def create_complete_event(full_message: str) -> WSEvent:
    return WSEvent(type=EventType.ASSISTANT_COMPLETE, message=full_message, state="speaking")

def create_error_event(error_msg: str) -> WSEvent:
    return WSEvent(type=EventType.ERROR, message=error_msg, state="error")

def create_status_event(status_data: dict) -> WSEvent:
    return WSEvent(type=EventType.SYSTEM_STATUS, data=status_data)
