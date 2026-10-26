"""
Phase 2 regression tests (kept): model-supplied confirmation flags never skip the human prompt.
Superseded in mechanism by tests/test_tool_policy_enforcement.py (approval grants); these remain as a
smaller sanity check against the current API. Isolated: fake skills only, no real files touched.
"""
import asyncio
import unittest

try:
    from tests.registry_harness import load_registry_module, make_fake_skill
except ImportError:  # run directly from the tests directory
    from registry_harness import load_registry_module, make_fake_skill


class ConfirmationFlagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pydantic  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("pydantic not installed in this interpreter; run inside the project venv")
        from skills.base import BaseSkill, ToolResult
        cls.mod = load_registry_module()
        cls.BaseSkill, cls.ToolResult = BaseSkill, ToolResult

    def setUp(self):
        self.calls = []
        self.registry = self.mod.SkillRegistry(register_defaults=False)
        self.registry.register_fixture("delete_file", make_fake_skill(self.BaseSkill, self.ToolResult, "delete_file", self.calls))

    def test_every_flag_alias_is_stripped_and_nothing_runs(self):
        for flag in self.mod.SkillRegistry.CONFIRMATION_FLAGS:
            res = asyncio.run(self.registry.execute_tool("delete_file", {"target_path": "x", flag: True, "permanent": True}))
            self.assertTrue(res.confirmation_required, flag)
        self.assertEqual(self.calls, [])

    def test_caller_dict_not_mutated(self):
        args = {"target_path": "x", "confirmed": True}
        asyncio.run(self.registry.execute_tool("delete_file", args))
        self.assertEqual(args, {"target_path": "x", "confirmed": True})

    def test_unknown_tool_fails_closed(self):
        res = asyncio.run(self.registry.execute_tool("nope", {"confirmed": True}))
        self.assertFalse(res.success)


if __name__ == "__main__":
    unittest.main()
