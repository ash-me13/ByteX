#!/usr/bin/env python3
"""
ByteX macOS runtime smoke test (run it yourself on the Mac, inside the project venv).

It calls the REAL ByteX code paths with harmless inputs and prints what actually happened. It stages and commits
nothing, never prints clipboard history, screenshots or secrets, and keeps ByteX's own data out of the way:

  * Test artifacts (C++ project, screenshot) go to a temp directory that is created only AFTER the macOS check.
  * ByteX's memory database and audit log are redirected to that temp directory before any ByteX module that uses
    them is imported, and the run verifies the redirect (fails closed) and fingerprints your real
    backend/bytex_memory.db and backend/storage/action_logs.json before/after to show they were not written.
  * The clipboard test only preserves plain TEXT (see clipboard_roundtrip); the restore is verified by read-back.
    Forced termination (kill -9, power loss) can skip the cleanup, so a stray test string may remain on the clipboard.
  * --browser leaves the browser it started running so you can look at the page (this runner only; ByteX's normal
    "close ByteX-launched browsers on exit" behaviour is unchanged).

  .venv/bin/python scripts/macos_runtime_smoke.py --compile
  .venv/bin/python scripts/macos_runtime_smoke.py --screenshot --clipboard
  .venv/bin/python scripts/macos_runtime_smoke.py --browser       (starts/uses ByteX's own Edge/Chrome/Brave profile)
  .venv/bin/python scripts/macos_runtime_smoke.py --screenshot --keep-artifacts   (also print the exact screenshot path)
  .venv/bin/python scripts/macos_runtime_smoke.py --all

Real GUI outcomes (text appearing after a paste, how a screenshot looks, a page showing in the browser) cannot be
observed by a script; those lines are printed as PENDING MANUAL VERIFICATION with exact steps.
"""
import argparse
import asyncio
import hashlib
import importlib
import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "backend" / "bytex_memory.db"
REAL_AUDIT_LOG = ROOT / "backend" / "storage" / "action_logs.json"

CPP = '#include <iostream>\n\nint main() {\n    std::cout << "ByteX C++ works!" << std::endl;\n    std::cout << 10 + 20 << std::endl;\n    return 0;\n}\n'
EXPECTED_STDOUT = "ByteX C++ works!\n30"
CLIP_TEXT = "ByteX clipboard test 123"
results = []
_STATE = {"tmp": None, "browser_name": "edge", "keep_artifacts": False}


def record(name, status, detail):
    results.append((name, status, detail))
    print(f"[{status}] {name}: {detail}")


def ensure_backend_on_path():
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def tmp_dir() -> Path:
    if _STATE["tmp"] is None:
        raise RuntimeError("temp directory requested before setup_workdir()")
    return _STATE["tmp"]


def setup_workdir() -> Path:
    """Create the temp directory (called only after the macOS check) and point the screenshot skill at it."""
    _STATE["tmp"] = Path(tempfile.mkdtemp(prefix="bytex_smoke_")).resolve()
    os.environ["BYTEX_SCREENSHOT_DIR"] = str(_STATE["tmp"] / "screenshots")  # read at skill import time
    return _STATE["tmp"]


# ---------------------------------------------------------------------------------------------------------------
# Fix 1: keep ByteX's memory DB and audit log out of the real backend/ directory.
# memory/database.py and security/audit_logger.py build their paths from `Path(__file__)` at import time and create
# `db_manager` / `audit_logger` at import time; there is no environment variable or constructor hook. So the REAL
# source files are executed with `__file__` pointing into the temp dir (same code, redirected paths) BEFORE anything
# else imports them. The redirect is then verified, and the run aborts if any module holds a non-temp instance.
# ---------------------------------------------------------------------------------------------------------------
def _load_with_redirected_file(modname: str, real_path: Path, fake_file: Path):
    importlib.import_module(modname.rpartition(".")[0])  # package __init__ (a comment-only file; verified)
    spec = importlib.util.spec_from_file_location(modname, str(real_path))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(fake_file)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    setattr(sys.modules[modname.rpartition(".")[0]], modname.rpartition(".")[2], module)
    return module


