import time
import json
import uuid
import re
import logging
from enum import Enum
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from memory.database import db_manager
from memory.models import is_sensitive_content

logger = logging.getLogger("bytex.agent.history")

class TaskStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    COMPLETED = "COMPLETED"  # Compatible alias
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    PARTIAL = "PARTIAL"      # Compatible alias
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERED = "RECOVERED"

class StepStatus(str, Enum):
    SUCCESS = "SUCCESS"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"  # Compatible alias
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

class TaskStepRecord(BaseModel):
    step_id: int = 1
    skill: str = ""
    action: str = ""
    target: Optional[str] = None
    status: StepStatus = StepStatus.SUCCESS
    started_at: float = Field(default_factory=time.time)
    completed_at: float = Field(default_factory=time.time)
    recovery_attempts: int = 0
    recovery_details: Optional[str] = None
    verification_status: str = "passed"
    human_readable_result: str = ""
    error_category: Optional[str] = None

class TaskHistoryRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    command: str = ""
    request: str = ""  # Compatible alias
    status: TaskStatus = TaskStatus.SUCCESS
    started_at: float = Field(default_factory=time.time)
    completed_at: float = Field(default_factory=time.time)
    duration_seconds: float = 0.0
    summary: str = ""
    recovery_occurred: bool = False
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    timestamp: float = Field(default_factory=time.time)
    steps: List[TaskStepRecord] = Field(default_factory=list)

def sanitize_history_text(text: str) -> str:
    """Removes sensitive credentials, passwords, tokens, and internal tags."""
    if not text:
        return ""
    from memory.models import SENSITIVE_PATTERNS, is_sensitive_content

    clean = re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()
    
    # Redact passwords and secrets mentioned in commands/text
    clean = re.sub(r"(?:password|passwd|pwd)\s+(?:is\s+)?([^\s,;.]+)", "password [REDACTED]", clean, flags=re.IGNORECASE)
    clean = re.sub(r"(?:type|enter|input)\s+([^\s,;.]+)\s+(?:into|in|to)\s+(?:the\s+)?(?:password|login|secret)", "type [REDACTED] into password", clean, flags=re.IGNORECASE)

    for pattern in SENSITIVE_PATTERNS:
        clean = re.sub(pattern, "[SENSITIVE REDACTED]", clean, flags=re.IGNORECASE)

    return clean

def generate_task_summary(command: str, steps: List[TaskStepRecord], status: TaskStatus, recovery_occurred: bool) -> str:
    """Generates a concise, high-clarity natural language summary for a task."""
    if not steps:
        return f"Executed command '{command}'."

    step_verbs = []
    for s in steps:
        act = s.action or s.skill
        tgt = s.target or "target"
        
        if "execute" in act.lower() or "run" in act.lower():
            step_verbs.append(f"executed {tgt}")
        elif "explain" in act.lower():
            step_verbs.append(f"explained {tgt}")
        elif "generate" in act.lower():
            step_verbs.append(f"generated {tgt}")
        elif "open" in act.lower():
            step_verbs.append(f"opened {tgt}")
        elif "close" in act.lower():
            step_verbs.append(f"closed {tgt}")
        elif "type" in act.lower():
            step_verbs.append("typed text into document")
        elif "click" in act.lower():
            if str(tgt).lower() == "save":
                step_verbs.append("saved the document")
            else:
                step_verbs.append(f"clicked {tgt}")
        elif "save" in act.lower():
            step_verbs.append(f"saved {tgt}")
        elif "search" in act.lower():
            step_verbs.append(f"searched for {tgt}")
        elif "status" in act.lower():
            step_verbs.append("retrieved system status")
        else:
            step_verbs.append(s.human_readable_result or f"performed {act}")

    # Build sentence
    if len(step_verbs) == 1:
        base = step_verbs[0].capitalize()
    elif len(step_verbs) == 2:
        base = f"{step_verbs[0].capitalize()} and {step_verbs[1]}"
    else:
        base = f"{step_verbs[0].capitalize()}, {', '.join(step_verbs[1:-1])}, and {step_verbs[-1]}"

    if recovery_occurred or status == TaskStatus.RECOVERED:
        return f"{base} (recovered during execution)."
    elif status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED]:
        return f"{base} successfully."
    elif status in [TaskStatus.PARTIAL, TaskStatus.PARTIAL_SUCCESS]:
        failed_s = next((s for s in steps if s.status not in [StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED]), None)
        fail_msg = f": {failed_s.human_readable_result}" if failed_s else "."
        return f"{base}, but partially failed{fail_msg}"
    else:
        failed_s = next((s for s in steps if s.status not in [StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED]), None)
        fail_reason = failed_s.human_readable_result if failed_s else "Execution failed"
        return f"Failed to complete '{command}': {fail_reason}."

