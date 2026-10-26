"""
Phase 3 regression tests: risk-policy enforcement, confirmation provenance, test-skill separation and
browser-launch configuration. Everything uses FAKE skills, temp directories and a fake clock; no real
file, application, browser or desktop is touched.

Run:  PYTHONPATH=backend python -m unittest tests.test_tool_policy_enforcement
"""
import ast
import asyncio
import contextlib
import re
import tempfile
import unittest
from pathlib import Path

try:
    from tests.registry_harness import BACKEND, load_registry_module, make_fake_skill
except ImportError:
    from registry_harness import BACKEND, load_registry_module, make_fake_skill

try:
    import pydantic  # noqa: F401
    HAVE_PYDANTIC = True
except ImportError:
    HAVE_PYDANTIC = False

needs_pydantic = unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed in this interpreter; run inside the project venv")


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@contextlib.contextmanager
def conversation(cid):
    from core.confirmation import set_conversation_id, reset_conversation_id
    token = set_conversation_id(cid)
    try:
        yield
    finally:
        reset_conversation_id(token)


def run(coro):
    return asyncio.run(coro)


@needs_pydantic
class PolicyBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from skills.base import BaseSkill, ToolResult
        from core.confirmation import ConfirmationManager
        cls.mod = load_registry_module()
        cls.BaseSkill, cls.ToolResult, cls.CM = BaseSkill, ToolResult, ConfirmationManager

    def setUp(self):
        self.calls = []
        self.clock = FakeClock()
        self.cm = self.CM(time_fn=self.clock)
        self.mod.confirmation_manager = self.cm  # registry module uses this manager
        self.registry = self.mod.SkillRegistry(register_defaults=False)
        for n in ["delete_file", "file_operations", "coding_workspace", "terminal_agent", "screen_vision",
                  "download_file", "open_application", "close_application", "browser_control", "website_automation",
                  "clipboard_control", "file_search", "list_files", "web_search", "system_status", "application_status",
                  "create_folder", "rename_file", "move_file", "fill_form", "read_webpage", "take_screenshot",
                  "play_media", "summarize", "research_mode"]:
            self.registry.register_fixture(n, make_fake_skill(self.BaseSkill, self.ToolResult, n, self.calls))
        # aliases exactly like production: several names, one skill
        for alias in ["execute_code", "run_code", "compile", "build", "read_file", "generate_code", "fix_code_error"]:
            self.registry._skills[alias] = self.registry._skills["coding_workspace"]
        for alias in ["click", "type_text", "describe_screen", "visual_click", "read_screen"]:
            self.registry._skills[alias] = self.registry._skills["screen_vision"]
        self.registry._skills["delete"] = self.registry._skills["delete_file"]
        self.registry._skills["download"] = self.registry._skills["download_file"]

    def call(self, name, args=None, **kw):
        return run(self.registry.execute_tool(name, args or {}, **kw))

    def assertNeedsApproval(self, name, args=None):
        before = len(self.calls)
        res = self.call(name, args)
        self.assertTrue(res.confirmation_required, f"{name} {args}")
        self.assertEqual(len(self.calls), before, f"{name} {args} executed without approval")
        self.assertNotIn("confirmed", res.pending_action or {})
        return res

    def assertRuns(self, name, args=None):
        before = len(self.calls)
        res = self.call(name, args)
        self.assertFalse(res.confirmation_required, f"{name} {args}: {res.message}")
        self.assertEqual(len(self.calls), before + 1)
        return res


