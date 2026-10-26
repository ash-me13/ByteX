"""
SMART LIFE persistence (SQLite, stdlib only).

* Tables are created with CREATE TABLE IF NOT EXISTS and a schema_version row; existing ByteX tables are never
  touched, dropped or recreated. The default database is the existing ``bytex_memory.db`` (additive tables only).
* Every mutation runs in one transaction. Creates are idempotent: the same logical request (same kind, title,
  due time, recurrence) returns the existing active item instead of inserting a duplicate.
* "overdue" is derived (pending and due before now), never stored, so it cannot go stale.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from smartlife import recurrence as rec

SCHEMA_VERSION = 1
KINDS = ("reminder", "task", "birthday", "event", "bill", "subscription", "trial_end", "document_expiry", "assignment", "exam")
STATUSES = ("pending", "completed", "cancelled")
PAYMENT_STATUSES = ("unpaid", "paid", "autopay")
MAX_TITLE = 200
MAX_TEXT = 4000
MAX_LEAD_MINUTES = 60 * 24 * 366 * 2

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "bytex_memory.db"


class ValidationError(ValueError):
    """The request is invalid; the message is safe to show the user."""


class NotFound(LookupError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _clean_text(value: Any, field: str, limit: int, required: bool = False) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"{field.capitalize()} is required.")
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field.capitalize()} must be text.")
    text = " ".join(value.split()) if field == "title" else value.strip()
    if len(text) > limit:
        raise ValidationError(f"{field.capitalize()} is too long (max {limit} characters).")
    return text


def _norm_title(title: str) -> str:
    return " ".join(title.lower().split())


def make_idempotency_key(kind: str, title: str, due_at: Optional[str], rule: Optional[Dict[str, Any]]) -> str:
    blob = json.dumps([kind, _norm_title(title), due_at, rule], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SmartLifeStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._init_schema()

    # ---- connection / schema -------------------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        conn = self.connect()
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS sl_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sl_items (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        category TEXT,
                        due_at TEXT,
                        tz TEXT NOT NULL,
                        all_day INTEGER NOT NULL DEFAULT 0,
                        lead_minutes INTEGER NOT NULL DEFAULT 0,
                        recurrence_json TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        amount REAL,
                        currency TEXT,
                        payment_status TEXT,
                        estimated_minutes INTEGER,
                        priority INTEGER NOT NULL DEFAULT 2,
                        source_json TEXT,
                        parent_id TEXT REFERENCES sl_items(id) ON DELETE SET NULL,
                        idempotency_key TEXT,
                        completed_count INTEGER NOT NULL DEFAULT 0,
                        last_completed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT,
                        cancelled_at TEXT
                    )""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_items_due ON sl_items(status, due_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_items_kind ON sl_items(kind, status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_items_parent ON sl_items(parent_id)")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sl_items_active_key ON sl_items(idempotency_key) "
                             "WHERE status = 'pending' AND idempotency_key IS NOT NULL")
                conn.execute("INSERT OR IGNORE INTO sl_meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        finally:
            conn.close()

    # ---- settings -------------------------------------------------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        conn = self.connect()
        try:
            row = conn.execute("SELECT value FROM sl_meta WHERE key = ?", (f"setting:{key}",)).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        conn = self.connect()
        try:
            with conn:
                conn.execute("INSERT INTO sl_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (f"setting:{key}", str(value)))
        finally:
            conn.close()

    # ---- validation -----------------------------------------------------------------------------------------
    def _validate_fields(self, f: Dict[str, Any], *, creating: bool) -> Dict[str, Any]:
        try:
            return self._validate_fields_inner(f, creating=creating)
        except rec.RecurrenceError as exc:  # bad time zone / timestamp / rule: a user-safe message, not an internal error
            raise ValidationError(str(exc))

    def _validate_fields_inner(self, f: Dict[str, Any], *, creating: bool) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if creating or "kind" in f:
            kind = str(f.get("kind", "")).strip().lower()
            if kind not in KINDS:
                raise ValidationError(f"Item type must be one of: {', '.join(KINDS)}.")
            out["kind"] = kind
        if creating or "title" in f:
            out["title"] = _clean_text(f.get("title"), "title", MAX_TITLE, required=True)
        if "description" in f:
            out["description"] = _clean_text(f.get("description"), "description", MAX_TEXT)
        if "category" in f:
            out["category"] = _clean_text(f.get("category"), "category", 40)
        if "tz" in f or creating:
            tz = str(f.get("tz") or "").strip()
            if not tz:
                raise ValidationError("A time zone is required.")
            rec.get_zone(tz)
            out["tz"] = tz
        if "due_at" in f:
            due = f.get("due_at")
            if due is None:
                out["due_at"] = None
            else:
                rec.from_utc_iso(str(due))
                out["due_at"] = str(due)
        if "all_day" in f:
            out["all_day"] = 1 if f.get("all_day") else 0
        if "lead_minutes" in f:
            try:
                lead = int(f.get("lead_minutes") or 0)
            except (TypeError, ValueError):
                raise ValidationError("Reminder lead time must be a whole number of minutes.")
            if not 0 <= lead <= MAX_LEAD_MINUTES:
                raise ValidationError("Reminder lead time is out of range.")
            out["lead_minutes"] = lead
        if "recurrence" in f:
            try:
                out["recurrence_json"] = json.dumps(rec.validate_rule(f.get("recurrence")), sort_keys=True) if f.get("recurrence") else None
            except rec.RecurrenceError as exc:
                raise ValidationError(str(exc))
        if "amount" in f:
            amount = f.get("amount")
            if amount is None:
                out["amount"] = None
            else:
                try:
                    out["amount"] = float(amount)
                except (TypeError, ValueError):
                    raise ValidationError("Amount must be a number.")
                if out["amount"] < 0 or out["amount"] > 1e12:
                    raise ValidationError("Amount is out of range.")
        if "currency" in f:
            cur = _clean_text(f.get("currency"), "currency", 8)
            out["currency"] = cur.upper() if cur else None
        if "payment_status" in f:
            ps = f.get("payment_status")
            if ps is not None and ps not in PAYMENT_STATUSES:
                raise ValidationError(f"Payment status must be one of: {', '.join(PAYMENT_STATUSES)}.")
            out["payment_status"] = ps
        if "estimated_minutes" in f:
            em = f.get("estimated_minutes")
            if em is not None:
                try:
                    em = int(em)
                except (TypeError, ValueError):
                    raise ValidationError("Estimated time must be a whole number of minutes.")
                if not 1 <= em <= 24 * 60:
                    raise ValidationError("Estimated time must be between 1 minute and 24 hours.")
            out["estimated_minutes"] = em
        if "priority" in f:
            try:
                pr = int(f.get("priority"))
            except (TypeError, ValueError):
                raise ValidationError("Priority must be 1 (high), 2 (normal) or 3 (low).")
            if pr not in (1, 2, 3):
                raise ValidationError("Priority must be 1 (high), 2 (normal) or 3 (low).")
            out["priority"] = pr
        if "source" in f:
            src = f.get("source")
            out["source_json"] = json.dumps(src, sort_keys=True)[:MAX_TEXT] if src else None
        if "parent_id" in f:
            out["parent_id"] = f.get("parent_id") or None
        return out

    # ---- helpers --------------------------------------------------------------------------------------------
    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["recurrence"] = json.loads(item.pop("recurrence_json")) if item.get("recurrence_json") else None
        item["source"] = json.loads(item.pop("source_json")) if item.get("source_json") else None
        item["all_day"] = bool(item["all_day"])
        return item

    def _fetch(self, conn: sqlite3.Connection, item_id: str) -> Dict[str, Any]:
        row = conn.execute("SELECT * FROM sl_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise NotFound("No item with that id.")
        return self._row_to_item(row)

    @staticmethod
    def is_overdue(item: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        if item["status"] != "pending" or not item.get("due_at"):
            return False
        return rec.from_utc_iso(item["due_at"]) < (now or utc_now())

    # ---- operations -----------------------------------------------------------------------------------------
    def create_item(self, fields: Dict[str, Any], idempotency_key: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
        """Returns (item, created). created is False when an identical active item already existed."""
        clean = self._validate_fields(fields, creating=True)
        rule = json.loads(clean["recurrence_json"]) if clean.get("recurrence_json") else None
        if rule is not None and not clean.get("due_at"):
            raise ValidationError("A recurring item needs a first due date.")
        if rule is not None:
            zone = rec.get_zone(clean["tz"])
            local = rec.from_utc_iso(clean["due_at"]).astimezone(zone)
            rule.setdefault("anchor", local.date().isoformat())
            rule.setdefault("anchor_time", local.strftime("%H:%M"))
            clean["recurrence_json"] = json.dumps(rec.validate_rule(rule), sort_keys=True)
        key = idempotency_key or make_idempotency_key(clean["kind"], clean["title"], clean.get("due_at"), rule)
        now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT * FROM sl_items WHERE idempotency_key = ? AND status = 'pending'", (key,)).fetchone()
                if existing:
                    return self._row_to_item(existing), False
                if clean.get("parent_id"):
                    self._fetch(conn, clean["parent_id"])
                item_id = uuid.uuid4().hex
                row = {
                    "id": item_id, "description": None, "category": None, "due_at": None, "all_day": 0, "lead_minutes": 0,
                    "recurrence_json": None, "amount": None, "currency": None, "payment_status": None,
                    "estimated_minutes": None, "priority": 2, "source_json": None, "parent_id": None,
                    **clean, "idempotency_key": key, "created_at": now, "updated_at": now, "status": "pending",
                }
                cols = list(row)
                conn.execute(f"INSERT INTO sl_items ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
                return self._fetch(conn, item_id), True
        finally:
            conn.close()

    def get_item(self, item_id: str) -> Dict[str, Any]:
        conn = self.connect()
        try:
            return self._fetch(conn, item_id)
        finally:
            conn.close()

    UPDATABLE = {"title", "description", "category", "due_at", "all_day", "lead_minutes", "recurrence", "amount", "currency",
                 "payment_status", "estimated_minutes", "priority", "tz"}

    def update_item(self, item_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        bad = set(changes) - self.UPDATABLE
        if bad:
            raise ValidationError(f"These fields cannot be changed: {', '.join(sorted(bad))}.")
        if not changes:
            raise ValidationError("Nothing to change.")
        conn = self.connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                item = self._fetch(conn, item_id)
                if item["status"] != "pending":
                    raise ValidationError(f"That item is {item['status']} and can no longer be changed.")
                clean = self._validate_fields({**changes}, creating=False)
                new_due = clean.get("due_at", item["due_at"])
                new_tz = clean.get("tz", item["tz"])
                rule = json.loads(clean["recurrence_json"]) if clean.get("recurrence_json") else (None if "recurrence_json" in clean else item["recurrence"])
                if rule is not None and not new_due:
                    raise ValidationError("A recurring item needs a due date.")
                if rule is not None and ("due_at" in clean or "tz" in clean or "recurrence_json" in clean):
                    local = rec.from_utc_iso(new_due).astimezone(rec.get_zone(new_tz))
                    rule = {k: v for k, v in rule.items() if k not in ("anchor", "anchor_time")} if ("due_at" in clean or "tz" in clean) else rule
                    rule.setdefault("anchor", local.date().isoformat())
                    rule.setdefault("anchor_time", local.strftime("%H:%M"))
                    clean["recurrence_json"] = json.dumps(rec.validate_rule(rule), sort_keys=True)
                title = clean.get("title", item["title"])
                clean["idempotency_key"] = make_idempotency_key(item["kind"], title, new_due, rule)
                clash = conn.execute("SELECT id FROM sl_items WHERE idempotency_key = ? AND status = 'pending' AND id != ?",
                                     (clean["idempotency_key"], item_id)).fetchone()
                if clash:
                    raise ValidationError("An identical active item already exists.")
                clean["updated_at"] = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
                sets = ", ".join(f"{c} = ?" for c in clean)
                conn.execute(f"UPDATE sl_items SET {sets} WHERE id = ?", [*clean.values(), item_id])
                return self._fetch(conn, item_id)
        finally:
            conn.close()

    def complete_item(self, item_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        """One-off items become completed. Recurring items advance to their next occurrence and stay pending."""
        now = now or utc_now()
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                item = self._fetch(conn, item_id)
                if item["status"] != "pending":
                    raise ValidationError(f"That item is already {item['status']}.")
                if item["recurrence"] and item["due_at"]:
                    try:
                        nxt = rec.next_occurrence(item["recurrence"], item["tz"], rec.from_utc_iso(item["due_at"]), after_utc=now)
                    except rec.RecurrenceError as exc:
                        raise ValidationError(str(exc))
                    if nxt is not None:
                        new_due = rec.to_utc_iso(nxt)
                        key = make_idempotency_key(item["kind"], item["title"], new_due, item["recurrence"])
                        conn.execute("UPDATE sl_items SET due_at=?, idempotency_key=?, completed_count=completed_count+1, "
                                     "last_completed_at=?, updated_at=? WHERE id=?", (new_due, key, stamp, stamp, item_id))
                        return self._fetch(conn, item_id)
                conn.execute("UPDATE sl_items SET status='completed', completed_at=?, last_completed_at=?, "
                             "completed_count=completed_count+1, updated_at=? WHERE id=?", (stamp, stamp, stamp, item_id))
                return self._fetch(conn, item_id)
        finally:
            conn.close()

    def cancel_item(self, item_id: str) -> Dict[str, Any]:
        stamp = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                item = self._fetch(conn, item_id)
                if item["status"] == "cancelled":
                    return item
                if item["status"] == "completed":
                    raise ValidationError("That item is already completed.")
                conn.execute("UPDATE sl_items SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=?", (stamp, stamp, item_id))
                return self._fetch(conn, item_id)
        finally:
            conn.close()

    def delete_item(self, item_id: str) -> None:
        """Permanent removal of one item (callers must have obtained user approval first)."""
        conn = self.connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                self._fetch(conn, item_id)
                conn.execute("DELETE FROM sl_items WHERE id = ?", (item_id,))
        finally:
            conn.close()

    def list_items(self, *, status: Optional[str] = "pending", kind: Optional[str] = None, kinds: Optional[List[str]] = None,
                   due_from: Optional[str] = None, due_to: Optional[str] = None, query: Optional[str] = None,
                   overdue_only: bool = False, limit: int = 100, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise ValidationError(f"Status must be one of: {', '.join(STATUSES)}.")
        clauses, params = [], []
        if status:
            clauses.append("status = ?"); params.append(status)
        if kind:
            clauses.append("kind = ?"); params.append(kind)
        if kinds:
            clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})"); params.extend(kinds)
        if due_from:
            clauses.append("due_at >= ?"); params.append(due_from)
        if due_to:
            clauses.append("due_at <= ?"); params.append(due_to)
        if query:
            escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = f"%{escaped}%"  # wildcards typed by the user are matched literally
            clauses.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(coalesce(description,'')) LIKE ? ESCAPE '\\')"); params.extend([q, q])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = max(1, min(int(limit), 500))
        conn = self.connect()
        try:
            rows = conn.execute(f"SELECT * FROM sl_items {where} ORDER BY due_at IS NULL, due_at, created_at LIMIT ?", [*params, limit]).fetchall()
        finally:
            conn.close()
        items = [self._row_to_item(r) for r in rows]
        if overdue_only:
            items = [i for i in items if self.is_overdue(i, now)]
        return items

    def counts(self) -> Dict[str, int]:
        conn = self.connect()
        try:
            return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM sl_items GROUP BY status")}
        finally:
            conn.close()
