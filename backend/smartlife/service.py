"""
SMART LIFE actions: validation, human-readable previews and execution. Pure stdlib; no model/network access.

The model only ever *requests* an action with structured arguments. This module (trusted code):
  * validates every argument and resolves dates in the user's time zone,
  * returns a clarification question instead of guessing when something important is missing or ambiguous,
  * builds the exact preview text the user is asked to approve,
  * and refuses to change data unless the caller (the skill registry) passes ``confirmed=True`` after a verified
    user approval. ``confirmed`` is never read from model-supplied arguments (the registry strips it).
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from smartlife import recurrence as rec
from smartlife.store import KINDS, NotFound, SmartLifeStore, ValidationError, utc_now

READ_ACTIONS = ("list", "upcoming", "today", "search", "get", "overdue")
WRITE_ACTIONS = ("create", "update", "complete", "cancel", "delete")
ALL_ACTIONS = READ_ACTIONS + WRITE_ACTIONS
ALL_DAY_KINDS = ("birthday", "document_expiry")
DEFAULT_REMINDER_TIME = "09:00"
ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_LIST = 50

_ALLOWED_ARGS = {
    "action", "kind", "title", "description", "category", "due_local", "before_item_id", "before_days", "before_minutes",
    "lead_days", "lead_minutes", "recurrence", "amount", "currency", "payment_status", "estimated_minutes", "priority",
    "parent_id", "item_id", "changes", "query", "status", "from_date", "to_date", "days", "limit", "source",
}


def detect_timezone() -> str:
    name = os.environ.get("BYTEX_TIMEZONE") or os.environ.get("TZ") or ""
    if name:
        try:
            rec.get_zone(name)
            return name
        except rec.RecurrenceError:
            pass
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            cand = target.split("zoneinfo/", 1)[1]
            rec.get_zone(cand)
            return cand
    except Exception:
        pass
    return "UTC"


@dataclass
class Plan:
    """Result of validating a request. ``fields`` is what would be written; nothing is written by planning."""
    ok: bool = False
    clarification: Optional[str] = None
    error: Optional[str] = None
    preview: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    item: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)


class SmartLifeService:
    def __init__(self, store: Optional[SmartLifeStore] = None, clock: Callable[[], datetime] = utc_now):
        self.store = store or SmartLifeStore()
        self.clock = clock

    # ---- settings -----------------------------------------------------------------------------------------
    @property
    def tz_name(self) -> str:
        return self.store.get_setting("timezone") or detect_timezone()

    @property
    def default_time(self) -> time:
        raw = self.store.get_setting("default_reminder_time") or DEFAULT_REMINDER_TIME
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return time.fromisoformat(DEFAULT_REMINDER_TIME)

    # ---- formatting ---------------------------------------------------------------------------------------
    def fmt_due(self, item: Dict[str, Any]) -> str:
        if not item.get("due_at"):
            return "no due date"
        local = rec.from_utc_iso(item["due_at"]).astimezone(rec.get_zone(item["tz"]))
        if item.get("all_day"):
            return local.strftime("%a %d %b %Y") + " (all day)"
        return local.strftime("%a %d %b %Y, %H:%M") + f" {local.tzname() or item['tz']}"

    @staticmethod
    def fmt_rule(rule: Optional[Dict[str, Any]]) -> str:
        if not rule:
            return "one time only"
        n = rule.get("interval", 1)
        unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[rule["freq"]]
        text = f"every {unit}" if n == 1 else f"every {n} {unit}s"
        return text + (f" until {rule['until']}" if rule.get("until") else "")

    def describe(self, item: Dict[str, Any]) -> str:
        bits = [f"'{item['title']}' ({item['kind'].replace('_', ' ')})", self.fmt_due(item)]
        if item.get("recurrence"):
            bits.append(self.fmt_rule(item["recurrence"]))
        return ", ".join(bits)

    # ---- date resolution ------------------------------------------------------------------------------------
    def _resolve_due(self, kind: str, args: Dict[str, Any], tz_name: str, plan: Plan) -> Optional[Dict[str, Any]]:
        """Returns {"due_at", "all_day"} or None (then plan.clarification/error is set)."""
        zone = rec.get_zone(tz_name)
        before = args.get("before_item_id")
        if before is not None:
            if not isinstance(before, str) or not ID_RE.match(before):
                plan.error = "before_item_id must be the id of an existing item."
                return None
            try:
                anchor = self.store.get_item(before)
            except NotFound:
                plan.error = "I couldn't find the item this reminder should come before."
                return None
            if not anchor.get("due_at"):
                plan.clarification = f"'{anchor['title']}' has no date yet. When is it?"
                return None
            try:
                offset = timedelta(days=int(args.get("before_days") or 0), minutes=int(args.get("before_minutes") or 0))
            except (TypeError, ValueError):
                plan.error = "before_days / before_minutes must be whole numbers."
                return None
            if offset <= timedelta(0) or offset > timedelta(days=3650):
                plan.clarification = f"How long before '{anchor['title']}' should I remind you?"
                return None
            due = rec.from_utc_iso(anchor["due_at"]) - offset
            plan.fields["parent_id"] = anchor["id"]
            return {"due_at": rec.to_utc_iso(due), "all_day": False}

        raw = args.get("due_local")
        if raw in (None, ""):
            return {"due_at": None, "all_day": False}
        if not isinstance(raw, str):
            plan.error = "due_local must be a date/time like 2026-10-30T19:00 or a date like 2026-10-30."
            return None
        raw = raw.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                d = date.fromisoformat(raw)
                if kind in ALL_DAY_KINDS:
                    return {"due_at": rec.to_utc_iso(rec.local_to_utc(d, time(0, 0), zone)), "all_day": True}
                plan.notes.append(f"No time given, so I used {self.default_time.strftime('%H:%M')}.")
                return {"due_at": rec.to_utc_iso(rec.local_to_utc(d, self.default_time, zone)), "all_day": False}
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            plan.error = "I couldn't read that date. Please give a date like 2026-10-30 or 2026-10-30T19:00."
            return None
        if dt.tzinfo is None:
            return {"due_at": rec.to_utc_iso(rec.local_to_utc(dt.date(), dt.time(), zone)), "all_day": False}
        return {"due_at": rec.to_utc_iso(dt), "all_day": False}

    def _lead(self, args: Dict[str, Any]) -> int:
        try:
            return int(args.get("lead_days") or 0) * 1440 + int(args.get("lead_minutes") or 0)
        except (TypeError, ValueError):
            raise ValidationError("Reminder lead time must be whole numbers.")

    # ---- planning (validation + preview), no writes ---------------------------------------------------------
    def plan(self, action: str, args: Dict[str, Any]) -> Plan:
        plan = Plan()
        try:
            if action not in ALL_ACTIONS:
                plan.error = f"Unknown SMART LIFE action '{action}'. Use one of: {', '.join(ALL_ACTIONS)}."
                return plan
            unknown = set(args) - _ALLOWED_ARGS
            if unknown:
                plan.error = f"Unsupported argument(s): {', '.join(sorted(unknown))}."
                return plan
            handler = getattr(self, f"_plan_{action}", None)
            if handler is None:  # read actions need no preview
                plan.ok = True
                return plan
            handler(args, plan)
        except (ValidationError, rec.RecurrenceError) as exc:
            plan.ok, plan.error = False, str(exc)
        return plan

    def _plan_create(self, args: Dict[str, Any], plan: Plan) -> None:
        kind = str(args.get("kind") or "").strip().lower()
        if kind not in KINDS:
            plan.clarification = f"What type of item is this? ({', '.join(KINDS)})"
            return
        title = " ".join(str(args.get("title") or "").split())
        if not title:
            plan.clarification = "What should I call it?"
            return
        tz_name = self.tz_name
        due = self._resolve_due(kind, args, tz_name, plan)
        if due is None:
            return
        rule = args.get("recurrence") or None
        needs_date = kind != "task"
        if due["due_at"] is None:
            if rule:
                plan.clarification = "When is the first occurrence?"
                return
            if needs_date:
                plan.clarification = f"What date{' and time' if kind == 'reminder' else ''} is '{title}'?"
                return
        now = self.clock()
        if due["due_at"] is not None:
            due_dt = rec.from_utc_iso(due["due_at"])
            if rule:
                clean_rule = rec.validate_rule(rule)
                if due_dt <= now:  # an annual/monthly series whose first date has passed starts at its next occurrence
                    zone = rec.get_zone(tz_name)
                    local = due_dt.astimezone(zone)
                    probe = {**clean_rule, "anchor": clean_rule.get("anchor") or local.date().isoformat(), "anchor_time": clean_rule.get("anchor_time") or local.strftime("%H:%M")}
                    nxt = rec.next_occurrence(probe, tz_name, due_dt, after_utc=now)
                    if nxt is None:
                        plan.error = "That recurring series has already ended."
                        return
                    due["due_at"] = rec.to_utc_iso(nxt)
                    args = {**args, "recurrence": probe}
                    plan.notes.append("The first date had already passed, so it starts at the next occurrence.")
            elif due_dt <= now:
                plan.clarification = f"That time has already passed. What new date and time should I use for '{title}'?"
                return
        lead = self._lead(args)
        fields = {
            "kind": kind, "title": title, "tz": tz_name, "due_at": due["due_at"], "all_day": due["all_day"], "lead_minutes": lead,
        }
        for key in ("description", "category", "amount", "currency", "payment_status", "estimated_minutes", "priority", "source"):
            if args.get(key) not in (None, ""):
                fields[key] = args[key]
        if rule:
            fields["recurrence"] = args["recurrence"]
        fields.update({k: v for k, v in plan.fields.items() if k == "parent_id"})
        if args.get("parent_id") and "parent_id" not in fields:
            fields["parent_id"] = args["parent_id"]
        # run the real validators now so the user is never asked to approve something that will be rejected
        self.store._validate_fields(fields, creating=True)
        plan.fields = fields
        shown = {"kind": kind, "title": title, "due_at": due["due_at"], "tz": tz_name, "all_day": due["all_day"],
                 "recurrence": fields.get("recurrence") and rec.validate_rule(fields["recurrence"])}
        lines = [f"Create {kind.replace('_', ' ')}: '{title}'", f"When: {self.fmt_due(shown)}", f"Repeats: {self.fmt_rule(shown['recurrence'])}"]
        if lead:
            lines.append(f"Remind me {lead // 1440} day(s) {lead % 1440} min before" if lead % 1440 else f"Remind me {lead // 1440} day(s) before")
        if fields.get("amount") is not None:
            lines.append(f"Amount: {fields['amount']} {fields.get('currency') or ''}".strip())
        lines.extend(plan.notes)
        plan.preview = "\n".join(lines)
        plan.ok = True

    def _target(self, args: Dict[str, Any], plan: Plan, verb: str, *, allow_done: bool = False) -> Optional[Dict[str, Any]]:
        item_id = args.get("item_id")
        if not item_id:
            plan.clarification = (f"Which item do you want to {verb}? Search for it first so I can use its exact id.")
            return None
        if not isinstance(item_id, str) or not ID_RE.match(item_id):
            plan.error = "item_id must be the exact id returned by a previous search or list."
            return None
        try:
            item = self.store.get_item(item_id)
        except NotFound:
            plan.error = "I couldn't find that item. It may have been removed; search again."
            return None
        if item["status"] != "pending" and not allow_done:
            plan.error = f"'{item['title']}' is already {item['status']}."
            return None
        return item

    def _plan_cancel(self, args: Dict[str, Any], plan: Plan) -> None:
        item = self._target(args, plan, "cancel")
        if item:
            plan.item, plan.ok = item, True
            plan.preview = f"Cancel: {self.describe(item)}. It will stay in your history as cancelled."

    def _plan_complete(self, args: Dict[str, Any], plan: Plan) -> None:
        item = self._target(args, plan, "mark done")
        if item:
            plan.item, plan.ok = item, True
            plan.preview = f"Mark done: {self.describe(item)}." + (" The next occurrence will be scheduled." if item.get("recurrence") else "")

    def _plan_delete(self, args: Dict[str, Any], plan: Plan) -> None:
        item = self._target(args, plan, "delete", allow_done=True)
        if item:
            plan.item, plan.ok = item, True
            plan.preview = f"PERMANENTLY DELETE: {self.describe(item)}. This cannot be undone (cancelling keeps a record)."

    def _plan_update(self, args: Dict[str, Any], plan: Plan) -> None:
        item = self._target(args, plan, "change")
        if not item:
            return
        changes = args.get("changes")
        if not isinstance(changes, dict) or not changes:
            plan.clarification = f"What should I change about '{item['title']}'?"
            return
        allowed = {"title", "description", "category", "due_local", "lead_days", "lead_minutes", "recurrence", "amount", "currency",
                   "payment_status", "estimated_minutes", "priority"}
        bad = set(changes) - allowed
        if bad:
            plan.error = f"These fields cannot be changed: {', '.join(sorted(bad))}."
            return
        out: Dict[str, Any] = {}
        lines = [f"Change {self.describe(item)}:"]
        if "due_local" in changes:
            sub = Plan()
            tz_name = item["tz"]
            due = self._resolve_due(item["kind"], {"due_local": changes["due_local"]}, tz_name, sub)
            if due is None or due["due_at"] is None:
                plan.clarification, plan.error = sub.clarification, sub.error or (None if sub.clarification else "Please give the new date and time.")
                if not (plan.clarification or plan.error):
                    plan.clarification = "What is the new date and time?"
                return
            if rec.from_utc_iso(due["due_at"]) <= self.clock() and not item.get("recurrence"):
                plan.clarification = "That time has already passed. What new date and time should I use?"
                return
            out["due_at"], out["all_day"] = due["due_at"], due["all_day"]
            lines.append(f"New time: {self.fmt_due({**item, **out})}")
            plan.notes.extend(sub.notes)
        if "lead_days" in changes or "lead_minutes" in changes:
            out["lead_minutes"] = self._lead(changes)
            lines.append(f"Remind me {out['lead_minutes']} minute(s) before")
        for key in ("title", "description", "category", "recurrence", "amount", "currency", "payment_status", "estimated_minutes", "priority"):
            if key in changes:
                out[key] = changes[key]
                lines.append(f"New {key.replace('_', ' ')}: {changes[key]}")
        probe = dict(out)
        self.store._validate_fields(probe, creating=False)
        lines.extend(plan.notes)
        plan.item, plan.fields, plan.ok = item, out, True
        plan.preview = "\n".join(lines)

    # ---- execution ------------------------------------------------------------------------------------------
    def execute(self, action: str, args: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        """
        Returns {"status": ..., "message": ..., "data": ..., "verified": bool}. Status is one of:
        ok, clarify, error, confirm. Data is changed only when ``confirmed`` is True.
        """
        plan = self.plan(action, args)
        if plan.clarification:
            return {"status": "clarify", "message": plan.clarification, "data": None, "verified": False}
        if plan.error:
            return {"status": "error", "message": plan.error, "data": None, "verified": False}
        if action in READ_ACTIONS:
            return self._read(action, args)
        if not confirmed:
            return {"status": "confirm", "message": plan.preview, "data": None, "verified": False}
        try:
            return self._write(action, plan)
        except (ValidationError, NotFound, rec.RecurrenceError) as exc:
            return {"status": "error", "message": str(exc), "data": None, "verified": False}

    def _write(self, action: str, plan: Plan) -> Dict[str, Any]:
        if action == "create":
            item, created = self.store.create_item(plan.fields)
            back = self.store.get_item(item["id"])
            ok = back["title"] == plan.fields["title"] and back["due_at"] == plan.fields.get("due_at")
            verb = "Created" if created else "Already existed, no duplicate made:"
            return {"status": "ok", "message": f"{verb} {self.describe(back)}.", "data": {"item": back, "created": created}, "verified": ok}
        item = plan.item
        if action == "update":
            back = self.store.update_item(item["id"], self._store_changes(plan.fields))
            return {"status": "ok", "message": f"Updated {self.describe(back)}.", "data": {"item": back}, "verified": self.store.get_item(item["id"]) == back}
        if action == "complete":
            back = self.store.complete_item(item["id"], now=self.clock())
            nxt = f" Next: {self.fmt_due(back)}." if back["status"] == "pending" else ""
            return {"status": "ok", "message": f"Marked done: '{back['title']}'.{nxt}", "data": {"item": back}, "verified": self.store.get_item(item["id"]) == back}
        if action == "cancel":
            back = self.store.cancel_item(item["id"])
            return {"status": "ok", "message": f"Cancelled: '{back['title']}'.", "data": {"item": back}, "verified": back["status"] == "cancelled"}
        if action == "delete":
            self.store.delete_item(item["id"])
            try:
                self.store.get_item(item["id"])
                gone = False
            except NotFound:
                gone = True
            return {"status": "ok" if gone else "error", "message": f"Deleted: '{item['title']}'." if gone else "The item could not be deleted.",
                    "data": {"deleted_id": item["id"]}, "verified": gone}
        raise ValidationError("Unsupported action.")

    @staticmethod
    def _store_changes(fields: Dict[str, Any]) -> Dict[str, Any]:
        return dict(fields)

    def _read(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        now = self.clock()
        tz = rec.get_zone(self.tz_name)
        limit = min(int(args.get("limit") or MAX_LIST), MAX_LIST)
        kind = args.get("kind")
        if kind and kind not in KINDS:
            return {"status": "error", "message": f"Type must be one of: {', '.join(KINDS)}.", "data": None, "verified": False}
        if action == "get":
            if not args.get("item_id") or not ID_RE.match(str(args["item_id"])):
                return {"status": "clarify", "message": "Which item? Search for it first.", "data": None, "verified": False}
            try:
                item = self.store.get_item(args["item_id"])
            except NotFound:
                return {"status": "error", "message": "I couldn't find that item.", "data": None, "verified": False}
            return {"status": "ok", "message": self.describe(item), "data": {"item": item}, "verified": True}
        if action == "today":
            local_now = now.astimezone(tz)
            start = rec.local_to_utc(local_now.date(), time(0, 0), tz)
            end = start + timedelta(days=1) - timedelta(seconds=1)
            items = self.store.list_items(due_from=rec.to_utc_iso(start), due_to=rec.to_utc_iso(end), kind=kind, limit=limit)
            overdue = self.store.list_items(overdue_only=True, now=start, kind=kind, limit=limit)
            items = overdue + [i for i in items if i["id"] not in {o["id"] for o in overdue}]
            title = f"{len(items)} item(s) for today or overdue"
        elif action == "overdue":
            items = self.store.list_items(overdue_only=True, now=now, kind=kind, limit=limit)
            title = f"{len(items)} overdue item(s)"
        elif action == "upcoming":
            days = max(1, min(int(args.get("days") or 7), 366))
            items = self.store.list_items(due_from=rec.to_utc_iso(now), due_to=rec.to_utc_iso(now + timedelta(days=days)), kind=kind, limit=limit)
            title = f"{len(items)} item(s) in the next {days} day(s)"
        elif action == "search":
            q = str(args.get("query") or "").strip()
            if not q:
                return {"status": "clarify", "message": "What should I search for?", "data": None, "verified": False}
            items = self.store.list_items(status=args.get("status") or "pending", query=q, kind=kind, limit=limit)
            title = f"{len(items)} match(es) for '{q}'"
        else:  # list
            items = self.store.list_items(status=args.get("status", "pending"), kind=kind, limit=limit)
            title = f"{len(items)} item(s)"
        lines = [title + ":"]
        for it in items:
            flag = " [OVERDUE]" if self.store.is_overdue(it, now) else ""
            lines.append(f"- id={it['id']} | {self.describe(it)}{flag}")
        if not items:
            lines = [title + "."]
        return {"status": "ok", "message": "\n".join(lines), "data": {"items": items}, "verified": True}


_default: Optional[SmartLifeService] = None


def default_service() -> SmartLifeService:
    """Process-wide service shared by the skill and the risk classifier (so both validate identically)."""
    global _default
    if _default is None:
        _default = SmartLifeService()
    return _default


def set_default_service(service: Optional[SmartLifeService]) -> None:
    global _default
    _default = service