class RiskMatrixTests(PolicyBase):
    """The tool-risk matrix as executable documentation (model/plan origin)."""

    def test_read_only_runs(self):
        for name, args in [
            ("file_search", {"query": "a"}), ("list_files", {}), ("web_search", {"query": "x"}),
            ("system_status", {}), ("application_status", {"application": "notes"}), ("read_webpage", {"url": "https://example.com"}),
            ("summarize", {}), ("research_mode", {}), ("take_screenshot", {}), ("play_media", {}), ("fill_form", {}),
            ("read_file", {"file_path": "a.py"}), ("generate_code", {"prompt": "hello"}),
            ("terminal_agent", {"operation": "python_version"}), ("terminal_agent", {"operation": "list_directory"}),
            ("screen_vision", {"action": "read_screen"}), ("describe_screen", {}), ("read_screen", {}),
            ("open_application", {"application": "Notes"}), ("browser_control", {"action": "list_tabs"}),
        ]:
            with self.subTest(name=name, args=args):
                self.assertRuns(name, args)

    def test_state_changing_or_high_impact_needs_approval(self):
        for name, args in [
            ("delete_file", {"target_path": "x"}), ("delete", {"target_path": "x", "permanent": True}),
            ("file_operations", {"operation": "delete", "target_path": "x"}),
            ("file_operations", {"operation": "move", "source_path": "a", "destination": "b"}),
            ("rename_file", {}), ("move_file", {}), ("create_folder", {"folder_name": "x"}), ("close_application", {"application": "Notes"}),
            ("download_file", {"url": "https://example.com/a"}), ("download", {"url": "https://example.com/a"}),
            ("website_automation", {}), ("clipboard_control", {"action": "set", "text": "x"}),
            ("browser_control", {"action": "click", "target": "Buy"}),
            ("execute_code", {"file_path": "a.py"}), ("run_code", {}), ("compile", {"file_path": "a.cpp"}), ("build", {}),
            ("fix_code_error", {"file_path": "a.py", "fix_mode": "confirm"}),
            ("terminal_agent", {"operation": "npm_install"}), ("terminal_agent", {"operation": "run_pytest"}),
            ("terminal_agent", {"operation": "start_dev_server"}), ("terminal_agent", {"operation": "something_new"}),
            ("click", {"target": "OK"}), ("type_text", {"text": "hi"}), ("visual_click", {"x": 1, "y": 2}),
            ("open_application", {"application": "/Users/me/Downloads/thing.app"}),
        ]:
            with self.subTest(name=name, args=args):
                self.assertNeedsApproval(name, args)

    def test_inferred_actions_cannot_hide_behind_a_safe_looking_name(self):
        # coding_workspace with file_path and no action is executed by the real skill (it infers execute_code)
        self.assertNeedsApproval("coding_workspace", {"file_path": "a.py"})
        self.assertNeedsApproval("coding_workspace", {"stdin": "x"})
        self.assertNeedsApproval("coding_workspace", {"instruction": "rewrite", "target_text": "x"})
        self.assertNeedsApproval("coding_workspace", {"action": "brand_new_action"})
        # screen_vision "describe" with text / coordinates is typing / clicking in the real skill
        self.assertNeedsApproval("screen_vision", {"action": "describe", "text": "rm -rf"})
        self.assertNeedsApproval("screen_vision", {"action": "analyze_screen", "x": 5, "y": 6})
        self.assertNeedsApproval("screen_vision", {"action": "read_screen", "raw_text": "click delete"})
        self.assertNeedsApproval("screen_vision", {"action": "unknown_future_action"})

    def test_shell_metacharacters_are_blocked_not_prompted(self):
        res = self.call("terminal_agent", {"operation": "list_files", "args": "a; rm -rf /"})
        self.assertFalse(res.success)
        self.assertEqual(res.error, "BlockedByPolicy")
        self.assertEqual(self.calls, [])

    def test_unregistered_tool_is_refused(self):
        res = self.call("totally_made_up", {})
        self.assertFalse(res.success)
        self.assertEqual(self.calls, [])

    def test_classifier_failure_fails_closed_for_model_calls(self):
        from core.risk_classifier import ActionRiskClassifier
        original = ActionRiskClassifier.assess
        ActionRiskClassifier.assess = classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        try:
            self.assertNeedsApproval("file_search", {"query": "a"})
        finally:
            ActionRiskClassifier.assess = original

    def test_user_typed_origin_keeps_skill_own_prompting(self):
        res = run(self.registry.execute_tool("delete_file", {"target_path": "x"}, origin=self.mod.SkillRegistry.ORIGIN_USER))
        self.assertFalse(res.confirmation_required)  # fake skill ran; real skill would return its own prompt
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("confirmed", self.calls[0][1])

    def test_user_origin_still_strips_confirmation_flags(self):
        run(self.registry.execute_tool("delete_file", {"target_path": "x", "confirmed": True}, origin=self.mod.SkillRegistry.ORIGIN_USER))
        self.assertNotIn("confirmed", self.calls[0][1])

    def test_model_cannot_pass_a_risk_level(self):
        res = self.call("delete_file", {"target_path": "x", "risk_level": "SAFE", "requires_confirmation": False, "is_safe": True})
        self.assertTrue(res.confirmation_required)
        self.assertEqual(self.calls, [])


