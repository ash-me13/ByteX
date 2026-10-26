import time
import re
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field
from memory.models import is_sensitive_content, MemoryCategory
from memory.manager import memory_manager
from memory.preferences import preference_manager

class PreferenceCandidate(BaseModel):
    key: str
    category: str
    candidate_value: str
    display_name: str
    evidence_count: int = 1
    confidence: float = 0.35
    first_seen: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
    status: str = "observing"  # "observing" (count=1), "candidate" (count=2), "ready_to_ask" (count>=3), "asked", "confirmed", "rejected"
    cooldown_until: float = 0.0

# Pattern definitions for low-risk, high-utility preference learning
LEARNING_RULES = [
    # 1. Response Style - Concise
    {
        "key": "response_style",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "concise",
        "display_name": "concise answers",
        "patterns": [
            r"\b(?:make\s+it\s+shorter|give\s+me\s+a\s+concise\s+version|just\s+give\s+me\s+the\s+important\s+parts|keep\s+it\s+brief|summarize\s+in\s+short|be\s+brief|short\s+version|concise\s+please|shorter\s+answers?|brief\s+answers?|keep\s+it\s+concise)\b",
            r"^(?:concise|brief|short|shorten\s+this|make\s+shorter)[.!?]*$"
        ]
    },
    # 2. Response Style - Detailed
    {
        "key": "response_style",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "detailed",
        "display_name": "detailed explanations",
        "patterns": [
            r"\b(?:give\s+more\s+details|explain\s+deeply|give\s+me\s+a\s+detailed\s+explanation|go\s+in-depth|explain\s+thoroughly|detailed\s+version|more\s+details\s+please|in-depth\s+explanation|deep\s+dive)\b",
            r"^(?:detailed|more\s+details|explain\s+in\s+detail)[.!?]*$"
        ]
    },
    # 3. Response Style - Bullet Points
    {
        "key": "response_style",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "bullet_points",
        "display_name": "bullet point responses",
        "patterns": [
            r"\b(?:in\s+bullet\s+points|give\s+bullets|use\s+bullet\s+points|bullet\s+points\s+please|as\s+a\s+bulleted\s+list)\b"
        ]
    },
    # 4. Programming Language - C++
    {
        "key": "preferred_programming_language",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "C++",
        "display_name": "C++ as your preferred programming language",
        "patterns": [
            r"(?:^|\b|\s)(?:give\s+me\s+the\s+c\+\+\s+solution|c\+\+\s+please|use\s+c\+\+|write\s+this\s+in\s+c\+\+|in\s+c\+\+|using\s+c\+\+|for\s+dsa\s+in\s+c\+\+|solution\s+in\s+c\+\+)(?:$|\s|[.!?])",
            r"^(?:c\+\+|cpp|in\s+c\+\+|use\s+c\+\+)[.!?]*$"
        ]
    },
    # 5. Programming Language - Python
    {
        "key": "preferred_programming_language",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "Python",
        "display_name": "Python as your preferred programming language",
        "patterns": [
            r"\b(?:give\s+me\s+the\s+python\s+solution|python\s+please|use\s+python|write\s+this\s+in\s+python|in\s+python|using\s+python|solution\s+in\s+python)\b",
            r"^(?:python|in\s+python)[.!?]*$"
        ]
    },
    # 6. Programming Language - Rust
    {
        "key": "preferred_programming_language",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "Rust",
        "display_name": "Rust as your preferred programming language",
        "patterns": [
            r"\b(?:give\s+me\s+the\s+rust\s+solution|rust\s+please|use\s+rust|write\s+this\s+in\s+rust|in\s+rust|using\s+rust)\b"
        ]
    },
    # 7. Browser - Edge
    {
        "key": "preferred_browser",
        "category": MemoryCategory.APPLICATION_PREFERENCE.value,
        "value": "Edge",
        "display_name": "Microsoft Edge as your preferred browser",
        "patterns": [
            r"\b(?:open\s+this\s+in\s+edge|use\s+edge|search\s+in\s+edge|in\s+edge|using\s+edge)\b"
        ]
    },
    # 8. Browser - Chrome
    {
        "key": "preferred_browser",
        "category": MemoryCategory.APPLICATION_PREFERENCE.value,
        "value": "Chrome",
        "display_name": "Google Chrome as your preferred browser",
        "patterns": [
            r"\b(?:open\s+this\s+in\s+chrome|use\s+chrome|search\s+in\s+chrome|in\s+chrome|using\s+chrome)\b"
        ]
    },
    # 9. Theme - Dark
    {
        "key": "theme",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "dark",
        "display_name": "dark theme",
        "patterns": [
            r"\b(?:switch\s+to\s+dark\s+mode|dark\s+theme\s+please|use\s+dark\s+mode|dark\s+mode\s+please)\b"
        ]
    },
    # 10. Theme - Light
    {
        "key": "theme",
        "category": MemoryCategory.USER_PREFERENCE.value,
        "value": "light",
        "display_name": "light theme",
        "patterns": [
            r"\b(?:switch\s+to\s+light\s+mode|light\s+theme\s+please|use\s+light\s+mode|light\s+mode\s+please)\b"
        ]
    }
]

