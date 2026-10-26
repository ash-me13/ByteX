"""
SMART LIFE through the REAL tool path: SkillRegistry.execute_tool, ActionRiskClassifier, ConfirmationManager and approval grants.
Uses a temporary database only. Needs pydantic (skipped otherwise).

    PYTHONPATH=backend python3 -m unittest tests.test_smartlife_tools -v
"""
import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from tests.registry_harness import load_registry_module
except ImportError:
    from registry_harness import load_registry_module

IST = "Asia/Kolkata"
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


class SmartLifeToolPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pydantic  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("pydantic not installed in this interpreter; run inside the project venv")
        from core import confirmation as conf
        from skills.smart_life import SmartLifeSkill
        from smartlife.service import SmartLifeService, set_default_service
        from smartlife.store import SmartLifeStore
        cls.conf, cls.Skill, cls.Service, cls.Store, cls.set_default = conf, SmartLifeSkill, SmartLifeService, SmartLifeStore, staticmethod(set_default_service)
        cls.mod = load_registry_module()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = self.Store(Path(self._tmp.name) / "t.db")
        self.store.set_setting("timezone", IST)
        self.svc = self.Service(self.store, clock=lambda: NOW)
        self.set_default(self.svc)
        self.addCleanup(self.set_default, None)
        self.registry = self.mod.SkillRegistry(register_defaults=False)
        self.registry.register_fixture("smart_life", self.Skill(self.svc))
        self.cm = self.conf.ConfirmationManager()
        self._orig = self.conf.confirmation_manager
        # the registry module imported the singleton by name; point both at one fresh manager for isolation
        self.mod.confirmation_manager = self.cm
        self.token = self.conf.set_conversation_id("conv-A")
        self.addCleanup(self.conf.reset_conversation_id, self.token)

    CREATE = {"action": "create", "kind": "reminder", "title": "Submit DBMS assignment", "due_local": "2026-10-30T19:00"}

    def call(self, args, **kw):
        return run(self.registry.execute_tool("smart_life", dict(args), **kw))

    def count(self):
        return len(self.store.list_items(status=None))

    # ---- classification / confirmation requirement -------------------------------------------------
    def test_reads_run_without_confirmation(self):
        for action in ("list", "today", "upcoming", "overdue", "search"):
            res = self.call({"action": action, "query": "x"})
            self.assertFalse(res.confirmation_required, action)
            self.assertTrue(res.success, action)

    def test_a_change_needs_approval_and_shows_the_exact_preview(self):
        res = self.call(self.CREATE)
        self.assertTrue(res.confirmation_required)
        self.assertIn("Fri 30 Oct 2026, 19:00", res.message)
        self.assertIn("Submit DBMS assignment", res.message)
        self.assertEqual(self.count(), 0)

    def test_every_change_action_is_gated(self):
        item = self.svc.execute("create", dict(self.CREATE, action=None) if False else {k: v for k, v in self.CREATE.items() if k != "action"}, confirmed=True)["data"]["item"]
        for args in ({"action": "update", "item_id": item["id"], "changes": {"title": "New title"}},
                     {"action": "complete", "item_id": item["id"]}, {"action": "cancel", "item_id": item["id"]},
                     {"action": "delete", "item_id": item["id"]}):
            res = self.call(args)
            self.assertTrue(res.confirmation_required, args["action"])
        self.assertEqual(self.store.get_item(item["id"])["status"], "pending")
        self.assertEqual(self.store.get_item(item["id"])["title"], "Submit DBMS assignment")

    def test_invalid_or_ambiguous_requests_ask_a_question_not_for_approval(self):
        for args in ({"action": "create", "kind": "reminder", "title": "x"},                              # no date
                     {"action": "create", "kind": "reminder", "title": "x", "due_local": "2026-10-01T10:00"},  # past
                     {"action": "cancel"}, {"action": "cancel", "item_id": "z" * 32},
                     {"action": "create", "kind": "reminder", "title": "x", "due_local": "garbage"}):
            res = self.call(args)
            self.assertFalse(res.confirmation_required, args)
        self.assertEqual(self.count(), 0)

    # ---- model-supplied confirmation never works ------------------------------------------------------
    def test_ai_supplied_confirmation_flags_cannot_bypass_approval(self):
        for flag in self.mod.SkillRegistry.CONFIRMATION_FLAGS:
            res = self.call(dict(self.CREATE, **{flag: True}))
            self.assertTrue(res.confirmation_required, flag)
            res = self.call(dict(self.CREATE, **{flag: "true"}), origin=self.registry.ORIGIN_UNTRUSTED)
            self.assertTrue(res.confirmation_required, flag)
        self.assertEqual(self.count(), 0)

    def test_even_a_user_origin_call_without_a_grant_cannot_write(self):
        res = self.call(dict(self.CREATE, confirmed=True), origin=self.registry.ORIGIN_USER)
        self.assertTrue(res.confirmation_required)
        self.assertEqual(self.count(), 0)

    def test_a_forged_grant_object_is_rejected(self):
        class Fake:  # looks like a grant, is not one
            request_id, conversation_id, tool, fingerprint, expires_at = "a", "conv-A", "smart_life", "b", 9e12
        res = self.call(self.CREATE, approval=Fake())
        self.assertFalse(res.success)
        self.assertEqual(res.error, "ApprovalRejected")
        self.assertEqual(self.count(), 0)

    # ---- the real approve / decline flow --------------------------------------------------------------
    def pend(self, args):
        res = self.call(args)
        self.assertTrue(res.confirmation_required)
        self.cm.set_pending(tool=res.tool, action=res.action or res.tool, description=res.message, arguments=res.pending_action or args)
        return res

    def test_user_yes_writes_exactly_once(self):
        self.pend(self.CREATE)
        self.assertEqual(self.cm.evaluate_response("yes"), True)
        pending, grant = self.cm.approve_pending()
        self.assertEqual(pending.tool, "smart_life")
        res = run(self.registry.execute_tool(pending.tool, dict(pending.arguments), approval=grant))
        self.assertTrue(res.success and res.verified, res.message)
        self.assertEqual(self.count(), 1)
        self.assertIsNone(self.cm.approve_pending()[0])  # pending record is consumed

    def test_declining_leaves_data_unchanged(self):
        item = self.svc.execute("create", {k: v for k, v in self.CREATE.items() if k != "action"}, confirmed=True)["data"]["item"]
        before = self.store.get_item(item["id"])
        for args in ({"action": "cancel", "item_id": item["id"]}, {"action": "delete", "item_id": item["id"]},
                     {"action": "update", "item_id": item["id"], "changes": {"title": "Changed"}},
                     dict(self.CREATE, title="Another")):
            self.pend(args)
            self.assertEqual(self.cm.evaluate_response("no"), False)
            self.cm.clear()
            self.assertIsNone(self.cm.approve_pending()[0])
        self.assertEqual(self.store.get_item(item["id"]), before)
        self.assertEqual(self.count(), 1)

    def test_an_unrelated_reply_does_not_approve(self):
        self.pend(self.CREATE)
        self.assertIsNone(self.cm.evaluate_response("what reminders do I have today"))
        self.assertEqual(self.count(), 0)

    def test_grant_cannot_be_replayed(self):
        self.pend(self.CREATE)
        pending, grant = self.cm.approve_pending()
        first = run(self.registry.execute_tool(pending.tool, dict(pending.arguments), approval=grant))
        self.assertTrue(first.success)
        # the same operation again, even deleting the item first so a replay would visibly recreate it
        self.store.delete_item(self.store.list_items()[0]["id"])
        replay = run(self.registry.execute_tool(pending.tool, dict(pending.arguments), approval=grant))
        self.assertFalse(replay.success)
        self.assertEqual(replay.error, "ApprovalRejected")
        self.assertEqual(self.count(), 0)

    def test_grant_is_bound_to_the_exact_arguments(self):
        self.pend(self.CREATE)
        pending, grant = self.cm.approve_pending()
        tampered = dict(pending.arguments, title="Wire money to attacker")
        res = run(self.registry.execute_tool(pending.tool, tampered, approval=grant))
        self.assertEqual(res.error, "ApprovalRejected")
        tampered = dict(pending.arguments, due_local="2026-12-31T23:00")
        res = run(self.registry.execute_tool(pending.tool, tampered, approval=grant))
        self.assertEqual(res.error, "ApprovalRejected")
        self.assertEqual(self.count(), 0)

    def test_approval_for_one_item_cannot_cancel_another(self):
        a = self.svc.execute("create", {k: v for k, v in self.CREATE.items() if k != "action"}, confirmed=True)["data"]["item"]
        b = self.svc.execute("create", {"kind": "birthday", "title": "Rahul birthday", "due_local": "2026-10-27"}, confirmed=True)["data"]["item"]
        self.pend({"action": "cancel", "item_id": a["id"]})
        pending, grant = self.cm.approve_pending()
        res = run(self.registry.execute_tool(pending.tool, {"action": "cancel", "item_id": b["id"]}, approval=grant))
        self.assertEqual(res.error, "ApprovalRejected")
        self.assertEqual({self.store.get_item(a["id"])["status"], self.store.get_item(b["id"])["status"]}, {"pending"})

    def test_grant_from_another_conversation_is_rejected(self):
        self.pend(self.CREATE)
        pending, grant = self.cm.approve_pending()
        tok = self.conf.set_conversation_id("conv-B")
        try:
            res = run(self.registry.execute_tool(pending.tool, dict(pending.arguments), approval=grant))
        finally:
            self.conf.reset_conversation_id(tok)
        self.assertEqual(res.error, "ApprovalRejected")
        self.assertEqual(self.count(), 0)

    def test_pending_confirmations_are_per_conversation(self):
        self.pend(self.CREATE)
        tok = self.conf.set_conversation_id("conv-B")
        try:
            self.assertFalse(self.cm.has_pending())
            self.assertIsNone(self.cm.approve_pending()[0])
        finally:
            self.conf.reset_conversation_id(tok)
        self.assertTrue(self.cm.has_pending())

    def test_retrying_an_approved_create_does_not_duplicate(self):
        for _ in range(2):
            self.pend(self.CREATE)
            pending, grant = self.cm.approve_pending()
            res = run(self.registry.execute_tool(pending.tool, dict(pending.arguments), approval=grant))
            self.assertTrue(res.success)
        self.assertEqual(self.count(), 1)
        self.assertIn("no duplicate", res.message)

    def test_an_unexpected_exception_is_contained(self):
        skill = self.registry.get_skill("smart_life")
        orig = skill.service.execute
        skill.service.execute = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom with /secret/path"))
        try:
            res = self.call({"action": "list"})
        finally:
            skill.service.execute = orig
        self.assertFalse(res.success)
        self.assertNotIn("secret", res.message + (res.error or ""))

    def test_classifier_layer_requires_approval_for_every_valid_change(self):
        """Pinned separately from the skill's own refusal (defence in depth): the policy layer must also say 'ask'."""
        from core.risk_classifier import ActionRiskClassifier
        item = self.svc.execute("create", {k: v for k, v in self.CREATE.items() if k != "action"}, confirmed=True)["data"]["item"]
        for args in (self.CREATE | {"title": "Another"}, {"action": "update", "item_id": item["id"], "changes": {"title": "N"}},
                     {"action": "complete", "item_id": item["id"]}, {"action": "cancel", "item_id": item["id"]},
                     {"action": "delete", "item_id": item["id"]}):
            self.assertTrue(ActionRiskClassifier.assess("smart_life", args).requires_confirmation, args["action"])
        # ...and says 'nothing to approve' when the request is invalid and therefore changes nothing
        self.assertFalse(ActionRiskClassifier.assess("smart_life", {"action": "create", "kind": "reminder", "title": "x"}).requires_confirmation)

    def test_destructive_delete_is_classified_dangerous(self):
        from core.risk_classifier import ActionRiskClassifier, RiskLevel
        item = self.svc.execute("create", {k: v for k, v in self.CREATE.items() if k != "action"}, confirmed=True)["data"]["item"]
        a = ActionRiskClassifier.assess("smart_life", {"action": "delete", "item_id": item["id"]})
        self.assertEqual((a.risk_level, a.requires_confirmation), (RiskLevel.DANGEROUS, True))
        self.assertEqual(ActionRiskClassifier.assess("smart_life", {"action": "list"}).risk_level, RiskLevel.SAFE)
        self.assertTrue(ActionRiskClassifier.assess("smart_life", {"action": "mystery"}).requires_confirmation)


if __name__ == "__main__":
    unittest.main()