class ConfirmationProvenanceTests(PolicyBase):
    def _request_delete(self, path="victim.txt", **extra):
        res = self.call("delete_file", {"target_path": path, **extra})
        self.assertTrue(res.confirmation_required)
        prompt = self.cm.set_pending(tool=res.tool, action=res.action, description=res.message, arguments=res.pending_action)
        self.assertIn("confirm", prompt.lower())
        return res

    def _user_says_yes(self):
        pending, grant = self.cm.approve_pending()
        return pending, grant

    def test_1_self_confirmed_deletion_does_not_execute(self):
        with conversation("A"):
            self.assertNeedsApproval("delete_file", {"target_path": "v", "confirmed": True, "permanent": True})
            self.assertFalse(self.cm.has_pending())

    def test_2_unapproved_destructive_operation_does_not_execute(self):
        with conversation("A"):
            self._request_delete()
        self.assertEqual(self.calls, [])

    def test_3_wrong_request_id_is_rejected(self):
        with conversation("A"):
            self._request_delete()
            pending, grant = self.cm.approve_pending(request_id="deadbeef")
            self.assertIsNone(pending)
            self.assertIsNone(grant)
            self.assertTrue(self.cm.has_pending())  # still waiting for the real approval

    def test_4_changed_operation_after_approval_needs_new_approval(self):
        with conversation("A"):
            self._request_delete("victim.txt")
            pending, grant = self._user_says_yes()
            res = self.call("delete_file", {"target_path": "OTHER.txt"}, approval=grant)
            self.assertFalse(res.success)
            self.assertEqual(res.error, "ApprovalRejected")
            self.assertEqual(self.calls, [])

    def test_5_consumed_approval_cannot_be_replayed(self):
        with conversation("A"):
            self._request_delete()
            pending, grant = self._user_says_yes()
            first = self.call(pending.tool, dict(pending.arguments), approval=grant)
            self.assertTrue(first.success)
            second = self.call(pending.tool, dict(pending.arguments), approval=grant)
            self.assertEqual(second.error, "ApprovalRejected")
            self.assertEqual(len(self.calls), 1)

    def test_6_expired_confirmation_and_expired_grant(self):
        with conversation("A"):
            self._request_delete()
            self.clock.now += 301
            self.assertEqual(self.cm.approve_pending(), (None, None))
            self._request_delete()
            pending, grant = self._user_says_yes()
            self.clock.now += 61
            res = self.call(pending.tool, dict(pending.arguments), approval=grant)
            self.assertEqual(res.error, "ApprovalRejected")
            self.assertEqual(self.calls, [])

    def test_7_two_connections_keep_separate_pending_actions(self):
        with conversation("A"):
            self._request_delete("a.txt")
        with conversation("B"):
            self._request_delete("b.txt")
        with conversation("A"):
            self.assertEqual(self.cm.get_pending().arguments["target_path"], "a.txt")
        with conversation("B"):
            self.assertEqual(self.cm.get_pending().arguments["target_path"], "b.txt")

    def test_8_yes_from_connection_a_cannot_authorize_connection_b(self):
        with conversation("B"):
            self._request_delete("b.txt")
        with conversation("A"):
            self.assertEqual(self.cm.approve_pending(), (None, None))  # A has nothing pending
        with conversation("B"):
            self.assertTrue(self.cm.has_pending())
        # a grant obtained in A is useless in B even for the identical operation
        with conversation("A"):
            grant = self.cm.issue_user_approval("delete_file", {"target_path": "b.txt"})
        with conversation("B"):
            res = self.call("delete_file", {"target_path": "b.txt"}, approval=grant)
            self.assertEqual(res.error, "ApprovalRejected")
        self.assertEqual(self.calls, [])

    def test_9_legitimate_user_approval_completes_exactly_once(self):
        with conversation("A"):
            self._request_delete("ok.txt", permanent=True)
            pending, grant = self._user_says_yes()
            res = self.call(pending.tool, dict(pending.arguments), approval=grant)
            self.assertTrue(res.success)
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(self.calls[0][1]["confirmed"])  # set by trusted code only, after verification
            self.assertFalse(self.cm.has_pending())

    def test_forged_grant_objects_are_rejected(self):
        from core.confirmation import ApprovalGrant, operation_fingerprint
        with conversation("A"):
            fp = operation_fingerprint("delete_file", {"target_path": "x"})
            forged = ApprovalGrant("r" * 32, "A", "delete_file", fp, self.clock.now + 60, "0" * 64)
            self.assertEqual(self.call("delete_file", {"target_path": "x"}, approval=forged).error, "ApprovalRejected")
            for junk in (True, "yes", {"approved": True}, 1):
                self.assertEqual(self.call("delete_file", {"target_path": "x"}, approval=junk).error, "ApprovalRejected")
        self.assertEqual(self.calls, [])

    def test_assistant_text_saying_yes_is_not_an_approval(self):
        # Only trusted code calls approve_pending(); model text never reaches evaluate_response/approve_pending.
        with conversation("A"):
            self._request_delete()
            self.assertEqual(self.calls, [])
            self.assertTrue(self.cm.has_pending())

    def test_new_request_supersedes_only_its_own_conversation(self):
        with conversation("A"):
            self._request_delete("first.txt")
            self._request_delete("second.txt")
            self.assertEqual(self.cm.get_pending().arguments["target_path"], "second.txt")
        with conversation("B"):
            self.assertIsNone(self.cm.get_pending())