DEFAULT_COOLDOWN_SECONDS = 3600.0  # 1 hour cooldown upon user rejection

class PreferenceLearner:
    """
    Feature #26: Learning User Preferences Engine.
    
    Observes natural repeated user behaviors, tracks lightweight evidence candidates,
    calculates confidence thresholds, and prompts the user for confirmation BEFORE
    persisting into the Feature #25 Long-Term Memory SQLite database.
    
    Security & Structural Invariants:
    1. Observe -> Detect Pattern -> Confidence -> Ask User -> Save.
    2. NEVER automatically persist unconfirmed inferred attributes into SQLite memory.
    3. Low-risk preferences only (response length, coding language, browser, theme, editor).
    4. Sensitive content (passwords, tokens, credentials, private info) is strictly excluded.
    5. Direct writes to SQLite MUST ONLY occur via the Feature #25 memory manager upon confirmation.
    6. Explicit user instructions ALWAYS override learned preferences.
    7. Negative feedback puts candidate on cooldown to prevent repeated nagging.
    8. Learning can be enabled/disabled via Settings.
    """

    def __init__(self):
        self.is_enabled: bool = True
        self._candidates: Dict[str, PreferenceCandidate] = {}  # key -> Candidate

    def set_enabled(self, enabled: bool):
        """Enables or disables automatic preference learning."""
        self.is_enabled = enabled
        print(f"[ByteX PreferenceLearner] Preference learning set to: {'ENABLED' if enabled else 'DISABLED'}")

    def get_candidate(self, key: str) -> Optional[PreferenceCandidate]:
        """Returns active candidate for a given key, if any."""
        return self._candidates.get(key)

    def get_all_candidates(self) -> List[PreferenceCandidate]:
        """Returns list of all active preference candidates."""
        return list(self._candidates.values())

    def clear_candidates(self):
        """Resets all in-memory candidate trackers."""
        self._candidates.clear()
        print("[ByteX PreferenceLearner] Cleared all candidate trackers.")

    def record_rejection(self, key: str, candidate_val: str, cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
        """Records user rejection, putting this preference candidate on cooldown."""
        candidate = self._candidates.get(key)
        if candidate and candidate.candidate_value == candidate_val:
            candidate.status = "rejected"
            candidate.cooldown_until = time.time() + cooldown_seconds
            print(f"[ByteX PreferenceLearner] Candidate '{key}={candidate_val}' REJECTED. Cooldown active for {cooldown_seconds}s.")

    def record_confirmation(self, key: str, candidate_val: str):
        """Records user confirmation, marking the candidate confirmed."""
        candidate = self._candidates.get(key)
        if candidate and candidate.candidate_value == candidate_val:
            candidate.status = "confirmed"
            print(f"[ByteX PreferenceLearner] Candidate '{key}={candidate_val}' CONFIRMED and marked saved.")

    def detect_rule_match(self, message: str) -> Optional[Dict[str, Any]]:
        """Matches user message against low-risk learning rule definitions."""
        msg_clean = message.strip().lower()
        for rule in LEARNING_RULES:
            for pat in rule["patterns"]:
                if re.search(pat, msg_clean, re.IGNORECASE):
                    return rule
        return None

    def observe_interaction(self, message: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Observes a user command/request.
        If sufficient repeated evidence is reached (3+ occurrences) and not on cooldown,
        returns (confirmation_prompt, confirmation_arguments) to ask the user.
        Otherwise returns None.
        """
        if not self.is_enabled:
            return None

        # Privacy Guard: Exclude any sensitive messages
        if is_sensitive_content(message):
            return None

        msg_lower = message.strip().lower()

        # Skip explicit memory commands (e.g. "Remember that...", "Forget...", "Clear all...")
        if any(msg_lower.startswith(p) for p in ["remember", "forget", "clear all", "clear memories", "what do you remember"]):
            return None

        matched_rule = self.detect_rule_match(message)
        if not matched_rule:
            return None

        key = matched_rule["key"]
        category = matched_rule["category"]
        cand_val = matched_rule["value"]
        display_name = matched_rule["display_name"]
        now = time.time()

        # Check existing candidate
        candidate = self._candidates.get(key)

        # Check cooldown
        if candidate and candidate.cooldown_until > now:
            print(f"[ByteX PreferenceLearner] Preference '{key}' on cooldown ({int(candidate.cooldown_until - now)}s remaining). Skipping.")
            return None

        # Check if this exact preference is ALREADY saved in #25 Long-Term Memory SQLite
        all_saved_mems = memory_manager.get_all_memories()
        existing_mem = next((m for m in all_saved_mems if m.key == key or (m.value and m.value.lower() == cand_val.lower())), None)
        
        is_update = False
        if existing_mem:
            if existing_mem.value and existing_mem.value.lower() == cand_val.lower():
                # Already saved with same value -> no need to ask again
                return None
            else:
                # User previously had a different preference -> potential preference change
                is_update = True

        if not candidate or candidate.candidate_value != cand_val:
            # First occurrence of this candidate
            candidate = PreferenceCandidate(
                key=key,
                category=category,
                candidate_value=cand_val,
                display_name=display_name,
                evidence_count=1,
                confidence=0.35,
                first_seen=now,
                last_seen=now,
                status="observing"
            )
            self._candidates[key] = candidate
            print(f"[ByteX PreferenceLearner] Observed pattern (Count: 1, Confidence: 0.35) -> '{key}' = '{cand_val}'")
            return None
        else:
            # Subsequent consistent occurrence
            candidate.evidence_count += 1
            candidate.last_seen = now
            candidate.confidence = min(0.95, round(0.35 + (candidate.evidence_count - 1) * 0.25, 2))
            
            if candidate.evidence_count == 2:
                candidate.status = "candidate"
                print(f"[ByteX PreferenceLearner] Candidate identified (Count: 2, Confidence: {candidate.confidence:.2f}) -> '{key}' = '{cand_val}'")
                return None
            
            elif candidate.evidence_count >= 3 and candidate.status not in ["asked", "confirmed"]:
                candidate.status = "asked"
                print(f"[ByteX PreferenceLearner] Threshold reached (Count: {candidate.evidence_count}, Confidence: {candidate.confidence:.2f}) -> Prompting user confirmation.")
                
                # Format natural confirmation prompt
                if is_update:
                    prompt_text = f"I've noticed you may now prefer {display_name}. Would you like me to update your preference?"
                elif key == "preferred_programming_language":
                    prompt_text = f"You frequently use {cand_val}. Would you like me to remember {cand_val} as your preferred programming language?"
                elif key == "preferred_browser":
                    prompt_text = f"I've noticed you frequently use {cand_val}. Would you like me to remember {cand_val} as your preferred browser?"
                else:
                    prompt_text = f"I've noticed you usually prefer {display_name}. Would you like me to remember this preference?"

                confirm_args = {
                    "key": key,
                    "value": cand_val,
                    "category": category,
                    "display_name": display_name,
                    "content": f"User prefers {display_name}." if "as your" not in display_name else f"User prefers {cand_val} for {key.replace('preferred_', '').replace('_', ' ')}."
                }
                return prompt_text, confirm_args

        return None

preference_learner = PreferenceLearner()
