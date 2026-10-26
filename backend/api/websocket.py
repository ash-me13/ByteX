import json
import logging
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
from core.assistant import bytex_core
from core.confirmation import set_conversation_id
from models.schemas import WSEvent
from monitoring.service import live_system_monitor
from monitoring.models import SystemEvent

router = APIRouter()
logger = logging.getLogger("bytex.ws")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        init_event = WSEvent(type="STATE_CHANGE", state="idle", message="ByteX WebSocket Connected")
        await websocket.send_text(init_event.model_dump_json())

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_event(self, websocket: WebSocket, event: WSEvent):
        from core.response_sanitizer import ResponseSanitizer
        if event.type in ["ASSISTANT_COMPLETE", "ASSISTANT_MESSAGE"] and event.message:
            event.message = ResponseSanitizer.sanitize(event.message)
        elif event.type == "ASSISTANT_DELTA" and event.data and isinstance(event.data, dict) and "delta" in event.data:
            delta_str = str(event.data.get("delta", ""))
            if any(p in delta_str for p in ["<think>", "<tool>", '"tool_use"', '"thought"']):
                return
        await websocket.send_text(event.model_dump_json())

    async def broadcast(self, event_dict: dict):
        """Broadcasts structured events to all connected frontend clients."""
        text = json.dumps(event_dict)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(text)
            except Exception:
                pass

manager = ConnectionManager()

# Hook Live System Monitor events to WebSocket broadcast
async def broadcast_system_event(event: SystemEvent):
    payload = {
        "type": "SYSTEM_NOTIFICATION",
        "data": event.to_dict(),
        "message": event.message,
    }
    await manager.broadcast(payload)

live_system_monitor.add_event_listener(broadcast_system_event)

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Each connection is its own conversation: pending confirmations and approvals never cross connections.
    set_conversation_id(f"ws:{uuid.uuid4().hex}")
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                user_msg = payload.get("message") or payload.get("content") or payload.get("data")
                
                if user_msg:
                    # Stream real-time events (ASSISTANT_DELTA, ASSISTANT_COMPLETE, STATE_CHANGE)
                    async for event in bytex_core.process_user_message(str(user_msg)):
                        await manager.send_event(websocket, event)
                else:
                    err_event = WSEvent(type="ERROR", message="Invalid payload: 'message' required", state="error")
                    await manager.send_event(websocket, err_event)

            except json.JSONDecodeError:
                err_event = WSEvent(type="ERROR", message="Invalid JSON format", state="error")
                await manager.send_event(websocket, err_event)
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                # An unhandled exception here makes the server drop the TCP connection (browser close code 1006)
                # and the user sees no reply at all. Log it, tell the UI generically (type only: no message text,
                # which could contain sensitive data) and keep the connection usable.
                try:
                    logger.exception("[ByteX WS] message processing failed")
                except Exception:
                    pass
                try:
                    await manager.send_event(websocket, WSEvent(
                        type="ERROR", state="error",
                        message=f"ByteX hit an internal error ({type(exc).__name__}) while handling that message. See the backend terminal for the traceback."))
                    await manager.send_event(websocket, WSEvent(type="STATE_CHANGE", state="idle"))
                except Exception:
                    manager.disconnect(websocket)
                    return

    except WebSocketDisconnect:
        manager.disconnect(websocket)