class PlanResumeTests(PolicyBase):
    def test_10_plan_resumes_only_the_exact_step_the_user_approved(self):
        from core.confirmation import operation_fingerprint  # noqa: F401  (documented dependency)
        with conversation("A"):
            # step 1 and step 2 both need approval; the user approves step 2 only
            grant_for_2 = self.cm.issue_user_approval("delete_file", {"target_path": "step2.txt"})
            r1 = self.call("delete_file", {"target_path": "step1.txt"}, approval=grant_for_2)
            self.assertEqual(r1.error, "ApprovalRejected")  # step 1 args differ -> not covered
            self.assertEqual(self.calls, [])
            r2 = self.call("delete_file", {"target_path": "step2.txt"}, approval=grant_for_2)
            self.assertTrue(r2.success)
            self.assertEqual([c[1]["target_path"] for c in self.calls], ["step2.txt"])

    def test_executor_source_binds_approval_to_the_step(self):
        src = (BACKEND / "agent" / "executor.py").read_text(encoding="utf-8") if (BACKEND / "agent" / "executor.py").exists() else None
        if src is None:
            self.skipTest("agent/executor.py not present in this checkout")
        self.assertIn("approvals.get(step.step_id)", src)
        self.assertIn("issue_user_approval(target_step.suggested_skill, target_step.arguments)", src)
        self.assertNotIn("user_confirmed", src)
        self.assertNotIn('{"confirmed": True', src)