def assert_isolated(tmp_root: Path) -> None:
    """Raise RuntimeError unless every loaded db_manager / audit_logger writes inside tmp_root."""
    tmp_root = Path(tmp_root).resolve()
    db_mod = sys.modules.get("memory.database")
    log_mod = sys.modules.get("security.audit_logger")
    if db_mod is None or log_mod is None:
        raise RuntimeError("isolation not applied: memory.database / security.audit_logger not loaded by the runner")
    db, log = db_mod.db_manager, log_mod.audit_logger
    for label, p in (("memory database", db.db_path), ("audit log", log.log_file)):
        rp = Path(p).resolve()
        if tmp_root not in rp.parents:
            raise RuntimeError(f"isolation failed: {label} path is outside the temp dir: {rp}")
    for name, mod in list(sys.modules.items()):
        if mod is None or name in ("memory.database", "security.audit_logger"):
            continue
        for attr, expected, cls in (("db_manager", db, "DatabaseManager"), ("audit_logger", log, "AuditLogger")):
            try:
                val = getattr(mod, attr, None)
            except Exception:
                continue
            if val is not None and type(val).__name__ == cls and val is not expected:
                raise RuntimeError(f"isolation failed: module {name} holds a different {cls}")


def isolate_user_data(tmp_root: Path):
    tmp_root = Path(tmp_root).resolve()
    for m in ("memory.database", "security.audit_logger"):
        if m in sys.modules:
            raise RuntimeError(f"isolation must run before {m} is imported (already loaded)")
    ensure_backend_on_path()
    (tmp_root / "backend" / "storage").mkdir(parents=True, exist_ok=True)
    backend = ROOT / "backend"
    _load_with_redirected_file("memory.database", backend / "memory" / "database.py", tmp_root / "backend" / "memory" / "database.py")
    _load_with_redirected_file("security.audit_logger", backend / "security" / "audit_logger.py", tmp_root / "backend" / "security" / "audit_logger.py")
    assert_isolated(tmp_root)


def real_data_fingerprint():
    out = {}
    for p in (REAL_DB, REAL_AUDIT_LOG):
        try:
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        except Exception as e:
            out[p.name] = f"unreadable:{type(e).__name__}"
    return out


def preload_bytex(tmp_root: Path) -> None:
    """Import ByteX the way the app does, then re-verify that nothing bound a non-temp DB/log."""
    importlib.import_module("skills.registry")
    importlib.import_module("core.command_router")
    assert_isolated(tmp_root)


# ---------------------------------------------------------------------------------------------------------------
# Fix 3: clipboard round trip with verified (text-only) restoration.
# ---------------------------------------------------------------------------------------------------------------
def restore_text_clipboard(previous, paste, copy):
    """Write `previous` back and read it back. Returns (status, detail). Never includes clipboard contents."""
    try:
        copy(previous)
    except Exception as e:
        return "FAIL", f"could not write your previous text back ({type(e).__name__}); the clipboard may still hold the test string"
    try:
        after = paste()
    except Exception as e:
        return "FAIL", f"restore was written but read-back failed ({type(e).__name__}); restoration is UNVERIFIED"
    if after == previous:
        return "PASS — AUTOMATED", f"previous plain TEXT restored and verified by read-back ({len(previous)} chars); non-text clipboard data is not preserved"
    return "FAIL", (f"restore MISMATCH: clipboard now holds {len(after)} chars, expected {len(previous)} "
                    f"(still the test string: {after == CLIP_TEXT}); contents not shown")


