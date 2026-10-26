"""
SMART LIFE service tests: structured validation, clarification instead of guessing, previews, no write without approval.
Pure stdlib; always uses a temporary database (never the real bytex_memory.db).

    PYTHONPATH=backend python3 -m unittest tests.test_smartlife_service -v
"""
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from smartlife import recurrence as rec  # noqa: E402
from smartlife.service import SmartLifeService  # noqa: E402
from smartlife.store import SmartLifeStore  # noqa: E402

IST = "Asia/Kolkata"
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)  # Mon 26 Oct 2026, 14:30 IST


class ServiceBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SmartLifeStore(Path(self._tmp.name) / "t.db")
        self.store.set_setting("timezone", IST)
        self.svc = SmartLifeService(self.store, clock=lambda: NOW)

    def create(self, confirmed=True, **kw):
        args = {"kind": "reminder", "title": "Submit DBMS assignment", "due_local": "2026-10-30T19:00"}
        args.update(kw)
        return self.svc.execute("create", args, confirmed=confirmed)


class CreateAndClarifyTests(ServiceBase):
    def test_nothing_is_written_without_approval(self):
        res = self.create(confirmed=False)
        self.assertEqual(res["status"], "confirm")
        self.assertIn("Fri 30 Oct 2026, 19:00", res["message"])
        self.assertIn("one time only", res["message"])
        self.assertEqual(self.store.list_items(status=None), [])

    def test_confirmed_create_is_written_and_verified_in_the_time_zone(self):
        res = self.create()
        self.assertEqual((res["status"], res["verified"]), ("ok", True))
        item = res["data"]["item"]
        self.assertEqual(item["due_at"], "2026-10-30T13:30:00Z")  # 19:00 IST
        self.assertEqual(item["tz"], IST)

    def test_duplicate_request_does_not_duplicate(self):
        self.create(); again = self.create()
        self.assertFalse(again["data"]["created"])
        self.assertIn("no duplicate", again["message"])
        self.assertEqual(len(self.store.list_items()), 1)

    def test_missing_pieces_ask_instead_of_guessing(self):
        self.assertEqual(self.svc.execute("create", {"title": "x", "due_local": "2026-10-30"})["status"], "clarify")
        self.assertEqual(self.svc.execute("create", {"kind": "reminder", "due_local": "2026-10-30"})["status"], "clarify")
        for kind in ("reminder", "birthday", "exam", "bill"):
            self.assertEqual(self.svc.execute("create", {"kind": kind, "title": "Thing"})["status"], "clarify", kind)
        self.assertEqual(self.svc.execute("create", {"kind": "task", "title": "Revise arrays"}, confirmed=True)["status"], "ok")
        self.assertEqual(self.store.counts().get("pending"), 1)

    def test_recurrence_without_date_asks(self):
        self.assertEqual(self.svc.execute("create", {"kind": "bill", "title": "Wi-Fi", "recurrence": {"freq": "monthly"}})["status"], "clarify")

    def test_past_time_asks_for_a_new_one(self):
        res = self.create(due_local="2026-10-20T10:00")
        self.assertEqual(res["status"], "clarify")
        self.assertIn("already passed", res["message"])
        self.assertEqual(self.store.list_items(status=None), [])

    def test_date_only_uses_default_time_and_says_so(self):
        res = self.create(confirmed=False, due_local="2026-10-30")
        self.assertIn("09:00", res["message"]); self.assertIn("No time given", res["message"])
        self.store.set_setting("default_reminder_time", "08:15")
        self.assertIn("08:15", self.create(confirmed=False, due_local="2026-10-31")["message"])

    def test_birthday_tomorrow_is_one_time_not_annual(self):
        item = self.create(kind="birthday", title="Rahul's birthday", due_local="2026-10-27")["data"]["item"]
        self.assertIsNone(item["recurrence"])
        self.assertTrue(item["all_day"])
        self.assertIn("one time only", self.create(confirmed=False, kind="birthday", title="Aman's birthday", due_local="2026-10-28")["message"])

    def test_annual_birthday_rolls_forward_when_the_date_passed(self):
        item = self.create(kind="birthday", title="Priya birthday", due_local="2026-03-04", recurrence={"freq": "yearly"})["data"]["item"]
        local = rec.from_utc_iso(item["due_at"]).astimezone(rec.get_zone(IST))
        self.assertEqual(local.date().isoformat(), "2027-03-04")
        self.assertEqual(item["recurrence"]["freq"], "yearly")
        self.assertIn("next occurrence", self.create(confirmed=False, kind="birthday", title="Q", due_local="2026-01-01", recurrence={"freq": "yearly"})["message"])

    def test_birthday_27_october_every_year_keeps_this_year_when_still_ahead(self):
        res = self.create(kind="birthday", title="Rahul birthday", due_local="2026-10-27", recurrence={"freq": "yearly"})
        self.assertEqual(rec.from_utc_iso(res["data"]["item"]["due_at"]).astimezone(rec.get_zone(IST)).date().isoformat(), "2026-10-27")

    def test_reminder_before_an_existing_exam(self):
        exam = self.create(kind="exam", title="DBMS exam", due_local="2026-11-10T10:00")["data"]["item"]
        res = self.svc.execute("create", {"kind": "reminder", "title": "Study for DBMS exam", "before_item_id": exam["id"], "before_days": 2}, confirmed=True)
        item = res["data"]["item"]
        self.assertEqual(item["due_at"], "2026-11-08T04:30:00Z")
        self.assertEqual(item["parent_id"], exam["id"])

    def test_before_unknown_or_undated_item(self):
        self.assertEqual(self.svc.execute("create", {"kind": "reminder", "title": "x", "before_item_id": "a" * 32, "before_days": 1})["status"], "error")
        task = self.svc.execute("create", {"kind": "task", "title": "Undated"}, confirmed=True)["data"]["item"]
        self.assertEqual(self.svc.execute("create", {"kind": "reminder", "title": "x", "before_item_id": task["id"], "before_days": 1})["status"], "clarify")
        exam = self.create(kind="exam", title="E", due_local="2026-11-10T10:00")["data"]["item"]
        self.assertEqual(self.svc.execute("create", {"kind": "reminder", "title": "x", "before_item_id": exam["id"]})["status"], "clarify")

    def test_explicit_offset_is_honoured(self):
        self.assertEqual(self.create(due_local="2026-10-30T19:00:00+00:00")["data"]["item"]["due_at"], "2026-10-30T19:00:00Z")

    def test_lead_time_is_saved(self):
        res = self.create(kind="document_expiry", title="Passport", due_local="2027-01-15", lead_days=90)
        self.assertEqual(res["data"]["item"]["lead_minutes"], 90 * 1440)

    def test_bill_with_amount_and_monthly_recurrence(self):
        item = self.create(kind="bill", title="Wi-Fi bill", due_local="2026-11-05T09:00", recurrence={"freq": "monthly"}, amount=799, currency="inr", payment_status="unpaid")["data"]["item"]
        self.assertEqual((item["amount"], item["currency"], item["recurrence"]["anchor"]), (799.0, "INR", "2026-11-05"))

    def test_invalid_input_is_rejected_with_a_message_and_no_write(self):
        for bad in ({"kind": "reminder", "title": "x", "due_local": "next friday"}, {"kind": "reminder", "title": "x", "due_local": 12345},
                    {"kind": "bill", "title": "x", "due_local": "2026-11-01", "amount": "lots"},
                    {"kind": "reminder", "title": "x", "due_local": "2026-11-01", "recurrence": {"freq": "hourly"}},
                    {"kind": "reminder", "title": "x", "due_local": "2026-11-01", "evil": "arg"},
                    {"kind": "reminder", "title": "y" * 500, "due_local": "2026-11-01"}):
            self.assertEqual(self.svc.execute("create", bad, confirmed=True)["status"], "error", bad)
        self.assertEqual(self.store.list_items(status=None), [])

    def test_unknown_action_rejected(self):
        self.assertEqual(self.svc.execute("run_sql", {"query": "DROP TABLE sl_items"}, confirmed=True)["status"], "error")


