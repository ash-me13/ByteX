import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field
from memory.database import db_manager
from memory.models import is_sensitive_content

logger = logging.getLogger("bytex.preferences")

class UserPreference(BaseModel):
    key: str
    category: str
    value: str
    confidence: float = 1.0
    source: str = "explicit"  # "explicit" | "inferred"
    occurrences: int = 1
    created_at: str
    updated_at: str

# Controlled Set of Supported Preferences
SUPPORTED_PREFERENCE_KEYS = {
    "preferred_browser": {
        "category": "application",
        "description": "User's default preferred web browser (e.g., Chrome, Edge, Brave, Firefox)",
        "aliases": ["browser", "web browser", "default browser", "preferred browser"]
    },
    "preferred_response_style": {
        "category": "interaction",
        "description": "User's preferred response style (e.g., concise, detailed, bullet points, technical)",
        "aliases": ["response style", "answer style", "style", "answers", "responses"]
    },
    "preferred_language": {
        "category": "interaction",
        "description": "User's preferred conversational language (e.g., English, Hinglish, Hindi, Spanish)",
        "aliases": ["language", "chat language", "speaking language"]
    },
    "preferred_voice_language": {
        "category": "interaction",
        "description": "User's preferred text-to-speech voice language (e.g., en-US, hi-IN)",
        "aliases": ["voice language", "voice"]
    },
    "preferred_application": {
        "category": "application",
        "description": "User's preferred commonly used desktop application",
        "aliases": ["app", "application", "favorite app"]
    },
    "preferred_workspace_dir": {
        "category": "workspace",
        "description": "User's preferred working workspace or project directory",
        "aliases": ["workspace", "project directory", "project folder"]
    },
    "preferred_units": {
        "category": "general",
        "description": "User's preferred unit system (e.g., metric, imperial, Celsius, Fahrenheit)",
        "aliases": ["units", "unit system", "temperature unit"]
    }
}

SENSITIVE_TOPICS = [
    r"(?:health|medical|disease|illness|diagnosis|prescription|medicine|doctor|asthma|patient)",
    r"(?:politics|political|democrat|republican|election|voting|party)",
    r"(?:religion|religious|faith|god|church|mosque|temple|hindu|muslim|christian|jewish)",
    r"(?:sexual|sexuality|orientation|gay|lesbian|bisexual|heterosexual)",
    r"(?:password|passwd|pin|token|secret|api_key|credential|ssn|credit_card|credit card)"
]

def is_disallowed_preference(text: str) -> bool:
    """Checks if text contains disallowed sensitive or private personal attributes."""
    if is_sensitive_content(text):
        return True
    for pattern in SENSITIVE_TOPICS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

