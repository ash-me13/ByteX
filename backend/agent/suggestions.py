import sys
import time
import re
import uuid
import logging
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field
from core.session import session_manager
from memory.models import is_sensitive_content

logger = logging.getLogger("bytex.agent.suggestions")

class SuggestionCandidate(BaseModel):
    id: str = Field(default_factory=lambda: f"sug_{uuid.uuid4().hex[:10]}")
    suggestion_type: str = "general"  # "bytex_dev" | "search_summary" | "save_document" | "repeat_action"
    title: str
    description: str
    action_type: str = "COMMAND"  # "COMMAND" | "AGENT_WORKFLOW" | "SKILL"
    command: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.85
    reason: str = ""
    risk_level: str = "low"  # "low" | "medium" | "high"
    target_app: Optional[str] = None
    target_hwnd: Optional[int] = None
    target_file: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 60.0)
    status: str = "active"  # "active" | "accepted" | "dismissed" | "expired"

# Disallowed destructive actions for proactive suggestions
DISALLOWED_PROACTIVE_KEYWORDS = {
    "delete", "remove", "erase", "format", "rmdir", "del", "kill", "taskkill",
    "shutdown", "restart", "reboot", "wipe", "pay", "transfer", "buy", "send email",
    "send message", "call", "post", "password", "token", "key"
}

class SuggestionFrequency(str):
    MINIMAL = "minimal"      # Threshold count >= 5, confidence >= 0.90
    BALANCED = "balanced"    # Threshold count >= 3, confidence >= 0.80
    FREQUENT = "frequent"    # Threshold count >= 2, confidence >= 0.70

