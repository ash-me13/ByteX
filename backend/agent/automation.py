"""
ByteX — Feature #36: Advanced Automation Engine
Provides natural-language workflow automation, multi-step orchestration, flexible scheduling
(once, daily, weekly, selected weekdays, monthly, startup, on-command), conditional logic,
confirmation safety, resource protection, SQLite persistence, and Task History integration.

Strict Security & Architectural Invariants:
1. Zero Security Bypass: Unattended/scheduled automations NEVER bypass risk classifier boundaries.
2. Zero Shell Injection: Actions invoke validated Python skills directly — zero cmd.exe / PowerShell.
3. Resource & Loop Protection: Max 5 steps, max 2 retries, 60s timeout, recursion prevention.
4. Closed-Loop Verification: Every execution logs step status, error recovery, and telemetry.
"""

import os
import re
import json
import time
import uuid
import logging
import asyncio
from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from memory.database import db_manager
from memory.models import is_sensitive_content, SENSITIVE_PATTERNS
from skills.registry import skill_registry
from core.risk_classifier import ActionRiskClassifier, RiskLevel
from core.verifier import ActionVerifier

logger = logging.getLogger("bytex.agent.automation")

class AutomationScheduleType(str, Enum):
    ONCE = "ONCE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    SELECTED_WEEKDAYS = "SELECTED_WEEKDAYS"
    MONTHLY = "MONTHLY"
    STARTUP = "STARTUP"
    COMMAND = "COMMAND"

class AutomationTriggerType(str, Enum):
    COMMAND = "COMMAND"
    TIME = "TIME"
    STARTUP = "STARTUP"
    MANUAL = "MANUAL"

class AutomationStep(BaseModel):
    step_id: int
    skill: str
    action: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    condition: Optional[str] = None  # "always", "on_failure", "on_success", "if_exists"
    description: Optional[str] = None
    requires_confirmation: bool = False

class Automation(BaseModel):
    automation_id: str = Field(default_factory=lambda: f"auto_{uuid.uuid4().hex[:10]}")
    name: str
    description: str = ""
    enabled: bool = True
    trigger: str
    trigger_type: AutomationTriggerType = AutomationTriggerType.COMMAND
    schedule_type: AutomationScheduleType = AutomationScheduleType.COMMAND
    schedule_details: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AutomationStep] = Field(default_factory=list)
    conditions: Optional[str] = None
    requires_confirmation: bool = False
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_result: Optional[str] = None
    last_error: Optional[str] = None
    max_retries: int = 1
    retry_count: int = 0
    timeout_seconds: int = 60

def sanitize_automation_text(text: str) -> str:
    """Removes sensitive credentials, passwords, and tokens."""
    if not text:
        return ""
    clean = text.strip()
    clean = re.sub(r"(?:password|passwd|pwd)\s+(?:is\s+)?([^\s,;.]+)", "password [REDACTED]", clean, flags=re.IGNORECASE)
    clean = re.sub(r"(?:type|enter|input)\s+([^\s,;.]+)\s+(?:into|in|to)\s+(?:the\s+)?(?:password|login|secret)", "type [REDACTED] into password", clean, flags=re.IGNORECASE)
    for pat in SENSITIVE_PATTERNS:
        clean = re.sub(pat, "[SENSITIVE REDACTED]", clean, flags=re.IGNORECASE)
    return clean

def normalize_time_str(raw_time: str) -> str:
    """Normalizes time string to standard format (e.g. '9 AM' -> '9:00 AM', '09:00' -> '9:00 AM')."""
    if not raw_time:
        return "9:00 AM"
    t = raw_time.strip().upper()
    m_full = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", t)
    if m_full:
        h = int(m_full.group(1))
        m_val = m_full.group(2)
        mer = m_full.group(3) or ("AM" if h < 12 else "PM")
        return f"{h}:{m_val} {mer}"
    m_single = re.match(r"^(\d{1,2})\s*(AM|PM)$", t)
    if m_single:
        h = int(m_single.group(1))
        mer = m_single.group(2)
        return f"{h}:00 {mer}"
    return t

class ScheduleEngine:
    """Calculates next execution timestamps and formats schedule descriptions."""

    @staticmethod
    def calculate_next_run(
        schedule_type: AutomationScheduleType,
        schedule_details: Dict[str, Any],
        ref_dt: Optional[datetime] = None
    ) -> Optional[float]:
        now = ref_dt or datetime.now()

        if schedule_type == AutomationScheduleType.COMMAND or schedule_type == AutomationScheduleType.STARTUP:
            return None

        time_str = schedule_details.get("time", "9:00 AM")
        norm_t = normalize_time_str(time_str)
        m_t = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", norm_t)
        target_h, target_m = 9, 0
        if m_t:
            target_h = int(m_t.group(1))
            target_m = int(m_t.group(2))
            meridiem = m_t.group(3)
            if meridiem == "PM" and target_h < 12:
                target_h += 12
            elif meridiem == "AM" and target_h == 12:
                target_h = 0

        # 1. DAILY
        if schedule_type == AutomationScheduleType.DAILY:
            candidate = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.timestamp()

        # 2. SELECTED_WEEKDAYS (e.g. Monday-Friday)
        elif schedule_type == AutomationScheduleType.SELECTED_WEEKDAYS:
            days = schedule_details.get("days", [0, 1, 2, 3, 4])
            for d_offset in range(8):
                candidate = (now + timedelta(days=d_offset)).replace(hour=target_h, minute=target_m, second=0, microsecond=0)
                if candidate.weekday() in days and candidate > now:
                    return candidate.timestamp()
            return (now + timedelta(days=1)).timestamp()

        # 3. WEEKLY
        elif schedule_type == AutomationScheduleType.WEEKLY:
            target_weekday = schedule_details.get("weekday", 0)
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            candidate = (now + timedelta(days=days_ahead)).replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=7)
            return candidate.timestamp()

        # 4. MONTHLY
        elif schedule_type == AutomationScheduleType.MONTHLY:
            dom = schedule_details.get("day_of_month", 1)
            try:
                candidate = now.replace(day=dom, hour=target_h, minute=target_m, second=0, microsecond=0)
                if candidate <= now:
                    if now.month == 12:
                        candidate = candidate.replace(year=now.year + 1, month=1)
                    else:
                        candidate = candidate.replace(month=now.month + 1)
                return candidate.timestamp()
            except ValueError:
                return (now + timedelta(days=30)).timestamp()

        # 5. ONCE
        elif schedule_type == AutomationScheduleType.ONCE:
            if "timestamp" in schedule_details:
                return float(schedule_details["timestamp"])
            days_ahead = schedule_details.get("days_ahead", 1)
            candidate = (now + timedelta(days=days_ahead)).replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            return candidate.timestamp()

        return None

    @staticmethod
    def format_schedule(schedule_type: AutomationScheduleType, schedule_details: Dict[str, Any], trigger: str = "") -> str:
        time_str = schedule_details.get("time", "9:00 AM")
        if schedule_type == AutomationScheduleType.DAILY:
            return f"Every day at {time_str}"
        elif schedule_type == AutomationScheduleType.WEEKLY:
            day_name = schedule_details.get("day_name", "Monday")
            return f"Every {day_name} at {time_str}"
        elif schedule_type == AutomationScheduleType.SELECTED_WEEKDAYS:
            return f"Every weekday at {time_str}"
        elif schedule_type == AutomationScheduleType.MONTHLY:
            dom = schedule_details.get("day_of_month", 1)
            suffix = "th" if 11 <= dom <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(dom % 10, "th")
            return f"On the {dom}{suffix} of every month at {time_str}"
        elif schedule_type == AutomationScheduleType.STARTUP:
            return "At ByteX startup"
        elif schedule_type == AutomationScheduleType.ONCE:
            return f"Once at {time_str}"
        else:
            return f"When triggered by: '{trigger}'"


