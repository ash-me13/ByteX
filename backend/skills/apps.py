import sys
import os
import asyncio
import ctypes
import shlex
import subprocess
from pathlib import Path
import psutil
from typing import Dict, Any, List, Tuple, Optional
from skills.base import BaseSkill, ToolResult

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
kernel32 = None
user32 = None
shell32 = None
WNDENUMPROC = None

if IS_WINDOWS and hasattr(ctypes, "windll"):
    try:
        from ctypes import (
            windll, byref, c_ulong, Structure, sizeof,
            c_void_p, c_wchar_p, c_ushort, c_uint32, create_unicode_buffer
        )
        kernel32 = windll.kernel32
        user32 = windll.user32
        shell32 = windll.shell32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        class STARTUPINFOW(Structure):
            _fields_ = [
                ("cb", c_uint32),
                ("lpReserved", c_wchar_p),
                ("lpDesktop", c_wchar_p),
                ("lpTitle", c_wchar_p),
                ("dwX", c_uint32),
                ("dwY", c_uint32),
                ("dwXSize", c_uint32),
                ("dwYSize", c_uint32),
                ("dwXCountChars", c_uint32),
                ("dwYCountChars", c_uint32),
                ("dwFillAttribute", c_uint32),
                ("dwFlags", c_uint32),
                ("wShowWindow", c_ushort),
                ("cbReserved2", c_ushort),
                ("lpReserved2", c_void_p),
                ("hStdInput", c_void_p),
                ("hStdOutput", c_void_p),
                ("hStdError", c_void_p),
            ]

        class PROCESS_INFORMATION(Structure):
            _fields_ = [
                ("hProcess", c_void_p),
                ("hThread", c_void_p),
                ("dwProcessId", c_uint32),
                ("dwThreadId", c_uint32),
            ]
    except Exception as e:
        pass



def launch_process_on_interactive_desktop(command_line: str) -> Tuple[bool, int, str]:
    """
    Spawns Windows process directly attached to the interactive user's 'WinSta0\\Default' desktop
    ensuring GUI windows are rendered visibly on the active monitor.
    On non-Windows, uses subprocess.Popen.
    """
    if not IS_WINDOWS or kernel32 is None:
        try:
            # Argument list, never a shell string: the command comes from the resolver, but nothing
            # in it should ever be interpreted by a shell.
            proc = subprocess.Popen(shlex.split(command_line, posix=not IS_WINDOWS), shell=False)
            return True, proc.pid, ""
        except Exception as e:
            return False, 0, f"Process launch failed: {e}"

    si = STARTUPINFOW()
    si.cb = sizeof(STARTUPINFOW)
    si.lpDesktop = "WinSta0\\Default" # Explicitly target interactive user desktop
    si.dwFlags = 0x00000001 # STARTF_USESHOWWINDOW
    si.wShowWindow = 1 # SW_SHOWNORMAL

    pi = PROCESS_INFORMATION()

    # CREATE_NEW_CONSOLE = 0x00000010
    success = kernel32.CreateProcessW(
        None,
        command_line,
        None,
        None,
        False,
        0x00000010,
        None,
        None,
        byref(si),
        byref(pi)
    )

    if success:
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)
        return True, pi.dwProcessId, ""
    else:
        err = kernel32.GetLastError()
        return False, 0, f"CreateProcessW failed with error code: {err}"

def find_matching_shortcut(app_input: str) -> Optional[Path]:
    """Resolves raw application input or shortcut path to a validated .lnk file on the system."""
    raw_path = Path(app_input.strip('"').strip("'"))
    if raw_path.exists() and raw_path.suffix.lower() == ".lnk":
        return raw_path

    clean_name = raw_path.stem.lower() if raw_path.suffix.lower() == ".lnk" else app_input.strip().lower()

    search_dirs = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]

    for s_dir in search_dirs:
        if s_dir.exists() and s_dir.is_dir():
            exact = s_dir / f"{clean_name}.lnk"
            if exact.exists():
                return exact
            try:
                for item in s_dir.rglob("*.lnk"):
                    if item.stem.lower() == clean_name or clean_name in item.stem.lower():
                        return item
            except Exception:
                continue

    return None

