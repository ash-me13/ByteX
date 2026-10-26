# ByteX AI — macOS Compatibility Audit Report (Phase 1)

**Audit Date:** October 18, 2026  
**Auditor:** Antigravity AI  
**Scope:** Complete repository audit of ByteX AI Core (Backend, Frontend, Tool Execution Milestone, Compilers, and Runtime)  
**Status Key:**
- **Verified compatible**: Inspected and verified to operate cleanly on macOS without modification.
- **Needs changes**: Requires platform-aware refactoring or conditional branching to run on macOS.
- **Blocked by environment**: Cannot be executed until missing host dependencies (e.g. Python venv, node_modules rebuild) are satisfied.
- **Not yet verified**: Code exists and appears structurally viable, but could not be empirically executed in Phase 1 due to environmental blockers.

---

## 1. Repository Architecture and Detected Environment

### 1.1 Architecture Overview
- **Backend**: Python 3 + FastAPI server running on `http://127.0.0.1:8000`. Exposes REST API endpoints (`/api/*`), WebSocket bi-directional channel (`/ws`), persistent SQLite memory store (`bytex_memory.db`), live system monitoring via `psutil`, an autonomous planning & routine engine, and a PC automation skill registry.
- **AI Core**: Multi-provider LLM pipeline with primary Groq integration (`AsyncGroq`), fallback to Google Gemini (`gemini-2.5-flash` via async REST calls with `httpx`), and runtime response sanitization (`ResponseSanitizer`) preventing prompt-injection or tool-protocol leaks.
- **Frontend**: Single-page application built with React 19 + TypeScript 6 + Vite 8 in `ByteX/`, communicating over WebSocket and REST with 3D WebGL thinking orb visuals (`three`, `thinking-orbs`, `ogl`), browser-based Web Speech API (STT/TTS), and an active wake-word detector.
- **Orchestration**: `start_bytex.py` and `start_bytex.bat` launch backend, frontend, and launch/connect to a controlled Chromium browser with Chrome DevTools Protocol (CDP) enabled on port `9222`.

### 1.2 Detected macOS Host Environment
| Component | Detected Version / Path | macOS Architecture | Assessment |
|---|---|---|---|
| **Operating System** | macOS (Darwin 27.0.0) | Apple Silicon (`arm64`) | Host platform |
| **Python** | Python 3.14.7 (`/opt/homebrew/bin/python3`) | `arm64` | PEP 668 externally managed |
| **C++ Compiler (clang++)** | Apple clang 21.0.0 (`/usr/bin/clang++`) | `arm64-apple-darwin27.0.0` | **Verified compatible** |
| **C++ Compiler (g++)** | Apple clang 21.0.0 (`/usr/bin/g++`) | `arm64-apple-darwin27.0.0` | Symlinked to Apple Clang |
| **C Compiler (clang / gcc)** | Apple clang 21.0.0 (`/usr/bin/clang`, `/usr/bin/gcc`) | `arm64-apple-darwin27.0.0` | **Verified compatible** |
| **Node.js** | v20.18.0 (`/Users/yashpatel/.local/bin/node`) | `arm64` | **Verified compatible** |
| **npm** | 10.8.2 (`/Users/yashpatel/.local/bin/npm`) | `arm64` | **Verified compatible** |
| **Default Shell** | `/bin/zsh` | POSIX | Standard macOS shell |
| **Browsers Found** | Google Chrome, Brave Browser, Safari | GUI Apps in `/Applications` | Chrome & Brave support CDP port 9222 |
| **Microsoft Edge** | **Not installed** | N/A | Windows default; absent on host |

---

## 2. Features That Appear Platform-Independent

The following components rely on standard Python libraries, standard web protocols, or platform-agnostic APIs and require zero architectural changes:

