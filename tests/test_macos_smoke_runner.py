"""
Regression tests for scripts/macos_runtime_smoke.py (stdlib only; nothing here touches the real clipboard, browser,
screen or ByteX data). They check the runner's safety behaviour, NOT macOS features.

Run from the repo root:  PYTHONPATH=backend python3 -m unittest tests.test_macos_smoke_runner -v
"""
import asyncio
import contextlib
import glob
import importlib.util
import inspect
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO / "scripts" / "macos_runtime_smoke.py"
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_runner():
    spec = importlib.util.spec_from_file_location("macos_runtime_smoke_under_test", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = load_runner()


def run_py(code: str):
    env = dict(os.environ, PYTHONPATH=str(BACKEND))
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=60)


class FakeClipboard:
    def __init__(self, text):
        self.text = text
        self.copy_calls = []

    def paste(self):
        return self.text

    def copy(self, value):
        self.copy_calls.append(value)
        self.text = value


class Res:
    def __init__(self, success=True, verified=True):
        self.success, self.verified = success, verified


def run_roundtrip(paste, copy, write):
    records, out = [], io.StringIO()
    with contextlib.redirect_stdout(out):
        asyncio.run(runner.clipboard_roundtrip(paste, copy, write, lambda n, s, d: records.append((n, s, d))))
    return records, out.getvalue()


