"""
SMART LIFE core tests: recurrence, time zones, persistence, idempotency, migration safety. Pure stdlib (no pydantic).

    PYTHONPATH=backend python3 -m unittest tests.test_smartlife_store -v
"""
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from smartlife import recurrence as rec  # noqa: E402
from smartlife.store import SmartLifeStore, ValidationError, NotFound, make_idempotency_key  # noqa: E402

IST = "Asia/Kolkata"


def utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def at(d, t, tz=IST):
    return rec.local_to_utc(d, t, rec.get_zone(tz))


class RecurrenceTests(unittest.TestCase):
    def series(self, rule, tz, first, n):
        out, cur = [], first
        for _ in range(n):
            cur = rec.next_occurrence(rule, tz, cur)
            out.append(cur.astimezone(rec.get_zone(tz)))
        return out

    def test_monthly_on_31st_clamps_without_drifting(self):
        first = at(date(2026, 1, 31), time(9, 0))
        days = [d.date().isoformat() for d in self.series({"freq": "monthly", "anchor": "2026-01-31"}, IST, first, 5)]
        self.assertEqual(days, ["2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"])

    def test_monthly_leap_february(self):
        first = at(date(2028, 1, 31), time(9, 0))
        self.assertEqual(self.series({"freq": "monthly", "anchor": "2028-01-31"}, IST, first, 1)[0].date().isoformat(), "2028-02-29")

    def test_yearly_feb_29_uses_feb_28_in_common_years(self):
        first = at(date(2024, 2, 29), time(9, 0))
        days = [d.date().isoformat() for d in self.series({"freq": "yearly", "anchor": "2024-02-29"}, IST, first, 5)]
        self.assertEqual(days, ["2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29", "2029-02-28"])

    def test_yearly_birthday_keeps_local_time(self):
        first = at(date(2026, 10, 27), time(9, 0))
        nxt = rec.next_occurrence({"freq": "yearly"}, IST, first)
        local = nxt.astimezone(rec.get_zone(IST))
        self.assertEqual((local.year, local.month, local.day, local.hour), (2027, 10, 27, 9))

    def test_weekly_and_daily_and_interval(self):
        first = at(date(2026, 10, 26), time(7, 0))
        self.assertEqual(self.series({"freq": "weekly", "interval": 2}, IST, first, 2)[1].date().isoformat(), "2026-11-23")
        self.assertEqual(self.series({"freq": "daily", "interval": 3}, IST, first, 1)[0].date().isoformat(), "2026-10-29")

    def test_dst_spring_forward_gap_and_return_to_anchor_time(self):
        tz = "America/New_York"
        first = at(date(2026, 3, 7), time(2, 30), tz)
        rule = {"freq": "daily", "anchor_time": "02:30"}
        days = self.series(rule, tz, first, 3)
        self.assertEqual([(d.day, d.hour, d.minute) for d in days], [(8, 3, 30), (9, 2, 30), (10, 2, 30)])

    def test_dst_fall_back_keeps_wall_clock(self):
        tz = "America/New_York"
        first = at(date(2026, 10, 31), time(9, 0), tz)
        nxt = self.series({"freq": "daily"}, tz, first, 2)
        self.assertEqual([(d.day, d.hour) for d in nxt], [(1, 9), (2, 9)])  # 9:00 local on both sides of the change

    def test_until_ends_series(self):
        first = at(date(2026, 10, 27), time(9, 0))
        self.assertIsNone(rec.next_occurrence({"freq": "yearly", "until": "2027-01-01"}, IST, first))

    def test_next_is_strictly_after_floor(self):
        first = at(date(2026, 10, 1), time(9, 0))
        nxt = rec.next_occurrence({"freq": "daily"}, IST, first, after_utc=at(date(2026, 10, 10), time(9, 0)))
        self.assertEqual(nxt.astimezone(rec.get_zone(IST)).date().isoformat(), "2026-10-11")

    def test_invalid_rules_and_zones_rejected(self):
        for bad in ({"freq": "hourly"}, {"freq": "daily", "interval": 0}, {"freq": "daily", "interval": "x"},
                    {"freq": "daily", "evil": 1}, {"freq": "daily", "anchor": "nope"}, "daily"):
            with self.assertRaises(rec.RecurrenceError, msg=str(bad)):
                rec.validate_rule(bad)
        with self.assertRaises(rec.RecurrenceError):
            rec.get_zone("Mars/Olympus")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sl.db"
        self.store = SmartLifeStore(self.path)
        self.due = rec.to_utc_iso(at(date(2026, 10, 30), time(19, 0)))

    def make(self, **kw):
        base = {"kind": "reminder", "title": "Submit DBMS assignment", "tz": IST, "due_at": self.due}
        base.update(kw)
        return self.store.create_item(base)

    def test_create_and_read_persist_across_reopen(self):
        item, created = self.make(description="  chapter 4  ", category="college")
        self.assertTrue(created)
        again = SmartLifeStore(self.path).get_item(item["id"])
        self.assertEqual((again["title"], again["description"], again["status"], again["due_at"]),
                         ("Submit DBMS assignment", "chapter 4", "pending", self.due))
        self.assertEqual(len(item["id"]), 32)

    def test_duplicate_create_is_idempotent_even_with_whitespace_and_case(self):
        a, c1 = self.make()
        b, c2 = self.make(title="  submit   dbms ASSIGNMENT ")
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.store.list_items()), 1)

    def test_same_title_different_time_is_a_different_item(self):
        self.make()
        _, created = self.make(due_at=rec.to_utc_iso(at(date(2026, 10, 31), time(19, 0))))
        self.assertTrue(created)

    def test_cancelled_item_can_be_recreated(self):
        a, _ = self.make()
        self.store.cancel_item(a["id"])
        b, created = self.make()
        self.assertTrue(created)
        self.assertNotEqual(a["id"], b["id"])

    def test_concurrent_identical_creates_insert_once(self):
        results = []
        def worker():
            results.append(self.make()[1])
        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(self.store.list_items()), 1)

    def test_validation_errors(self):
        for kw in ({"title": "   "}, {"title": "x" * 201}, {"kind": "nonsense"}, {"tz": "Nowhere/City"}, {"due_at": "tomorrow"},
                   {"lead_minutes": -5}, {"amount": "abc"}, {"payment_status": "maybe"}, {"priority": 9},
                   {"recurrence": {"freq": "hourly"}}, {"estimated_minutes": 0}):
            with self.assertRaises(ValidationError, msg=str(kw)):
                self.make(**kw)
        with self.assertRaises(ValidationError):
            self.make(recurrence={"freq": "daily"}, due_at=None)
        self.assertEqual(self.store.list_items(), [])

    def test_update_changes_only_allowed_fields_and_keeps_timestamps_sane(self):
        item, _ = self.make()
        new_due = rec.to_utc_iso(at(date(2026, 10, 30), time(19, 0)))
        out = self.store.update_item(item["id"], {"due_at": new_due, "title": "Submit DBMS lab file"})
        self.assertEqual(out["title"], "Submit DBMS lab file")
        self.assertGreaterEqual(out["updated_at"], item["updated_at"])
        self.assertEqual(out["created_at"], item["created_at"])
        for bad in ({"status": "completed"}, {"id": "x"}, {"idempotency_key": "x"}, {"completed_count": 9}):
            with self.assertRaises(ValidationError):
                self.store.update_item(item["id"], bad)
        with self.assertRaises(ValidationError):
            self.store.update_item(item["id"], {})
        with self.assertRaises(NotFound):
            self.store.update_item("0" * 32, {"title": "x"})

    def test_update_cannot_create_a_duplicate(self):
        a, _ = self.make()
        b, _ = self.make(title="Other thing")
        with self.assertRaises(ValidationError):
            self.store.update_item(b["id"], {"title": a["title"]})

    def test_complete_one_off_and_double_complete_rejected(self):
        item, _ = self.make()
        done = self.store.complete_item(item["id"])
        self.assertEqual((done["status"], done["completed_count"]), ("completed", 1))
        self.assertTrue(done["completed_at"])
        with self.assertRaises(ValidationError):
            self.store.complete_item(item["id"])
        with self.assertRaises(ValidationError):
            self.store.update_item(item["id"], {"title": "late edit"})

    def test_complete_recurring_advances_and_stays_pending(self):
        item, _ = self.store.create_item({"kind": "bill", "title": "Wi-Fi bill", "tz": IST, "due_at": rec.to_utc_iso(at(date(2026, 10, 5), time(9, 0))),
                                           "recurrence": {"freq": "monthly"}, "amount": 799, "currency": "inr"})
        self.assertEqual(item["recurrence"]["anchor"], "2026-10-05")
        self.assertEqual(item["currency"], "INR")
        done = self.store.complete_item(item["id"], now=utc(2026, 10, 5, 4, 0))
        self.assertEqual(done["status"], "pending")
        self.assertEqual(done["completed_count"], 1)
        self.assertEqual(rec.from_utc_iso(done["due_at"]).astimezone(rec.get_zone(IST)).date().isoformat(), "2026-11-05")

    def test_completing_late_skips_missed_occurrences(self):
        item, _ = self.store.create_item({"kind": "bill", "title": "Rent", "tz": IST, "due_at": rec.to_utc_iso(at(date(2026, 1, 1), time(9, 0))),
                                           "recurrence": {"freq": "monthly"}})
        done = self.store.complete_item(item["id"], now=utc(2026, 4, 10))
        self.assertEqual(rec.from_utc_iso(done["due_at"]).astimezone(rec.get_zone(IST)).date().isoformat(), "2026-05-01")

    def test_recurring_series_that_ended_completes(self):
        item, _ = self.store.create_item({"kind": "reminder", "title": "Trial", "tz": IST, "due_at": rec.to_utc_iso(at(date(2026, 10, 5), time(9, 0))),
                                           "recurrence": {"freq": "daily", "until": "2026-10-05"}})
        self.assertEqual(self.store.complete_item(item["id"], now=utc(2026, 10, 5, 4))["status"], "completed")

    def test_cancel_only_target_and_is_repeatable(self):
        a, _ = self.make()
        b, _ = self.make(title="Rahul birthday", kind="birthday")
        out = self.store.cancel_item(b["id"])
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(self.store.get_item(a["id"])["status"], "pending")
        self.assertEqual(self.store.cancel_item(b["id"])["status"], "cancelled")
        c, _ = self.make(title="done one")
        self.store.complete_item(c["id"])
        with self.assertRaises(ValidationError):
            self.store.cancel_item(c["id"])

    def test_delete_removes_only_that_row_and_links_survive(self):
        parent, _ = self.make(title="Exam", kind="exam")
        child, _ = self.make(title="Revise", parent_id=parent["id"], due_at=rec.to_utc_iso(at(date(2026, 10, 29), time(9, 0))))
        self.assertEqual(child["parent_id"], parent["id"])
        self.store.delete_item(parent["id"])
        self.assertIsNone(self.store.get_item(child["id"])["parent_id"])
        with self.assertRaises(NotFound):
            self.store.get_item(parent["id"])
        with self.assertRaises(NotFound):
            self.make(title="Orphan2", parent_id="f" * 32)

    def test_list_filters_search_and_overdue_are_derived(self):
        past = rec.to_utc_iso(utc(2026, 10, 1, 4))
        a, _ = self.make(title="Old thing", due_at=past)
        b, _ = self.make(title="Future thing")
        c, _ = self.make(title="Rahul birthday", kind="birthday", due_at=rec.to_utc_iso(at(date(2026, 10, 27), time(9, 0))))
        now = utc(2026, 10, 26, 8)
        self.assertEqual([i["id"] for i in self.store.list_items(overdue_only=True, now=now)], [a["id"]])
        self.assertEqual([i["id"] for i in self.store.list_items(kind="birthday")], [c["id"]])
        self.assertEqual([i["id"] for i in self.store.list_items(query="RAHUL")], [c["id"]])
        self.assertEqual(self.store.list_items(query="%"), [])
        window = self.store.list_items(due_from=rec.to_utc_iso(utc(2026, 10, 26)), due_to=rec.to_utc_iso(utc(2026, 10, 28)))
        self.assertEqual([i["id"] for i in window], [c["id"]])
        self.store.complete_item(a["id"])
        self.assertEqual(self.store.list_items(overdue_only=True, now=now), [])
        self.assertEqual({i["id"] for i in self.store.list_items(status=None)}, {a["id"], b["id"], c["id"]})
        with self.assertRaises(ValidationError):
            self.store.list_items(status="weird")

    def test_no_sql_injection_through_text_fields(self):
        item, _ = self.make(title="x'); DROP TABLE sl_items;--")
        self.assertEqual(self.store.get_item(item["id"])["title"], "x'); DROP TABLE sl_items;--")
        self.assertEqual(len(self.store.list_items(query="'); drop")), 1)
        self.assertEqual(self.store.counts()["pending"], 1)

    def test_settings_roundtrip(self):
        self.assertIsNone(self.store.get_setting("timezone"))
        self.store.set_setting("timezone", IST)
        self.store.set_setting("timezone", "UTC")
        self.assertEqual(self.store.get_setting("timezone"), "UTC")

    def test_idempotency_key_is_stable(self):
        self.assertEqual(make_idempotency_key("reminder", "A  b", "t", None), make_idempotency_key("reminder", "a B", "t", None))
        self.assertNotEqual(make_idempotency_key("reminder", "a", "t", None), make_idempotency_key("task", "a", "t", None))


class MigrationSafetyTests(unittest.TestCase):
    def test_existing_database_and_tables_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bytex_memory.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
            conn.execute("INSERT INTO memories VALUES ('m1', 'likes tea')")
            conn.commit(); conn.close()
            SmartLifeStore(path)
            SmartLifeStore(path)  # reopening is a no-op
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute("SELECT content FROM memories").fetchall(), [("likes tea",)])
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"memories", "sl_items", "sl_meta"} <= tables)
            self.assertEqual(conn.execute("SELECT value FROM sl_meta WHERE key='schema_version'").fetchone()[0], "1")
            conn.close()


if __name__ == "__main__":
    unittest.main()