class ProductionRegistryTests(unittest.TestCase):
    EXPECTED_CLASSES = {
        "OpenApplicationSkill", "CloseApplicationSkill", "ApplicationStatusSkill", "OpenWebsiteSkill",
        "TakeScreenshotSkill", "SystemStatusSkill", "WebSearchSkill", "ReadWebpageSkill", "FormFillingSkill",
        "DownloadFileSkill", "WebsiteAutomationSkill", "ResearchModeSkill", "SummarizeSkill", "PlayMediaSkill",
        "DesktopClipboardSkill", "ScreenVisionSkill", "CodingWorkspaceSkill", "TerminalAgentSkill",
        "ListFilesSkill", "FileSearchSkill", "FileOperationsSkill", "CreateFolderSkill", "CreateFileSkill",
        "RenameFileSkill", "MoveFileSkill", "CopyFileSkill", "DeleteFileSkill",
        "SmartLifeSkill",  # SMART LIFE reminders: reviewed addition; reads are SAFE, every change needs approval (see tests/test_smartlife_tools.py)
    }

    def _registry_source(self):
        return (BACKEND / "skills" / "registry.py").read_text(encoding="utf-8")

    def test_default_registration_is_exactly_the_reviewed_production_set(self):
        tree = ast.parse(self._registry_source())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_register_default_skills")
        listed = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "skills":
                listed = {e.func.id for e in node.value.elts if isinstance(e, ast.Call)}
        self.assertEqual(listed, self.EXPECTED_CLASSES)

    def test_test_fixtures_are_not_imported_or_registered_in_production(self):
        src = self._registry_source()
        for forbidden in ("risky_test", "RiskyTestActionSkill", "MockVerificationFailureSkill", "risky_test_action"):
            self.assertNotIn(forbidden, src)

    def test_no_environment_switch_can_enable_test_tools(self):
        src = self._registry_source()
        self.assertIsNone(re.search(r"os\.environ|getenv|environ\[", src))

    def test_router_no_longer_routes_a_phrase_to_the_test_skill(self):
        self.assertNotIn("risky_test_action", (BACKEND / "core" / "command_router.py").read_text(encoding="utf-8"))

    def test_only_tests_call_register_fixture(self):
        offenders = []
        for path in BACKEND.rglob("*.py"):
            if "register_fixture(" in path.read_text(encoding="utf-8", errors="ignore") and path.name not in ("registry.py", "risky_test.py"):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    @needs_pydantic
    def test_isolated_registry_accepts_fixtures_without_touching_production_defaults(self):
        from skills.base import BaseSkill, ToolResult
        mod = load_registry_module()
        calls = []
        iso = mod.SkillRegistry(register_defaults=False)
        self.assertEqual(iso.list_skills(), {})
        iso.register_fixture("risky_test_action", make_fake_skill(BaseSkill, ToolResult, "risky_test_action", calls))
        self.assertIn("risky_test_action", iso.list_skills())
        other = mod.SkillRegistry(register_defaults=False)
        self.assertNotIn("risky_test_action", other.list_skills())

    @needs_pydantic
    def test_fixture_is_still_gated_by_policy(self):
        from skills.base import BaseSkill, ToolResult
        mod = load_registry_module()
        calls = []
        iso = mod.SkillRegistry(register_defaults=False)
        iso.register_fixture("risky_test_action", make_fake_skill(BaseSkill, ToolResult, "risky_test_action", calls))
        res = run(iso.execute_tool("risky_test_action", {"confirmed": True}))
        self.assertTrue(res.confirmation_required)
        self.assertEqual(calls, [])