class ImportAndNonMacOSTests(unittest.TestCase):
    def test_import_has_no_side_effects(self):
        fresh = load_runner()
        self.assertIsNone(fresh._STATE["tmp"], "temp dir must not exist at import time")

    def test_refuses_non_macos_before_creating_anything(self):
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "bytex_smoke_*")))
        out = io.StringIO()
        with mock.patch.object(runner.platform, "system", return_value="Linux"), \
                mock.patch.object(runner.tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp called on non-macOS")), \
                mock.patch.object(runner, "isolate_user_data", side_effect=AssertionError("isolation ran on non-macOS")), \
                contextlib.redirect_stdout(out):
            rc = asyncio.run(runner.main(["--compile", "--all"]))
        self.assertEqual(rc, 2)
        self.assertIn("not macOS", out.getvalue())
        self.assertIsNone(runner._STATE["tmp"])
        self.assertEqual(before, set(glob.glob(os.path.join(tempfile.gettempdir(), "bytex_smoke_*"))))

    def test_macos_without_flags_prints_help_and_creates_nothing(self):
        with mock.patch.object(runner.platform, "system", return_value="Darwin"), \
                mock.patch.object(runner.tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp called")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(asyncio.run(runner.main([])), 0)

    def test_isolation_failure_fails_closed_and_runs_no_test(self):
        tmp = Path(tempfile.mkdtemp(prefix="smoke_unit_"))
        fakes = {n: mock.AsyncMock() for n in ("smoke_compile", "smoke_screenshot", "smoke_clipboard", "smoke_browser")}
        runner.results.clear()
        try:
            with mock.patch.object(runner.platform, "system", return_value="Darwin"), \
                    mock.patch.object(runner, "setup_workdir", return_value=tmp), \
                    mock.patch.object(runner, "isolate_user_data", side_effect=RuntimeError("boom")), \
                    mock.patch.multiple(runner, **fakes), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(runner.main(["--all"]))
            self.assertEqual(rc, 1)
            for name, f in fakes.items():
                f.assert_not_called()
            self.assertEqual(runner.results[-1][1], "BLOCKED")
        finally:
            runner.results.clear()
            tmp.rmdir()


class IsolationTests(unittest.TestCase):
    def test_db_and_audit_log_redirected_and_real_files_untouched(self):
        proc = run_py(f"""
            import importlib.util, tempfile
            from pathlib import Path
            spec = importlib.util.spec_from_file_location("r", r"{RUNNER_PATH}")
            r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
            tmp = Path(tempfile.mkdtemp(prefix="smoke_iso_")).resolve()
            before = r.real_data_fingerprint()
            r.isolate_user_data(tmp)
            from memory.database import db_manager
            from security.audit_logger import audit_logger
            assert tmp in Path(db_manager.db_path).resolve().parents, db_manager.db_path
            assert tmp in Path(audit_logger.log_file).resolve().parents, audit_logger.log_file
            audit_logger.log_action("smoke_isolation_test", "ok", "unit test entry")
            with db_manager.get_connection() as c:
                c.execute("CREATE TABLE IF NOT EXISTS isolation_probe (x)")
                c.execute("INSERT INTO isolation_probe VALUES (1)")
            assert (tmp / "backend" / "bytex_memory.db").exists()
            assert "smoke_isolation_test" in (tmp / "backend" / "storage" / "action_logs.json").read_text()
            assert r.real_data_fingerprint() == before, "real ByteX data changed"
            r.assert_isolated(tmp)
            print("ISOLATION_OK")
        """)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ISOLATION_OK", proc.stdout)

    def test_isolation_refuses_if_modules_already_imported(self):
        proc = run_py(f"""
            import importlib.util, sys, tempfile, types
            from pathlib import Path
            spec = importlib.util.spec_from_file_location("r", r"{RUNNER_PATH}")
            r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
            sys.modules["memory.database"] = types.ModuleType("memory.database")  # stand-in; real DB never opened
            try:
                r.isolate_user_data(Path(tempfile.mkdtemp()))
            except RuntimeError as e:
                print("REFUSED", e)
            else:
                raise SystemExit("isolation should have refused")
        """)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("REFUSED", proc.stdout)

    def test_assert_isolated_detects_foreign_instances(self):
        proc = run_py(f"""
            import importlib.util, sys, tempfile, types
            from pathlib import Path
            spec = importlib.util.spec_from_file_location("r", r"{RUNNER_PATH}")
            r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
            tmp = Path(tempfile.mkdtemp(prefix="smoke_iso2_")).resolve()
            r.isolate_user_data(tmp)
            class DatabaseManager:  # a second instance bound to some other (e.g. real) database
                db_path = tmp / "backend" / "elsewhere.db"
            other = types.ModuleType("some_late_module"); other.db_manager = DatabaseManager()
            sys.modules["some_late_module"] = other
            try:
                r.assert_isolated(tmp)
            except RuntimeError as e:
                print("DETECTED", e)
            else:
                raise SystemExit("foreign instance not detected")
        """)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DETECTED", proc.stdout)

    def test_isolation_runs_before_any_bytex_import(self):
        src = inspect.getsource(runner.main)
        self.assertLess(src.index("isolate_user_data"), src.index("preload_bytex"))
        self.assertLess(src.index("preload_bytex"), src.index("smoke_compile"))
        top_level = [l for l in RUNNER_PATH.read_text().splitlines() if l.startswith(("import ", "from "))]
        for l in top_level:
            for banned in ("skills", "core", "memory", "security", "agent"):
                self.assertFalse(l.split()[1].split(".")[0] == banned, f"top-level ByteX import: {l}")


class BrowserLifetimeTests(unittest.TestCase):
    def test_keep_browser_open_disables_exit_cleanup_for_this_run_only(self):
        from security.browser_launch import LaunchedBrowserTracker, close_on_exit_enabled

        class FakeProc:
            terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.terminated = True

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch("atexit.register"):
            os.environ.pop("BYTEX_BROWSER_CLOSE_ON_EXIT", None)
            self.assertTrue(close_on_exit_enabled(), "ByteX default must stay: close ByteX-launched browsers on exit")
            normal = LaunchedBrowserTracker(); p1 = FakeProc(); normal.add(p1)
            self.assertEqual(normal.terminate_all(), 1)
            self.assertTrue(p1.terminated, "normal ByteX lifecycle must be unchanged")

            self.assertTrue(runner.keep_browser_open())
            self.assertEqual(os.environ["BYTEX_BROWSER_CLOSE_ON_EXIT"], "0")
            smoke = LaunchedBrowserTracker(); p2 = FakeProc(); smoke.add(p2)
            self.assertEqual(smoke.terminate_all(), 0)
            self.assertFalse(p2.terminated, "browser must survive the runner's exit-time cleanup")
        self.assertNotEqual(os.environ.get("BYTEX_BROWSER_CLOSE_ON_EXIT"), "0", "patch.dict must restore the environment")

    def test_browser_step_disables_cleanup_before_launching_and_never_terminates(self):
        src = inspect.getsource(runner.smoke_browser)
        self.assertLess(src.index("keep_browser_open()"), src.index("browser_control"))
        self.assertNotIn("terminate", RUNNER_PATH.read_text().replace("terminate exit-time", ""))
        self.assertNotIn("launched_browsers", RUNNER_PATH.read_text())
        self.assertIsNone(re.search(r"(?<![A-Za-z_])kill\(", RUNNER_PATH.read_text()))  # not matching e.g. get_skill(
        self.assertIn("LEFT RUNNING", src)


class ClipboardRestorationTests(unittest.TestCase):
    SECRET = "SECRET-PREVIOUS-CLIPBOARD-XYZ"

    def test_success_restores_and_verifies_text(self):
        clip = FakeClipboard(self.SECRET)

        async def write(text):
            clip.copy(text)
            return Res()

        records, out = run_roundtrip(clip.paste, clip.copy, write)
        by_name = {n: s for n, s, _ in records}
        self.assertEqual(by_name["D1. Clipboard write (pyperclip -> pbcopy)"], "PASS — AUTOMATED")
        self.assertEqual(by_name["D0. Clipboard restoration (text only)"], "PASS — AUTOMATED")
        self.assertEqual(clip.text, self.SECRET)

    def test_warns_text_only_and_never_prints_previous_contents(self):
        clip = FakeClipboard(self.SECRET)

        async def write(text):
            clip.copy(text)
            return Res()

        records, out = run_roundtrip(clip.paste, clip.copy, write)
        self.assertIn("only plain TEXT", out)
        self.assertIn("NOT preserved", out)
        self.assertIn("kill -9", out)
        self.assertNotIn(self.SECRET, out + repr(records))
        detail = [d for n, s, d in records if n.startswith("D0")][0]
        self.assertIn("non-text clipboard data is not preserved", detail)

    def test_restore_still_happens_when_the_write_raises(self):
        clip = FakeClipboard(self.SECRET)

        async def write(text):
            clip.copy(text)
            raise RuntimeError("tool exploded")

        records, _ = run_roundtrip(clip.paste, clip.copy, write)
        by_name = {n: s for n, s, _ in records}
        self.assertEqual(by_name["D1. Clipboard write (pyperclip -> pbcopy)"], "FAIL")
        self.assertEqual(by_name["D0. Clipboard restoration (text only)"], "PASS — AUTOMATED")
        self.assertEqual(clip.text, self.SECRET)

    def test_failed_write_is_not_reported_as_pass(self):
        clip = FakeClipboard(self.SECRET)

        async def write(text):
            return Res(success=True)  # claims success but the clipboard never changed

        records, _ = run_roundtrip(clip.paste, clip.copy, write)
        self.assertEqual([s for n, s, _ in records if n.startswith("D1")], ["FAIL"])

    def test_restore_mismatch_is_reported_as_fail(self):
        clip = FakeClipboard(self.SECRET)

        def lossy_copy(value):  # restore silently does nothing
            if value == runner.CLIP_TEXT:
                clip.text = value

        async def write(text):
            lossy_copy(text)
            return Res()

        records, out = run_roundtrip(clip.paste, lossy_copy, write)
        status, detail = [(s, d) for n, s, d in records if n.startswith("D0")][0]
        self.assertEqual(status, "FAIL")
        self.assertIn("MISMATCH", detail)
        self.assertIn("still the test string: True", detail)
        self.assertNotIn(self.SECRET, out + repr(records))

    def test_restore_exception_is_reported_as_fail(self):
        clip = FakeClipboard(self.SECRET)

        def copy(value):
            if value != runner.CLIP_TEXT:
                raise OSError("pbcopy failed")
            clip.text = value

        async def write(text):
            copy(text)
            return Res()

        records, _ = run_roundtrip(clip.paste, copy, write)
        status, detail = [(s, d) for n, s, d in records if n.startswith("D0")][0]
        self.assertEqual(status, "FAIL")
        self.assertIn("OSError", detail)

    def test_readback_failure_after_restore_is_unverified_fail(self):
        status, detail = runner.restore_text_clipboard("abc", mock.Mock(side_effect=OSError("x")), lambda v: None)
        self.assertEqual(status, "FAIL")
        self.assertIn("UNVERIFIED", detail)

    def test_unreadable_clipboard_blocks_and_writes_nothing(self):
        wrote = []

        async def write(text):
            wrote.append(text)
            return Res()

        records, _ = run_roundtrip(mock.Mock(side_effect=OSError("no pbpaste")), lambda v: wrote.append(v), write)
        self.assertEqual([s for _, s, _ in records], ["BLOCKED"])
        self.assertEqual(wrote, [])


class OriginConstantTests(unittest.TestCase):
    def test_runner_uses_registry_origin_constant(self):
        src = RUNNER_PATH.read_text()
        self.assertNotIn('origin="user"', src)
        self.assertNotIn("origin='user'", src)
        self.assertGreaterEqual(src.count("origin=skill_registry.ORIGIN_USER"), 3)  # screenshot, clipboard write, browser
        reg = (BACKEND / "skills" / "registry.py").read_text()
        self.assertIn('ORIGIN_USER = "user"', reg)
        self.assertIn("class SkillRegistry", reg)


class KeepArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="smoke_keep_")).resolve()
        self.shot = self.tmp / "screenshots" / "shot.png"
        self.shot.parent.mkdir()
        self.shot.write_bytes(b"not a real image")
        runner._STATE["tmp"] = self.tmp
        self.addCleanup(runner._STATE.update, tmp=None, keep_artifacts=False)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run_screenshot(self, keep, data):
        class FakeRegistry:
            ORIGIN_USER = "user"

            async def execute_tool(self, name, args, origin=None):
                return types.SimpleNamespace(success=True, verified=True, message="ok", data=data)

        fake_mod = types.ModuleType("skills.registry"); fake_mod.skill_registry = FakeRegistry()
        runner._STATE["keep_artifacts"] = keep
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"skills": types.ModuleType("skills"), "skills.registry": fake_mod}), \
                contextlib.redirect_stdout(out):
            asyncio.run(runner.smoke_screenshot())
        runner.results.clear()
        return out.getvalue()

    def test_flag_is_parsed_and_defaults_off(self):
        seen = []

        async def spy():
            seen.append(runner._STATE["keep_artifacts"])

        for argv, expected in ((["--screenshot"], False), (["--screenshot", "--keep-artifacts"], True)):
            with mock.patch.object(runner.platform, "system", return_value="Darwin"), \
                    mock.patch.object(runner, "setup_workdir", return_value=self.tmp), \
                    mock.patch.object(runner, "isolate_user_data"), mock.patch.object(runner, "preload_bytex"), \
                    mock.patch.object(runner, "smoke_screenshot", spy), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(asyncio.run(runner.main(argv)), 0)
            self.assertEqual(seen[-1], expected)

    def test_flag_prints_exact_path_and_keeps_everything(self):
        out = self._run_screenshot(True, {"path": str(self.shot), "size": 16})
        self.assertIn(f"KEEP-ARTIFACTS screenshot file: {self.shot}", out)
        self.assertIn(f"run directory kept (this script does not delete it): {self.tmp}", out)
        self.assertTrue(self.shot.is_file() and self.tmp.is_dir())

    def test_without_flag_output_and_cleanup_unchanged(self):
        out = self._run_screenshot(False, {"path": str(self.shot), "size": 16})
        self.assertNotIn("KEEP-ARTIFACTS", out)
        self.assertIn(f"Delete when done: rm -rf '{self.tmp}'", out)
        self.assertTrue(self.shot.is_file() and self.tmp.is_dir())

    def test_flag_reports_when_no_screenshot_was_produced(self):
        for data in (None, {}, {"path": str(self.tmp / "missing.png")}):
            out = self._run_screenshot(True, data)
            self.assertIn("no screenshot file was produced", out)
            self.assertNotIn("screenshot file:", out)

    def test_runner_never_deletes_anything(self):
        src = RUNNER_PATH.read_text()
        for banned in ("rmtree", "unlink(", "os.remove", "os.rmdir", ".rmdir(", "TemporaryDirectory"):
            self.assertNotIn(banned, src)

    def test_flag_alone_or_on_non_macos_creates_nothing(self):
        with mock.patch.object(runner.tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp called")), \
                contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(runner.platform, "system", return_value="Darwin"):
                self.assertEqual(asyncio.run(runner.main(["--keep-artifacts"])), 0)
            with mock.patch.object(runner.platform, "system", return_value="Linux"):
                self.assertEqual(asyncio.run(runner.main(["--screenshot", "--keep-artifacts"])), 2)


if __name__ == "__main__":
    unittest.main()
