import re
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from memory.database import db_manager
from skills.registry import skill_registry
from skills.resolver import universal_app_resolver, ResolutionStatus

logger = logging.getLogger("bytex.agent.routines")

FORBIDDEN_RAW_COMMAND_PATTERNS = [
    r"\bpowershell\b",
    r"\bcmd(?:\.exe)?\b",
    r"\bbash\b",
    r"\bsh\b",
    r"\bpython\s+-c\b",
    r"\btaskkill\b",
    r"\brmdir\b",
    r"\bdel\s+/[fFqQsS]\b",
    r"\bformat\s+[a-zA-Z]:",
    r"\bInvoke-Expression\b",
    r"\biex\b",
    r"\beval\(",
]

class RoutineStep(BaseModel):
    skill: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    description: str

class UserRoutine(BaseModel):
    id: str = Field(default_factory=lambda: f"routine_{uuid.uuid4().hex[:10]}")
    name: str
    display_name: str
    description: str = ""
    steps: List[RoutineStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class RoutineManager:
    """
    Dedicated Natural-Language Routine & Automation Manager for ByteX.
    
    Security Invariants:
    1. Data Only: Stored routines are declarative data, never executable code.
    2. Strict Allowlist: Every step must map to an existing registered ByteX skill.
    3. Rejection of Raw Commands: Rejects arbitrary PowerShell, CMD, shell, Python, or raw executable paths.
    4. Execution Decoupling: Creating or viewing a routine NEVER triggers execution.
    5. Unified Execution: Routine execution flows through the authoritative Agent Pipeline (risk checks, verification, error recovery, task history).
    6. No Silent Overwrite: Duplicate routine names require distinct names or explicit replacement.
    """

    @classmethod
    def create_routine(
        cls,
        name: str,
        display_name: str,
        steps: List[RoutineStep],
        description: str = ""
    ) -> Tuple[bool, str, Optional[UserRoutine]]:
        """
        Validates and stores a new user routine.
        """
        norm_name = name.strip().lower()
        if not norm_name:
            return False, "Routine name cannot be empty.", None

        # 1. Check for duplicate routine
        existing = cls.get_routine(norm_name)
        if existing:
            return False, f"A routine named '{existing.display_name}' already exists. Please use a different name or delete the existing routine first.", None

        # 2. Validate all steps
        if not steps:
            return False, "Cannot create a routine with no steps.", None

        for idx, step in enumerate(steps, 1):
            # Verify skill exists in registry
            if not skill_registry.get_skill(step.skill):
                return False, f"Step {idx} references an unsupported or unregistered skill '{step.skill}'.", None

            # Check arguments and description for forbidden raw command injection
            serialized = f"{step.description} {json.dumps(step.arguments)}"
            for pat in FORBIDDEN_RAW_COMMAND_PATTERNS:
                if re.search(pat, serialized, re.IGNORECASE):
                    return False, f"Step {idx} contains forbidden raw command or shell syntax: '{pat}'.", None

        routine_id = f"routine_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.utcnow().isoformat()
        steps_json = json.dumps([s.model_dump() for s in steps])

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_routines (id, name, display_name, description, steps_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (routine_id, norm_name, display_name, description, steps_json, now_iso, now_iso)
            )
            conn.commit()

        routine = UserRoutine(
            id=routine_id,
            name=norm_name,
            display_name=display_name,
            description=description,
            steps=steps,
            created_at=now_iso,
            updated_at=now_iso
        )
        print(f"[ByteX RoutineManager] Created routine '{display_name}' with {len(steps)} step(s).")
        return True, f"Created the {display_name} routine with {len(steps)} step(s).", routine

    @classmethod
    def get_routine(cls, name: str) -> Optional[UserRoutine]:
        """Retrieves a routine by name or alias."""
        norm_name = name.strip().lower()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_routines WHERE name = ?", (norm_name,))
            row = cursor.fetchone()
            if not row:
                return None
            row_dict = dict(row)
            steps_raw = json.loads(row_dict["steps_json"])
            steps = [RoutineStep(**s) for s in steps_raw]
            return UserRoutine(
                id=row_dict["id"],
                name=row_dict["name"],
                display_name=row_dict["display_name"],
                description=row_dict["description"],
                steps=steps,
                created_at=row_dict["created_at"],
                updated_at=row_dict["updated_at"]
            )

    @classmethod
    def list_routines(cls) -> List[UserRoutine]:
        """Lists all stored user routines."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_routines ORDER BY created_at ASC")
            rows = cursor.fetchall()
            routines = []
            for row in rows:
                row_dict = dict(row)
                steps_raw = json.loads(row_dict["steps_json"])
                steps = [RoutineStep(**s) for s in steps_raw]
                routines.append(
                    UserRoutine(
                        id=row_dict["id"],
                        name=row_dict["name"],
                        display_name=row_dict["display_name"],
                        description=row_dict["description"],
                        steps=steps,
                        created_at=row_dict["created_at"],
                        updated_at=row_dict["updated_at"]
                    )
                )
            return routines

    @classmethod
    def delete_routine(cls, name: str) -> Tuple[bool, str]:
        """Deletes a routine definition by name."""
        norm_name = name.strip().lower()
        existing = cls.get_routine(norm_name)
        if not existing:
            return False, f"I couldn't find a routine named '{name}'."

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_routines WHERE name = ?", (norm_name,))
            conn.commit()
            print(f"[ByteX RoutineManager] Deleted routine '{existing.display_name}'.")
            return True, f"Deleted the {existing.display_name} routine."

    @classmethod
    def parse_routine_creation(cls, text: str) -> Optional[Dict[str, Any]]:
        """
        Extracts routine name, display name, and steps from natural language requests.
        """
        clean_text = text.strip()
        
        # Check for raw script/command injection attempts
        for pat in FORBIDDEN_RAW_COMMAND_PATTERNS:
            if re.search(pat, clean_text, re.IGNORECASE):
                return {"error": f"Raw command or shell automation is not permitted: '{pat}'."}

        # Pattern 1: "Create a routine (called|named) <name> that/to <actions>"
        m1 = re.search(r"create\s+(?:a\s+)?(?:routine|automation|workflow)\s+(?:called|named)\s+([a-zA-Z0-9_\s-]+?)\s+(?:that|to|which)\s+(.+)$", clean_text, re.IGNORECASE)
        # Pattern 2: "Save this as my <name> (setup|routine|workflow): <actions>"
        m2 = re.search(r"save\s+(?:this\s+as\s+)?(?:my\s+)?([a-zA-Z0-9_\s-]+?)\s*(?:setup|routine|workflow)?\s*:\s*(.+)$", clean_text, re.IGNORECASE)
        # Pattern 3: "Create (a|an) <name> routine (that|to) <actions>"
        m3 = re.search(r"create\s+(?:a|an)?\s*([a-zA-Z0-9_\s-]+?)\s+routine\s+(?:that|to|which)\s+(.+)$", clean_text, re.IGNORECASE)

        m = m1 or m2 or m3
        if not m:
            return None

        raw_name = m.group(1).strip()
        actions_phrase = m.group(2).strip()

        # Clean routine name
        display_name = raw_name.strip('"\'').title()
        norm_name = raw_name.strip('"\'').lower()

        # Parse actions in phrase
        steps = []
        
        # Handle Open/Launch applications
        m_open = re.search(r"(?:opens?|launch(?:es)?|start(?:s)?|run(?:s)?)\s+(.+)$", actions_phrase, re.IGNORECASE)
        if m_open:
            app_phrase = m_open.group(1)
            # Split comma and and
            parts = re.split(r",|\band\b", app_phrase, flags=re.IGNORECASE)
            for p in parts:
                clean_p = p.strip().strip(".")
                if clean_p and clean_p.lower() not in ["and", "the", "my", "a", "an"]:
                    status, rec, _ = universal_app_resolver.resolve(clean_p)
                    app_name = rec.display_name if (status == ResolutionStatus.FOUND and rec) else clean_p
                    steps.append(
                        RoutineStep(
                            skill="open_application",
                            arguments={"application": app_name},
                            description=f"Open {app_name}"
                        )
                    )

        # Handle Close applications
        m_close = re.search(r"(?:close(?:s)?|quit(?:s)?|exit(?:s)?|stop(?:s)?)\s+(.+)$", actions_phrase, re.IGNORECASE)
        if m_close:
            app_phrase = m_close.group(1)
            parts = re.split(r",|\band\b", app_phrase, flags=re.IGNORECASE)
            for p in parts:
                clean_p = p.strip().strip(".")
                if clean_p and clean_p.lower() not in ["and", "the", "my", "a", "an"]:
                    status, rec, _ = universal_app_resolver.resolve(clean_p)
                    app_name = rec.display_name if (status == ResolutionStatus.FOUND and rec) else clean_p
                    steps.append(
                        RoutineStep(
                            skill="close_application",
                            arguments={"application": app_name},
                            description=f"Close {app_name}"
                        )
                    )

        # Handle System Status
        if any(k in actions_phrase.lower() for k in ["check system", "system status", "check computer"]):
            steps.append(
                RoutineStep(
                    skill="system_status",
                    arguments={},
                    description="Check system status"
                )
            )

        if not steps:
            return {"error": "Could not determine valid supported actions for this routine."}

        return {
            "name": norm_name,
            "display_name": display_name,
            "description": f"Automated routine for {display_name}",
            "steps": steps
        }

    @classmethod
    def handle_natural_routine_command(cls, user_message: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        Handles natural language routine queries: CREATE, LIST, VIEW, RUN, DELETE.
        Returns: (is_handled, response_message, action_type, payload)
        """
        msg_norm = user_message.strip()
        msg_clean = re.sub(r"[.!?]+$", "", msg_norm).strip()
        msg_lower = msg_clean.lower()

        # 1. LIST Routines
        if msg_lower in [
            "what routines do i have",
            "show my routines",
            "show my automations",
            "list my routines",
            "list routines",
            "list my automations",
            "show routines"
        ]:
            routines = cls.list_routines()
            if not routines:
                return True, "You don't have any saved routines yet. You can create one by saying: 'Create a routine called Study that opens Chrome and VS Code.'", "speaking", None

            lines = ["Your saved routines:"]
            for r in routines:
                lines.append(f"• **{r.display_name}** ({len(r.steps)} step(s))")
            return True, "\n".join(lines), "speaking", None

        # 2. VIEW Routine
        m_view = re.match(r"^(?:what(?:'s|\s+is)\s+in\s+my\s+|show\s+my\s+|view\s+my\s+|what\s+is\s+the\s+)([a-zA-Z0-9_\s-]+?)\s+(?:routine|automation|workflow)$", msg_lower)
        if m_view:
            target_name = m_view.group(1).strip()
            routine = cls.get_routine(target_name)
            if not routine:
                return True, f"I couldn't find a routine named '{target_name}'.", "speaking", None

            lines = [f"Your **{routine.display_name}** routine:"]
            for idx, s in enumerate(routine.steps, 1):
                lines.append(f"{idx}. {s.description}")
            return True, "\n".join(lines), "speaking", None

        # 3. RUN Routine
        m_run = re.match(r"^(?:run|execute|start)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\s-]+?)(?:\s+routine|\s+automation|\s+workflow)?$", msg_lower)
        if m_run:
            target_name = m_run.group(1).strip()
            routine = cls.get_routine(target_name)
            if routine:
                return True, None, "RUN_ROUTINE", {"routine": routine}
            elif "routine" in msg_norm.lower() or "automation" in msg_norm.lower() or "workflow" in msg_norm.lower():
                return True, f"I couldn't find a routine named '{target_name}'.", "speaking", None

        # 4. DELETE Routine
        m_del = re.match(r"^(?:delete|remove)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\s-]+?)\s+(?:routine|automation|workflow)$", msg_lower)
        if m_del:
            target_name = m_del.group(1).strip()
            success, msg = cls.delete_routine(target_name)
            return True, msg, "speaking", None

        # 5. CREATE Routine
        if any(k in msg_lower for k in ["create a routine", "create routine", "save this as my", "create an automation"]):
            parsed = cls.parse_routine_creation(msg_norm)
            if not parsed:
                return False, None, None, None

            if "error" in parsed:
                return True, parsed["error"], "error", None

            success, msg, routine = cls.create_routine(
                name=parsed["name"],
                display_name=parsed["display_name"],
                steps=parsed["steps"],
                description=parsed["description"]
            )
            state = "speaking" if success else "error"
            return True, msg, state, {"routine": routine.model_dump() if routine else None}

        return False, None, None, None

routine_manager = RoutineManager()
