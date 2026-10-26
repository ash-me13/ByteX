"""
Static (AST) checks of how the FastAPI app is assembled. They need neither FastAPI nor a running server,
so they run anywhere; they do NOT replace a real startup test (see docs/TESTING.md).

Run:  python -m unittest tests.test_app_wiring_static
"""
import ast
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def _calls(path, attr):
    tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def _src(path):
    return (BACKEND / path).read_text(encoding="utf-8")


class AppWiringTests(unittest.TestCase):
    def test_phone_rest_routes_registered_exactly_once(self):
        # api/routes.py mounts them under /api; main.py must not mount the REST router again.
        routes_includes = [ast.unparse(c.args[0]) for c in _calls("api/routes.py", "include_router")]
        self.assertEqual(routes_includes.count("phone_router"), 1)
        main_includes = [ast.unparse(c.args[0]) for c in _calls("main.py", "include_router")]
        self.assertNotIn("phone_router", main_includes)
        self.assertEqual(main_includes.count("phone_ws_router"), 1)

    def test_phone_websocket_not_in_rest_router(self):
        src = _src("api/phone_routes.py")
        self.assertIn('@ws_router.websocket("/ws/phone")', src)
        self.assertNotIn("@router.websocket", src)

    def test_guard_added_after_cors_so_it_runs_first(self):
        order = [ast.unparse(c.args[0]) for c in _calls("main.py", "add_middleware")]
        self.assertEqual(order, ["CORSMiddleware", "LocalOnlyGuardMiddleware"])

    def test_server_binds_loopback_only(self):
        self.assertIsNone(re.search(r"host\s*=\s*[\"']0\.0\.0\.0", _src("main.py")))
        self.assertIn('host="127.0.0.1"', _src("main.py"))
        root = BACKEND.parent
        self.assertIn('"--host", "127.0.0.1"', (root / "start_bytex.py").read_text(encoding="utf-8"))
        self.assertIn("--host 127.0.0.1", (root / "start_bytex.bat").read_text(encoding="utf-8"))

    def test_health_route_exists_for_frontend_checkHealth(self):
        self.assertRegex(_src("api/routes.py"), r'@router\.get\("/health"\)')

    def test_no_hardcoded_windows_user_paths_in_backend(self):
        offenders = []
        for p in BACKEND.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if re.search(r"Users\\\\?ryzzn", p.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(p.relative_to(BACKEND)))
        self.assertEqual(offenders, [])

    def test_no_shell_true_in_app_launcher(self):
        self.assertNotIn("shell=True", _src("skills/apps.py").replace("Never uses `shell=True`", ""))


if __name__ == "__main__":
    unittest.main()