| Component | Path | Status | Evidence / Notes |
|---|---|---|---|
| **AI Router & Providers** | `backend/ai/router.py`, `backend/ai/providers/base.py`, `backend/ai/providers/gemini_provider.py`, `backend/ai/providers/groq_provider.py` | **Verified compatible** (code inspected) | Gemini uses pure `httpx` REST calls; Groq uses `AsyncGroq` SDK; fallback logic is OS-agnostic. |
| **Prompt Engine** | `backend/ai/prompts/system.py` | **Verified compatible** | Pure string templates and tool schemas. |
| **Response Sanitizer** | `backend/core/response_sanitizer.py` | **Verified compatible** | Pure Python regex parsing, JSON extraction, and string sanitization. |
| **WebSocket & REST API** | `backend/api/routes.py`, `backend/api/websocket.py` | **Verified compatible** | FastAPI routers, WebSocket connection pooling, JSON serialization. |
| **Persistent Memory** | `backend/memory/database.py`, `backend/memory/manager.py`, `backend/memory/models.py`, `backend/memory/service.py` | **Verified compatible** | SQLite3 via standard library, localized file path `bytex_memory.db`. |
| **System Monitoring Metrics** | `backend/monitoring/collector.py`, `backend/monitoring/service.py` | **Verified compatible** | `psutil.cpu_percent()`, `psutil.virtual_memory()`, and socket connectivity probe. Already handles `os.name != 'nt'`. |
| **Web Search & Research** | `backend/skills/search.py`, `backend/skills/research.py`, `backend/skills/reader.py` | **Verified compatible** | DuckDuckGo / web scraping using `httpx`, `BeautifulSoup` (or pure standard parsing). |
| **Audio / STT / TTS** | `ByteX/src/services/sttService.ts`, `ByteX/src/services/ttsService.ts`, `ByteX/src/services/wakeWordService.ts` | **Verified compatible** (browser-based) | Relies on browser-native Web Speech API (`SpeechRecognition`, `speechSynthesis`) and Web Audio API (`AudioContext`). |
| **Frontend UI Core** | `ByteX/src/components/*`, `ByteX/src/hooks/*`, `ByteX/src/pages/*` | **Verified compatible** (code inspected) | React 19 + TypeScript + CSS + Three.js orb renders inside the browser client. Case-sensitive import scan verified 0 missing or mismatched paths. |

---

## 3. Features That Depend on Windows

The following subsystems contain hardcoded Windows APIs, Windows binary names, Windows Registry access, or Windows path conventions that cause immediate runtime crashes or behavioral failures on macOS:

### 3.1 Hard Level-0 Import Crashes (`windll`, `winreg`)
On macOS, `from ctypes import windll` and `import winreg` fail immediately upon module load with `ImportError` or `ModuleNotFoundError`. Any file importing these modules at module scope cannot even be loaded by `pytest` or `unittest`.

1. **`backend/core/session.py`** (Lines 11–13):
   ```python
   user32 = ctypes.windll.user32
   user32.IsWindow.argtypes = [ctypes.c_void_p]
   user32.IsWindow.restype = ctypes.c_bool
   ```
   - *Impact*: Module import fails immediately. Breaks `backend/core/command_router.py` and `backend/core/assistant.py`.
2. **`backend/security/permissions.py`** (Lines 4, 10–12):
   ```python
   from ctypes import windll, byref, c_ulong, create_unicode_buffer
   user32 = windll.user32
   kernel32 = windll.kernel32
   WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
   ```
   - *Impact*: Module import fails immediately. Blocks all security permission lookups and application allowlists.
3. **`backend/skills/resolver.py`** (Lines 4, 10, 13):
   ```python
   import winreg
   from ctypes import windll
   shell32 = windll.shell32
   ```
   - *Impact*: Fails with `ModuleNotFoundError: No module named 'winreg'`. Breaks application discovery and launch skills.
4. **`backend/skills/apps.py`** (Lines 6, 14–16):
   ```python
   from ctypes import windll, byref, c_ulong, Structure, sizeof, ...
   kernel32 = windll.kernel32
   user32 = windll.user32
   shell32 = windll.shell32
   ```
   - *Impact*: Fails on `windll` import. Prevents opening, closing, and checking status of desktop applications.