class SuggestionEngine:
    """
    Feature #27: Proactive Suggestion Engine.
    
    Observes context, recent actions, and repeated workflows to generate low-risk,
    high-confidence suggestions.
    
    Security & Structural Invariants:
    1. PROACTIVE = Suggest -> Wait for User Confirmation -> Execute (NEVER silent execution).
    2. Zero Destructive Operations: Excludes deletion, system termination, financials, and credentials.
    3. Revalidation: Validates HWND, process, and file targets before executing an accepted suggestion.
    4. Anti-Spam: Single active suggestion at a time, rejection cooldown, expiration TTL.
    5. Settings Control: Can be toggled ON/OFF with configurable frequency.
    """

    DEFAULT_REJECTION_COOLDOWN: float = 1800.0  # 30 minutes

    def __init__(self):
        self.is_enabled: bool = True
        self.frequency: str = SuggestionFrequency.BALANCED
        self._active_suggestion: Optional[SuggestionCandidate] = None
        self._cooldowns: Dict[str, float] = {}  # suggestion_type / command -> cooldown_until
        self._workflow_counts: Dict[str, int] = {}  # workflow_key -> count

    def set_enabled(self, enabled: bool):
        self.is_enabled = enabled
        if not enabled:
            self._active_suggestion = None
        print(f"[ByteX SuggestionEngine] Proactive suggestions set to: {'ENABLED' if enabled else 'DISABLED'}")

    def set_frequency(self, freq: str):
        if freq in [SuggestionFrequency.MINIMAL, SuggestionFrequency.BALANCED, SuggestionFrequency.FREQUENT]:
            self.frequency = freq
            print(f"[ByteX SuggestionEngine] Suggestion frequency set to: {freq}")

    def get_active_suggestion(self) -> Optional[SuggestionCandidate]:
        """Returns active suggestion if not expired."""
        if not self.is_enabled:
            return None
        if self._active_suggestion:
            if time.time() > self._active_suggestion.expires_at or self._active_suggestion.status != "active":
                self._active_suggestion = None
        return self._active_suggestion

    def clear(self):
        """Clears active suggestion and workflow counts for testing."""
        self._active_suggestion = None
        self._cooldowns.clear()
        self._workflow_counts.clear()
        print("[ByteX SuggestionEngine] Reset suggestion state.")

    def is_on_cooldown(self, key: str) -> bool:
        until = self._cooldowns.get(key.lower(), 0.0)
        return time.time() < until

    def record_dismissal(self, suggestion_id: str, cooldown_seconds: float = DEFAULT_REJECTION_COOLDOWN):
        """Marks active suggestion dismissed and sets cooldown."""
        if self._active_suggestion and self._active_suggestion.id == suggestion_id:
            self._active_suggestion.status = "dismissed"
            type_key = self._active_suggestion.suggestion_type.lower()
            cmd_key = self._active_suggestion.command.lower()
            cooldown_time = time.time() + cooldown_seconds
            self._cooldowns[type_key] = cooldown_time
            self._cooldowns[cmd_key] = cooldown_time
            print(f"[ByteX SuggestionEngine] Suggestion '{suggestion_id}' ({type_key} / {cmd_key}) DISMISSED. Cooldown active for {cooldown_seconds}s.")
            self._active_suggestion = None

    def record_acceptance(self, suggestion_id: str):
        """Marks active suggestion accepted."""
        if self._active_suggestion and self._active_suggestion.id == suggestion_id:
            self._active_suggestion.status = "accepted"
            print(f"[ByteX SuggestionEngine] Suggestion '{suggestion_id}' ACCEPTED by user.")
            self._active_suggestion = None

    def is_safe_action(self, text: str) -> bool:
        """Verifies an action is completely free of destructive keywords or sensitive content."""
        clean = text.lower()
        if is_sensitive_content(clean):
            return False
        for kw in DISALLOWED_PROACTIVE_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", clean):
                return False
        return True

    def evaluate_triggers(self, last_action: str, target: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Optional[SuggestionCandidate]:
        """
        Evaluates context triggers (e.g., search completed, project opened, document opened/edited, workflow repeated)
        and generates a single high-confidence suggestion candidate.
        """
        if not self.is_enabled:
            return None

        now = time.time()
        act_clean = last_action.strip().lower()
        tgt_clean = (target or "").strip().lower()

        # 1. Project Development Workflow (e.g. "Open VS Code" -> "Open ByteX" / "ByteX Project")
        if "bytex" in tgt_clean or "bytex" in act_clean:
            wf_key = "wf_bytex_dev"
            self._workflow_counts[wf_key] = self._workflow_counts.get(wf_key, 0) + 1
            count = self._workflow_counts[wf_key]
            
            threshold = 3 if self.frequency == SuggestionFrequency.BALANCED else (5 if self.frequency == SuggestionFrequency.MINIMAL else 2)
            if count >= threshold and not self.is_on_cooldown("bytex_dev") and not self.is_on_cooldown("start backend and frontend servers"):
                cand = SuggestionCandidate(
                    suggestion_type="bytex_dev",
                    title="Start Development Environment",
                    description="You opened the ByteX project. Want me to start the backend and frontend servers?",
                    action_type="COMMAND",
                    command="Start backend and frontend servers",
                    arguments={"project": "ByteX", "action": "start_dev_environment"},
                    confidence=0.88,
                    reason=f"Repeated ByteX development workflow ({count} occurrences)",
                    target_app="VS Code"
                )
                self._active_suggestion = cand
                return cand

        # 2. Search Results Follow-up (e.g. "Search for C++ tutorials" / "Search for...")
        if any(act_clean.startswith(p) for p in ["search", "web_search", "google"]) or "tutorials" in tgt_clean:
            if not self.is_on_cooldown("search_summary") and not self.is_on_cooldown(f"summarize the search results for {tgt_clean or 'query'}"):
                cand = SuggestionCandidate(
                    suggestion_type="search_summary",
                    title="Summarize Search Results",
                    description=f"You just searched for {target or 'topics'}. Want me to summarize the key results?",
                    action_type="COMMAND",
                    command=f"Summarize the search results for {target or 'query'}",
                    arguments={"query": target},
                    confidence=0.82,
                    reason="Contextual follow-up to completed search"
                )
                self._active_suggestion = cand
                return cand

        # 3. Document / Notepad Editing Follow-up (e.g. typed into Notepad -> suggest save)
        if ("notepad" in tgt_clean or "document" in tgt_clean) and ("type" in act_clean or "write" in act_clean):
            if not self.is_on_cooldown("save_document") and not self.is_on_cooldown("save this document"):
                active_ctx = session_manager.get_working_context()
                target_hwnd = None
                if active_ctx and isinstance(active_ctx, dict):
                    win = active_ctx.get("active_window") or active_ctx.get("active_application")
                    if isinstance(win, dict):
                        target_hwnd = win.get("hwnd")

                cand = SuggestionCandidate(
                    suggestion_type="save_document",
                    title="Save Document",
                    description="You've finished typing in Notepad. Want me to save this document?",
                    action_type="COMMAND",
                    command="Save this document",
                    arguments={"target": "Notepad"},
                    confidence=0.85,
                    reason="Active document editing completed",
                    target_app="Notepad",
                    target_hwnd=target_hwnd
                )
                self._active_suggestion = cand
                return cand

        # 4. Repeated Generic Low-Risk Workflow Detection (3+ occurrences)
        if self.is_safe_action(act_clean):
            wf_key = f"wf_{act_clean}_{tgt_clean}"
            self._workflow_counts[wf_key] = self._workflow_counts.get(wf_key, 0) + 1
            count = self._workflow_counts[wf_key]

            threshold = 3 if self.frequency == SuggestionFrequency.BALANCED else (5 if self.frequency == SuggestionFrequency.MINIMAL else 2)
            if count >= threshold and not self.is_on_cooldown("repeat_action") and not self.is_on_cooldown(act_clean):
                cand = SuggestionCandidate(
                    suggestion_type="repeat_action",
                    title="Repeat Frequent Action",
                    description=f"You frequently perform '{last_action}'. Want me to run this workflow?",
                    action_type="COMMAND",
                    command=last_action,
                    arguments={"target": target},
                    confidence=min(0.95, 0.70 + count * 0.05),
                    reason=f"Repeated workflow pattern observed ({count} times)"
                )
                self._active_suggestion = cand
                return cand

        return None

    def validate_suggestion_context(self, candidate: SuggestionCandidate) -> Tuple[bool, str]:
        """
        Validates target HWND, application process, and files before executing an accepted suggestion.
        Returns (is_valid, reason_if_invalid).
        """
        # 1. Target HWND Check (Windows only)
        if candidate.target_hwnd and sys.platform == "win32":
            import ctypes
            if hasattr(ctypes, "windll"):
                user32 = ctypes.windll.user32
                if not user32.IsWindow(candidate.target_hwnd):
                    return False, f"The target window (HWND {candidate.target_hwnd}) is no longer open."

        # 2. Target File Check
        if candidate.target_file:
            import os
            if not os.path.exists(candidate.target_file):
                return False, f"The target file '{candidate.target_file}' no longer exists."

        # 3. Target Application Check
        if candidate.target_app:
            import psutil
            app_low = candidate.target_app.lower()
            if app_low in ["notepad", "word", "excel"]:
                is_running = any(app_low in (p.name() or "").lower() for p in psutil.process_iter(["name"]))
                if not is_running:
                    return False, f"{candidate.target_app} is no longer running."

        return True, "Context verified."

suggestion_engine = SuggestionEngine()
