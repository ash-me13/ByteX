"""
Confirmation records and approval grants.

Trust model
-----------
* A pending confirmation is created only by trusted application code (the command router, the assistant
  loop, the agent executor) after a tool asked for approval. It is stored per *conversation* (one per
  WebSocket connection), never in a single global slot.
* An approval is produced only by ``approve_pending`` / ``issue_user_approval``, which trusted code calls
  after a real user "yes" typed by the user. The result is an ``ApprovalGrant``: single use, bound to the
  conversation, the tool name and a fingerprint of the exact arguments, and time limited.
* ``SkillRegistry.execute_tool`` accepts a grant and verifies it with ``verify_and_consume``. Nothing a
  model writes (tool arguments, assistant text, plan fields) can create or carry a valid grant.

Honest limit: this protects against model output, plans, other connections and replays. Code running
inside the backend process (or any process that can already drive the API as the user) is out of scope.
"""

import contextvars
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel

CONFIRMATION_TTL_SECONDS = 300
GRANT_TTL_SECONDS = 60

# Arguments that claim "a human already approved this". Never trusted from callers.
CONFIRMATION_FLAGS = ("confirmed", "user_confirmed", "skip_confirmation", "auto_confirm", "force_confirm")

_current_conversation: "contextvars.ContextVar[str]" = contextvars.ContextVar("bytex_conversation_id", default="default")
_PROCESS_KEY = secrets.token_bytes(32)


def get_conversation_id() -> str:
    return _current_conversation.get()


def set_conversation_id(conversation_id: str):
    """Bind the current async context (e.g. one WebSocket handler) to a conversation. Returns a reset token."""
    return _current_conversation.set(conversation_id)


def reset_conversation_id(token) -> None:
    _current_conversation.reset(token)


