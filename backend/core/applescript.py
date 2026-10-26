"""
AppleScript execution and escaping utilities for macOS runtime safety.

Guarantees:
1. Prevents script injection by safely quoting and escaping arguments.
2. Supports argument-passing via `on run argv` so strings are never interpolated directly into script bodies.
3. Strictly uses argument lists with `shell=False`.
4. Returns structured results with return codes and detailed stderr for truthful error reporting.
"""

import sys
import subprocess
from typing import List, Optional, Tuple

IS_MACOS = sys.platform == "darwin"


def escape_applescript_string(val: str) -> str:
    """
    Escapes a string for safe inclusion in an AppleScript string literal.
    
    - Replaces backslashes with double backslashes (\\\\)
    - Replaces double quotes with escaped double quotes (\\")
    - Escapes carriage returns (\\r) and newlines (\\n)
    - Rejects null bytes (\\0) to prevent termination attacks
    """
    if not isinstance(val, str):
        val = str(val)

    if "\0" in val:
        raise ValueError("Null bytes are strictly prohibited in AppleScript arguments.")

    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return escaped


def applescript_quote(val: str) -> str:
    """
    Wraps an escaped string in AppleScript double quotes: "escaped_value".
    """
    return f'"{escape_applescript_string(val)}"'


def run_applescript(
    script: str,
    args: Optional[List[str]] = None,
    timeout: float = 5.0
) -> subprocess.CompletedProcess:
    """
    Executes an AppleScript via `osascript` using an explicit argument list.
    Never uses `shell=True`.
    """
    cmd = ["osascript", "-e", script]
    if args:
        cmd.extend([str(a) for a in args])

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )


def activate_application(app_name: str, timeout: float = 2.0) -> Tuple[bool, str]:
    """
    Safely activates a macOS application by name or bundle identifier without script injection.
    """
    if not IS_MACOS or not app_name or not app_name.strip():
        return False, "Not supported on this platform or invalid application name."

    clean_name = app_name.strip()
    script = """on run argv
    set appName to item 1 of argv
    tell application appName to activate
end run"""

    try:
        res = run_applescript(script, args=[clean_name], timeout=timeout)
        if res.returncode == 0:
            return True, res.stdout.strip()
        return False, res.stderr.strip() or f"osascript returned exit code {res.returncode}"
    except Exception as e:
        return False, str(e)


def quit_application(app_name: str, timeout: float = 3.0) -> Tuple[bool, str]:
    """
    Safely asks a macOS application to quit via AppleScript without script injection.
    """
    if not IS_MACOS or not app_name or not app_name.strip():
        return False, "Not supported on this platform or invalid application name."

    clean_name = app_name.strip()
    script = """on run argv
    set appName to item 1 of argv
    tell application appName to quit
end run"""

    try:
        res = run_applescript(script, args=[clean_name], timeout=timeout)
        if res.returncode == 0:
            return True, res.stdout.strip()
        return False, res.stderr.strip() or f"osascript returned exit code {res.returncode}"
    except Exception as e:
        return False, str(e)


def delete_to_trash(posix_path: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """
    Safely moves a file or folder to the macOS Trash via Finder without script injection.
    Uses `on run argv` and `POSIX file ... as alias` for rock-solid path handling.
    """
    if not IS_MACOS or not posix_path or not str(posix_path).strip():
        return False, "Not supported on this platform or invalid path."

    clean_path = str(posix_path).strip()
    script = """on run argv
    set filePath to item 1 of argv
    set f to POSIX file filePath as alias
    tell application "Finder" to delete f
end run"""

    try:
        res = run_applescript(script, args=[clean_path], timeout=timeout)
        if res.returncode == 0:
            return True, res.stdout.strip()
        return False, res.stderr.strip() or f"Finder delete returned code {res.returncode}"
    except Exception as e:
        return False, str(e)