class ChangeTests(ServiceBase):
    def setUp(self):
        super().setUp()
        self.item = self.create()["data"]["item"]
        self.other = self.create(title="Rahul birthday", kind="birthday", due_local="2026-10-27")["data"]["item"]

    def test_move_reminder(self):
        res = self.svc.execute("update", {"item_id": self.item["id"], "changes": {"due_local": "2026-10-31T19:00"}}, confirmed=False)
        self.assertEqual(res["status"], "confirm")
        self.assertEqual(self.store.get_item(self.item["id"])["due_at"], self.item["due_at"])
        res = self.svc.execute("update", {"item_id": self.item["id"], "changes": {"due_local": "2026-10-31T19:00"}}, confirmed=True)
        self.assertEqual((res["status"], res["data"]["item"]["due_at"]), ("ok", "2026-10-31T13:30:00Z"))

    def test_changes_require_an_exact_id(self):
        for action in ("update", "cancel", "complete", "delete"):
            self.assertEqual(self.svc.execute(action, {}, confirmed=True)["status"], "clarify", action)
            self.assertEqual(self.svc.execute(action, {"item_id": "not-an-id"}, confirmed=True)["status"], "error", action)
            self.assertEqual(self.svc.execute(action, {"item_id": "e" * 32}, confirmed=True)["status"], "error", action)
        self.assertEqual(len(self.store.list_items()), 2)

    def test_update_rejects_unsupported_fields_and_past_times(self):
        for changes in ({"status": "completed"}, {"kind": "exam"}, {"due_local": "2026-10-01T10:00"}, {"amount": "x"}):
            res = self.svc.execute("update", {"item_id": self.item["id"], "changes": changes}, confirmed=True)
            self.assertIn(res["status"], ("error", "clarify"), changes)
        self.assertEqual(self.store.get_item(self.item["id"])["due_at"], self.item["due_at"])

    def test_cancel_targets_only_the_chosen_item_and_nothing_without_approval(self):
        self.assertEqual(self.svc.execute("cancel", {"item_id": self.other["id"]}, confirmed=False)["status"], "confirm")
        self.assertEqual(self.store.get_item(self.other["id"])["status"], "pending")
        self.assertEqual(self.svc.execute("cancel", {"item_id": self.other["id"]}, confirmed=True)["status"], "ok")
        self.assertEqual(self.store.get_item(self.other["id"])["status"], "cancelled")
        self.assertEqual(self.store.get_item(self.item["id"])["status"], "pending")
        self.assertEqual(self.svc.execute("cancel", {"item_id": self.other["id"]}, confirmed=True)["status"], "error")

    def test_complete_recurring_schedules_next(self):
        bill = self.create(kind="bill", title="Rent", due_local="2026-11-01T09:00", recurrence={"freq": "monthly"})["data"]["item"]
        res = self.svc.execute("complete", {"item_id": bill["id"]}, confirmed=True)
        self.assertIn("Next:", res["message"])
        self.assertEqual(res["data"]["item"]["status"], "pending")

    def test_delete_preview_is_explicit_and_verified(self):
        self.assertIn("PERMANENTLY DELETE", self.svc.execute("delete", {"item_id": self.item["id"]}, confirmed=False)["message"])
        self.assertEqual(len(self.store.list_items()), 2)
        res = self.svc.execute("delete", {"item_id": self.item["id"]}, confirmed=True)
        self.assertEqual((res["status"], res["verified"]), ("ok", True))
        self.assertEqual(len(self.store.list_items()), 1)