def operation_fingerprint(tool: str, arguments: Optional[Dict[str, Any]]) -> str:
    """Stable hash of the operation. Confirmation flags are excluded so they can never change the identity."""
    clean = {k: v for k, v in (arguments or {}).items() if k not in CONFIRMATION_FLAGS}
    blob = json.dumps({"tool": tool, "args": clean}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class PendingConfirmation(BaseModel):
    tool: str
    action: str
    description: str
    arguments: Dict[str, Any]
    created_at: float
    request_id: str = ""
    conversation_id: str = "default"
    fingerprint: str = ""
    expires_at: float = 0.0
    state: str = "pending"  # pending -> approved (consumed into a grant) | rejected | expired


class ApprovalGrant:
    """Single-use proof that a user approved one exact operation in one conversation."""

    __slots__ = ("request_id", "conversation_id", "tool", "fingerprint", "expires_at", "_sig", "_consumed")

    def __init__(self, request_id, conversation_id, tool, fingerprint, expires_at, sig):
        self.request_id = request_id
        self.conversation_id = conversation_id
        self.tool = tool
        self.fingerprint = fingerprint
        self.expires_at = expires_at
        self._sig = sig
        self._consumed = False

    def __repr__(self) -> str:  # never print the signature
        return f"<ApprovalGrant request={self.request_id[:8]} tool={self.tool}>"


def _sign(request_id: str, conversation_id: str, tool: str, fingerprint: str, expires_at: float) -> str:
    msg = f"{request_id}|{conversation_id}|{tool}|{fingerprint}|{expires_at!r}".encode("utf-8")
    return hmac.new(_PROCESS_KEY, msg, hashlib.sha256).hexdigest()


class ConfirmationManager:
    """Pending confirmations per conversation, plus issuance/verification of approval grants."""

    _instance: Optional["ConfirmationManager"] = None

    CONFIRM_POSITIVE_PATTERN = r"^(?:yes|y|confirm|do\s+it|proceed|sure|okay|ok|approve|go\s+ahead|yes,?\s+(?:delete|do|proceed)\s+it|yes\s+please)$"
    CONFIRM_NEGATIVE_PATTERN = r"^(?:no|n|cancel|stop|abort|don\'?t\s+do\s+it|reject|deny|don\'?t\s+delete|no\s+don\'?t)$"

    def __init__(self, time_fn=time.time):
        self._time = time_fn
        self._pending_by_conversation: Dict[str, PendingConfirmation] = {}

    @classmethod
    def get_instance(cls) -> "ConfirmationManager":
        if cls._instance is None:
            cls._instance = ConfirmationManager()
        return cls._instance

    # ---- pending records (scoped to the current conversation) ------------------------------------
    def set_pending(self, tool: str, action: str, description: str, arguments: Dict[str, Any]) -> str:
        """Stores a pending action requiring user approval and returns the prompt text."""
        self.create_pending(tool, action, description, arguments)
        if action == "delete_file":
            return f"{description}\n\nPlease confirm: (Yes, delete it / No)"
        return f"[Confirmation Required]: {description}\nDo you want to proceed? (yes/no)"

    def create_pending(self, tool: str, action: str, description: str, arguments: Dict[str, Any]) -> PendingConfirmation:
        now = self._time()
        args = {k: v for k, v in (arguments or {}).items() if k not in CONFIRMATION_FLAGS}
        record = PendingConfirmation(
            tool=tool,
            action=action,
            description=description,
            arguments=args,
            created_at=now,
            request_id=uuid.uuid4().hex,
            conversation_id=get_conversation_id(),
            fingerprint=operation_fingerprint(tool, args),
            expires_at=now + CONFIRMATION_TTL_SECONDS,
        )
        self._pending_by_conversation[record.conversation_id] = record
        print(f"[ByteX Confirmation] Pending action stored: {action} (request {record.request_id[:8]})")
        return record

    def has_pending(self) -> bool:
        return self.get_pending() is not None

    def get_pending(self) -> Optional[PendingConfirmation]:
        cid = get_conversation_id()
        record = self._pending_by_conversation.get(cid)
        if record is None:
            return None
        if self._time() >= record.expires_at:
            print("[ByteX Confirmation] Pending action expired.")
            self._pending_by_conversation.pop(cid, None)
            return None
        return record

    def clear(self) -> None:
        record = self._pending_by_conversation.pop(get_conversation_id(), None)
        if record:
            print(f"[ByteX Confirmation] Cleared pending action: {record.action}")

    # ---- approval ---------------------------------------------------------------------------------
    def approve_pending(self, request_id: Optional[str] = None) -> Tuple[Optional[PendingConfirmation], Optional[ApprovalGrant]]:
        """
        Called by trusted code after a real user "yes". Removes the pending record of the CURRENT
        conversation (single use) and returns it with a grant bound to its exact operation.
        If request_id is given it must match. Returns (None, None) when nothing valid is pending.
        """
        record = self.get_pending()
        if record is None:
            return None, None
        if request_id is not None and request_id != record.request_id:
            return None, None
        if operation_fingerprint(record.tool, record.arguments) != record.fingerprint:
            self.clear()  # record was altered after creation
            return None, None
        self._pending_by_conversation.pop(record.conversation_id, None)
        record.state = "approved"
        return record, self._issue(record.request_id, record.conversation_id, record.tool, record.fingerprint)

    def issue_user_approval(self, tool: str, arguments: Dict[str, Any]) -> ApprovalGrant:
        """
        For trusted code that has just obtained a real user approval outside the pending-record flow
        (e.g. resuming a plan step the user approved). Bound to the current conversation.
        """
        return self._issue(uuid.uuid4().hex, get_conversation_id(), tool, operation_fingerprint(tool, arguments))

    def _issue(self, request_id: str, conversation_id: str, tool: str, fingerprint: str) -> ApprovalGrant:
        expires_at = self._time() + GRANT_TTL_SECONDS
        return ApprovalGrant(request_id, conversation_id, tool, fingerprint, expires_at,
                             _sign(request_id, conversation_id, tool, fingerprint, expires_at))

    def verify_and_consume(self, grant: Any, tool: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        """Registry-side check. Consumes the grant only when every condition holds."""
        if not isinstance(grant, ApprovalGrant):
            return False, "not an approval grant"
        if grant._consumed:
            return False, "approval already used"
        if not hmac.compare_digest(grant._sig, _sign(grant.request_id, grant.conversation_id, grant.tool, grant.fingerprint, grant.expires_at)):
            return False, "approval signature invalid"
        if self._time() >= grant.expires_at:
            return False, "approval expired"
        if grant.conversation_id != get_conversation_id():
            return False, "approval belongs to another conversation"
        if grant.tool != tool or grant.fingerprint != operation_fingerprint(tool, arguments):
            return False, "operation changed after approval"
        grant._consumed = True
        return True, "ok"

    # ---- user reply classification ------------------------------------------------------------------
    def evaluate_response(self, user_message: str) -> Optional[bool]:
        """True = user said yes, False = user said no, None = unrelated. Only call with USER text."""
        clean = user_message.strip().lower()
        clean = re.sub(r"[.!?,\"\']+$", "", clean).strip()
        if re.match(self.CONFIRM_POSITIVE_PATTERN, clean):
            return True
        elif re.match(self.CONFIRM_NEGATIVE_PATTERN, clean):
            return False
        return None


confirmation_manager = ConfirmationManager.get_instance()