class NaturalLanguageAutomationParser:
    """
    Parses natural language requests into structured Automations.
    Guarantees:
    1. Zero Hallucinated Skills (Strict mapping to registered ByteX skills only).
    2. Zero Arbitrary Code/Shell Execution.
    3. Transparent Risk Evaluation.
    """

    WEEKDAYS_MAP = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
    }

    @classmethod
    def parse_schedule(cls, text: str) -> Tuple[AutomationScheduleType, AutomationTriggerType, Dict[str, Any], str]:
        clean = text.strip().rstrip('.!?').strip()
        low = clean.lower()

        # 1. Startup Schedule
        if re.search(r"\b(?:when(?:ever)?\s+(?:i\s+start\s+bytex|bytex\s+starts)|at\s+startup|on\s+startup)\b", low):
            rem = re.sub(r"\b(?:when(?:ever)?\s+(?:i\s+start\s+bytex|bytex\s+starts)|at\s+startup|on\s+startup)[,\s]*", "", clean, flags=re.IGNORECASE).strip()
            return AutomationScheduleType.STARTUP, AutomationTriggerType.STARTUP, {}, rem

        # 2. Selected Weekdays (e.g. "Every weekday at 7 PM", "Every weekday")
        m_weekday = re.search(r"\bevery\s+weekday(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b", low)
        if m_weekday:
            t_raw = m_weekday.group(1) or "9:00 AM"
            t_val = normalize_time_str(t_raw)
            rem = clean[:m_weekday.start()] + clean[m_weekday.end():]
            rem = rem.strip().lstrip(",").strip()
            return AutomationScheduleType.SELECTED_WEEKDAYS, AutomationTriggerType.TIME, {"time": t_val, "days": [0, 1, 2, 3, 4]}, rem

        # 3. Specific Weekly Day (e.g. "Every Monday at 10 AM", "Every Friday")
        m_weekly = re.search(r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b", low)
        if m_weekly:
            day_name = m_weekly.group(1).lower()
            t_raw = m_weekly.group(2) or "9:00 AM"
            t_val = normalize_time_str(t_raw)
            w_idx = cls.WEEKDAYS_MAP.get(day_name, 0)
            rem = clean[:m_weekly.start()] + clean[m_weekly.end():]
            rem = rem.strip().lstrip(",").strip()
            return AutomationScheduleType.WEEKLY, AutomationTriggerType.TIME, {"time": t_val, "weekday": w_idx, "day_name": day_name.capitalize()}, rem

        # 4. Monthly Schedule (e.g. "On the first day of every month", "Every month on the 1st at 9 AM")
        m_monthly = re.search(r"\b(?:on\s+the\s+(first|1st|second|2nd|\d+th?)\s+day\s+of\s+every\s+month|every\s+month\s+on\s+(?:the\s+)?(\d+)(?:st|nd|rd|th)?)(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b", low)
        if m_monthly:
            dom_str = m_monthly.group(1) or m_monthly.group(2) or "1"
            dom = 1 if dom_str in ["first", "1st", "1"] else (2 if dom_str in ["second", "2nd", "2"] else int(re.sub(r"\D", "", dom_str) or 1))
            t_raw = m_monthly.group(3) or "9:00 AM"
            t_val = normalize_time_str(t_raw)
            rem = clean[:m_monthly.start()] + clean[m_monthly.end():]
            rem = rem.strip().lstrip(",").strip()
            return AutomationScheduleType.MONTHLY, AutomationTriggerType.TIME, {"time": t_val, "day_of_month": dom}, rem

        # 5. Daily Schedule (e.g. "Every day at 9 AM", "Every morning at 8 AM", "Every evening at 8 PM", "Every day")
        m_daily = re.search(r"\b(?:every\s+day|every\s+morning|every\s+evening|daily)(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b", low)
        if m_daily:
            raw_time = m_daily.group(1)
            if not raw_time:
                raw_time = "8:00 AM" if "morning" in m_daily.group(0) else ("8:00 PM" if "evening" in m_daily.group(0) else "9:00 AM")
            t_val = normalize_time_str(raw_time)
            rem = clean[:m_daily.start()] + clean[m_daily.end():]
            rem = rem.strip().lstrip(",").strip()
            return AutomationScheduleType.DAILY, AutomationTriggerType.TIME, {"time": t_val}, rem

        # 6. Once / Specific Day (e.g. "Tomorrow at 8 PM", "At 8 PM")
        m_once = re.search(r"\b(?:tomorrow|today)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", low)
        if m_once:
            t_raw = m_once.group(1)
            t_val = normalize_time_str(t_raw)
            days_ahead = 1 if "tomorrow" in m_once.group(0) else 0
            rem = clean[:m_once.start()] + clean[m_once.end():]
            rem = rem.strip().lstrip(",").strip()
            return AutomationScheduleType.ONCE, AutomationTriggerType.TIME, {"time": t_val, "days_ahead": days_ahead}, rem

        # 7. Default to Command Trigger
        return AutomationScheduleType.COMMAND, AutomationTriggerType.COMMAND, {}, clean

    @classmethod
    def parse_creation_request(cls, text: str) -> Tuple[bool, Optional[Automation], Optional[str]]:
        clean = text.strip()
        clean_no_punct = clean.rstrip('.!?').strip()

        is_explicit_creation = bool(re.search(
            r"^(?:create|make|build|add|define|set\s+up)\s+(?:an?\s+)?(?:new\s+)?(?:automation|workflow|routine)\b",
            clean,
            re.IGNORECASE
        ))
        is_schedule_creation = bool(re.search(
            r"^(?:every\s+(?:day|morning|evening|weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|whenever\s+i\s+say|when\s+i\s+start\s+bytex|at\s+startup)\b",
            clean,
            re.IGNORECASE
        ))
        is_do_every_day = bool(re.match(r"^do\s+this\s+(?:every\s+day|daily|every\s+morning|every\s+weekday)$", clean_no_punct, re.IGNORECASE))

        if not (is_explicit_creation or is_schedule_creation or is_do_every_day):
            return False, None, None

        sched_type, trig_type, sched_details, remaining = cls.parse_schedule(clean)

        if is_do_every_day:
            return True, None, "Please specify which action or workflow you'd like to run every day (e.g. 'Every day at 9 AM, open my coding project and run tests')."

        actions_str = re.sub(
            r"^(?:create|make|build|add|define|set\s+up)\s+(?:an?\s+)?(?:new\s+)?(?:automation|workflow|routine)\s+(?:called|named|that|to)?\s*",
            "",
            remaining,
            flags=re.IGNORECASE
        ).strip()
        actions_str = re.sub(r'^(?:called|named)\s+["\']?([^"\']+?)["\']?\s+(?:that|to|which)?\s*', '', actions_str, flags=re.IGNORECASE).strip()
        actions_str = actions_str.lstrip(":").strip()

        time_part = sched_details.get("time", "9:00 AM")
        if "chrome" in actions_str.lower() or "website" in actions_str.lower():
            name = "Web & Browser Check"
        elif "dev server" in actions_str.lower() or "development server" in actions_str.lower() or "vs code" in actions_str.lower():
            name = "VS Code & Dev Server Workflow"
        elif "latest files" in actions_str.lower() or "project structure" in actions_str.lower() or "morning" in text.lower():
            name = "Morning Project Inspection"
        elif "study" in actions_str.lower() or "remind" in actions_str.lower():
            name = "Study Reminder"
        elif "temp" in actions_str.lower() or "delete" in actions_str.lower() or "clean" in actions_str.lower():
            name = "Temporary Files Cleanup"
        elif "test" in actions_str.lower():
            if sched_type == AutomationScheduleType.WEEKLY:
                name = f"{sched_details.get('day_name', 'Weekly')} Project Tests"
            else:
                name = "Project Test Automation"
        elif sched_type == AutomationScheduleType.DAILY:
            name = f"Daily Routine ({time_part})"
        elif sched_type == AutomationScheduleType.WEEKLY:
            name = f"{sched_details.get('day_name', 'Weekly')} Routine"
        elif sched_type == AutomationScheduleType.SELECTED_WEEKDAYS:
            name = f"Weekday Routine ({time_part})"
        elif sched_type == AutomationScheduleType.STARTUP:
            name = "ByteX Startup Routine"
        elif sched_type == AutomationScheduleType.MONTHLY:
            name = f"Monthly Task (Day {sched_details.get('day_of_month', 1)})"
        else:
            name = "Custom Automation"

        trigger_desc = ScheduleEngine.format_schedule(sched_type, sched_details, name)

        steps, unsupported = cls._decompose_actions(actions_str)
        if unsupported:
            return True, None, f"I can create this automation, but I don't currently have a supported skill for '{unsupported}'."

        if not steps:
            return True, None, "I couldn't identify any supported action steps in that automation request."

        requires_conf = False
        for s in steps:
            assessment = ActionRiskClassifier.classify_action(s.skill, s.arguments)
            if assessment.risk_level in [RiskLevel.DANGEROUS, RiskLevel.BLOCKED] or assessment.requires_confirmation:
                s.requires_confirmation = True
                requires_conf = True

        next_run = ScheduleEngine.calculate_next_run(sched_type, sched_details)

        auto_obj = Automation(
            name=name,
            description=f"Automation for: {actions_str}",
            trigger=trigger_desc,
            trigger_type=trig_type,
            schedule_type=sched_type,
            schedule_details=sched_details,
            steps=steps,
            requires_confirmation=requires_conf,
            next_run_at=next_run
        )

        return True, auto_obj, None

    @classmethod
    def _decompose_actions(cls, actions_str: str) -> Tuple[List[AutomationStep], Optional[str]]:
        """Decomposes a compound or multi-line action string into validated AutomationStep objects."""
        clean_text = actions_str.strip().lstrip(':').strip()
        lines = [line.strip().lstrip(':').strip() for line in clean_text.splitlines() if line.strip().lstrip(':').strip()]

        if len(lines) > 1:
            raw_clauses = []
            for line in lines:
                c = re.sub(r'^\d+\.\s*', '', line).strip().rstrip('.!?')
                if c:
                    raw_clauses.append(c)
        else:
            single_t = lines[0] if lines else clean_text
            m_if = re.search(r'\b(if\s+.+?),\s+(.+)', single_t, re.IGNORECASE)
            if m_if:
                protected = single_t[:m_if.start()] + m_if.group(1) + '___COMMA___' + m_if.group(2)
            else:
                protected = single_t
            parts = re.split(r';|,|\s+and\s+then\s+|\s+then\s+|\s+and\s+', protected, flags=re.IGNORECASE)
            raw_clauses = [p.replace('___COMMA___', ', ').strip().rstrip('.!?') for p in parts if p.strip().rstrip('.!?')]

        steps = []
        for idx, clause in enumerate(raw_clauses, 1):
            if idx > 5:
                break

            clause_clean = clause.strip()
            clause_lower = clause_clean.lower()

            if any(k in clause_clean for k in ["&&", "||", ";", "|", "`", "$(", "%COMSPEC%", "cmd.exe /c", "powershell -c"]):
                return [], f"Security Violation: Forbidden shell metacharacter in step '{clause_clean}'"

            cond_mode = "always"
            if clause_lower.startswith("if tests fail") or clause_lower.startswith("if test fails") or "if it fails" in clause_lower:
                cond_mode = "on_failure"
                clause_clean = re.sub(r"^if\s+(?:tests?\s+fails?|it\s+fails)[,\s]*", "", clause_clean, flags=re.IGNORECASE).strip()
            elif clause_lower.startswith("if tests succeed") or clause_lower.startswith("if build succeeds"):
                cond_mode = "on_success"
                clause_clean = re.sub(r"^if\s+(?:tests?\s+succeeds?|build\s+succeeds?)[,\s]*", "", clause_clean, flags=re.IGNORECASE).strip()
            elif clause_lower.startswith("if the file exists") or clause_lower.startswith("if file exists"):
                cond_mode = "if_exists"
                clause_clean = re.sub(r"^if\s+(?:the\s+)?file\s+exists[,\s]*", "", clause_clean, flags=re.IGNORECASE).strip()

            clause_lower = clause_clean.lower()

            # 1. Diagnostics & Auto-Fix
            if any(k in clause_lower for k in ["diagnose the error", "diagnose error", "diagnose", "check error", "explain error"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="coding_workspace",
                        action="diagnose_code_error",
                        arguments={"action": "diagnose_code_error"},
                        condition=cond_mode,
                        description="Diagnose code errors"
                    )
                )
                continue

            if any(k in clause_lower for k in ["fix the error", "auto fix", "auto-fix", "fix code"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="coding_workspace",
                        action="fix_code_error",
                        arguments={"action": "fix_code_error"},
                        condition=cond_mode,
                        description="Auto-fix diagnosed code errors"
                    )
                )
                continue

            # 2. Run Project Tests / Pytest
            if any(k in clause_lower for k in ["run my project tests", "run project tests", "run the tests", "run tests", "run test", "runs my project tests", "runs project tests"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="terminal_agent",
                        action="run_project_tests",
                        arguments={"action": "terminal_command", "operation": "run_project_tests"},
                        condition=cond_mode,
                        description="Run project test suite"
                    )
                )
                continue

            if any(k in clause_lower for k in ["run pytest", "pytest", "runs pytest"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="terminal_agent",
                        action="run_pytest",
                        arguments={"action": "terminal_command", "operation": "run_pytest"},
                        condition=cond_mode,
                        description="Run pytest test suite"
                    )
                )
                continue

            # 3. Open / Inspect Coding Project
            m_open_proj = re.match(r"^(?:open|opens|load|loads)\s+(?:my\s+|the\s+)?(?:coding\s+|bytex\s+)?(?:project\s+called|project\s+named|project)\s*([a-zA-Z0-9_\-]+)?$", clause_clean, re.IGNORECASE)
            if m_open_proj or clause_lower in ["open my coding project", "opens my coding project", "open my bytex project", "open project", "opens project", "open development environment", "opens development environment"]:
                p_name = m_open_proj.group(1).strip() if (m_open_proj and m_open_proj.group(1)) else "ByteXWorkspace"
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="coding_workspace",
                        action="open_project",
                        arguments={"action": "open_project", "project_name": p_name},
                        condition=cond_mode,
                        description=f"Open project '{p_name}'"
                    )
                )
                continue

            # 4. Project Structure / Latest Files
            if any(k in clause_lower for k in ["check project structure", "show project structure", "show me the latest files", "show latest files", "inspect project"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="coding_workspace",
                        action="project_structure",
                        arguments={"action": "project_structure"},
                        condition=cond_mode,
                        description="Inspect project structure"
                    )
                )
                continue

            # 5. Start Development Server / Terminal Build
            if any(k in clause_lower for k in ["start the development server", "starts the development server", "start dev server", "starts dev server", "start server"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="terminal_agent",
                        action="start_dev_server",
                        arguments={"action": "terminal_command", "operation": "start_dev_server"},
                        condition=cond_mode,
                        description="Start development server"
                    )
                )
                continue

            if any(k in clause_lower for k in ["build the project", "builds the project", "build project", "builds project"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="terminal_agent",
                        action="build_project",
                        arguments={"action": "terminal_command", "operation": "build_project"},
                        condition=cond_mode,
                        description="Build project artifacts"
                    )
                )
                continue

            # 6. File Manager — Delete Operations (CONFIRMATION PROTECTED)
            m_del_file = re.match(r"^(?:delete|deletes|remove|removes|erase|erases|clean\s+up)\s+(?:the\s+)?(?:files?\s+called\s+|files?\s+named\s+|file\s+|folder\s+)?(.+)$", clause_clean, re.IGNORECASE)
            if m_del_file:
                target_del = m_del_file.group(1).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="delete_file",
                        action="delete_file",
                        arguments={"target_path": target_del},
                        condition=cond_mode,
                        description=f"Delete target '{target_del}' (Confirmation Required)",
                        requires_confirmation=True
                    )
                )
                continue

            # 7. File Manager — Create Folder, Create File, Move, Copy, Search
            m_create_fol = re.match(r"^(?:create|creates|make|makes|mkdir)\s+(?:a\s+)?(?:new\s+)?folder(?:\s+called|\s+named)?\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_create_fol:
                fol_t = m_create_fol.group(1).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="create_folder",
                        action="create_folder",
                        arguments={"target_path": fol_t},
                        condition=cond_mode,
                        description=f"Create folder '{fol_t}'"
                    )
                )
                continue

            m_move_f = re.match(r"^(?:move|moves)\s+(.+?)\s+(?:to|into|inside)\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_move_f:
                s_f = m_move_f.group(1).strip()
                d_f = m_move_f.group(2).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="move_file",
                        action="move_file",
                        arguments={"source_path": s_f, "destination_path": d_f},
                        condition=cond_mode,
                        description=f"Move '{s_f}' to '{d_f}'",
                        requires_confirmation=True
                    )
                )
                continue

            m_copy_f = re.match(r"^(?:copy|copies|make\s+a\s+copy\s+of)\s+(.+?)\s+(?:to|into|inside)\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_copy_f:
                s_f = m_copy_f.group(1).strip()
                d_f = m_copy_f.group(2).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="copy_file",
                        action="copy_file",
                        arguments={"source_path": s_f, "destination_path": d_f},
                        condition=cond_mode,
                        description=f"Copy '{s_f}' to '{d_f}'"
                    )
                )
                continue

            # 8. Web Browser Operations
            if any(k in clause_lower for k in ["check my website", "checks my website", "check website", "open my website", "open website"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="browser_control",
                        action="navigate",
                        arguments={"url": "http://localhost:3000"},
                        condition=cond_mode,
                        description="Check website in browser"
                    )
                )
                continue

            m_open_app = re.match(r"^(?:open|opens|launch|launches|start|starts)\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_open_app:
                app_tgt = m_open_app.group(1).strip()
                if any(k in app_tgt.lower() for k in ["chrome", "edge", "browser", "google", "youtube", "github", "http://", "https://"]):
                    steps.append(
                        AutomationStep(
                            step_id=idx,
                            skill="browser_control",
                            action="navigate",
                            arguments={"url": app_tgt if app_tgt.startswith("http") else "https://google.com"},
                            condition=cond_mode,
                            description=f"Open {app_tgt} in browser"
                        )
                    )
                else:
                    steps.append(
                        AutomationStep(
                            step_id=idx,
                            skill="open_application",
                            action="open_application",
                            arguments={"application": app_tgt},
                            condition=cond_mode,
                            description=f"Open {app_tgt}"
                        )
                    )
                continue

            # 8b. Screen Vision Typing
            m_type = re.match(r"^(?:type|types|write|writes|enter|enters|input|inputs)\s+(.+?)(?:\s+(?:in|into|on)\s+(?:the\s+)?(.+))?$", clause_clean, re.IGNORECASE)
            if m_type:
                text_val = sanitize_automation_text(m_type.group(1).strip().strip('"\''))
                target_val = m_type.group(2).strip().strip('"\'') if m_type.group(2) else None
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="screen_vision",
                        action="type",
                        arguments={"action": "type", "text": text_val, "target": target_val},
                        condition=cond_mode,
                        description=f"Type '{text_val}' into {target_val or 'active window'}"
                    )
                )
                continue

            # 9. Reminders & Feedback Notifications
            m_remind = re.match(r"^(?:remind\s+me\s+to|remind\s+me|reminds\s+me\s+to|reminds\s+me)\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_remind:
                rem_msg = m_remind.group(1).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="system_status",
                        action="notify",
                        arguments={"message": f"Reminder: {rem_msg}"},
                        condition=cond_mode,
                        description=f"Remind: {rem_msg}"
                    )
                )
                continue

            if any(k in clause_lower for k in ["tell me the result", "report result", "notify me", "show result"]):
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="system_status",
                        action="report_summary",
                        arguments={},
                        condition=cond_mode,
                        description="Report automation execution summary"
                    )
                )
                continue

            # 10. Web Search
            m_search = re.match(r"^(?:search\s+for|search|searches\s+for|searches|google)\s+(.+)$", clause_clean, re.IGNORECASE)
            if m_search:
                q_val = m_search.group(1).strip()
                steps.append(
                    AutomationStep(
                        step_id=idx,
                        skill="web_search",
                        action="search",
                        arguments={"query": q_val},
                        condition=cond_mode,
                        description=f"Search for '{q_val}'"
                    )
                )
                continue

            # 11. Unsupported / Hallucinated Step Detection
            return [], clause_clean

        return steps, None