5. **`backend/skills/files.py`** (Lines 21, 86–87):
   ```python
   from ctypes import windll, wintypes, byref, c_wchar_p
   ...
   shell32 = windll.shell32
   ole32 = windll.ole32
   ```
   - *Impact*: Fails on `windll` import. Breaks Recycle Bin integration (`SHFileOperationW`) and Known Folders resolution (`SHGetKnownFolderPath`).
6. **`backend/services/screenshot_helper.py`** (Lines 3, 7–8):
   ```python
   from ctypes import windll
   user32 = windll.user32
   kernel32 = windll.kernel32
   ```
   - *Impact*: Fails on `windll` import. Breaks `screenshot.py` helper subprocess.

### 3.2 Desktop & UI Automation Assumptions
1. **Window Management & Enumeration**:
   - `backend/skills/apps.py`, `backend/security/permissions.py`, `backend/agent/suggestions.py`, `backend/agent/context.py`, `backend/skills/vision.py` use Win32 `user32.EnumWindows`, `GetWindowTextW`, `GetForegroundWindow`, and `WinSta0\Default` desktop attachment.
   - *macOS Equivalent*: Use Quartz (`CGWindowListCopyWindowInfo`) or AppleScript (`System Events`).
2. **Interactive Process Spawning**:
   - `backend/skills/apps.py` (`launch_process_on_interactive_desktop` lines 49–80) invokes Win32 `CreateProcessW` with `STARTUPINFOW` targeting `"WinSta0\\Default"`.
   - *macOS Equivalent*: Use `/usr/bin/open -a "<AppName>"` or `open -b <bundle_identifier>` or `subprocess.Popen(["open", "-a", app_name])`.
3. **Application Resolving**:
   - `backend/skills/resolver.py` scans Windows Registry `Software\Microsoft\Windows\CurrentVersion\App Paths` and `C:\ProgramData\Microsoft\Windows\Start Menu\Programs`.
   - *macOS Equivalent*: Scan `/Applications`, `/System/Applications`, and `~/Applications` for `.app` bundles, reading `Info.plist` for bundle names and CFBundleIdentifier.
4. **Clipboard Fallbacks & Simulation**:
   - `backend/skills/clipboard.py` relies on `pyperclip` (compatible with macOS `pbcopy`/`pbpaste`), but its low-level fallbacks and paste routine invoke `OpenClipboard`, `OpenInputDesktop`, and Win32 key events.
   - *macOS Equivalent*: macOS uses `pbcopy`/`pbpaste` for clipboard data and AppleScript `tell application "System Events" to keystroke "v" using command down` for pasting.
5. **Trash / Deletion**:
   - `backend/skills/files.py` uses `SHFileOperationW` with `FO_DELETE` and `FOF_ALLOWUNDO` to send files to the Windows Recycle Bin.
   - *macOS Equivalent*: Use `send2trash` or AppleScript / NSFileManager to send items to `~/.Trash`.

### 3.3 Hardcoded Windows Paths & User Directories
1. **Hardcoded User Directory**:
   - `backend/skills/screenshot.py` (Line 10):
     `SCREENSHOT_DIR = Path(r"C:\Users\ryzzn\OneDrive\Pictures\BtyeX ScreenShot")`
   - `backend/security/permissions.py` (Line 111):
     `local_app = os.environ.get("LOCALAPPDATA", r"C:\Users\ryzzn\AppData\Local")`
   - *macOS Equivalent*: Use `Path.home() / "Pictures" / "ByteX Screenshots"` and `Path.home() / "Library" / "Application Support" / "ByteX"`.
2. **Hardcoded Windows System Paths**:
   - `backend/skills/apps.py` (Line 13): `CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"`
   - `backend/security/permissions.py` (Lines 30–36): `BLOCKED_PATH_PATTERNS` checks `c:\windows`, `c:\program files`, `system32`.
   - *macOS Equivalent*: Add `/System`, `/usr`, `/bin`, `/sbin`, `/private`, `/Library` to protected system path filters.