def find_visible_windows_on_default_desktop(proc_keywords: List[str]) -> List[Tuple[int, int, str, str]]:
    """
    Switches thread desktop context to 'Default' to enumerate top-level visible GUI windows on Windows.
    On macOS / non-Windows, inspects active processes matching proc_keywords.
    Returns: List of (hwnd, pid, proc_name, window_title)
    """
    if not IS_WINDOWS or user32 is None:
        found = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pname = (p.info['name'] or '').lower()
                if any(kw in pname for kw in proc_keywords):
                    found.append((0, p.info['pid'], pname, pname))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found

    h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if not h_default:
        h_default = user32.OpenInputDesktop(0, False, 0x01FF)

    found = []
    if h_default:
        old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        user32.SetThreadDesktop(h_default)

        def enum_cb(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    pid = c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, byref(pid))
                    proc = ""
                    try:
                        proc = psutil.Process(pid.value).name().lower()
                    except Exception:
                        pass

                    if any(kw in proc for kw in proc_keywords) or any(kw in title.lower() for kw in proc_keywords):
                        found.append((hwnd, pid.value, proc, title))
            return True

        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)

        user32.SetThreadDesktop(old_desk)
        user32.CloseDesktop(h_default)

    return found

def find_windows_for_process_or_title(app_name: str) -> List[Dict[str, Any]]:
    """Helper to find all matching open top-level windows for an application."""
    clean = app_name.strip().lower()
    keywords = [clean, clean.replace(" ", "")]
    tuples = find_visible_windows_on_default_desktop(keywords)
    results = []
    for hwnd, pid, proc_name, title in tuples:
        results.append({
            "hwnd": hwnd,
            "pid": pid,
            "proc_name": proc_name,
            "title": title
        })
    return results

class OpenApplicationSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "open_application"

    @property
    def description(self) -> str:
        return "Launches and visibly verifies Windows desktop applications and .lnk shortcuts."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "application": {"type": "string"}
            },
            "required": ["application"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        app_input = arguments.get("application", "notepad").strip()
        if not app_input:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_application",
                message="No application name specified.",
                error="Missing application argument"
            )

        # 0. Check if user requested opening a folder/directory (e.g. "Downloads", "Desktop", or absolute path)
        from skills.files import find_existing_user_folder
        folder_target = None
        if app_input.lower().startswith("folder "):
            folder_query = app_input[7:].strip()
            f_path, _, _ = find_existing_user_folder(folder_query)
            if f_path and f_path.exists():
                folder_target = f_path
        else:
            p = Path(app_input)
            if p.is_absolute() and p.is_dir():
                folder_target = p
            else:
                f_path, _, _ = find_existing_user_folder(app_input)
                if f_path and f_path.exists() and app_input.lower() in ["downloads", "documents", "pictures", "videos", "music", "desktop"]:
                    folder_target = f_path

        if folder_target:
            print(f"[ByteX PC Control] Opening folder '{folder_target.name}': {folder_target}")
            if IS_MACOS:
                subprocess.run(["/usr/bin/open", str(folder_target)])
            elif shell32 is not None:
                shell32.ShellExecuteW(None, "open", "explorer.exe", str(folder_target), None, 1)
            else:
                subprocess.run(["open" if IS_MACOS else "explorer", str(folder_target)])
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="open_application",
                message=f"Opened {folder_target.name} folder.",
                data={"application": f"{folder_target.name} Folder", "path": str(folder_target), "status": "folder_opened"}
            )

        # 1. Universal Application Resolution
        from skills.resolver import universal_app_resolver, ResolutionStatus
        status, record, candidates = universal_app_resolver.resolve(app_input)

        if status == ResolutionStatus.NOT_FOUND:
            print(f"[ByteX Universal Resolver] Application '{app_input}' not found in installed catalog.")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_application",
                message=f"I couldn't find {app_input} installed on this PC.",
                error="Application not found"
            )

        if status == ResolutionStatus.AMBIGUOUS:
            candidate_names = [c.display_name for c in candidates]
            print(f"[ByteX Universal Resolver] Ambiguous application query '{app_input}' -> {candidate_names}")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_application",
                message=f"I found multiple applications matching '{app_input}': {', '.join(candidate_names)}. Which one do you want to open?",
                data={"status": "ambiguous", "candidates": candidate_names}
            )

        label = record.display_name
        target_cmd = record.target
        proc_keywords = record.proc_keywords
        is_shell_launch = (record.target_type in ["shortcut", "protocol_uri"])

        # 1. Check if visible window is already present on the user's interactive desktop
        existing_windows = find_visible_windows_on_default_desktop(proc_keywords)
        if existing_windows:
            hwnd, pid, proc_name, title = existing_windows[0]
            if user32 is not None:
                try:
                    user32.ShowWindow(hwnd, 9) # SW_RESTORE
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    user32.SwitchToThisWindow(hwnd, True)
                except Exception:
                    pass
            elif IS_MACOS:
                try:
                    from core.applescript import activate_application
                    activate_application(label, timeout=2.0)
                except Exception:
                    pass
            msg = f"{label} opened successfully."
            clean_title = (title or "").encode("ascii", "replace").decode("ascii")
            print(f"[ByteX PC Control] Brought Existing Window to Foreground on Default Desktop: HWND {hwnd} ('{clean_title}')")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="open_application",
                message=msg,
                data={"application": label, "pid": pid, "hwnd": hwnd, "title": title, "status": "already_visible"}
            )

        # 2. Launch Validated Target
        if IS_MACOS:
            try:
                if record.target_type == "macos_app" or str(target_cmd).endswith(".app"):
                    res = subprocess.run(["/usr/bin/open", "-a", target_cmd], capture_output=True, text=True, timeout=5.0)
                else:
                    res = subprocess.run(["/usr/bin/open", target_cmd], capture_output=True, text=True, timeout=5.0)
                success = res.returncode == 0
                pid = 0
                err_msg = "" if success else res.stderr
            except Exception as e:
                success = False
                pid = 0
                err_msg = str(e)
        elif is_shell_launch:
            # Safe Windows Shell launch for .lnk shortcuts and registered protocol handlers (SW_SHOWNORMAL = 1)
            print(f"[APP_DEBUG] launching {label} via ShellExecuteW: {target_cmd}")
            ret = shell32.ShellExecuteW(None, "open", target_cmd, None, None, 1) if shell32 else 0
            success = ret > 32
            pid = 0
            err_msg = "" if success else f"ShellExecuteW returned code {ret}"
        else:
            # Direct Win32 CreateProcess on 'WinSta0\Default'
            print(f"[APP_DEBUG] launching {label} on 'WinSta0\\Default' -> {target_cmd}")
            success, pid, err_msg = launch_process_on_interactive_desktop(target_cmd)

        if not success:
            print(f"[APP_DEBUG] launch failed for {label}: {err_msg}")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_application",
                message=f"I found {label}, but couldn't open it.",
                error=err_msg
            )
        else:
            print(f"[APP_DEBUG] launch success for {label} (PID: {pid})")

        # 3. Wait for process initialization and GUI window creation
        await asyncio.sleep(1.5)

        # 4. Verify that a visible application window is now rendered on the interactive desktop
        visible_windows = find_visible_windows_on_default_desktop(proc_keywords)
        if visible_windows:
            hwnd, pid, proc_name, title = visible_windows[0]
            msg = f"{label} opened successfully."
            clean_title = (title or "").encode("ascii", "replace").decode("ascii")
            print(f"[ByteX PC Control] Visible Window Verified on Default Desktop: HWND {hwnd} ('{clean_title}')")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="open_application",
                message=msg,
                data={"application": label, "pid": pid, "hwnd": hwnd, "title": title, "status": "newly_opened"}
            )

        # 5. Process presence fallback check
        proc_running = any(any(kw in p.info['name'].lower() for kw in proc_keywords) for p in psutil.process_iter(['name']) if p.info['name'])

        if proc_running:
            msg = f"{label} opened successfully."
            print(f"[ByteX PC Control] Process confirmed active on interactive desktop (PID: {pid})")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="open_application",
                message=msg,
                data={"application": label, "status": "process_active", "pid": pid}
            )

        msg = f"{label} launch could not be verified."
        print(f"[ByteX PC Control] Launch Verification FAILED for {label}")
        return ToolResult(
            success=False,
            verified=False,
            tool=self.name,
            action="open_application",
            message=msg,
            error=f"No visible window or process detected for '{label}'."
        )

class CloseApplicationSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "close_application"

    @property
    def description(self) -> str:
        return "Safely closes a validated Windows desktop application."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "application": {"type": "string"}
            },
            "required": ["application"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        app_input = arguments.get("application", "").strip()
        if not app_input:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="close_application",
                message="No application specified.",
                error="Missing application argument"
            )

        # 0. Reject any arbitrary PID or direct process name patterns for safety
        if app_input.lower().startswith("process ") or app_input.isdigit():
            print(f"[ByteX CloseSkill] Direct PID/Process targeting rejected for security: '{app_input}'")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="close_application",
                message="Targeting arbitrary processes or PIDs directly is not permitted.",
                error="Arbitrary process targeting prohibited"
            )

        # 1. Resolve Application Identity via Universal Application Resolver
        from skills.resolver import universal_app_resolver, ResolutionStatus
        status, record, candidates = universal_app_resolver.resolve(app_input)

        if status == ResolutionStatus.NOT_FOUND:
            print(f"[ByteX Universal Resolver] Application '{app_input}' not found for close.")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="close_application",
                message=f"I couldn't find {app_input} installed on this PC.",
                error="Application not found"
            )

        if status == ResolutionStatus.AMBIGUOUS:
            candidate_names = [c.display_name for c in candidates]
            print(f"[ByteX Universal Resolver] Ambiguous application query for close '{app_input}' -> {candidate_names}")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="close_application",
                message=f"I found multiple applications matching '{app_input}': {', '.join(candidate_names)}. Which one do you want to close?",
                data={"status": "ambiguous", "candidates": candidate_names}
            )

        label = record.display_name
        proc_keywords = record.proc_keywords

        # 2. Check if application is already closed / not active
        existing_windows = find_visible_windows_on_default_desktop(proc_keywords)
        active_procs = []
        for p in psutil.process_iter(['name', 'pid']):
            try:
                pname = p.info['name']
                if pname and any(kw in pname.lower() for kw in proc_keywords):
                    active_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not existing_windows and not active_procs:
            msg = f"{label} is already closed."
            print(f"[ByteX PC Control] Application '{label}' is already closed.")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="close_application",
                message=msg,
                data={"application": label, "status": "already_closed"}
            )

        # 3. Graceful UI Window Close (PostMessage WM_CLOSE = 0x0010 on Windows or osascript quit on macOS)
        if user32 is not None:
            for hwnd, pid, proc_name, title in existing_windows:
                try:
                    print(f"[ByteX PC Control] Sending WM_CLOSE to HWND {hwnd} ('{title}')")
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                except Exception as e:
                    pass
        elif IS_MACOS:
            try:
                from core.applescript import quit_application
                quit_application(label, timeout=2.0)
            except Exception:
                pass

        await asyncio.sleep(0.8)

        # 4. Safe Process Termination Fallback if still running
        for p in active_procs:
            try:
                if p.is_running():
                    print(f"[ByteX PC Control] Terminating process {p.pid} ({p.name()})")
                    p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        await asyncio.sleep(1.0)

        # 5. Verify application is completely closed (zero visible windows and zero processes)
        remaining_windows = find_visible_windows_on_default_desktop(proc_keywords)
        remaining_procs = []
        for p in psutil.process_iter(['name', 'pid']):
            try:
                pname = p.info['name']
                if pname and any(kw in pname.lower() for kw in proc_keywords):
                    remaining_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not remaining_windows and not remaining_procs:
            msg = f"{label} closed successfully."
            print(f"[ByteX PC Control] Verified: {label} is completely closed.")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="close_application",
                message=msg,
                data={"application": label, "status": "closed"}
            )
        else:
            msg = f"{label} could not be confirmed as closed."
            print(f"[ByteX PC Control] Verification FAILED for closing {label} (remaining: {len(remaining_windows)} windows, {len(remaining_procs)} procs)")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="close_application",
                message=msg,
                error="Processes or windows remained active"
            )

class ApplicationStatusSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "application_status"

    @property
    def description(self) -> str:
        return "Checks application status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "application": {"type": "string"}
            },
            "required": ["application"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        app_input = arguments.get("application", "notepad").strip().lower()
        wins = find_visible_windows_on_default_desktop([app_input])
        is_running = len(wins) > 0 or any(app_input in p.info['name'].lower() for p in psutil.process_iter(['name']) if p.info['name'])
        status_text = "running" if is_running else "not running"
        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="application_status",
            message=f"{app_input.capitalize()} is currently {status_text}.",
            data={"application": app_input, "running": is_running, "visible_windows": len(wins)}
        )