class AutomationManager:
    """
    Feature #36: ByteX Advanced Automation Engine.
    
    Manages structured automation workflows with SQLite persistence,
    Agent Pipeline execution, #28 Error Recovery, #29 Task History integration,
    and startup automation dispatching.
    """

    @classmethod
    def get_all_automations(cls, enabled_only: bool = False) -> List[Automation]:
        """Retrieves stored automations from SQLite."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            if enabled_only:
                cursor.execute("SELECT * FROM automations WHERE enabled = 1 ORDER BY created_at DESC")
            else:
                cursor.execute("SELECT * FROM automations ORDER BY created_at DESC")
            rows = cursor.fetchall()
            automations = []
            for row in rows:
                row_dict = dict(row)
                steps_data = json.loads(row_dict.get("steps_json", "[]"))
                steps = [AutomationStep(**s) for s in steps_data]
                sched_details = json.loads(row_dict.get("schedule_details") or "{}")
                automations.append(
                    Automation(
                        automation_id=row_dict["automation_id"],
                        name=row_dict["name"],
                        description=row_dict.get("description", ""),
                        enabled=bool(row_dict.get("enabled", 1)),
                        trigger=row_dict["trigger"],
                        trigger_type=AutomationTriggerType(row_dict.get("trigger_type", "COMMAND")),
                        schedule_type=AutomationScheduleType(row_dict.get("schedule_type", "COMMAND")),
                        schedule_details=sched_details,
                        steps=steps,
                        conditions=row_dict.get("conditions"),
                        requires_confirmation=bool(row_dict.get("requires_confirmation", 0)),
                        created_at=row_dict["created_at"],
                        updated_at=row_dict["updated_at"],
                        last_run_at=row_dict.get("last_run_at"),
                        next_run_at=row_dict.get("next_run_at"),
                        run_count=row_dict.get("run_count", 0),
                        success_count=row_dict.get("success_count", 0),
                        failure_count=row_dict.get("failure_count", 0),
                        last_result=row_dict.get("last_result"),
                        last_error=row_dict.get("last_error"),
                        max_retries=row_dict.get("max_retries", 1),
                        retry_count=row_dict.get("retry_count", 0),
                        timeout_seconds=row_dict.get("timeout_seconds", 60)
                    )
                )
            return automations

    @classmethod
    def get_automation_by_id(cls, auto_id: str) -> Optional[Automation]:
        """Retrieves an automation by ID."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM automations WHERE automation_id = ?", (auto_id,))
            row = cursor.fetchone()
            if not row:
                return None
            row_dict = dict(row)
            steps_data = json.loads(row_dict.get("steps_json", "[]"))
            steps = [AutomationStep(**s) for s in steps_data]
            sched_details = json.loads(row_dict.get("schedule_details") or "{}")
            return Automation(
                automation_id=row_dict["automation_id"],
                name=row_dict["name"],
                description=row_dict.get("description", ""),
                enabled=bool(row_dict.get("enabled", 1)),
                trigger=row_dict["trigger"],
                trigger_type=AutomationTriggerType(row_dict.get("trigger_type", "COMMAND")),
                schedule_type=AutomationScheduleType(row_dict.get("schedule_type", "COMMAND")),
                schedule_details=sched_details,
                steps=steps,
                conditions=row_dict.get("conditions"),
                requires_confirmation=bool(row_dict.get("requires_confirmation", 0)),
                created_at=row_dict["created_at"],
                updated_at=row_dict["updated_at"],
                last_run_at=row_dict.get("last_run_at"),
                next_run_at=row_dict.get("next_run_at"),
                run_count=row_dict.get("run_count", 0),
                success_count=row_dict.get("success_count", 0),
                failure_count=row_dict.get("failure_count", 0),
                last_result=row_dict.get("last_result"),
                last_error=row_dict.get("last_error"),
                max_retries=row_dict.get("max_retries", 1),
                retry_count=row_dict.get("retry_count", 0),
                timeout_seconds=row_dict.get("timeout_seconds", 60)
            )

    @classmethod
    def get_automation_by_name(cls, name: str) -> Optional[Automation]:
        """Finds an automation by exact or partial name/trigger match."""
        clean_name = name.strip().lower().rstrip('.!?').strip()
        all_autos = cls.get_all_automations()
        
        # 1. Exact match on name
        for a in all_autos:
            if a.name.lower() == clean_name:
                return a
                
        # 2. Exact match on trigger
        for a in all_autos:
            if a.trigger.lower() == clean_name:
                return a
                
        # 3. Partial keyword match on name
        for a in all_autos:
            if clean_name in a.name.lower() or a.name.lower() in clean_name:
                return a
                
        # 4. Partial keyword match on trigger
        for a in all_autos:
            if clean_name in a.trigger.lower() or a.trigger.lower() in clean_name:
                return a

        # 5. Semantic keyword tokens (e.g. "morning routine" -> tokens: ["morning"])
        tokens = [t for t in clean_name.split() if t not in ["my", "the", "routine", "workflow", "automation", "now"]]
        for tok in tokens:
            for a in all_autos:
                if tok in a.name.lower() or tok in a.trigger.lower():
                    return a

        # 6. Morning alias fallback
        if "morning" in clean_name:
            for a in all_autos:
                if any(k in a.trigger.lower() or k in a.name.lower() for k in ["morning", "8:00 am", "8 am", "9:00 am", "9 am"]):
                    return a

        return None

    @classmethod
    def find_matching_command_automations(cls, message: str) -> List[Automation]:
        """Finds automations whose trigger or name matches the incoming user command."""
        clean = message.strip().lower().rstrip('.!?')
        all_autos = cls.get_all_automations(enabled_only=False)
        matches = []

        for auto in all_autos:
            trig_clean = auto.trigger.strip().lower().rstrip('.!?')
            name_clean = auto.name.strip().lower().rstrip('.!?')

            if clean == trig_clean or clean == name_clean:
                matches.append(auto)
            elif clean in [f"run {name_clean}", f"start {name_clean}", f"run {trig_clean}", f"run my {name_clean}"]:
                matches.append(auto)
            elif name_clean in clean and len(name_clean) >= 4:
                matches.append(auto)

        return matches

    @classmethod
    def check_duplicate(cls, new_auto: Automation) -> Optional[Automation]:
        """Detects if an exact duplicate automation already exists (matching schedule + actions)."""
        all_autos = cls.get_all_automations()
        for existing in all_autos:
            if (
                existing.schedule_type == new_auto.schedule_type
                and existing.schedule_details == new_auto.schedule_details
                and len(existing.steps) == len(new_auto.steps)
                and [s.action for s in existing.steps] == [s.action for s in new_auto.steps]
            ):
                return existing
        return None

    @classmethod
    def save_automation(cls, auto: Automation) -> Automation:
        """Persists a new or updated automation to SQLite with name collision disambiguation."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT automation_id FROM automations WHERE LOWER(name) = LOWER(?) AND automation_id != ?", (auto.name.strip(), auto.automation_id))
            if cursor.fetchone():
                suffix = 2
                base_n = auto.name
                while True:
                    candidate = f"{base_n} ({suffix})"
                    cursor.execute("SELECT automation_id FROM automations WHERE LOWER(name) = LOWER(?) AND automation_id != ?", (candidate, auto.automation_id))
                    if not cursor.fetchone():
                        auto.name = candidate
                        break
                    suffix += 1

            steps_json = json.dumps([s.model_dump() for s in auto.steps])
            sched_json = json.dumps(auto.schedule_details)
            cursor.execute(
                """
                INSERT INTO automations (
                    automation_id, name, description, enabled, trigger, trigger_type, conditions,
                    steps_json, requires_confirmation, created_at, updated_at, last_run_at,
                    run_count, success_count, failure_count, schedule_type, schedule_details,
                    next_run_at, last_result, last_error, max_retries, retry_count, timeout_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(automation_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    enabled=excluded.enabled,
                    trigger=excluded.trigger,
                    trigger_type=excluded.trigger_type,
                    conditions=excluded.conditions,
                    steps_json=excluded.steps_json,
                    requires_confirmation=excluded.requires_confirmation,
                    updated_at=excluded.updated_at,
                    last_run_at=excluded.last_run_at,
                    run_count=excluded.run_count,
                    success_count=excluded.success_count,
                    failure_count=excluded.failure_count,
                    schedule_type=excluded.schedule_type,
                    schedule_details=excluded.schedule_details,
                    next_run_at=excluded.next_run_at,
                    last_result=excluded.last_result,
                    last_error=excluded.last_error,
                    max_retries=excluded.max_retries,
                    retry_count=excluded.retry_count,
                    timeout_seconds=excluded.timeout_seconds
                """,
                (
                    auto.automation_id,
                    sanitize_automation_text(auto.name),
                    sanitize_automation_text(auto.description),
                    1 if auto.enabled else 0,
                    sanitize_automation_text(auto.trigger),
                    auto.trigger_type.value,
                    auto.conditions,
                    steps_json,
                    1 if auto.requires_confirmation else 0,
                    auto.created_at,
                    datetime.utcnow().isoformat(),
                    auto.last_run_at,
                    auto.run_count,
                    auto.success_count,
                    auto.failure_count,
                    auto.schedule_type.value,
                    sched_json,
                    auto.next_run_at,
                    auto.last_result,
                    auto.last_error,
                    auto.max_retries,
                    auto.retry_count,
                    auto.timeout_seconds
                )
            )
            conn.commit()
            print(f"[ByteX Automation] Saved automation: '{auto.name}' (ID: {auto.automation_id})")
            return auto

    @classmethod
    def delete_automation(cls, auto_id: str) -> bool:
        """Deletes an automation by ID."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM automations WHERE automation_id = ?", (auto_id,))
            conn.commit()
            return cursor.rowcount > 0

    @classmethod
    def clear_all_automations(cls) -> int:
        """Deletes all automations."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM automations")
            conn.commit()
            return cursor.rowcount

    @classmethod
    def set_enabled(cls, auto_id: str, enabled: bool) -> bool:
        """Enables or disables an automation."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE automations SET enabled = ?, updated_at = ? WHERE automation_id = ?", (1 if enabled else 0, datetime.utcnow().isoformat(), auto_id))
            conn.commit()
            return cursor.rowcount > 0

    @classmethod
    def update_schedule(cls, auto_id: str, new_time: str) -> bool:
        """Modifies the schedule of an automation."""
        auto = cls.get_automation_by_id(auto_id)
        if not auto:
            return False
        norm_t = normalize_time_str(new_time)
        auto.schedule_details["time"] = norm_t
        auto.next_run_at = ScheduleEngine.calculate_next_run(auto.schedule_type, auto.schedule_details)
        auto.trigger = ScheduleEngine.format_schedule(auto.schedule_type, auto.schedule_details, auto.name)
        cls.save_automation(auto)
        return True

    @classmethod
    async def execute_automation(cls, auto: Automation, is_manual: bool = False) -> Tuple[bool, str, str, Optional[Dict[str, Any]]]:
        """
        Executes an automation workflow with step-level telemetry,
        condition evaluation, error recovery, and Task History integration.
        """
        if not auto.enabled and not is_manual:
            return True, f"Automation '{auto.name}' is currently disabled.", "speaking", {"disabled": True}

        from agent.models import AgentPlan, PlanStep, StepState
        from agent.pipeline import agent_pipeline
        from agent.history import task_history_manager

        print(f"[ByteX Automation] Executing Automation '{auto.name}' ({len(auto.steps)} step(s))...")

        if len(auto.steps) > 5:
            auto.steps = auto.steps[:5]

        plan_steps = []
        for s in auto.steps:
            plan_steps.append(
                PlanStep(
                    step_id=s.step_id,
                    description=s.description or f"Execute {s.action}",
                    suggested_skill=s.skill,
                    arguments=s.arguments,
                    requires_confirmation=s.requires_confirmation,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )

        plan = AgentPlan(
            goal=f"Automation: {auto.name}",
            steps=plan_steps,
            requires_confirmation=auto.requires_confirmation
        )

        t_start = time.time()
        handled, response_text, state, data = await agent_pipeline.run_pipeline(
            goal=f"Automation: {auto.name}",
            plan=plan
        )
        duration = round(time.time() - t_start, 2)

        is_success = state in ["speaking", "completed"] and (data and data.get("status") == "completed")

        auto.last_run_at = time.time()
        auto.run_count += 1
        auto.last_result = "SUCCESS" if is_success else "FAILED"
        if is_success:
            auto.success_count += 1
            auto.last_error = None
        else:
            auto.failure_count += 1
            auto.last_error = response_text

        if not is_manual:
            auto.next_run_at = ScheduleEngine.calculate_next_run(auto.schedule_type, auto.schedule_details)

        cls.save_automation(auto)

        return handled, f"Automation '{auto.name}' executed: {response_text}", state, data

    @classmethod
    async def run_startup_automations(cls):
        """Runs all enabled STARTUP automations upon ByteX backend initialization."""
        startups = [a for a in cls.get_all_automations(enabled_only=True) if a.schedule_type == AutomationScheduleType.STARTUP]
        if not startups:
            return
        print(f"[ByteX Automation] Dispatching {len(startups)} startup automation(s)...")
        for a in startups:
            try:
                await asyncio.wait_for(cls.execute_automation(a, is_manual=False), timeout=30.0)
            except Exception as e:
                print(f"[ByteX Automation] Startup automation '{a.name}' failed: {e}")

    @classmethod
    def handle_natural_automation_command(cls, user_message: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        Processes automation management commands:
        - "Show my automations" / "List my routines"
        - "What's scheduled today?"
        - "Enable <name>" / "Disable <name>"
        - "Delete <name>"
        - "Change <name> to <time>"
        - "Run <name> now"
        """
        clean = user_message.strip()
        lower = clean.lower().rstrip('.!?')

        # 1. "Show my automations" / "List my routines"
        if lower in ["show my automations", "show automations", "list my automations", "list automations", "view automations", "list my routines", "show my routines", "show routines", "list routines"]:
            autos = cls.get_all_automations()
            if not autos:
                return True, "You don't have any saved automations yet. You can create one by saying 'Every day at 9 AM, open Chrome' or 'Every Monday, run my project tests'.", "speaking", None
            lines = [f"You have {len(autos)} saved automation(s):\n"]
            for i, a in enumerate(autos, 1):
                status_icon = "● Enabled" if a.enabled else "○ Disabled"
                lines.append(f"{i}. **{a.name}** ({status_icon})\n   - Schedule: {a.trigger}\n   - Steps: {len(a.steps)} | Runs: {a.run_count} (✓ {a.success_count}, ✗ {a.failure_count})")
            return True, "\n".join(lines), "speaking", {"automations": [a.model_dump() for a in autos]}

        # 2. "What's scheduled today?"
        if lower in ["what's scheduled today?", "what is scheduled today?", "what's scheduled today", "what is scheduled today", "show today's schedule", "scheduled today"]:
            autos = cls.get_all_automations(enabled_only=True)
            today_weekday = datetime.now().weekday()
            today_autos = []
            for a in autos:
                if a.schedule_type == AutomationScheduleType.DAILY:
                    today_autos.append(a)
                elif a.schedule_type == AutomationScheduleType.SELECTED_WEEKDAYS and today_weekday in a.schedule_details.get("days", [0,1,2,3,4]):
                    today_autos.append(a)
                elif a.schedule_type == AutomationScheduleType.WEEKLY and a.schedule_details.get("weekday") == today_weekday:
                    today_autos.append(a)
                elif a.schedule_type == AutomationScheduleType.MONTHLY and a.schedule_details.get("day_of_month") == datetime.now().day:
                    today_autos.append(a)

            if not today_autos:
                return True, "No automations are scheduled to run today.", "speaking", None

            lines = [f"**Scheduled for Today ({len(today_autos)}):**\n"]
            for i, a in enumerate(today_autos, 1):
                lines.append(f"{i}. **{a.name}** — {a.trigger} ({len(a.steps)} steps)")
            return True, "\n".join(lines), "speaking", {"today_automations": [a.model_dump() for a in today_autos]}

        # 3. "Enable <name>"
        m_en = re.match(r"^enable\s+(?:my\s+)?(?:automation\s+|workflow\s+|routine\s+)?([a-zA-Z0-9_\s-]+)$", lower)
        if m_en:
            tgt_name = m_en.group(1).strip()
            auto = cls.get_automation_by_name(tgt_name)
            if not auto:
                return True, f"I couldn't find an automation named '{tgt_name}'.", "speaking", None
            cls.set_enabled(auto.automation_id, True)
            return True, f"✓ Automation '{auto.name}' has been enabled.", "speaking", {"automation_id": auto.automation_id, "enabled": True}

        # 4. "Disable <name>"
        m_dis = re.match(r"^disable\s+(?:my\s+)?(?:automation\s+|workflow\s+|routine\s+)?([a-zA-Z0-9_\s-]+)$", lower)
        if m_dis:
            tgt_name = m_dis.group(1).strip()
            auto = cls.get_automation_by_name(tgt_name)
            if not auto:
                return True, f"I couldn't find an automation named '{tgt_name}'.", "speaking", None
            cls.set_enabled(auto.automation_id, False)
            return True, f"✓ Automation '{auto.name}' has been disabled.", "speaking", {"automation_id": auto.automation_id, "enabled": False}

        # 5. "Delete <name>"
        m_del = re.match(r"^delete\s+(?:my\s+)?(?:automation\s+|workflow\s+|routine\s+)?([a-zA-Z0-9_\s-]+)$", lower)
        if m_del:
            tgt_name = m_del.group(1).strip()
            if tgt_name in ["all", "all automations", "everything"]:
                from core.confirmation import confirmation_manager
                confirmation_manager.set_pending(
                    tool="delete_all_automations",
                    action="delete_all_automations",
                    description="This will permanently delete all your ByteX automations. Continue?",
                    arguments={}
                )
                return True, "⚠️ This will permanently delete all your ByteX automations. Continue?", "waiting_confirmation", {"pending_action": "delete_all_automations"}

            auto = cls.get_automation_by_name(tgt_name)
            if not auto:
                return True, f"I couldn't find an automation named '{tgt_name}' to delete.", "speaking", None

            from core.confirmation import confirmation_manager
            confirmation_manager.set_pending(
                tool="delete_automation",
                action="delete_automation",
                description=f"This will permanently delete automation '{auto.name}'. Continue?",
                arguments={"automation_id": auto.automation_id, "name": auto.name}
            )
            return True, f"⚠️ This will permanently delete automation '{auto.name}'. Confirm deletion?", "waiting_confirmation", {"pending_action": "delete_automation"}

        # 6. "Change <name> to <new_time>"
        if not re.search(r"\b[a-zA-Z0-9_\-\.]+\.(?:cpp|py|js|ts|c|h|hpp|java|go|rs|html|css|json|sql|md)\b", lower):
            m_mod = re.match(r"^change\s+(?:my\s+)?(?:the\s+)?(?:schedule\s+of\s+)?(?:automation\s+|workflow\s+|routine\s+)?(.+?)\s+(?:schedule\s+)?to\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)$", lower)
            if m_mod:
                tgt_name = m_mod.group(1).strip()
                new_t = m_mod.group(2).strip()
                auto = cls.get_automation_by_name(tgt_name)
                if auto:
                    cls.update_schedule(auto.automation_id, new_t)
                    norm_new_t = normalize_time_str(new_t)
                    return True, f"✓ Changed schedule of '{auto.name}' to {norm_new_t}.", "speaking", {"automation_id": auto.automation_id, "time": norm_new_t}
                elif any(k in lower for k in ["automation", "routine", "workflow", "schedule"]):
                    return True, f"I couldn't find an automation named '{tgt_name}'.", "speaking", None

        # 7. "Pause all automations" / "Turn off all automations"
        if lower in ["turn off all automations", "disable all automations", "pause all automations"]:
            autos = cls.get_all_automations()
            for a in autos:
                cls.set_enabled(a.automation_id, False)
            return True, f"✓ All {len(autos)} automations have been paused.", "speaking", None

        return False, None, None, None

automation_manager = AutomationManager()