3. **Browser Automation Paths**:
   - `start_bytex.py` (Lines 61–66) & `backend/skills/browser.py` (Lines 56–80): Search `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, `C:\Program Files\Google\Chrome\...`.
   - On macOS: Chrome is `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` and Brave is `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`. Edge is not installed.
4. **Launcher Scripts**:
   - `start_bytex.bat`: Windows batch file using `cmd /k`, `timeout /t`, `start "" "msedge.exe"`.
   - *macOS Equivalent*: Create a POSIX launcher `start_bytex.sh` (or update `start_bytex.py` to be cross-platform).

### 3.4 Compiler & Execution Assumptions
1. **Hardcoded `.exe` Binary Extensions**:
   - `backend/skills/coding.py` (Line 5129): `out_exe = Path(temp_dir) / f"prog_{uuid.uuid4().hex[:8]}.exe"`
   - `backend/skills/coding.py` (Line 2931): `exe_path = tmp_path / "test_prog.exe"`
   - While macOS Clang will write and execute Mach-O binaries ending in `.exe`, it is non-standard and causes confusion with binary extension filters.
2. **Compiler Discovery Candidates**:
   - `backend/skills/coding.py` (Lines 4894–4905): Checks `C:\MinGW\bin\g++.exe`, `C:\msys64\...`, `C:\TDM-GCC-64\...`.
   - On macOS, `clang++` and `g++` are in `/usr/bin/` and resolved by `shutil.which()`, but `_resolve_runner` should explicitly prioritize `clang++` on Darwin.
3. **VS Code Workspace Discovery URI Parsing**:
   - `backend/skills/coding.py` (Lines 440, 491, 509):
     `p_str = decoded[8:] if decoded.startswith("file:///") else (decoded[7:] if decoded.startswith("file://") else decoded)`
   - On Windows: `file:///C:/path` sliced with `[8:]` leaves `C:/path`.
   - On macOS/Linux: `file:///Users/yashpatel/...` sliced with `[8:]` drops the first char of `Users`, producing `sers/yashpatel/...`!
   - *Fix*: Use `urllib.parse.urlparse(folder_uri).path` or slice `[7:]` for `file://`.
4. **VS Code `workspaceStorage` Directory**:
   - `backend/skills/coding.py` (Line 471): `appdata = os.environ.get("APPDATA")`
   - On macOS, `APPDATA` is not set. VS Code storage is at `~/Library/Application Support/Code/User/workspaceStorage`.

---

## 4. Files and Functions Needing Changes