class ReadTests(ServiceBase):
    def test_today_upcoming_overdue_and_search(self):
        self.store.create_item({"kind": "reminder", "title": "Old overdue", "tz": IST, "due_at": "2026-10-20T04:00:00Z"})
        self.create(title="Today evening", due_local="2026-10-26T20:00")
        self.create(title="This week", due_local="2026-10-29T10:00")
        self.create(title="Next month", due_local="2026-12-01T10:00")
        today = self.svc.execute("today", {})["message"]
        self.assertIn("Today evening", today); self.assertIn("Old overdue", today); self.assertIn("[OVERDUE]", today)
        self.assertNotIn("This week", today)
        up = self.svc.execute("upcoming", {"days": 7})["message"]
        self.assertIn("This week", up); self.assertNotIn("Next month", up)
        self.assertIn("Old overdue", self.svc.execute("overdue", {})["message"])
        self.assertIn("Next month", self.svc.execute("search", {"query": "NEXT"})["message"])
        self.assertEqual(self.svc.execute("search", {})["status"], "clarify")
        self.assertEqual(self.svc.execute("list", {"kind": "bogus"})["status"], "error")

    def test_reads_never_write(self):
        before = self.store.counts()
        for action in ("list", "today", "upcoming", "overdue"):
            self.assertEqual(self.svc.execute(action, {})["status"], "ok")
        self.assertEqual(self.store.counts(), before)

    def test_empty_state(self):
        self.assertIn("0 item(s)", self.svc.execute("list", {})["message"])


if __name__ == "__main__":
    unittest.main()