async def clipboard_roundtrip(paste, copy, write, emit):
    """paste()/copy(text) access the clipboard as text; write(text) is the ByteX tool call; emit(name, status, detail)."""
    print("  NOTE: only plain TEXT on the clipboard is saved and restored. Images, files and rich text are NOT preserved;")
    print("        if you copied one of those, it will be replaced by text. Forced termination (kill -9) can skip the restore.")
    try:
        previous = paste()
    except Exception as e:
        emit("D1. Clipboard write", "BLOCKED", f"cannot read the existing clipboard ({type(e).__name__}); nothing was written")
        return
    if previous == "":
        print("  NOTE: the clipboard has no text. It may be empty or hold non-text data; that data cannot be restored.")
    try:
        res = await write(CLIP_TEXT)
        readback = paste()
        ok = bool(res.success) and readback == CLIP_TEXT
        emit("D1. Clipboard write (pyperclip -> pbcopy)", "PASS — AUTOMATED" if ok else "FAIL",
             f"success={res.success} verified={res.verified} readback_matches={readback == CLIP_TEXT}")
    except Exception as e:
        emit("D1. Clipboard write (pyperclip -> pbcopy)", "FAIL", f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        status, detail = restore_text_clipboard(previous, paste, copy)
        emit("D0. Clipboard restoration (text only)", status, detail)


# ---------------------------------------------------------------------------------------------------------------
# Fix 2: browser stays open for manual inspection (runner-only; ByteX's own lifecycle code is not modified).
# ---------------------------------------------------------------------------------------------------------------
def keep_browser_open() -> bool:
    """Disable ByteX's exit-time browser cleanup for THIS process. Returns True if it is really disabled."""
    ensure_backend_on_path()
    os.environ["BYTEX_BROWSER_CLOSE_ON_EXIT"] = "0"
    from security.browser_launch import close_on_exit_enabled
    return not close_on_exit_enabled()


async def smoke_compile():
    from skills.registry import skill_registry
    from core.command_router import CommandRouter
    work = tmp_dir() / "cpp"
    work.mkdir()
    (work / "bytex_smoke.cpp").write_text(CPP, encoding="utf-8")
    skill = skill_registry.get_skill("coding_workspace")
    skill._active_project_path = work
    skill._active_project_name = work.name
    cmd = "Compile and run bytex_smoke.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."
    handled, response, state, data = await CommandRouter.route_command(cmd)
    data = data or {}
    stdout = (data.get("stdout") or "").replace("\r\n", "\n").strip()
    ok = handled and data.get("exit_code") == 0 and stdout == EXPECTED_STDOUT
    record("A. C++ compile and run (router -> coding skill -> compiler)", "PASS — AUTOMATED" if ok else "FAIL",
           f"state={state} compiled={data.get('compiled')} exit_code={data.get('exit_code')} stdout_matches={stdout == EXPECTED_STDOUT} "
           f"compiler={data.get('compiler') or shutil.which('clang++')} source_unmodified={(work / 'bytex_smoke.cpp').read_text() == CPP}")
    if not ok:
        print("  response (first 400 chars):", (response or "")[:400])
        print("  stderr (first 400 chars):", (data.get("stderr") or "")[:400])
    record("A2. Same command typed in the ByteX UI", "PENDING MANUAL VERIFICATION",
           "type the compile command in the UI; expect the lines 'ByteX C++ works!' and '30'")


def report_screenshot_artifact(raw_path):
    """--keep-artifacts: say exactly where the screenshot is. The runner never deletes the run directory (with or without the flag)."""
    if _STATE["keep_artifacts"]:
        f = Path(raw_path) if raw_path else None
        if f is not None and f.is_file():
            print(f"  KEEP-ARTIFACTS screenshot file: {f}")
        else:
            print("  KEEP-ARTIFACTS: no screenshot file was produced")
        print(f"  KEEP-ARTIFACTS run directory kept (this script does not delete it): {tmp_dir()}")
    print(f"  Delete when done: rm -rf '{tmp_dir()}'  (this script never uploads or displays the image)")


async def smoke_screenshot():
    from skills.registry import skill_registry
    res = await skill_registry.execute_tool("take_screenshot", {}, origin=skill_registry.ORIGIN_USER)
    path = Path((res.data or {}).get("path", "")) if res.data else None
    exists = bool(path and path.exists() and path.stat().st_size > 0)
    record("C. Screenshot capture", "PASS — AUTOMATED" if (res.success and exists) else "FAIL",
           f"success={res.success} verified={res.verified} file_exists_nonempty={exists} dims={(res.data or {}).get('dimensions')} "
           f"bytes={(res.data or {}).get('size')} dir={tmp_dir() / 'screenshots'} message={res.message}")
    record("C2. Screenshot shows real windows", "PENDING MANUAL VERIFICATION",
           "open the image yourself; wallpaper-only means Screen Recording permission is missing (this script cannot tell)")
    report_screenshot_artifact((res.data or {}).get("path") if res.data else None)


async def smoke_clipboard():
    import pyperclip
    from skills.registry import skill_registry

    async def write(text):
        return await skill_registry.execute_tool("clipboard_control", {"action": "set", "text": text}, origin=skill_registry.ORIGIN_USER)

    await clipboard_roundtrip(pyperclip.paste, pyperclip.copy, write, record)
    record("D2. Cmd+V paste into a target app", "PENDING MANUAL VERIFICATION",
           "ByteX cannot see text arrive; do the TextEdit steps below and look")
    print("  Paste steps (needs Accessibility permission and a focused text field):")
    print("   1. Open TextEdit with an empty document and keep it frontmost.")
    print(f"   2. Put '{CLIP_TEXT}' on the clipboard, then trigger ByteX paste so that TextEdit is still frontmost")
    print("      (a voice command, or the UI button while TextEdit regains focus). Note which app was frontmost.")
    print("   3. Expect the text to appear in TextEdit. If macOS shows a permission prompt or ByteX reports Accessibility denied,")
    print("      that is the honest failure path; grant it in System Settings > Privacy & Security > Accessibility and retry.")
    print("   NOTE: ByteX reports 'Pasted ...' once Cmd+V was dispatched without error; it cannot see the text arrive. Confirm by eye.")


async def smoke_browser():
    from skills.registry import skill_registry
    import httpx
    if not keep_browser_open():
        record("B. Browser opens https://example.com", "FAIL", "could not disable exit-time browser cleanup; not launching a browser that would close before you can look")
        return
    res = await skill_registry.execute_tool("browser_control", {"action": "navigate", "url": "https://example.com", "browser": _STATE["browser_name"]},
                                            origin=skill_registry.ORIGIN_USER)
    data = res.data or {}
    port = data.get("cdp_port")
    seen = False
    if port:
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                tabs = (await c.get(f"http://127.0.0.1:{port}/json")).json()
            seen = any("example.com" in (t.get("url") or "") for t in tabs)
        except Exception as e:
            print("  could not list tabs:", e)
    record("B. Browser opens https://example.com", "PASS — AUTOMATED" if (res.success and seen) else "FAIL",
           f"success={res.success} verified={res.verified} cdp_port={port} tab_with_example_com_listed={seen} message={res.message}")
    record("B2. Page visibly shows Example Domain", "PENDING MANUAL VERIFICATION", "look at the browser window")
    print("  The browser was LEFT RUNNING on purpose so you can inspect it. Quit it yourself (Cmd+Q in that browser window) when done.")
    print(f"  Until you quit it, its debugging port stays open on 127.0.0.1:{port or '<port>'} (unauthenticated, loopback only).")
    print(f"  Port check (separate terminal): lsof -nP -iTCP:{port or 9223} -sTCP:LISTEN   (expect 127.0.0.1 only)")


async def main(argv=None):
    ap = argparse.ArgumentParser()
    for flag in ("compile", "screenshot", "clipboard", "browser", "all"):
        ap.add_argument(f"--{flag}", action="store_true")
    ap.add_argument("--browser-name", default="edge", choices=["edge", "chrome", "brave"], help="installed browser to use for --browser")
    ap.add_argument("--keep-artifacts", action="store_true", help="with --screenshot: print the exact screenshot path and say the run directory is kept")
    a = ap.parse_args(argv)
    _STATE["browser_name"] = a.browser_name
    _STATE["keep_artifacts"] = a.keep_artifacts
    print(f"macOS {platform.mac_ver()[0] or 'NOT macOS (' + platform.system() + ')'} | Python {platform.python_version()} | repo {ROOT}")
    if platform.system() != "Darwin":  # checked before any temp directory is created or ByteX module is imported
        print("This is not macOS: results would not count as macOS verification. Aborting.")
        return 2
    if not any([a.compile, a.screenshot, a.clipboard, a.browser, a.all]):
        ap.print_help()
        return 0
    if a.keep_artifacts and not (a.screenshot or a.all):
        print("NOTE: --keep-artifacts only affects --screenshot; ignored for this run.")
    tmp_root = setup_workdir()
    before = real_data_fingerprint()
    try:
        isolate_user_data(tmp_root)
        preload_bytex(tmp_root)
    except Exception as e:  # fail closed: never run a test against the real database/log
        record("Setup. ByteX data isolation", "BLOCKED", f"{type(e).__name__}: {e}. No test was run.")
        return 1
    print(f"Isolated: ByteX memory DB and audit log for this run are under {tmp_root / 'backend'} (your real ones are not written).")
    for flag, fn in (("compile", smoke_compile), ("screenshot", smoke_screenshot), ("clipboard", smoke_clipboard), ("browser", smoke_browser)):
        if a.all or getattr(a, flag):
            try:
                await fn()
            except Exception as e:  # report honestly, never as a pass
                record(flag, "FAIL", f"{type(e).__name__}: {e}")
    after = real_data_fingerprint()
    record("E. Real ByteX data unchanged (bytex_memory.db, action_logs.json)", "PASS — AUTOMATED" if before == after else "FAIL",
           "SHA-256 identical before/after" if before == after else "CHANGED during the run (the runner is isolated, so a ByteX backend running at the same time is the likely cause)")
    print("\nSummary:")
    for name, status, _ in results:
        print(f"  {status:30s} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
