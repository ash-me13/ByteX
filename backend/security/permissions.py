import sys
import os
import re
import ctypes
import psutil
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

user32 = None
kernel32 = None
WNDENUMPROC = None
RECT = None

if IS_WINDOWS and hasattr(ctypes, "windll"):
    try:
        from ctypes import windll, byref, c_ulong, create_unicode_buffer, wintypes
        user32 = windll.user32
        kernel32 = windll.kernel32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)
            ]

        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
    except Exception as e:
        pass

ALLOWED_APPLICATIONS = {
    "chrome": ["chrome", "google chrome"],
    "edge": ["edge", "msedge", "microsoft edge"],
    "notepad": ["notepad", "textedit"],
    "calc": ["calc", "calculator"],
    "code": ["code", "vscode", "visual studio code"],
    "mspaint": ["mspaint", "paint"],
    "cmd": ["cmd", "command prompt", "terminal"],
    "powershell": ["powershell"],
    "terminal": ["terminal"],
    "safari": ["safari"],
    "textedit": ["textedit"],
    "finder": ["finder"],
    "explorer": ["explorer", "file explorer", "finder"],
    "discord": ["discord"],
    "spotify": ["spotify"],
    "whatsapp": ["whatsapp", "whatsapp desktop"],
}

# Root-anchored protected system roots on macOS (protects system while permitting user-owned files & temp dirs)
MACOS_PROTECTED_ROOTS = [
    "/system",
    "/library",        # Root-level /Library (does NOT block /Users/<user>/Library)
    "/usr",            # /usr/bin, /usr/sbin, /usr/lib, /usr/libexec, /usr/share
    "/bin",
    "/sbin",
    "/private/etc",
    "/etc",
    "/private/var/root",
    "/var/root",
    "/private/var/db",
    "/var/db",
    "/private/var/log",
    "/var/log",
    "/private/var/audit",
    "/var/audit",
]

# Sensitive credentials, private keys, and user security directories across all platforms
SENSITIVE_PATH_PATTERNS = [
    r"(?:^|/)\.ssh(?:/|$)",
    r"(?:^|/)\.gnupg(?:/|$)",
    r"(?:^|/)\.aws(?:/|$)",
    r"(?:^|/)\.env(?:\..+)?$",
    r"(?:^|/)(?:id_rsa|id_ed25519|id_ecdsa|id_dsa)(?:\.pub)?$",
    r"(?:^|/)(?:master\.passwd|shadow|sudoers)$",
    r"\.(?:pem|key|pfx|p12|keystore)$",
    r"(?:credentials|passwords?)\.(?:json|ya?ml|txt|ini|env)$",
]

BLOCKED_PATH_PATTERNS = [
    # Windows system paths
    r"c:\\windows",
    r"c:\\program files",
    r"c:\\program files \(x86\)",
    r"c:\\programdata",
    r"system32",
    r"syswow64",
    r"system volume information",
]

# Hidden background system window titles to ignore
IGNORE_WINDOW_TITLES = {
    "tooltip",
    "default ime",
    "cicerouiwndframe",
    "tf_floatinglangbar_wndtitle",
    "gdi+ window (notepad.exe)",
}

# Win32 RECT structure initialized conditionally above when IS_WINDOWS is True