class PreferenceManager:
    """
    ByteX User Preference Management Engine.
    
    Invariants & Security Rules:
    1. Single Persistent Store: Operates on existing SQLite database (user_preferences table).
    2. Strict Privacy: Never stores sensitive personal attributes, credentials, or secrets.
    3. Explicit > Inferred: Explicit statements have confidence=1.0. Inferred behaviors increase gradually.
    4. Current Instruction Wins: Stored preferences NEVER override direct, explicit user commands.
    5. Relevance-Only Retrieval: Injects only preferences relevant to the active task.
    """

    @classmethod
    def set_explicit_preference(cls, key: str, value: str, category: Optional[str] = None) -> Tuple[bool, str, Optional[UserPreference]]:
        """Stores or updates an explicit user preference with confidence 1.0."""
        clean_key = key.strip().lower()
        clean_val = value.strip()

        if is_disallowed_preference(f"{clean_key} {clean_val}"):
            print(f"[ByteX PreferenceManager] Rejected sensitive preference: '{clean_key}'")
            return False, "I cannot store sensitive personal information or credentials as preferences.", None

        cat = category or SUPPORTED_PREFERENCE_KEYS.get(clean_key, {}).get("category", "general")
        now_iso = datetime.utcnow().isoformat()

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_preferences (key, category, value, confidence, source, occurrences, created_at, updated_at)
                VALUES (?, ?, ?, 1.0, 'explicit', 1, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    category=excluded.category,
                    confidence=1.0,
                    source='explicit',
                    occurrences=user_preferences.occurrences + 1,
                    updated_at=excluded.updated_at
                """,
                (clean_key, cat, clean_val, now_iso, now_iso)
            )
            conn.commit()

        pref = UserPreference(
            key=clean_key,
            category=cat,
            value=clean_val,
            confidence=1.0,
            source="explicit",
            occurrences=1,
            created_at=now_iso,
            updated_at=now_iso
        )
        print(f"[ByteX PreferenceManager] Stored explicit preference: {clean_key} = '{clean_val}' (Confidence: 1.0)")
        return True, f"Saved preference: {clean_key.replace('_', ' ').title()} is set to '{clean_val}'.", pref

    @classmethod
    def record_inferred_behavior(cls, key: str, value: str, category: Optional[str] = None) -> Tuple[bool, str, Optional[UserPreference]]:
        """
        Records an observed user action, gradually increasing inferred confidence.
        Does NOT turn a single action into a permanent preference.
        """
        clean_key = key.strip().lower()
        clean_val = value.strip()

        if is_disallowed_preference(f"{clean_key} {clean_val}"):
            return False, "Sensitive data excluded.", None

        existing = cls.get_raw_preference(clean_key)
        cat = category or SUPPORTED_PREFERENCE_KEYS.get(clean_key, {}).get("category", "general")
        now_iso = datetime.utcnow().isoformat()

        # If existing preference was set explicitly by the user, do not let background inference degrade it
        if existing and existing.source == "explicit":
            return True, "Explicit preference remains authoritative.", existing

        if existing:
            if existing.value.lower() == clean_val.lower():
                # Repeated consistent behavior -> increase confidence gradually (up to max 0.8)
                new_conf = round(min(0.8, existing.confidence + 0.15), 2)
                new_occ = existing.occurrences + 1
            else:
                # Contradictory behavior -> decrease confidence
                new_conf = round(max(0.1, existing.confidence - 0.2), 2)
                new_occ = existing.occurrences
                # If confidence drops very low, switch to new inferred value
                if new_conf <= 0.2:
                    clean_val = clean_val
                    new_conf = 0.3
                    new_occ = 1
        else:
            # First occurrence -> weak confidence (0.3), not yet an active strong preference
            new_conf = 0.3
            new_occ = 1

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_preferences (key, category, value, confidence, source, occurrences, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'inferred', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    occurrences=excluded.occurrences,
                    updated_at=excluded.updated_at
                """,
                (clean_key, cat, clean_val, new_conf, new_occ, now_iso, now_iso)
            )
            conn.commit()

        pref = UserPreference(
            key=clean_key,
            category=cat,
            value=clean_val,
            confidence=new_conf,
            source="inferred",
            occurrences=new_occ,
            created_at=now_iso,
            updated_at=now_iso
        )
        print(f"[ByteX PreferenceManager] Updated inferred behavior: {clean_key} = '{clean_val}' (Occurrences: {new_occ}, Confidence: {new_conf:.2f})")
        return True, "Inferred behavior updated.", pref

    @classmethod
    def get_raw_preference(cls, key: str) -> Optional[UserPreference]:
        """Retrieves raw preference row regardless of confidence threshold."""
        clean_key = key.strip().lower()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_preferences WHERE key = ?", (clean_key,))
            row = cursor.fetchone()
            if row:
                return UserPreference(**dict(row))
        return None

    @classmethod
    def get_preference(cls, key: str, min_confidence: float = 0.5) -> Optional[UserPreference]:
        """Retrieves an active preference satisfying the minimum confidence threshold."""
        pref = cls.get_raw_preference(key)
        if pref and pref.confidence >= min_confidence:
            return pref
        return None

    @classmethod
    def get_all_preferences(cls) -> List[UserPreference]:
        """Retrieves all stored preferences."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_preferences ORDER BY confidence DESC, updated_at DESC")
            rows = cursor.fetchall()
            return [UserPreference(**dict(row)) for row in rows]

    @classmethod
    def delete_preference(cls, key: str) -> bool:
        """Deletes a single preference by key or matching alias."""
        clean_key = key.strip().lower()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_preferences WHERE key = ?", (clean_key,))
            conn.commit()
            if cursor.rowcount > 0:
                print(f"[ByteX PreferenceManager] Deleted preference: '{clean_key}'")
                return True
        return False

    @classmethod
    def clear_all_preferences(cls) -> int:
        """Clears all stored preferences."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_preferences")
            conn.commit()
            count = cursor.rowcount
            print(f"[ByteX PreferenceManager] Cleared all {count} preference(s).")
            return count

    @classmethod
    def get_relevant_preferences(cls, prompt: str) -> List[UserPreference]:
        """Retrieves only preferences relevant to the given query/task context."""
        prompt_lower = prompt.lower()
        active_prefs = [p for p in cls.get_all_preferences() if p.confidence >= 0.5]
        relevant = []

        for p in active_prefs:
            key_name = p.key.replace("_", " ")
            aliases = SUPPORTED_PREFERENCE_KEYS.get(p.key, {}).get("aliases", [])

            # Check if query mentions the preference domain or alias
            is_rel = False
            if p.key == "preferred_browser" and any(w in prompt_lower for w in ["browser", "web", "internet", "website", "search online"]):
                is_rel = True
            elif p.key == "preferred_response_style" and any(w in prompt_lower for w in ["explain", "answer", "tell me", "what is", "how to", "style"]):
                is_rel = True
            elif p.key == "preferred_language" and any(w in prompt_lower for w in ["speak", "talk", "chat", "language", "respond in"]):
                is_rel = True
            elif any(alias in prompt_lower for alias in aliases):
                is_rel = True

            if is_rel and p not in relevant:
                relevant.append(p)

        return relevant

    @classmethod
    def handle_natural_preference_command(cls, user_message: str) -> Tuple[bool, Optional[str]]:
        """
        Interprets natural language user preference commands.
        Returns (is_handled, response_text).
        """
        msg_norm = user_message.strip()
        msg_lower = msg_norm.lower()

        # 1. Show / List Preferences
        if msg_lower in [
            "show my preferences",
            "show my preferences.",
            "show preferences",
            "show preferences.",
            "list my preferences",
            "list preferences",
            "what are my preferences",
            "what are my preferences?",
            "get my preferences"
        ]:
            prefs = cls.get_all_preferences()
            if not prefs:
                return True, "You don't have any saved preferences yet. You can say things like 'Remember that I prefer Chrome' or 'I prefer concise answers'."
            lines = [f"Here are your learned preferences ({len(prefs)}):"]
            for p in prefs:
                src_label = "Explicit" if p.source == "explicit" else f"Inferred ({int(p.confidence*100)}%)"
                lines.append(f"• **{p.key.replace('_', ' ').title()}**: {p.value} [{src_label}]")
            return True, "\n".join(lines)

        # 2. Clear All Preferences
        if msg_lower in [
            "forget all learned preferences",
            "forget all preferences",
            "clear all preferences",
            "clear preferences",
            "forget my preferences",
            "reset preferences"
        ]:
            cnt = cls.clear_all_preferences()
            return True, f"I have cleared all {cnt} learned preference(s)."

        # 3. Explicit "Forget my preference for X" / "Forget that I prefer X"
        forget_pref_match = re.match(
            r"^forget\s+(?:that\s+i\s+prefer|my\s+preference\s+(?:for|about)?|preference\s+for|preferred\s+)?\s*(.+)$",
            msg_lower
        )
        if forget_pref_match and ("prefer" in msg_lower or "preference" in msg_lower or "browser" in msg_lower):
            target = forget_pref_match.group(1).strip().strip(".")
            # Identify which preference key matches
            deleted = False
            for key, info in SUPPORTED_PREFERENCE_KEYS.items():
                if target in key or any(a in target for a in info["aliases"]) or (cls.get_raw_preference(key) and cls.get_raw_preference(key).value.lower() in target):
                    cls.delete_preference(key)
                    deleted = True
                    return True, f"Forgotten. Removed preference for '{key.replace('_', ' ')}'."
            if not deleted:
                return True, f"I couldn't find a preference matching '{target}' to forget."

        # 4. Explicit "Remember that I prefer X over Y" / "Remember I prefer X" / "I prefer X"
        # 4a. Browser preference: Chrome / Edge / Brave / Firefox
        browser_match = re.search(r"\b(?:prefer|use)\s+(chrome|google chrome|edge|msedge|brave|firefox)\b", msg_lower)
        if browser_match and any(w in msg_lower for w in ["remember", "prefer", "browser", "default"]):
            browser_val = browser_match.group(1).title()
            if "google" in browser_val.lower():
                browser_val = "Chrome"
            cls.set_explicit_preference("preferred_browser", browser_val)
            return True, f"Understood. I've noted that you prefer {browser_val} as your browser."

        # 4b. Response style preference: concise / detailed / bullet points / technical
        style_match = re.search(r"\b(?:prefer|want|like)\s+(concise|short|brief|detailed|in-depth|bullet points?|bulleted|technical)\s+(?:answers?|responses?|style)?\b", msg_lower)
        if style_match and any(w in msg_lower for w in ["remember", "prefer", "answers", "responses", "style"]):
            style_val = style_match.group(1).lower()
            if style_val in ["short", "brief"]:
                style_val = "concise"
            elif style_val in ["bulleted", "bullet point", "bullet points"]:
                style_val = "bullet points"
            cls.set_explicit_preference("preferred_response_style", style_val)
            return True, f"Understood. I've noted that you prefer {style_val} responses."

        # 4c. Language preference: Hinglish / English / Hindi / Spanish
        lang_match = re.search(r"\b(?:use|speak|talk|respond in|chat in|reply in)\s+(hinglish|hindi|english|spanish|french)\b", msg_lower)
        if lang_match and any(w in msg_lower for w in ["remember", "use", "speak", "talk", "talking", "when"]):
            lang_val = lang_match.group(1).title()
            cls.set_explicit_preference("preferred_language", lang_val)
            return True, f"Understood. I've set your preferred language to {lang_val}."

        # 4d. Units preference: Metric / Imperial / Celsius / Fahrenheit
        units_match = re.search(r"\b(?:prefer|use)\s+(metric|imperial|celsius|fahrenheit)\s+(?:units?|system)?\b", msg_lower)
        if units_match and any(w in msg_lower for w in ["remember", "prefer", "units"]):
            unit_val = units_match.group(1).title()
            cls.set_explicit_preference("preferred_units", unit_val)
            return True, f"Understood. I've noted that you prefer {unit_val} units."

        return False, None

preference_manager = PreferenceManager()