class BrowserLaunchTests(unittest.TestCase):
    def setUp(self):
        from security import browser_launch
        self.bl = browser_launch

    def test_flags_pin_loopback_and_dedicated_profile(self):
        flags = self.bl.build_cdp_launch_flags(9222, "/tmp/ByteX_Edge_Profile")
        self.assertIn("--remote-debugging-port=9222", flags)
        self.assertIn("--remote-debugging-address=127.0.0.1", flags)
        self.assertIn("--user-data-dir=/tmp/ByteX_Edge_Profile", flags)
        self.assertFalse(any("0.0.0.0" in f for f in flags))

    def test_invalid_ports_and_missing_profile_are_refused(self):
        for bad in (0, -1, 80, 70000, "9222", None, True):
            with self.assertRaises(ValueError):
                self.bl.build_cdp_launch_flags(bad, "/tmp/p")
        with self.assertRaises(ValueError):
            self.bl.build_cdp_launch_flags(9222, "")

    def test_cdp_url_is_loopback_only(self):
        self.assertEqual(self.bl.cdp_base_url(9223), "http://127.0.0.1:9223")

    def test_cleanup_terminates_only_tracked_running_processes(self):
        class Proc:
            def __init__(self, running):
                self.running, self.terminated, self.killed = running, False, False

            def poll(self):
                return None if self.running else 0

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.killed = True

        tracker = self.bl.LaunchedBrowserTracker()
        a, b = Proc(True), Proc(False)
        tracker.add(a)
        tracker.add(b)
        self.assertEqual(tracker.terminate_all(), 1)
        self.assertTrue(a.terminated)
        self.assertFalse(b.terminated)
        self.assertEqual(tracker.count, 0)

    def test_cleanup_kills_process_that_ignores_terminate(self):
        class Stubborn:
            killed = False

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                raise TimeoutError()

            def kill(self):
                Stubborn.killed = True

        tracker = self.bl.LaunchedBrowserTracker()
        tracker.add(Stubborn())
        tracker.terminate_all()
        self.assertTrue(Stubborn.killed)

    def test_close_on_exit_can_be_disabled_explicitly(self):
        import os
        tracker = self.bl.LaunchedBrowserTracker()

        class P:
            terminated = False

            def poll(self):
                return None

            def terminate(self):
                P.terminated = True

            def wait(self, timeout=None):
                return 0

        tracker.add(P())
        os.environ["BYTEX_BROWSER_CLOSE_ON_EXIT"] = "0"
        try:
            self.assertEqual(tracker.terminate_all(), 0)
            self.assertFalse(P.terminated)
        finally:
            os.environ.pop("BYTEX_BROWSER_CLOSE_ON_EXIT", None)

    def test_browser_skill_uses_the_helper_and_has_no_raw_debug_flag(self):
        src = (BACKEND / "skills" / "browser.py").read_text(encoding="utf-8")
        self.assertIn("build_cdp_launch_flags(", src)
        self.assertIn("launched_browsers.add(", src)
        self.assertNotIn('"--remote-debugging-port=', src)
        self.assertNotIn("f\"--remote-debugging-port=", src)


class WiringTests(unittest.TestCase):
    def _src(self, rel):
        return (BACKEND / rel).read_text(encoding="utf-8")

    def test_router_approval_comes_only_from_approve_pending(self):
        src = self._src("core/command_router.py")
        self.assertIn("confirmation_manager.approve_pending()", src)
        self.assertIn("approval=approval", src)
        self.assertNotIn("user_confirmed", src)
        self.assertNotIn('{"confirmed": True, **pending.arguments}', src)

    def test_router_user_commands_are_marked_user_origin(self):
        src = self._src("core/command_router.py")
        self.assertEqual(len(re.findall(r"execute_tool\([^)]*origin=skill_registry\.ORIGIN_USER", src)), 2)

    def test_assistant_model_path_stays_untrusted_and_asks_the_user(self):
        src = self._src("core/assistant.py")
        self.assertNotIn("ORIGIN_USER", src)
        self.assertNotIn("approval=", src)
        self.assertIn("tool_res.confirmation_required", src)

    def test_websocket_binds_a_conversation_per_connection(self):
        src = self._src("api/websocket.py")
        self.assertIn("set_conversation_id(", src)
        self.assertLess(src.index("set_conversation_id("), src.index("await manager.connect(websocket)"))

    def test_rest_chat_uses_its_own_conversation(self):
        self.assertIn('set_conversation_id("http-chat")', self._src("api/routes.py"))

    def test_no_module_other_than_executor_and_router_issues_approvals(self):
        issuers = []
        for path in BACKEND.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\b(approve_pending|issue_user_approval)\(", text) and path.name != "confirmation.py":
                issuers.append(path.relative_to(BACKEND).as_posix())
        self.assertEqual(sorted(issuers), ["agent/executor.py", "core/command_router.py"])


if __name__ == "__main__":
    unittest.main()