class TaskHistoryManager:
    """
    Feature #29: ByteX Task History Engine.
    
    Maintains a structured, persistent, sanitized history of actions performed by ByteX.
    
    Security & Structural Invariants:
    1. Ground-Truth Verified Execution: Only records actual execution results, never assumptions.
    2. Strict Sanitization: Passwords, tokens, API keys, and clipboard blobs are redacted.
    3. Isolated Persistence: Stored in task_history table; separate from Long-Term Memory.
    4. Bounded Retention: Retains up to 500 tasks (MAX_HISTORY_ENTRIES = 500).
    5. Searchable & Filterable: Supports filtering by status, date, keyword, and application.
    6. Confirmation for Deletion: Clearing history requires explicit user confirmation.
    """

    MAX_HISTORY_ENTRIES: int = 500

    @classmethod
    def record_task(
        cls,
        request: str,
        steps: List[TaskStepRecord],
        status: Optional[TaskStatus] = None,
        duration_seconds: float = 0.0,
        task_id: Optional[str] = None,
        started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
        recovery_occurred: bool = False
    ) -> TaskHistoryRecord:
        """
        Records a completed, partial, recovered, or failed task into SQLite Task History.
        """
        clean_request = sanitize_history_text(request)
        sanitized_steps = []
        has_recovered_step = False

        now_ts = time.time()
        start_ts = started_at or (now_ts - duration_seconds)
        end_ts = completed_at or now_ts

        for s in steps:
            # Check for recovery
            is_rec = s.status == StepStatus.RECOVERED or s.recovery_attempts > 0 or recovery_occurred
            if is_rec:
                has_recovered_step = True

            sanitized_steps.append(
                TaskStepRecord(
                    step_id=s.step_id,
                    skill=s.skill or s.action,
                    action=s.action or s.skill,
                    target=sanitize_history_text(s.target or ""),
                    status=s.status,
                    started_at=s.started_at,
                    completed_at=s.completed_at,
                    recovery_attempts=s.recovery_attempts,
                    recovery_details=sanitize_history_text(s.recovery_details or ""),
                    verification_status=s.verification_status,
                    human_readable_result=sanitize_history_text(s.human_readable_result),
                    error_category=s.error_category
                )
            )

        # Authoritative Task Status Evaluation
        if status is None:
            if not sanitized_steps:
                evaluated_status = TaskStatus.SUCCESS
            else:
                success_count = sum(1 for s in sanitized_steps if s.status in [StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED])
                if has_recovered_step and success_count == len(sanitized_steps):
                    evaluated_status = TaskStatus.RECOVERED
                elif success_count == len(sanitized_steps):
                    evaluated_status = TaskStatus.SUCCESS
                elif success_count > 0:
                    evaluated_status = TaskStatus.PARTIAL_SUCCESS
                else:
                    evaluated_status = TaskStatus.FAILED
        else:
            evaluated_status = status

        final_recovery_flag = recovery_occurred or has_recovered_step or (evaluated_status == TaskStatus.RECOVERED)
        summary = generate_task_summary(clean_request, sanitized_steps, evaluated_status, final_recovery_flag)

        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.utcnow().isoformat()
        steps_json = json.dumps([s.model_dump() for s in sanitized_steps])

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_history (task_id, request, status, duration_seconds, steps_json, created_at, timestamp, summary, recovery_occurred)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t_id, clean_request, evaluated_status.value, round(duration_seconds, 2), steps_json, now_iso, now_ts, summary, 1 if final_recovery_flag else 0)
            )
            conn.commit()

        cls._prune_history()

        record = TaskHistoryRecord(
            task_id=t_id,
            command=clean_request,
            request=clean_request,
            status=evaluated_status,
            started_at=start_ts,
            completed_at=end_ts,
            duration_seconds=round(duration_seconds, 2),
            summary=summary,
            recovery_occurred=final_recovery_flag,
            created_at=now_iso,
            timestamp=now_ts,
            steps=sanitized_steps
        )
        print(f"[ByteX TaskHistory] Recorded Task '{clean_request}' -> Status: {evaluated_status.value} ({len(sanitized_steps)} step(s))")
        return record

    @classmethod
    def get_recent_tasks(cls, limit: int = 10, offset: int = 0) -> List[TaskHistoryRecord]:
        """Retrieves most recent task history records ordered by time descending."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_history ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
            rows = cursor.fetchall()
            records = []
            for row in rows:
                row_dict = dict(row)
                steps_raw = json.loads(row_dict.get("steps_json", "[]"))
                steps = [TaskStepRecord(**s) for s in steps_raw]
                
                status_str = row_dict.get("status", "SUCCESS")
                try:
                    status_enum = TaskStatus(status_str)
                except ValueError:
                    status_enum = TaskStatus.SUCCESS if "success" in status_str.lower() or "completed" in status_str.lower() else TaskStatus.FAILED

                records.append(
                    TaskHistoryRecord(
                        task_id=row_dict["task_id"],
                        command=row_dict["request"],
                        request=row_dict["request"],
                        status=status_enum,
                        started_at=row_dict.get("timestamp", 0.0) - row_dict.get("duration_seconds", 0.0),
                        completed_at=row_dict.get("timestamp", 0.0),
                        duration_seconds=row_dict.get("duration_seconds", 0.0),
                        summary=row_dict.get("summary") or row_dict["request"],
                        recovery_occurred=bool(row_dict.get("recovery_occurred", 0)),
                        created_at=row_dict["created_at"],
                        timestamp=row_dict["timestamp"],
                        steps=steps
                    )
                )
            return records

    @classmethod
    def get_task_by_id(cls, task_id: str) -> Optional[TaskHistoryRecord]:
        """Retrieves a single task by its unique ID."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_history WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            row_dict = dict(row)
            steps_raw = json.loads(row_dict.get("steps_json", "[]"))
            steps = [TaskStepRecord(**s) for s in steps_raw]
            return TaskHistoryRecord(
                task_id=row_dict["task_id"],
                command=row_dict["request"],
                request=row_dict["request"],
                status=TaskStatus(row_dict["status"]),
                started_at=row_dict.get("timestamp", 0.0) - row_dict.get("duration_seconds", 0.0),
                completed_at=row_dict.get("timestamp", 0.0),
                duration_seconds=row_dict.get("duration_seconds", 0.0),
                summary=row_dict.get("summary") or row_dict["request"],
                recovery_occurred=bool(row_dict.get("recovery_occurred", 0)),
                created_at=row_dict["created_at"],
                timestamp=row_dict["timestamp"],
                steps=steps
            )

    @classmethod
    def get_last_task(cls) -> Optional[TaskHistoryRecord]:
        """Retrieves the single most recent task history record."""
        tasks = cls.get_recent_tasks(limit=1)
        return tasks[0] if tasks else None

    @classmethod
    def search_tasks(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        date_filter: Optional[str] = None,
        application: Optional[str] = None,
        skill: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[TaskHistoryRecord]:
        """
        Advanced filtering & searching across tasks by status, date, keyword, application, or skill.
        """
        all_tasks = cls.get_recent_tasks(limit=cls.MAX_HISTORY_ENTRIES)
        filtered = []

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

        kw = (keyword or "").strip().lower()
        st = (status or "").strip().upper()
        app_kw = (application or "").strip().lower()
        sk_kw = (skill or "").strip().lower()

        for t in all_tasks:
            # 1. Date Filter
            if date_filter:
                d_clean = date_filter.strip().lower()
                task_date = t.created_at[:10]
                if d_clean == "today" and task_date != today_str:
                    continue
                elif d_clean == "yesterday" and task_date != yesterday_str:
                    continue
                elif d_clean not in ["today", "yesterday"] and task_date != d_clean:
                    continue

            # 2. Status Filter
            if st and st != "ALL":
                if st in ["SUCCESS", "COMPLETED"] and t.status not in [TaskStatus.SUCCESS, TaskStatus.COMPLETED]:
                    continue
                elif st in ["FAILED"] and t.status != TaskStatus.FAILED:
                    continue
                elif st in ["RECOVERED"] and not (t.status == TaskStatus.RECOVERED or t.recovery_occurred):
                    continue
                elif st in ["PARTIAL", "PARTIAL_SUCCESS"] and t.status not in [TaskStatus.PARTIAL, TaskStatus.PARTIAL_SUCCESS]:
                    continue

            # 3. Application Filter
            if app_kw:
                has_app = app_kw in t.command.lower() or any(app_kw in (s.target or "").lower() for s in t.steps)
                if not has_app:
                    continue

            # 4. Skill Filter
            if sk_kw:
                has_skill = any(sk_kw in s.skill.lower() or sk_kw in s.action.lower() for s in t.steps)
                if not has_skill:
                    continue

            # 5. Keyword Search
            if kw:
                matches_cmd = kw in t.command.lower()
                matches_sum = kw in t.summary.lower()
                matches_step = any(kw in (s.target or "").lower() or kw in s.action.lower() or kw in s.human_readable_result.lower() for s in t.steps)
                if not (matches_cmd or matches_sum or matches_step):
                    continue

            filtered.append(t)

        return filtered[offset:offset + limit]

    @classmethod
    def delete_task(cls, task_id: str) -> bool:
        """Deletes a single task by ID."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    @classmethod
    def clear_history(cls) -> int:
        """Clears all task history entries without touching Long-Term Memories."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_history")
            conn.commit()
            count = cursor.rowcount
            print(f"[ByteX TaskHistory] Cleared {count} task history record(s).")
            return count

    @classmethod
    def _prune_history(cls):
        """Keeps only the most recent MAX_HISTORY_ENTRIES records."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM task_history")
            row = cursor.fetchone()
            count = row["cnt"] if row else 0
            if count > cls.MAX_HISTORY_ENTRIES:
                overflow = count - cls.MAX_HISTORY_ENTRIES
                cursor.execute(
                    """
                    DELETE FROM task_history WHERE task_id IN (
                        SELECT task_id FROM task_history ORDER BY timestamp ASC LIMIT ?
                    )
                    """,
                    (overflow,)
                )
                conn.commit()
                print(f"[ByteX TaskHistory] Pruned {overflow} oldest task history record(s).")

    @classmethod
    def handle_natural_history_query(cls, user_message: str) -> Tuple[bool, Optional[str]]:
        """
        Interprets natural language queries regarding past task execution history.
        Returns (is_handled, response_text).
        """
        msg_norm = user_message.strip()
        msg_lower = msg_norm.lower()

        # 1. "What did you do recently?" / "What did I do recently?" / "Show my recent tasks."
        if msg_lower in [
            "what did you do recently", "what did you do recently?",
            "what did i do recently", "what did i do recently?",
            "what have you done recently", "what have you done recently?",
            "what have i done recently", "what have i done recently?",
            "show my recent tasks", "show my recent tasks.",
            "list my recent tasks", "list recent tasks",
            "show recent tasks", "what tasks did you do",
            "what tasks did you do?", "show task history"
        ]:
            recent = cls.get_recent_tasks(limit=5)
            if not recent:
                return True, "I haven't performed any PC tasks recently."

            lines = ["Here are your recent tasks:"]
            for i, t in enumerate(recent, 1):
                icon = "✓" if t.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED] else ("↻" if t.status == TaskStatus.RECOVERED or t.recovery_occurred else "✕")
                lines.append(f"{i}. {icon} **{t.command}** [{t.status.value.title()}] — {t.summary}")
            return True, "\n".join(lines)

        # 2. "What did you do today?" / "What did I do today?"
        if msg_lower in [
            "what did you do today", "what did you do today?",
            "what did i do today", "what did i do today?",
            "show today's tasks", "show today's tasks.",
            "show tasks from today", "what tasks did you do today", "what tasks did you do today?"
        ]:
            today_tasks = cls.search_tasks(date_filter="today", limit=10)
            if not today_tasks:
                return True, "I haven't performed any tasks today."

            lines = [f"Here is what I did today ({len(today_tasks)} task(s)):"]
            for i, t in enumerate(today_tasks, 1):
                icon = "✓" if t.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED] else ("↻" if t.status == TaskStatus.RECOVERED or t.recovery_occurred else "✕")
                lines.append(f"{i}. {icon} **{t.command}** — {t.summary}")
            return True, "\n".join(lines)

        # 3. "Show failed tasks." / "Show my failed tasks."
        if msg_lower in ["show failed tasks", "show failed tasks.", "show my failed tasks", "show my failed tasks."]:
            failed_tasks = cls.search_tasks(status="FAILED", limit=5)
            if not failed_tasks:
                return True, "There are no failed tasks in your history."
            lines = ["Here are the recent failed tasks:"]
            for i, t in enumerate(failed_tasks, 1):
                lines.append(f"{i}. ✕ **{t.command}** — {t.summary}")
            return True, "\n".join(lines)

        # 4. "Show recovered tasks."
        if msg_lower in ["show recovered tasks", "show recovered tasks.", "show my recovered tasks"]:
            rec_tasks = cls.search_tasks(status="RECOVERED", limit=5)
            if not rec_tasks:
                return True, "There are no recovered tasks in your history."
            lines = ["Here are the tasks where automatic error recovery occurred:"]
            for i, t in enumerate(rec_tasks, 1):
                lines.append(f"{i}. ↻ **{t.command}** — {t.summary}")
            return True, "\n".join(lines)

        # 5. "What was my last task?" / "What happened with my last task?" / "Tell me about my last task."
        if msg_lower in [
            "what was my last task", "what was my last task?",
            "what was the last task", "what was the last task?",
            "what happened with my last task", "what happened with my last task?",
            "tell me about my last task", "tell me about my last task.",
            "what did you do last", "what did you do last?"
        ]:
            last_task = cls.get_last_task()
            if not last_task:
                return True, "There are no recorded previous tasks."

            st_title = last_task.status.value.title()
            resp = f"**Last Task**: '{last_task.command}' [{st_title}]\n**Summary**: {last_task.summary}\n**Duration**: {last_task.duration_seconds}s"
            if last_task.steps:
                resp += "\n**Steps**:\n" + "\n".join([f"- Step {s.step_id} ({s.action}): {s.human_readable_result} [{s.status.value}]" for s in last_task.steps])
            return True, resp

        # 6. "Show tasks involving <App>"
        app_match = re.match(r"^show\s+(?:all\s+)?tasks\s+involving\s+([a-zA-Z0-9_\s-]+)\.?$", msg_lower)
        if app_match:
            app_target = app_match.group(1).strip()
            app_tasks = cls.search_tasks(application=app_target, limit=5)
            if not app_tasks:
                return True, f"I don't have any recorded tasks involving '{app_target}'."
            lines = [f"Here are the tasks involving '{app_target}':"]
            for i, t in enumerate(app_tasks, 1):
                icon = "✓" if t.status in [TaskStatus.SUCCESS, TaskStatus.COMPLETED] else "✕"
                lines.append(f"{i}. {icon} **{t.command}** [{t.status.value.title()}] — {t.summary}")
            return True, "\n".join(lines)

        # 7. "Did you successfully <action> <target>?" (e.g. "Did you successfully save test.txt?")
        did_match = re.match(r"^did\s+you\s+(?:successfully\s+)?(open|launch|close|delete|search|find|save|type)\s+([a-zA-Z0-9_.\s-]+)(?:\s+earlier|\s+recently)?\??$", msg_lower)
        if did_match:
            action_verb = did_match.group(1).lower()
            target_entity = did_match.group(2).strip().lower()
            matching_tasks = cls.search_tasks(keyword=target_entity, limit=3)
            if not matching_tasks:
                return True, f"I don't have a record of {action_verb}ing {target_entity} recently."

            latest = matching_tasks[0]
            matched_step = next((s for s in latest.steps if target_entity in (s.target or "").lower() or target_entity in s.human_readable_result.lower()), None)
            if matched_step:
                if matched_step.status in [StepStatus.SUCCESS, StepStatus.VERIFIED_SUCCESS, StepStatus.RECOVERED]:
                    return True, f"Yes, I {matched_step.human_readable_result} (Task: '{latest.command}')."
                else:
                    return True, f"I attempted to {action_verb} {target_entity}, but it failed ({matched_step.human_readable_result})."
            else:
                return True, f"In task '{latest.command}', the overall status was {latest.status.value}: {latest.summary}"

        return False, None

task_history_manager = TaskHistoryManager()
