"""
Browser remote-debugging (CDP) launch configuration and cleanup. Stdlib only so it can be unit tested anywhere.

What this does and does not protect
-----------------------------------
* ByteX needs the Chrome DevTools Protocol to list/open/close tabs, so it is started only on demand and only
  for the dedicated ByteX profile directories (never the user's main browser profile).
* The debugging endpoint is pinned to the loopback interface explicitly. Recent Chromium builds ignore or
  already enforce this for headed browsers, so treat it as defence in depth, not as a verified guarantee.
* CDP has NO authentication. Any process running as the same user can connect to 127.0.0.1:<port> and drive
  that browser, including reading cookies of sites the user signs into inside the ByteX profile. Loopback
  binding stops other machines, not other local processes.
* Browsers ByteX started are terminated when the backend exits so the debugging port does not outlive
  ByteX (set BYTEX_BROWSER_CLOSE_ON_EXIT=0 to keep them open).
"""

import atexit
import os
import threading
from typing import Any, List, Optional

LOOPBACK_ADDRESS = "127.0.0.1"
MIN_PORT = 1024
MAX_PORT = 65535


def cdp_base_url(port: int) -> str:
    return f"http://{LOOPBACK_ADDRESS}:{_validate_port(port)}"


def _validate_port(port: Any) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not (MIN_PORT <= port <= MAX_PORT):
        raise ValueError(f"Invalid remote-debugging port: {port!r}")
    return port


def build_cdp_launch_flags(port: int, user_data_dir: str) -> List[str]:
    """Flags used to start a Chromium-family browser with DevTools on loopback only."""
    if not user_data_dir or not isinstance(user_data_dir, str):
        raise ValueError("A dedicated user-data-dir is required; never start CDP on the default profile")
    return [
        f"--remote-debugging-port={_validate_port(port)}",
        f"--remote-debugging-address={LOOPBACK_ADDRESS}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeStartupBoost",
        "--new-window",
    ]


def close_on_exit_enabled() -> bool:
    return os.environ.get("BYTEX_BROWSER_CLOSE_ON_EXIT", "1").strip().lower() not in ("0", "false", "no", "off")


class LaunchedBrowserTracker:
    """Remembers processes ByteX itself started so they can be shut down with the backend."""

    def __init__(self) -> None:
        self._procs: List[Any] = []
        self._lock = threading.Lock()
        self._atexit_installed = False

    def add(self, proc: Any) -> None:
        with self._lock:
            self._procs.append(proc)
            if not self._atexit_installed:
                atexit.register(self.terminate_all)
                self._atexit_installed = True

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._procs)

    def terminate_all(self, timeout: float = 3.0, force: bool = False) -> int:
        """Terminate tracked processes (only those ByteX started). Returns how many were stopped."""
        if not (force or close_on_exit_enabled()):
            return 0
        with self._lock:
            procs, self._procs = self._procs, []
        stopped = 0
        for proc in procs:
            try:
                if proc.poll() is not None:
                    continue
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except Exception:
                    proc.kill()
                stopped += 1
            except Exception:
                pass
        return stopped


launched_browsers = LaunchedBrowserTracker()