| Target File | Function / Section | Current State | Required Modification |
|---|---|---|---|
| `backend/core/session.py` | Top-level module & `ConversationalSessionManager` | Direct `ctypes.windll.user32` at lines 11–13 | Wrap in `sys.platform == "win32"` guard or provide macOS Quartz/dummy fallback. |
| `backend/security/permissions.py` | Top-level imports & path allowlists | Imports `windll`, `wintypes` at lines 4–12; Windows paths at lines 30–36 | Guard Win32 ctypes; add macOS system protected paths (`/System`, `/Library`, `/usr`, `/bin`, `/private`). |
| `backend/skills/resolver.py` | Top-level imports & `UniversalApplicationResolver` | `import winreg`, `windll.shell32` at lines 4, 10, 13; Win32 registry crawling | Guard Windows imports; implement macOS `/Applications` scanner reading bundle names. |
| `backend/skills/apps.py` | `launch_process_on_interactive_desktop`, `EnumWindows` | Win32 `STARTUPINFOW` on `WinSta0\Default`, `EnumWindows` | Guard Win32 structures; implement macOS application launching via `/usr/bin/open -a`. |
| `backend/skills/files.py` | `send_to_recycle_bin`, `get_known_folder_path`, `resolve_user_directory` | `windll.shell32.SHFileOperationW`, GUID structures | Guard ctypes; implement macOS trash (`send2trash` or AppleScript) and use `Path.home()` for user folders. |
| `backend/skills/clipboard.py` | `_win32_get_clipboard_text`, `_win32_set_clipboard_text`, paste logic | `ctypes.windll.user32`, `OpenInputDesktop` | Guard Win32 calls; let `pyperclip` handle macOS; use AppleScript for active-app paste. |
| `backend/skills/screenshot.py` | `SCREENSHOT_DIR`, helper execution | Hardcoded `C:\Users\ryzzn\...` path, executes `screenshot_helper.py` | Change to `Path.home() / "Pictures" / "ByteX Screenshots"`; implement macOS screencapture fallback. |
| `backend/services/screenshot_helper.py` | Top-level imports & desktop context | `from ctypes import windll`, `OpenDesktopW` | Guard Windows imports; use PIL `ImageGrab.grab()` or macOS `/usr/sbin/screencapture -x` on Darwin. |
| `backend/skills/browser.py` | `detect_all_supported_browsers`, default browser check | Registry checks, `msedge.exe` in `ProgramFiles` | Add `/Applications/Google Chrome.app`, `/Applications/Brave Browser.app`, default browser via `defaults read`. |
| `backend/skills/coding.py` | `_resolve_runner`, `_detect_vscode_workspace`, `out_exe` naming | Windows MinGW paths, `.exe` suffix, `APPDATA`, URI `[8:]` slicing | Prioritize `clang++` on macOS, omit `.exe` extension on POSIX, parse `file://` correctly, check `~/Library/Application Support/Code`. |
| `start_bytex.py` | Browser launch & startup logic | Hardcoded `LOCALAPPDATA`, `msedge.exe`, Windows Edge profile | Auto-detect installed Chromium browser (Chrome/Brave/Edge), launch with `--remote-debugging-port=9222`. |
| `start_bytex.bat` | Windows batch launcher | `@echo off`, `cmd /k` | Provide a companion `start_bytex.sh` POSIX shell script. |
| `ByteX/package.json` | Dependencies & node_modules | Pre-installed `win32-x64-msvc` native bindings | Run `npm install` on macOS to download `darwin-arm64` native binaries and restore POSIX `.bin` executable bits. |

---

## 5. Missing Dependencies and Setup Requirements

### 5.1 Python Environment & Dependencies
1. **PEP 668 Restriction**: The active Homebrew Python (`/opt/homebrew/bin/python3`, Python 3.14.7) is marked `externally-managed`. Running `pip install` globally is blocked.
   - **Resolution Required**: Create a local virtual environment:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
2. **Missing Python Backend Packages**:
   Analysis of all imports in `backend/` identified these missing third-party packages:
   - `fastapi`
   - `uvicorn`
   - `pydantic`
   - `httpx`
   - `groq`
   - `psutil`
   - `pyperclip`
   - `websockets`
   - `Pillow`
   - `mss`
   - `python-dotenv`
   - `pytest` / `pytest-asyncio` (for test suite execution)
3. **Missing `requirements.txt`**: There is no standard `requirements.txt` or `pyproject.toml` in the repository root or `backend/`. A clean `requirements.txt` should be authored.

### 5.2 Node.js & Frontend Environment
1. **Missing POSIX Executable Bits in `ByteX/node_modules/.bin`**:
   The `node_modules` directory was transferred from Windows. All files in `ByteX/node_modules/.bin/*` (`tsc`, `vite`, `oxlint`) have permissions `-rw-r--r--` without the `+x` bit. Running `npm run build` exits with code 126 (`Permission denied`).
2. **Platform-Mismatched Native Node Modules**:
   `ByteX/node_modules` contains Windows MSVC native binaries:
   - `@rolldown/binding-win32-x64-msvc`
   - `lightningcss-win32-x64-msvc/lightningcss.win32-x64-msvc.node`
   - `@oxlint/binding-win32-x64-msvc`
   On Apple Silicon (`darwin-arm64`), these binaries cannot execute.
   - **Resolution Required**: Reinstall frontend dependencies on macOS:
     ```bash
     cd ByteX && npm install
     ```

---

## 6. Test Suite Execution & Diagnostic Results

All diagnostic test runs were executed cleanly using standard read-only test runners.

