# ByteX macOS runtime smoke tests (2026-10-26)

Statuses: `PASS — AUTOMATED`, `PASS — MANUAL`, `FAIL`, `BLOCKED`, `PENDING MANUAL VERIFICATION`, `NOT TESTED`.

## Environment actually available to the assistant
Linux aarch64 VM (kernel 6.8, Python 3.10.12, Node 22.23.2, `g++` present, **no** `clang++`, no `sw_vers`, no `screencapture`/`osascript`/`pbcopy`). Project root on the Mac: `/Users/yashpatel/Desktop/byteX/BETTER ByteX Core` (the VM sees it as a mounted folder). The project's macOS `.venv` and native binaries cannot run in the VM, so **nothing below was executed on macOS and no GUI action was observed.** macOS, Python, Node and compiler versions on the Mac: NOT KNOWN. The runner prints them.

## How to produce the evidence yourself (Mac, repo root, project venv)
```
.venv/bin/python scripts/macos_runtime_smoke.py --compile
.venv/bin/python scripts/macos_runtime_smoke.py --screenshot --clipboard
.venv/bin/python scripts/macos_runtime_smoke.py --browser --browser-name edge   # or chrome / brave
```
The runner refuses to run on non-macOS (before creating any temp directory), keeps its artifacts and ByteX's own memory database and audit log in a temp directory, restores your clipboard **text** and verifies the restore, leaves the browser it started open for you to inspect, and never prints screenshots, clipboard history or secrets. It stages and commits nothing. Every run ends with a line comparing SHA-256 of your real `backend/bytex_memory.db` and `backend/storage/action_logs.json` before/after (a ByteX backend running at the same time can change them and cause a FAIL there). Existing regression suites to run first (project venv): `python -m pytest tests/test_compiler_toolchain_and_uri_compat.py tests/test_compile_and_run_safe_pipeline_e2e.py tests/test_browser_discovery_macos.py tests/test_clipboard_truthful_reporting.py tests/test_applescript_security.py tests/test_tool_policy_enforcement.py tests/test_tool_confirmation_gate.py` (the `*_e2e.py` file compiles and runs code in a temp workspace; read it before running).

## Results
| Feature | Status | Notes |
|---|---|---|
| A. C++ compile and run | **NOT TESTED** (BLOCKED: no macOS) | Static trace below. Runner command: `--compile`. UI-to-backend check: PENDING MANUAL VERIFICATION |
| B. Browser opens https://example.com | **NOT TESTED** (BLOCKED) | Runner: `--browser`; visual confirmation PENDING MANUAL VERIFICATION |
| C. Screenshot capture | **NOT TESTED** (BLOCKED) | Runner: `--screenshot`; image content PENDING MANUAL VERIFICATION |
| D. Clipboard write | **NOT TESTED** (BLOCKED) | Runner: `--clipboard` |
| D. Clipboard paste into target app | **PENDING MANUAL VERIFICATION** | Needs Accessibility permission and a focused text field; exact steps printed by the runner |

For every row the expected result, command, exit code and test names will be filled in from your run output. No row is marked passed from static analysis or mocked tests.

## Static trace (code read, not executed)
**A. Compile/run.** Router `classify_request` -> `coding_workspace` (`action=execute_code`) -> `skills/coding.py` toolchain lookup: `shutil.which` for `clang++`, `g++`, `c++` plus `/usr/bin/clang++`, `/opt/homebrew/bin/clang++`, `/usr/local/bin/clang++` on macOS, a clear message suggesting `xcode-select --install` when none is found, `asyncio.create_subprocess_exec` (argument lists, no shell) with timeouts for compile and run. The existing e2e test drives `CommandRouter.route_command` (user origin), which Phase 3 left unchanged. Expected stdout for the smoke program: `ByteX C++ works!` then `30`, exit code 0. Note: when the **model** (not the user) asks to run code, ByteX now asks for your confirmation first (Phase 3).

**B. Browser.** UI -> `/ws` -> `CommandRouter` -> `browser_control` (`navigate`/`open_browser`) -> `_ensure_browser_ready`: launches the browser executable (macOS `.app/Contents/MacOS/...` binaries are tried first) with DevTools on a loopback port in a ByteX-only profile, then "success" means the CDP endpoint answered and a tab list could be read. Phase 3 changed only the flag list (adds `--remote-debugging-address=127.0.0.1`) and exit cleanup; Chromium on macOS may ignore that flag, NOT VERIFIED. The `.app` directory candidates exist as paths but cannot be executed; an exception there is caught and reported as launch failure.

**C. Screenshot.** `take_screenshot` -> `services/screenshot_helper.py` -> `/usr/sbin/screencapture -x` (argument list), `mss` fallback; output dir `$BYTEX_SCREENSHOT_DIR` or `~/Pictures/ByteX Screenshots` (no Windows path); a six-point check (exists, non-empty, parses, size, not all-black). Findings:
* **Suspected overclaim (not reproduced):** without Screen Recording permission macOS usually returns a wallpaper-only image with exit code 0; it is not black, so ByteX would report `verified=True`. Only a total failure produces a permission hint, and that hint exists only in console logs, not in the message the user sees. Proposed small fix (not applied): on macOS call `CGPreflightScreenCaptureAccess()` first and fail with an explicit permission message.
* The skill description string still says "Windows desktop screenshots" (cosmetic).