class SecurityPermissions:
    """Security permissions & allowlist enforcement engine."""

    @staticmethod
    def get_allowed_app_key(app_name: str) -> Optional[str]:
        """Resolves raw application input to an allowlisted app key, validated catalog target, or valid .lnk shortcut."""
        norm = app_name.strip().lower()
        for key, aliases in ALLOWED_APPLICATIONS.items():
            if norm == key or norm in aliases:
                return key

        # Check against Universal Application Resolver (Start Menu, Desktop, Registry, Builtins)
        try:
            from skills.resolver import universal_app_resolver, ResolutionStatus
            status, rec, _ = universal_app_resolver.resolve(app_name)
            if status == ResolutionStatus.FOUND and rec:
                return rec.normalized_name
        except Exception:
            pass

        # Check if input corresponds to an existing .lnk shortcut on the system
        from skills.apps import find_matching_shortcut
        try:
            lnk = find_matching_shortcut(app_name)
            if lnk and lnk.exists():
                return str(lnk)
        except Exception:
            pass

        return None

    @staticmethod
    def get_allowed_app_executable(app_name: str) -> Optional[str]:
        """Alias for get_allowed_app_key."""
        return SecurityPermissions.get_allowed_app_key(app_name)

    @staticmethod
    def resolve_executable_path(app_key: str) -> Tuple[Optional[str], List[str], List[str]]:
        """
        Resolves trusted executable path, process keywords, and window title keywords.
        Returns: (executable_cmd, process_keywords, title_keywords)
        """
        key = app_key.lower().strip()

        if IS_MACOS:
            # macOS application bundles and binaries
            macos_apps = {
                "chrome": ("/Applications/Google Chrome.app", ["chrome", "google chrome"]),
                "google chrome": ("/Applications/Google Chrome.app", ["chrome", "google chrome"]),
                "safari": ("/Applications/Safari.app", ["safari"]),
                "edge": ("/Applications/Microsoft Edge.app", ["msedge", "edge", "microsoft edge"]),
                "msedge": ("/Applications/Microsoft Edge.app", ["msedge", "edge", "microsoft edge"]),
                "calc": ("/System/Applications/Calculator.app", ["calc", "calculator"]),
                "calculator": ("/System/Applications/Calculator.app", ["calc", "calculator"]),
                "notepad": ("/System/Applications/TextEdit.app", ["textedit", "notepad"]),
                "textedit": ("/System/Applications/TextEdit.app", ["textedit", "notepad"]),
                "code": ("/Applications/Visual Studio Code.app", ["code", "visual studio code"]),
                "vscode": ("/Applications/Visual Studio Code.app", ["code", "visual studio code"]),
                "terminal": ("/System/Applications/Utilities/Terminal.app", ["terminal"]),
                "cmd": ("/System/Applications/Utilities/Terminal.app", ["terminal", "cmd"]),
                "spotify": ("/Applications/Spotify.app", ["spotify"]),
                "discord": ("/Applications/Discord.app", ["discord"]),
                "whatsapp": ("/Applications/WhatsApp.app", ["whatsapp"]),
            }
            if key in macos_apps:
                app_path, kws = macos_apps[key]
                return f'open -a "{app_path}"', kws, kws
            return f'open -a "{key}"', [key], [key]

        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))

        if key in ["chrome", "google chrome"]:
            candidates = [
                os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    return f'"{c}"', ["chrome"], ["chrome"]
            return "start chrome", ["chrome"], ["chrome"]

        if key in ["edge", "msedge", "microsoft edge"]:
            candidates = [
                os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(local_app, r"Microsoft\Edge\Application\msedge.exe"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    return f'"{c}"', ["msedge", "edge", "microsoft edge"], ["edge", "microsoft edge", "msedge"]
            return "start msedge", ["msedge", "edge", "microsoft edge"], ["edge", "microsoft edge", "msedge"]

        if key == "notepad":
            return "notepad.exe", ["notepad"], ["notepad"]

        if key in ["calc", "calculator"]:
            return "calc.exe", ["calc", "calculator"], ["calculator", "calc"]

        if key in ["code", "vscode"]:
            return "code", ["code"], ["visual studio code", "code"]

        if key in ["mspaint", "paint"]:
            return "mspaint.exe", ["mspaint"], ["paint"]

        if key in ["cmd", "command prompt"]:
            return "cmd.exe", ["cmd"], ["command prompt", "cmd"]

        if key == "powershell":
            return "powershell.exe", ["powershell"], ["powershell"]

        if key in ["explorer", "file explorer"]:
            return "explorer.exe", ["explorer"], ["explorer", "file explorer"]

        if key == "discord":
            return "Discord.exe", ["discord"], ["discord"]

        if key == "spotify":
            return "Spotify.exe", ["spotify"], ["spotify"]

        if key in ["whatsapp", "whatsapp desktop"]:
            return "whatsapp:", ["whatsapp", "whatsapp.root"], ["whatsapp"]

        return None, [key], [key]

    @staticmethod
    def verify_application_window(app_key: str, target_pid: Optional[int] = None, target_hwnd: Optional[int] = None) -> Dict[str, Any]:
        """
        Generic Windows Window Verification Helper.
        Enumerates top-level Windows desktop windows using User32 EnumWindows API.
        Checks for REAL visible windows (filtering out hidden IME/tooltip frames),
        ensures the window is on-screen, restores minimized windows, forces foreground focus,
        and returns structured inspection data.
        """
        exe_cmd, proc_keywords, title_keywords = SecurityPermissions.resolve_executable_path(app_key)
        if not exe_cmd and target_pid is None and target_hwnd is None:
            return {
                "verified": False,
                "process_found": False,
                "window_found": False,
                "visible": False,
                "window_title": "",
                "pid": None,
                "hwnd": None
            }

        if not IS_WINDOWS or user32 is None:
            # macOS / non-Windows process and window verification
            matched_proc = None
            if target_pid and psutil.pid_exists(target_pid):
                try:
                    matched_proc = psutil.Process(target_pid)
                except Exception:
                    pass
            if not matched_proc:
                for p in psutil.process_iter(["pid", "name"]):
                    try:
                        pname = (p.info["name"] or "").lower()
                        if any(kw in pname for kw in proc_keywords):
                            matched_proc = p
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            if not matched_proc:
                return {
                    "verified": False,
                    "process_found": False,
                    "window_found": False,
                    "visible": False,
                    "window_title": "",
                    "pid": None,
                    "hwnd": None
                }

            pid = matched_proc.pid
            pname = matched_proc.name()
            # On macOS, check if it's the frontmost application via AppleScript
            is_fg = False
            front_title = pname
            if IS_MACOS:
                try:
                    import subprocess
                    script = 'tell application "System Events" to get name of first process whose frontmost is true'
                    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
                    if res.returncode == 0:
                        front_app = res.stdout.strip()
                        if front_app and (front_app.lower() in pname.lower() or any(kw in front_app.lower() for kw in proc_keywords)):
                            is_fg = True
                            front_title = front_app
                except Exception:
                    pass

            return {
                "verified": True,
                "process_found": True,
                "window_found": True,
                "visible": True,
                "minimized": False,
                "is_foreground": is_fg,
                "hwnd": None,
                "pid": pid,
                "rect": (0, 0, 1920, 1080),
                "window_title": front_title
            }

        found_windows = []

        h_default = user32.OpenInputDesktop(0, False, 0x01FF)
        if not h_default:
            h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)

        old_desk = None
        if h_default:
            old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            user32.SetThreadDesktop(h_default)

        def enum_window_callback(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    title_clean = title.replace("\u200b", "").lower()

                    # Ignore internal hidden background UI titles
                    if title_clean in IGNORE_WINDOW_TITLES or title_clean.startswith("gdi+"):
                        return True

                    pid = c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, byref(pid))

                    proc_name = ""
                    try:
                        p = psutil.Process(pid.value)
                        proc_name = p.name().lower()
                    except Exception:
                        pass

                    proc_matched = any(kw in proc_name for kw in proc_keywords) if proc_name else False
                    title_matched = any(kw in title_clean for kw in title_keywords)

                    if target_hwnd is not None and hwnd != target_hwnd:
                        return True

                    if target_pid is not None:
                        is_target = (pid.value == target_pid)
                        if not is_target:
                            try:
                                is_target = (psutil.Process(pid.value).ppid() == target_pid)
                            except Exception:
                                pass
                        if not is_target:
                            return True

                    if proc_matched or title_matched or target_pid is not None or target_hwnd is not None:
                        rect = RECT()
                        user32.GetWindowRect(hwnd, byref(rect))
                        is_minimized = bool(user32.IsIconic(hwnd))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top

                        # Filter out invisible 0x0 tool windows if not minimized
                        if not is_minimized and (w <= 10 or h <= 10):
                            return True

                        found_windows.append({
                            "hwnd": hwnd,
                            "pid": pid.value,
                            "proc_name": proc_name,
                            "title": title,
                            "rect": (rect.left, rect.top, rect.right, rect.bottom),
                            "minimized": is_minimized
                        })
            return True

        try:
            cb_func = WNDENUMPROC(enum_window_callback)
            if h_default:
                user32.EnumDesktopWindows(h_default, cb_func, 0)
            if not found_windows:
                user32.EnumWindows(cb_func, 0)
        finally:
            if h_default and old_desk:
                user32.SetThreadDesktop(old_desk)
                user32.CloseDesktop(h_default)

        # Check background process status
        proc_found = False
        if target_pid:
            proc_found = psutil.pid_exists(target_pid)
        else:
            for p in psutil.process_iter(['name']):
                try:
                    name = p.info['name']
                    if name and any(kw in name.lower() for kw in proc_keywords):
                        proc_found = True
                        break
                except Exception:
                    pass

        if not found_windows:
            print(f"[PC] Application: {app_key} | Process found: {proc_found} | Window found: False | Visible: False | Verification: False")
            return {
                "verified": False,
                "process_found": proc_found,
                "window_found": False,
                "visible": False,
                "window_title": "",
                "pid": target_pid,
                "hwnd": None
            }

        target_win = found_windows[0]
        hwnd = target_win["hwnd"]

        # 1. Restore window if minimized
        if target_win["minimized"]:
            user32.ShowWindow(hwnd, 9) # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5) # SW_SHOW

        # 2. Check window bounds and ensure on-screen
        rect = RECT()
        user32.GetWindowRect(hwnd, byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        # If off-screen or too small, reposition and size onto primary display
        if w < 300 or h < 200 or rect.right < 100 or rect.bottom < 100 or rect.left > 3000 or rect.top > 3000:
            user32.SetWindowPos(hwnd, 0, 100, 100, 1280, 800, 0x0040) # SWP_SHOWWINDOW

        # 3. Robust Foreground Window Activation and Z-Order Management
        try:
            h_input = user32.OpenInputDesktop(0, False, 0x01FF)
            old_d = None
            if h_input:
                old_d = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
                user32.SetThreadDesktop(h_input)

            # If activating browser, lower any fullscreen Antigravity/ByteX window to bottom of Z-order
            if any(k in app_key.lower() for k in ["edge", "msedge", "chrome", "brave", "firefox", "browser"]):
                def lower_antigravity_cb(h_other, lp):
                    if h_other != hwnd and user32.IsWindowVisible(h_other):
                        pid_other = c_ulong()
                        user32.GetWindowThreadProcessId(h_other, byref(pid_other))
                        try:
                            p_name = psutil.Process(pid_other.value).name().lower()
                            if "antigravity" in p_name:
                                # Send Antigravity behind the activated browser
                                user32.SetWindowPos(h_other, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010) # HWND_BOTTOM | SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                        except Exception:
                            pass
                    return True

                try:
                    if h_input:
                        user32.EnumDesktopWindows(h_input, WNDENUMPROC(lower_antigravity_cb), 0)
                    else:
                        user32.EnumWindows(WNDENUMPROC(lower_antigravity_cb), 0)
                except Exception:
                    pass

            fg_hwnd = user32.GetForegroundWindow()
            cur_thread_id = kernel32.GetCurrentThreadId()
            fg_thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)

            if fg_thread_id and fg_thread_id != cur_thread_id:
                user32.AttachThreadInput(cur_thread_id, fg_thread_id, True)
            if target_thread_id and target_thread_id != cur_thread_id:
                user32.AttachThreadInput(cur_thread_id, target_thread_id, True)

            # Bypass Windows LockSetForegroundWindow via simulated Alt key tap
            VK_MENU = 0x12
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

            # Bring to Top and Set Foreground
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SwitchToThisWindow(hwnd, True)

            if fg_thread_id and fg_thread_id != cur_thread_id:
                user32.AttachThreadInput(cur_thread_id, fg_thread_id, False)
            if target_thread_id and target_thread_id != cur_thread_id:
                user32.AttachThreadInput(cur_thread_id, target_thread_id, False)

            if h_input and old_d:
                user32.SetThreadDesktop(old_d)
                user32.CloseDesktop(h_input)
        except Exception as e:
            print(f"[Permissions] Window foreground activation: {e}")

        # Check final foreground state
        final_fg_hwnd = user32.GetForegroundWindow()
        fg_pid = c_ulong()
        if final_fg_hwnd:
            user32.GetWindowThreadProcessId(final_fg_hwnd, byref(fg_pid))

        is_fg = bool(final_fg_hwnd == hwnd or fg_pid.value == target_win["pid"])

        clean_title = (target_win['title'] or "").encode('ascii', 'replace').decode('ascii')
        print(f"[PC] Application: {app_key} | Process found: True | Window found: True | Visible: True | Title: '{clean_title}' | PID: {target_win['pid']} | HWND: {hwnd} | Foreground: {is_fg}")

        return {
            "verified": True,
            "process_found": True,
            "window_found": True,
            "visible": True,
            "minimized": False,
            "is_foreground": is_fg,
            "hwnd": hwnd,
            "pid": target_win["pid"],
            "rect": target_win.get("rect") or (rect.left, rect.top, rect.right, rect.bottom),
            "window_title": target_win["title"]
        }

    @staticmethod
    def validate_url(url: str) -> Tuple[bool, str]:
        """Validates URL protocols, allowing only http/https."""
        url_clean = url.strip()
        if not url_clean:
            return False, "URL cannot be empty."

        lower_raw = url_clean.lower()
        if lower_raw.startswith("javascript:") or lower_raw.startswith("file:") or lower_raw.startswith("data:") or lower_raw.startswith("shell:"):
            return False, "Security Violation: Potentially unsafe protocol (file/javascript/data/shell) is strictly blocked."

        if not re.match(r"^[a-zA-Z0-9]+://", url_clean):
            url_clean = "https://" + url_clean

        lower_url = url_clean.lower()
        if not (lower_url.startswith("http://") or lower_url.startswith("https://")):
            return False, "Security Violation: Only HTTP/HTTPS web URLs are allowed."

        return True, url_clean

    @staticmethod
    def validate_path(target_path: str) -> Tuple[bool, str, Optional[Path]]:
        """Restricts file access to safe user directories."""
        if not target_path or not str(target_path).strip():
            return False, "Target path cannot be empty.", None

        raw_str = str(target_path).strip()

        # 1. Reject UNC network paths
        if raw_str.startswith(r"\\") or raw_str.startswith("//"):
            return False, "Security Violation: UNC network paths are blocked.", None

        # 2. Reject path traversal attempts in raw string
        parts = raw_str.replace("\\", "/").split("/")
        if ".." in parts:
            return False, "Security Violation: Path traversal ('..') is strictly blocked.", None

        try:
            raw_path = Path(raw_str).expanduser()
            resolved = raw_path.resolve()

            # Check both raw path (with user expansion) and real resolved symlink target
            paths_to_check = [str(raw_path), str(resolved)]

            for p in paths_to_check:
                p_norm = p.replace("\\", "/").lower()

                # On macOS / POSIX, check protected system roots
                if IS_MACOS or not IS_WINDOWS:
                    for root in MACOS_PROTECTED_ROOTS:
                        if p_norm == root or p_norm.startswith(root + "/"):
                            return False, f"Security Violation: Path access to restricted system directory '{root}' is blocked.", None

                # On Windows, check Windows system directories
                if IS_WINDOWS:
                    for pattern in BLOCKED_PATH_PATTERNS:
                        if re.search(pattern, p_norm):
                            return False, f"Security Violation: Path access to restricted system directory '{pattern}' is blocked.", None

                # Check sensitive credential, key, and user security paths (e.g. ~/.ssh) across all platforms
                for pattern in SENSITIVE_PATH_PATTERNS:
                    if re.search(pattern, p_norm):
                        return False, f"Security Violation: Access to sensitive path matching pattern '{pattern}' is blocked.", None

            return True, "Path validated.", resolved
        except Exception as e:
            return False, f"Invalid filesystem path: {e}", None

permissions = SecurityPermissions()
