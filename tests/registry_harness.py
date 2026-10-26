"""
Test harness: loads the REAL skills/registry.py source with every concrete skill module stubbed out, so policy
and confirmation behaviour can be tested with fake tools, without httpx/psutil/browsers/desktop access.
"""
import ast
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_registry_module():
    source = (BACKEND / "skills" / "registry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stubbed = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("skills.") and node.module != "skills.base":
            mod = types.ModuleType(node.module)
            for alias in node.names:
                setattr(mod, alias.name, type(alias.name, (), {"name": "stub_" + alias.name, "description": ""}))
            stubbed[node.module] = mod
    saved = {k: sys.modules.get(k) for k in stubbed}
    try:
        sys.modules.update(stubbed)
        marker = "skill_registry = SkillRegistry()"
        assert marker in source
        module = types.ModuleType("skills.registry_under_test")
        exec(compile(source.replace(marker, "skill_registry = None"), "skills/registry.py", "exec"), module.__dict__)
        return module
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def make_fake_skill(base_cls, tool_result_cls, skill_name, calls, result_message="done"):
    """A fake skill that records every call it receives and never touches the real system."""

    class FakeSkill(base_cls):
        name = skill_name
        description = "fake skill for tests"
        parameters = {}

        async def execute(self, arguments):
            calls.append((skill_name, dict(arguments)))
            return tool_result_cls(success=True, verified=True, tool=skill_name, action=skill_name, message=result_message)

    return FakeSkill()