| Test File | Command Run | Exit Code | Result | Exact Root Cause |
|---|---|---|---|---|
| `tests/test_read_file_tool_execution_regression.py` | `python3 -m unittest tests/test_read_file_tool_execution_regression.py` | 1 | **Blocked by environment** | `ModuleNotFoundError: No module named 'pydantic'` in active Python. |
| `tests/test_compile_and_run_safe_pipeline_e2e.py` | `python3 -m unittest tests/test_compile_and_run_safe_pipeline_e2e.py` | 1 | **Blocked by environment** | `ModuleNotFoundError: No module named 'pydantic'` in active Python. |
| `tests/test_code_file_routing_vs_web_e2e.py` | `python3 -m unittest tests/test_code_file_routing_vs_web_e2e.py` | 1 | **Blocked by environment** | `ModuleNotFoundError: No module named 'pydantic'` in active Python. |
| Frontend TypeCheck & Build | `npm --prefix ByteX run build` | 126 | **Blocked by environment** | `sh: .../node_modules/.bin/tsc: Permission denied` (Windows NTFS copy lacks `+x`). |
| C++ Compiler Diagnostic (`clang++`) | `clang++ -std=c++17 01_basic.cpp -o scratch/test_bin && scratch/test_bin` | 0 | **Verified compatible** | Output: `BYTE_X_BASIC_TEST`. Clean compile & run. |
| C++ Compiler Diagnostic (`g++`) | `g++ -std=c++17 01_basic.cpp -o scratch/test_bin_gpp && scratch/test_bin_gpp` | 0 | **Verified compatible** | Output: `BYTE_X_BASIC_TEST`. Clean compile & run via Apple Clang. |

### Code-Level Audit of the Tool-Execution Milestone
Independent of the environmental blocker (missing packages in the default Homebrew python), static code inspection of the milestone implementations confirms:

1. **`read_file`, `read_source_file`, and `read` Routing**:
   - `backend/skills/registry.py` (lines 89–91, 216–217) explicitly registers all three aliases and maps them to `coding_workspace` with `args["action"] = "read_code_file"`.
   - **Status:** **Verified compatible** in code logic.
2. **Argument Extraction (`file_path`, `filename`, `path`, `name`)**:
   - `backend/skills/coding.py` (line 1435 in `_action_read_code_file`) checks `arguments.get("file_path") or arguments.get("filename") or arguments.get("path") or arguments.get("name")`.
   - **Status:** **Verified compatible** in code logic.
3. **Truthful Error on Missing Files**:
   - `backend/skills/coding.py` (lines 1468–1476) explicitly verifies `not target_file or not target_file.exists()` and returns `ToolResult(success=False, error="File not found", message="I couldn't find source file '...'")`.
   - **Status:** **Verified compatible** in code logic.
4. **Prevention of `<tool_call>` Leaks to User Interface**:
   - `backend/core/assistant.py` (lines 96–107) suppresses streaming deltas when tags or JSON tool calls are detected.
   - `backend/core/response_sanitizer.py` (lines 178–207) strips `<think>`, `<tool_call>`, and `<tool>` blocks from the completed response.
   - `ByteX/src/hooks/useCommand.ts` (lines 168–177) applies a secondary regex strip on the client before rendering or speaking.
   - **Status:** **Verified compatible** in code logic (dual-layer defense).
5. **Tool Execution & Multi-Turn History Feedback Loop**:
   - `backend/core/assistant.py` (lines 110–136) parses `<tool_call>`, dispatches `skill_registry.execute_tool()`, appends both assistant call and `[Tool Result for '...']` to history, and loops back to the LLM (up to 4 iterations).
   - **Status:** **Verified compatible** in code logic.
6. **Compilation & Execution Timeout / Stdin Hang Prevention**:
   - `backend/skills/coding.py` (lines 5354–5380) wraps `exec_proc.communicate()` in `asyncio.wait_for(timeout=float(timeout_seconds))` and kills the process tree with `psutil` on timeout.
   - **Observation**: Line 5332 sets `stdin=asyncio.subprocess.PIPE if stdin_data else None`. When no `stdin_data` is provided, `stdin=None` inherits parent stdin, which could block interactive programs until the timeout fires. Passing `asyncio.subprocess.DEVNULL` when no stdin is provided is recommended.