**D. Clipboard.** Mechanism: `pyperclip` (pbcopy/pbpaste on macOS) with a Win32 fallback; set is verified by read-back; paste on macOS uses `osascript` -> System Events `keystroke "v" using command down` via `core.applescript.run_applescript` (argument list). Permission failures (`-1743`, "not allowed to send keystrokes") return `success=False`.
* **Overclaim (code reading, deterministic):** after the keystroke is dispatched with exit code 0, ByteX returns `success=True, verified=True, "Pasted clipboard content into <frontmost app>"`. It cannot see whether text arrived (no focused field, wrong app, secure input). The mocked test `test_macos_paste_success_reports_verified` codifies this wording. Also the frontmost app is usually the browser showing ByteX itself. Proposed fix (not applied; changes an existing test and the product wording, so I am asking first): report "Sent Cmd+V to <app>" with `verified=False`, or verify via the Accessibility API.
* A failed `pyperclip.copy` on macOS is swallowed, but the read-back check still makes the set operation fail honestly.

## Fixes made in this task (runner only; no ByteX feature code changed)
Found by reading the runner (not by a Mac run) and approved before editing. Backup of the previous runner and this document: `audit-backup-2026-10-26-step3c-runner.tgz`.

1. **Data isolation.** The compile test goes through `CommandRouter`, which records history in `backend/bytex_memory.db`, and every skill appends to `backend/storage/action_logs.json`. Verified mechanism: `memory/database.py` and `security/audit_logger.py` derive their paths from `Path(__file__)` at import time and create `db_manager` / `audit_logger` at import time; there is no environment variable or constructor hook. The runner therefore executes those two real source files with `__file__` pointing into its temp directory before anything else imports them, then verifies that every loaded `db_manager` / `audit_logger` writes inside the temp directory, and stops (`BLOCKED`, no test run) otherwise. Other persistent writes on the compile path were looked for (`Path(__file__)` users, home-directory use) but not exhaustively audited; the before/after hash line is the safety net.
2. **Browser stays open.** Phase 3 added an exit-time cleanup (`launched_browsers`, `BYTEX_BROWSER_CLOSE_ON_EXIT`, default on) that closed the browser as soon as the runner exited. `--browser` now sets `BYTEX_BROWSER_CLOSE_ON_EXIT=0` for the runner process only and refuses to launch if that did not take effect. ByteX's own default (close on exit) is unchanged and tested. Consequence: the dedicated browser, and its unauthenticated loopback-only debugging port, stay up until you quit that browser yourself.
3. **Clipboard restoration.** The runner prints that only plain text is preserved (images, files and rich text are not), writes the test string, then restores the previous text and reads it back. A mismatch, write error or read-back error is reported as `FAIL` (without printing clipboard contents). Restoration runs in a `finally`, so ordinary exceptions are covered; `kill -9` or power loss can skip it.
4. **No temp directory before the macOS check** (non-macOS now creates nothing and imports nothing).
5. **`ORIGIN_USER`.** Calls use `skill_registry.ORIGIN_USER` (a class attribute of `SkillRegistry` in `skills/registry.py`) instead of the literal `"user"`.

Also added: the summary now lists the manual items (A2, B2, C2, D2) as `PENDING MANUAL VERIFICATION`.

### Tests for the runner (Linux VM, stdlib only; these do not verify any macOS feature)
`PYTHONPATH=backend python3 -m unittest tests.test_macos_smoke_runner` -> Ran 19, OK. Combined with `tests.test_local_guard tests.test_phone_pairing_lifecycle tests.test_app_wiring_static tests.test_tool_confirmation_gate tests.test_tool_policy_enforcement` -> Ran 109, OK (skipped=26: pydantic is not installed in the VM). Mutation checks on a throwaway copy (restore removed, browser cleanup left on, isolation redirect off, literal origin) each made the expected tests fail. The real database and audit-log hashes were identical before and after the test runs. Limitation: the isolation test proves the redirect for the two modules and the verification helper; it does not import the full ByteX app (needs the Mac venv), so `preload_bytex` is exercised only on the Mac.

Still open, unchanged: paste wording (`verified=True` after Cmd+V), screenshot Screen Recording preflight, whether `--remote-debugging-address` is honoured on macOS. None has been reproduced or changed.

## Pending for you
1. Environment check: `cd "$HOME/Desktop/byteX/BETTER ByteX Core"; pwd; sw_vers; ./.venv/bin/python --version; /usr/bin/clang++ --version; git status --short`. Send me the output; no runtime test is guided until I have it.
2. Then, one at a time: `--compile`; `--screenshot --clipboard`; `--browser --browser-name edge|chrome|brave`; perform the manual steps the runner prints (TextEdit paste, look at the screenshot and at the Example Domain page) and send me the output.
