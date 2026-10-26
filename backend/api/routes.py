from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from skills.system import GetSystemStatsSkill

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    message: str
    state: str
    data: Optional[Dict[str, Any]] = None

@router.get("/health")
async def health():
    """Liveness probe used by the UI. Reports only that this API process is answering."""
    from services.health import HealthService
    return HealthService.get_health()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Processes natural language user requests synchronously via REST."""
    from core.command_router import CommandRouter
    from core.confirmation import set_conversation_id
    set_conversation_id("http-chat")  # REST has no connection identity; keep it separate from every WebSocket
    try:
        handled, response_text, state, data = await CommandRouter.route_command(req.message)
        return ChatResponse(
            message=response_text,
            state=state,
            data=data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/diagnostics/paths")
async def get_diagnostic_paths():
    from pathlib import Path
    import core.command_router as _cr
    import skills.coding as _cd
    return {
        "backend_dir": str(Path(__file__).resolve().parent.parent),
        "command_router_path": str(Path(_cr.__file__).resolve()),
        "coding_path": str(Path(_cd.__file__).resolve())
    }

# --- MEMORY & PREFERENCE ENDPOINTS (FEATURE #39 PERSISTENT MEMORY 2.0) ---

from memory.manager import memory_manager
from memory.models import MemoryUpdate

@router.get("/memory/all")
async def get_all_memories(category: Optional[str] = None, search: Optional[str] = None):
    """Retrieves all stored long-term memories with optional filtering."""
    return memory_manager.get_all_memories(category=category, search=search)

@router.post("/memory/add")
async def add_memory(content: str, category: str = "FACT", key: Optional[str] = None, value: Optional[str] = None):
    """Adds a new explicit long-term memory."""
    ok, msg, item = memory_manager.add_memory(content=content, category=category, key=key, value=value)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return item.model_dump() if item else {"status": "saved", "message": msg}

@router.get("/memory/{memory_id}")
async def get_single_memory(memory_id: str):
    """Retrieves a single memory by ID."""
    item = memory_manager.get_memory(memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    return item.model_dump()

@router.put("/memory/{memory_id}")
async def update_single_memory(memory_id: str, updates: MemoryUpdate):
    """Updates an existing memory entry."""
    ok, msg, item = memory_manager.update_memory(memory_id, updates)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return item.model_dump() if item else {"status": "updated", "message": msg}

@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """Deletes a single memory by ID."""
    ok = memory_manager.delete_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "id": memory_id}

@router.post("/memory/clear")
async def clear_all_memories():
    """Clears all stored memories."""
    count = memory_manager.clear_all_memories()
    return {"status": "cleared", "count": count}

# --- ACTIVE PROJECT CONTEXT ENDPOINTS (FEATURE #39.24) ---

@router.get("/memory/project/active")
async def get_active_project():
    """Retrieves current active project context."""
    act = memory_manager.get_active_project()
    return act.model_dump() if act else None

@router.post("/memory/project/active")
async def set_active_project(project_name: str, workspace_path: Optional[str] = None, framework: Optional[str] = None):
    """Sets the current active project context."""
    act = memory_manager.set_active_project(project_name=project_name, workspace_path=workspace_path, framework=framework)
    return act.model_dump()

@router.delete("/memory/project/active")
async def clear_active_project():
    """Clears the active project context."""
    ok = memory_manager.clear_active_project()
    return {"status": "cleared", "success": ok}

# --- PREFERENCE LEARNING ENDPOINTS ---

from memory.learning import preference_learner

@router.get("/learning/status")
async def get_learning_status():
    """Retrieves preference learning status and pending candidates."""
    return {
        "is_enabled": preference_learner.is_enabled,
        "active_prompt": preference_learner.get_active_prompt().model_dump() if preference_learner.get_active_prompt() else None
    }

@router.post("/learning/toggle")
async def toggle_preference_learning(enabled: bool):
    """Enables or disables automatic preference learning."""
    preference_learner.set_enabled(enabled)
    return {"is_enabled": preference_learner.is_enabled}

# --- PROACTIVE SUGGESTIONS ENDPOINTS ---

from agent.suggestions import suggestion_engine

@router.get("/suggestions/active")
async def get_active_suggestion():
    """Retrieves currently active proactive suggestion candidate if available."""
    active = suggestion_engine.get_active_suggestion()
    return {
        "has_suggestion": active is not None,
        "suggestion": active.model_dump() if active else None
    }

@router.post("/suggestions/accept")
async def accept_suggestion():
    """Marks active suggestion as accepted."""
    active = suggestion_engine.get_active_suggestion()
    if not active:
        return {"status": "no_active_suggestion"}
    suggestion_engine.record_acceptance(active.id)
    return {"status": "accepted", "id": active.id}

@router.post("/suggestions/dismiss")
async def dismiss_suggestion():
    """Marks active suggestion as dismissed with cooldown."""
    active = suggestion_engine.get_active_suggestion()
    if not active:
        return {"status": "no_active_suggestion"}
    suggestion_engine.record_dismissal(active.id)
    return {"status": "dismissed", "id": active.id}

@router.post("/suggestions/settings")
async def update_suggestion_settings(enabled: bool = True, frequency: str = "balanced"):
    """Updates proactive suggestions enabled toggle and frequency."""
    suggestion_engine.set_enabled(enabled)
    suggestion_engine.set_frequency(frequency)
    return {
        "is_enabled": suggestion_engine.is_enabled,
        "frequency": suggestion_engine.frequency
    }

# --- TASK HISTORY ENDPOINTS (FEATURE #29) ---

from agent.history import task_history_manager

@router.get("/tasks")
async def get_tasks(
    status: Optional[str] = None,
    date: Optional[str] = None,
    application: Optional[str] = None,
    keyword: Optional[str] = None,
    skill: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
):
    """
    Retrieves task history records with optional filtering by status, date, keyword, application, or skill.
    """
    tasks = task_history_manager.search_tasks(
        keyword=keyword,
        status=status,
        date_filter=date,
        application=application,
        skill=skill,
        limit=limit,
        offset=offset
    )
    return {
        "count": len(tasks),
        "tasks": [t.model_dump() for t in tasks]
    }

@router.get("/tasks/{task_id}")
async def get_task_by_id(task_id: str):
    """Retrieves detailed information for a single task."""
    task = task_history_manager.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump()

@router.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    """Deletes a single task history entry."""
    ok = task_history_manager.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "task_id": task_id}

@router.delete("/tasks")
async def clear_tasks_endpoint():
    """Clears all task history entries."""
    count = task_history_manager.clear_history()
    return {"status": "cleared", "count": count}

# --- AUTOMATIONS ENDPOINTS (FEATURE #30) ---

from agent.automation import automation_manager, Automation

@router.get("/automations")
async def get_automations(enabled_only: bool = False):
    """Retrieves all stored automations."""
    autos = automation_manager.get_all_automations(enabled_only=enabled_only)
    return {
        "count": len(autos),
        "automations": [a.model_dump() for a in autos]
    }

@router.get("/automations/{automation_id}")
async def get_automation_endpoint(automation_id: str):
    """Retrieves a single automation by ID."""
    auto = automation_manager.get_automation_by_id(automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    return auto.model_dump()

@router.post("/automations")
async def create_or_update_automation(auto_data: Dict[str, Any]):
    """Saves or updates an automation."""
    auto_obj = Automation(**auto_data)
    saved = automation_manager.save_automation(auto_obj)
    return saved.model_dump()

@router.delete("/automations/{automation_id}")
async def delete_automation_endpoint(automation_id: str):
    """Deletes an automation."""
    ok = automation_manager.delete_automation(automation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"status": "deleted", "automation_id": automation_id}

@router.post("/automations/{automation_id}/run")
async def run_automation_endpoint(automation_id: str):
    """Manually triggers an automation."""
    auto = automation_manager.get_automation_by_id(automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    handled, resp_text, state, data = await automation_manager.execute_automation(auto)
    return {
        "handled": handled,
        "message": resp_text,
        "state": state,
        "data": data
    }

@router.post("/automations/{automation_id}/enable")
async def enable_automation_endpoint(automation_id: str):
    """Enables an automation."""
    ok = automation_manager.set_enabled(automation_id, True)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"status": "enabled", "automation_id": automation_id}

@router.post("/automations/{automation_id}/disable")
async def disable_automation_endpoint(automation_id: str):
    """Disables an automation."""
    ok = automation_manager.set_enabled(automation_id, False)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"status": "disabled", "automation_id": automation_id}

# --- SYSTEM & ACTION AUDIT ENDPOINTS ---

@router.get("/system/stats")
async def get_system_stats():
    """Retrieves real-time system performance statistics."""
    skill = GetSystemStatsSkill()
    res = await skill.execute()
    return res.to_dict()

# --- LIVE MONITORING ENDPOINTS ---

from monitoring.service import live_system_monitor
from monitoring.models import SystemEvent

@router.get("/monitoring/status")
async def get_monitoring_status():
    """Retrieves the live system monitoring service status and telemetry."""
    return {
        "is_running": live_system_monitor.is_running,
        "is_paused": live_system_monitor.is_paused,
        "poll_count": live_system_monitor.poll_count,
        "latest_metrics": live_system_monitor.get_latest_metrics(),
    }

@router.get("/monitoring/events")
async def get_monitoring_events():
    """Retrieves recent structured monitoring events."""
    return {
        "events": live_system_monitor.get_recent_events(limit=20)
    }

@router.post("/monitoring/test-event")
async def trigger_test_monitoring_event(event_type: str = "CPU_HIGH", severity: str = "warning", message: str = "CPU usage is high (94.5%)."):
    """Emits a structured test event to broadcast across WebSockets."""
    from datetime import datetime, timezone
    event = SystemEvent(
        event_type=event_type,
        timestamp=datetime.now(timezone.utc).isoformat(),
        severity=severity,
        message=message,
        value=94.5,
        threshold=90.0,
    )
    await live_system_monitor._emit_events([event])
    return {"status": "emitted", "event": event.to_dict()}

@router.get("/actions/logs")
async def get_action_logs(limit: int = 50):
    """Retrieves recent local action logs."""
    tasks = task_history_manager.get_recent_tasks(limit=limit)
    return {"count": len(tasks), "logs": [t.model_dump() for t in tasks]}

# --- PHONE INTEGRATION ENDPOINTS (FEATURE #38.1) ---
from api.phone_routes import router as phone_router
router.include_router(phone_router)