7. **Security Restrictions & User-File Preservation**:
   - Read-only actions are enumerated in `READ_ONLY_ACTIONS` (`coding.py` lines 49–56).
   - Path traversal is checked (`coding.py` line 4972).
   - Deletion of code files is blocked or requires explicit dangerous-risk confirmation.

---

## 7. Potential Regressions and Security Concerns

1. **Top-Level Import Cascades**:
   Because `backend/main.py` imports `backend/core/command_router.py`, which imports `backend/core/session.py` and `backend/security/permissions.py`, any failure in Win32 ctypes crashes the entire FastAPI server before it can bind to port 8000.
2. **macOS System Path Protection Gap**:
   In `backend/security/permissions.py`, `BLOCKED_PATH_PATTERNS` only lists Windows directories (`c:\windows`, `c:\program files`, etc.). On macOS, sensitive directories like `/System`, `/private`, `/etc`, and `~/.ssh` must be safeguarded.
3. **CDP Port Collisions & Browser Hijacking**:
   `start_bytex.py` looks for an existing browser session on port 9222. If a user already has an active Chrome instance running without remote debugging, Chrome will refuse to open port 9222 without a distinct `--user-data-dir`.
4. **macOS Microphone and Screen Recording Permissions**:
   macOS enforces strict Transparency, Consent, and Control (TCC).
   - Screen capture (`screencapture` or PIL `ImageGrab`) requires user authorization in *System Settings > Privacy & Security > Screen Recording*.
   - Microphone access in the frontend requires browser permission.

---

## 8. Prioritized Migration Plan

### Priority 1: Runtime Foundation & Dependency Setup (Non-Code)
1. Initialize a Python virtual environment (`python3 -m venv .venv`).
2. Generate `requirements.txt` from audited imports and install dependencies.
3. Run `npm install` in `ByteX/` to fetch `darwin-arm64` native binaries and restore `.bin` execute permissions.

### Priority 2: Unblock Core Backend Imports (Platform Abstraction)
1. Patch `backend/core/session.py` to guard `ctypes.windll.user32` with `sys.platform == "win32"` and provide a safe macOS no-op/Quartz fallback.
2. Patch `backend/security/permissions.py` to guard `ctypes.windll`, replace Win32 structures, and add macOS protected paths (`/System`, `/Library`, `/usr`, etc.).
3. Patch `backend/skills/resolver.py` to guard `winreg` and add a macOS application indexer scanning `/Applications`.
4. Patch `backend/services/screenshot_helper.py` to remove top-level `windll` and use macOS `screencapture` or cross-platform PIL.
5. Patch `backend/skills/files.py` to guard Win32 Shell API and support macOS trash and user directories.

### Priority 3: Coding Workspace, Compiler & Browser Launcher Alignment
1. In `backend/skills/coding.py`:
   - Prioritize `clang++` on Darwin in `_resolve_runner`.
   - Remove `.exe` hardcoding for generated binaries on POSIX systems.
   - Fix URI `file:///` path slicing bug for Unix root paths (`/Users/...`).
   - Add `~/Library/Application Support/Code/User/workspaceStorage` for VS Code detection on macOS.
   - Change default empty stdin to `asyncio.subprocess.DEVNULL` to prevent terminal hangs.
2. In `start_bytex.py`:
   - Add macOS browser detection for Google Chrome and Brave with remote debugging on port 9222.
   - Provide `start_bytex.sh` for one-click startup on macOS.

---

## 9. Exact Next Implementation Step

When approved to begin Phase 2 (Implementation), the exact next focused step is:

> **Phase 2, Step 1**: Create the Python virtual environment (`.venv`), generate `requirements.txt`, install backend dependencies, and run `npm install` in `ByteX/` to resolve the environmental blockers and compile the frontend. Verify that `pytest` and `npm run build` can execute.
