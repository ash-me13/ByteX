import sys
import os
import re
import time
import urllib.parse
import webbrowser
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

import httpx
import websockets
import json
import psutil

from skills.base import BaseSkill, ToolResult
from security.browser_launch import build_cdp_launch_flags, launched_browsers
from security.permissions import permissions
from security.audit_logger import audit_logger
from skills.resolver import universal_app_resolver, ResolutionStatus

KNOWN_WEBSITES = {
    "youtube": ("https://www.youtube.com", "YouTube"),
    "google": ("https://www.google.com", "Google"),
    "github": ("https://www.github.com", "GitHub"),
    "chatgpt": ("https://chatgpt.com", "ChatGPT"),
    "openai": ("https://openai.com", "OpenAI"),
    "the openai website": ("https://openai.com", "OpenAI"),
    "openai website": ("https://openai.com", "OpenAI"),
    "reddit": ("https://www.reddit.com", "Reddit"),
    "twitter": ("https://www.twitter.com", "Twitter"),
    "x": ("https://www.x.com", "X"),
    "wikipedia": ("https://www.wikipedia.org", "Wikipedia"),
    "microsoft": ("https://www.microsoft.com", "Microsoft"),
    "nios": ("https://www.nios.ac.in", "NIOS"),
    "the nios website": ("https://www.nios.ac.in", "NIOS"),
    "nios website": ("https://www.nios.ac.in", "NIOS"),
}

@dataclass
class BrowserTarget:
    """Universal browser target abstraction for ByteX."""
    browser_name: str          # "edge" | "chrome" | "brave" | "firefox"
    display_name: str          # "Microsoft Edge" | "Google Chrome" | "Brave" | "Mozilla Firefox"
    executable: Optional[str]  # Absolute path to .exe
    user_data_dir: str         # Profile directory
    profile: str               # "Default"
    automation_backend: str    # "chromium_cdp" | "firefox_automation" | "unsupported"
    cdp_port: int              # 9222 (Edge), 9223 (Chrome), 9224 (Brave)
    proc_keywords: List[str]   # Process name keywords
    is_installed: bool = False

def detect_all_supported_browsers() -> Dict[str, BrowserTarget]:
    """Detects all supported desktop browsers installed on the host system."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app = os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")

    is_macos = sys.platform == "darwin"
    user_home = Path.home()

    if is_macos:
        base_profile = str(user_home / "Library" / "Application Support" / "ByteX")
    else:
        base_profile = local_app

    browser_specs = {
        "edge": {
            "display_name": "Microsoft Edge",
            "candidates": [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                str(user_home / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                "/Applications/Microsoft Edge.app",
                str(user_home / "Applications/Microsoft Edge.app"),
                os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(local_app, r"Microsoft\Edge\Application\msedge.exe"),
            ],
            "user_data_dir": os.path.join(base_profile, "ByteX_Edge_Profile"),
            "profile": "Default",
            "automation_backend": "chromium_cdp",
            "cdp_port": 9222,
            "proc_keywords": ["msedge", "edge"]
        },
        "chrome": {
            "display_name": "Google Chrome",
            "candidates": [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                str(user_home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                "/Applications/Google Chrome.app",
                str(user_home / "Applications/Google Chrome.app"),
                os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"),
            ],
            "user_data_dir": os.path.join(base_profile, "ByteX_Chrome_Profile"),
            "profile": "Default",
            "automation_backend": "chromium_cdp",
            "cdp_port": 9223,
            "proc_keywords": ["chrome"]
        },
        "brave": {
            "display_name": "Brave",
            "candidates": [
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                str(user_home / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                "/Applications/Brave Browser.app",
                str(user_home / "Applications/Brave Browser.app"),
                os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                os.path.join(local_app, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                os.path.join(pfx86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            ],
            "user_data_dir": os.path.join(base_profile, "ByteX_Brave_Profile"),
            "profile": "Default",
            "automation_backend": "chromium_cdp",
            "cdp_port": 9224,
            "proc_keywords": ["brave"]
        },
        "firefox": {
            "display_name": "Mozilla Firefox",
            "candidates": [
                "/Applications/Firefox.app/Contents/MacOS/firefox",
                str(user_home / "Applications/Firefox.app/Contents/MacOS/firefox"),
                "/Applications/Firefox.app",
                str(user_home / "Applications/Firefox.app"),
                os.path.join(pf, r"Mozilla Firefox\firefox.exe"),
                os.path.join(pfx86, r"Mozilla Firefox\firefox.exe"),
                os.path.join(local_app, r"Mozilla Firefox\firefox.exe"),
            ],
            "user_data_dir": os.path.join(base_profile, "ByteX_Firefox_Profile"),
            "profile": "Default",
            "automation_backend": "unsupported",
            "cdp_port": 0,
            "proc_keywords": ["firefox"]
        }
    }

    result = {}
    for name, spec in browser_specs.items():
        found_path = None
        for cand in spec["candidates"]:
            if os.path.exists(cand):
                found_path = cand
                break
        result[name] = BrowserTarget(
            browser_name=name,
            display_name=spec["display_name"],
            executable=found_path,
            user_data_dir=spec["user_data_dir"],
            profile=spec["profile"],
            automation_backend=spec["automation_backend"],
            cdp_port=spec["cdp_port"],
            proc_keywords=spec["proc_keywords"],
            is_installed=found_path is not None
        )
    return result

def resolve_browser_target(
    requested_browser: Optional[str] = None,
    raw_text: Optional[str] = None
) -> Tuple[bool, Optional[BrowserTarget], str]:
    """
    Universal Browser Target Resolution according to strict priority:
    1. Explicit browser requested by the user.
    2. Saved ByteX browser preference (if configured).
    3. User's Windows default browser (from registry).
    4. First supported installed browser found on PC.
    """
    all_browsers = detect_all_supported_browsers()

    # 1. Explicit User Request
    explicit_req = None
    if requested_browser:
        explicit_req = requested_browser.strip().lower()
    elif raw_text:
        text_lower = raw_text.lower()
        for b_name in ["edge", "chrome", "brave", "firefox"]:
            if re.search(rf"\b(?:in|using|with|via|on)\s+(?:google\s+|mozilla\s+)?{b_name}\b", text_lower) or re.search(rf"\b(?:open|launch)\s+{b_name}\b", text_lower):
                explicit_req = b_name
                break

    if explicit_req:
        norm_name = "edge" if "edge" in explicit_req else ("chrome" if "chrome" in explicit_req else ("brave" if "brave" in explicit_req else ("firefox" if "firefox" in explicit_req else None)))
        if norm_name:
            target = all_browsers.get(norm_name)
            if not target or not target.is_installed:
                disp = target.display_name if target else norm_name.capitalize()
                return False, None, f"{disp} is not installed on this PC."
            if target.automation_backend == "unsupported":
                return False, target, f"Advanced browser automation and CDP control is currently not supported for {target.display_name}. Please use a supported Chromium browser (Microsoft Edge, Google Chrome, or Brave)."
            return True, target, ""

    # 2. Saved ByteX Browser Preference
    try:
        from memory.preferences import preference_manager
        pref = preference_manager.get_preference("preferred_browser")
        if pref and pref.value:
            p_val = pref.value.lower()
            for b_name in ["edge", "chrome", "brave", "firefox"]:
                if b_name in p_val:
                    target = all_browsers.get(b_name)
                    if target and target.is_installed and target.automation_backend != "unsupported":
                        return True, target, ""
    except Exception:
        pass

    # 3. Windows Default Browser (Registry)
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
                prog_id, _ = winreg.QueryValueEx(key, "ProgId")
                prog_lower = (prog_id or "").lower()
                for b_name in ["edge", "chrome", "brave", "firefox"]:
                    if b_name in prog_lower or (b_name == "edge" and "msedge" in prog_lower):
                        target = all_browsers.get(b_name)
                        if target and target.is_installed and target.automation_backend != "unsupported":
                            return True, target, ""
        except Exception:
            pass

    # 4. Fallback to First Installed Supported Chromium Browser
    for b_name in ["edge", "brave", "chrome"]:
        target = all_browsers.get(b_name)
        if target and target.is_installed and target.automation_backend != "unsupported":
            return True, target, ""

    return False, None, "No supported Chromium browser (Microsoft Edge, Google Chrome, or Brave) is installed on this PC."


class BrowserControlSkill(BaseSkill):
    """
    Universal Browser Control Skill for ByteX (Feature #32 Browser Control).
    
    Supports 14 core browser automation actions:
    1. open_browser / focus
    2. navigate
    3. back
    4. forward
    5. refresh
    6. new_tab
    7. close_tab
    8. switch_tab
    9. list_tabs
    10. search_page
    11. stop_loading
    12. get_current_page
    13. click (DOM element)
    14. search (in browser)
    """

    @property
    def name(self) -> str:
        return "browser_control"

    @property
    def description(self) -> str:
        return "Controls installed desktop browsers (Microsoft Edge) via CDP for navigation, tab management, history, and DOM interactions."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate", "open_browser", "back", "forward", "refresh",
                        "new_tab", "close_tab", "switch_tab", "list_tabs",
                        "search_page", "stop_loading", "get_current_page",
                        "click", "search"
                    ],
                    "description": "The specific browser action to execute."
                },
                "url": {
                    "type": "string",
                    "description": "Target website name, domain, or full URL."
                },
                "index": {
                    "type": "integer",
                    "description": "Tab index for switch_tab action (1-indexed)."
                },
                "target": {
                    "type": "string",
                    "description": "Target tab title/domain, or element selector for click."
                },
                "direction": {
                    "type": "string",
                    "enum": ["next", "previous"],
                    "description": "Tab switch direction ('next' or 'previous')."
                },
                "query": {
                    "type": "string",
                    "description": "Search query for search_page or web search in browser."
                },
                "selector": {
                    "type": "string",
                    "description": "DOM selector for click action."
                },
                "browser": {
                    "type": "string",
                    "description": "Target browser name ('edge', 'chrome', 'brave'). Defaults to edge."
                },
                "raw_text": {
                    "type": "string",
                    "description": "Original user command."
                }
            },
            "required": []
        }

    async def _check_cdp_alive(self, cdp_port: int) -> Tuple[bool, List[Dict[str, Any]]]:
        """Checks if CDP endpoint is reachable on the specified port."""
        if not cdp_port or cdp_port <= 0:
            return False, []
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                r = await client.get(f"http://127.0.0.1:{cdp_port}/json")
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        return True, data
        except Exception:
            pass
        return False, []

    async def _ensure_browser_ready(self, target: BrowserTarget) -> Tuple[bool, Optional[int], Optional[int]]:
        """Ensures browser process and CDP port are running, returns (is_ready, pid, hwnd)."""
        cdp_up, _ = await self._check_cdp_alive(target.cdp_port)
        if cdp_up:
            w_info = permissions.verify_application_window(target.browser_name)
            return True, w_info.get("pid"), w_info.get("hwnd")

        # Launch the browser with DevTools pinned to loopback, in ByteX's own profile only (see security/browser_launch.py)
        try:
            cdp_flags = build_cdp_launch_flags(target.cdp_port, target.user_data_dir)
            if target.executable and os.path.exists(target.executable):
                proc = subprocess.Popen([target.executable] + cdp_flags + ["http://localhost:5173"], shell=False)
                launched_browsers.add(proc)
                for _ in range(15):
                    await asyncio.sleep(0.3)
                    cdp_up, _ = await self._check_cdp_alive(target.cdp_port)
                    if cdp_up:
                        w_info = permissions.verify_application_window(target.browser_name)
                        return True, w_info.get("pid"), w_info.get("hwnd")
        except Exception as e:
            logger.error(f"[ByteX BrowserControl] Failed to launch {target.display_name}: {e}")
        return False, None, None

    async def _get_page_tabs(self, cdp_port: int) -> List[Dict[str, Any]]:
        """Returns non-extension page tabs from CDP."""
        cdp_ok, tabs = await self._check_cdp_alive(cdp_port)
        if not cdp_ok or not tabs:
            return []
        pages = [t for t in tabs if t.get("type") == "page" and not t.get("url", "").startswith("chrome-extension:")]
        return pages if pages else tabs

    async def _get_active_tab(self, cdp_port: int) -> Optional[Dict[str, Any]]:
        """Retrieves the active/focused web page tab from CDP."""
        pages = await self._get_page_tabs(cdp_port)
        if not pages:
            return None
        # Prefer non-bytex page if available, else first page
        for p in pages:
            url = p.get("url", "")
            if not ("5173" in url or "localhost:5173" in url):
                return p
        return pages[0]

    def _normalize_destination(self, raw_url: str) -> Tuple[bool, str, str]:
        """Validates and normalizes target URL."""
        raw_clean = raw_url.strip()
        raw_lower = raw_clean.lower()

        # Strict security rejection of forbidden protocols / script injections
        if any(raw_lower.startswith(proto) for proto in ["javascript:", "data:", "file:", "vbscript:", "about:", "shell:"]):
            return False, "Security Violation: Potentially unsafe protocol (javascript/data/file/shell) is strictly blocked.", ""

        if any(re.search(pat, raw_lower) for pat in [r"javascript:", r"<script", r"eval\(", r"cmd\.exe", r"powershell"]):
            return False, "Security Violation: Unsafe input or script injection detected.", ""

        if re.match(r"^[a-zA-Z]:[\\/]", raw_clean) or raw_clean.startswith(r"\\"):
            return False, "Security Violation: Local filesystem paths cannot be opened in browser navigation.", ""

        if any(raw_lower.endswith(ext) for ext in [".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh"]):
            return False, "Security Violation: Executable files and scripts cannot be opened in browser navigation.", ""

        # Shorthands
        clean_alias = re.sub(r"^(?:the\s+)?", "", raw_lower).strip()
        clean_alias = re.sub(r"\s+website$", "", clean_alias).strip()
        if clean_alias in KNOWN_WEBSITES:
            return True, KNOWN_WEBSITES[clean_alias][0], KNOWN_WEBSITES[clean_alias][1]

        if not raw_clean.startswith("http://") and not raw_clean.startswith("https://"):
            if "." in raw_clean and not " " in raw_clean:
                raw_clean = f"https://{raw_clean}"
            elif raw_clean.startswith("localhost"):
                raw_clean = f"http://{raw_clean}"
            else:
                raw_clean = f"https://www.google.com/search?q={urllib.parse.quote_plus(raw_clean)}"

        is_val, val_url = permissions.validate_url(raw_clean)
        if not is_val:
            return False, val_url, ""
        parsed = urllib.parse.urlparse(val_url)
        disp = parsed.netloc.replace("www.", "") or parsed.path
        return True, val_url, disp.capitalize()

    async def execute(self, arguments: dict) -> ToolResult:
        action = arguments.get("action", "navigate").lower().strip()
        req_browser = arguments.get("browser")
        raw_text = arguments.get("raw_text", "")

        is_resolved, target, err_msg = resolve_browser_target(req_browser, raw_text)
        if not is_resolved or not target:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action=action,
                message=err_msg or "No supported browser found.",
                error="Browser target resolution failed"
            )

        cdp_port = target.cdp_port

        # -------------------------------------------------------------
        # 1. ACTION: OPEN BROWSER / FOCUS
        # -------------------------------------------------------------
        if action in ["open_browser", "open", "focus"]:
            is_ready, pid, hwnd = await self._ensure_browser_ready(target)
            if not is_ready:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"I couldn't launch or connect to {target.display_name}.",
                    error="Browser launch failed"
                )
            # Bring window to foreground
            permissions.verify_application_window(target.browser_name)
            active_tab = await self._get_active_tab(cdp_port)
            tab_url = active_tab.get("url", "") if active_tab else "about:blank"
            tab_title = active_tab.get("title", target.display_name) if active_tab else target.display_name

            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message=f"{target.display_name} opened and focused.",
                data={
                    "browser": target.browser_name,
                    "pid": pid,
                    "hwnd": hwnd,
                    "cdp_port": cdp_port,
                    "url": tab_url,
                    "title": tab_title,
                    "tab_id": active_tab.get("id") if active_tab else None
                }
            )

        # -------------------------------------------------------------
        # 2. ACTION: LIST TABS
        # -------------------------------------------------------------
        if action in ["list_tabs", "show_tabs", "tabs"]:
            is_ready, pid, hwnd = await self._ensure_browser_ready(target)
            pages = await self._get_page_tabs(cdp_port)
            if not pages:
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action=action,
                    message="No open browser tabs found.",
                    data={"tabs": [], "count": 0}
                )
            active_tab = await self._get_active_tab(cdp_port)
            lines = ["Here are your open browser tabs:"]
            tabs_data = []
            for idx, p in enumerate(pages, 1):
                p_url = p.get("url", "")
                p_title = p.get("title") or p_url
                is_active = (active_tab and p.get("id") == active_tab.get("id"))
                prefix = "→ " if is_active else "  "
                lines.append(f"{prefix}{idx}. **{p_title}** ({p_url})")
                tabs_data.append({
                    "index": idx,
                    "tab_id": p.get("id"),
                    "title": p_title,
                    "url": p_url,
                    "is_active": is_active
                })
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message="\n".join(lines),
                data={"tabs": tabs_data, "count": len(tabs_data), "active_tab": active_tab}
            )

        # -------------------------------------------------------------
        # 3. ACTION: NEW TAB
        # -------------------------------------------------------------
        if action in ["new_tab", "create_tab"]:
            is_ready, pid, hwnd = await self._ensure_browser_ready(target)
            raw_target_url = (arguments.get("url") or "").strip()

            if raw_target_url and raw_target_url.lower() not in ["about:blank", "blank"]:
                is_val, norm_url, disp = self._normalize_destination(raw_target_url)
                if not is_val:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=action,
                        message=f"Navigation rejected: {norm_url}",
                        error=norm_url
                    )
                target_url = norm_url
                disp_title = disp or raw_target_url
            else:
                target_url = "about:blank"
                disp_title = "New Tab"

            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    encoded_url = urllib.parse.quote(target_url, safe=":/#?=&%@+")
                    r = await client.put(f"http://127.0.0.1:{cdp_port}/json/new?{encoded_url}")
                    if r.status_code == 200:
                        new_tab = r.json()
                        tab_id = new_tab.get("id")
                        await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{tab_id}")
                        pages = await self._get_page_tabs(cdp_port)
                        idx = next((i for i, p in enumerate(pages, 1) if p.get("id") == tab_id), len(pages))
                        final_title = new_tab.get("title") or disp_title
                        if final_title in ["about:blank", ""] and target_url != "about:blank":
                            final_title = disp_title

                        msg = f"Opened {disp_title} in a new tab ({target_url})." if target_url != "about:blank" else "Opened a new tab (about:blank)."
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action=action,
                            message=msg,
                            data={
                                "browser": target.browser_name,
                                "pid": pid,
                                "hwnd": hwnd,
                                "tab_id": tab_id,
                                "index": idx,
                                "url": target_url,
                                "title": final_title
                            }
                        )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"Failed to create new tab: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 4. ACTION: CLOSE TAB
        # -------------------------------------------------------------
        if action in ["close_tab", "close_current_tab"]:
            pages = await self._get_page_tabs(cdp_port)
            if not pages:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No open browser tabs to close.",
                    error="No tabs available"
                )
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab:
                active_tab = pages[0]
            tab_id = active_tab.get("id")
            
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.get(f"http://127.0.0.1:{cdp_port}/json/close/{tab_id}")
                    # Get remaining tabs
                    await asyncio.sleep(0.3)
                    rem_pages = await self._get_page_tabs(cdp_port)
                    next_tab = rem_pages[0] if rem_pages else None
                    if next_tab:
                        await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{next_tab.get('id')}")
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action=action,
                        message=f"Closed tab '{active_tab.get('title', 'Tab')}'.",
                        data={
                            "closed_tab_id": tab_id,
                            "remaining_tabs": len(rem_pages),
                            "active_tab": next_tab
                        }
                    )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"Failed to close tab: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 5. ACTION: SWITCH TAB / SELECT TAB
        # -------------------------------------------------------------
        if action in ["switch_tab", "select_tab"]:
            pages = await self._get_page_tabs(cdp_port)
            if not pages:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No browser tabs are currently open.",
                    error="No tabs"
                )

            req_idx = arguments.get("index")
            req_dir = arguments.get("direction")
            req_target = (arguments.get("target") or "").strip().lower()

            target_tab = None

            # 5.1. By Index
            if req_idx is not None:
                try:
                    i_val = int(req_idx)
                    if 1 <= i_val <= len(pages):
                        target_tab = pages[i_val - 1]
                    else:
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action=action,
                            message=f"Tab {i_val} does not exist. There are {len(pages)} open tab(s).",
                            error="Invalid tab index"
                        )
                except ValueError:
                    pass

            # 5.2. By Direction (next / previous)
            elif req_dir in ["next", "previous"]:
                active_tab = await self._get_active_tab(cdp_port)
                curr_idx = 0
                if active_tab:
                    for i, p in enumerate(pages):
                        if p.get("id") == active_tab.get("id"):
                            curr_idx = i
                            break
                new_idx = (curr_idx + 1) % len(pages) if req_dir == "next" else (curr_idx - 1) % len(pages)
                target_tab = pages[new_idx]

            # 5.3. By Title / Domain Substring Matching
            elif req_target:
                matches = []
                for p in pages:
                    p_title = p.get("title", "").lower()
                    p_url = p.get("url", "").lower()
                    if req_target in p_title or req_target in p_url:
                        matches.append(p)
                
                if len(matches) == 1:
                    target_tab = matches[0]
                elif len(matches) > 1:
                    lines = [f"I found multiple tabs matching '{req_target}'. Which one would you like to switch to?"]
                    for idx, m in enumerate(matches, 1):
                        lines.append(f"{idx}. {m.get('title', m.get('url'))}")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=action,
                        message="\n".join(lines),
                        data={"matching_tabs": matches}
                    )
                else:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=action,
                        message=f"I couldn't find an open tab matching '{req_target}'.",
                        error="Tab not found"
                    )

            if not target_tab:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="Please specify which tab to switch to (by name, number, next, or previous).",
                    error="Target tab unspecified"
                )

            tab_id = target_tab.get("id")
            ws_url = target_tab.get("webSocketDebuggerUrl")
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{tab_id}")
                if ws_url:
                    async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                        await ws.send(json.dumps({"id": 1, "method": "Page.bringToFront"}))
                permissions.verify_application_window(target.browser_name)
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action=action,
                    message=f"Switched to tab: {target_tab.get('title') or target_tab.get('url')}",
                    data={
                        "browser": target.browser_name,
                        "tab_id": tab_id,
                        "url": target_tab.get("url"),
                        "title": target_tab.get("title")
                    }
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"Failed to switch tab: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 6. ACTION: BACK / FORWARD
        # -------------------------------------------------------------
        if action in ["back", "go_back", "forward", "go_forward"]:
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab or not active_tab.get("webSocketDebuggerUrl"):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No active browser tab found to navigate history.",
                    error="No active tab"
                )
            ws_url = active_tab.get("webSocketDebuggerUrl")
            hist_expr = "window.history.back()" if "back" in action else "window.history.forward()"
            try:
                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                    await ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": hist_expr}
                    }))
                    await asyncio.sleep(0.5)
                    # Read resulting URL/title
                    await ws.send(json.dumps({
                        "id": 2,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "JSON.stringify({url: window.location.href, title: document.title})", "returnByValue": True}
                    }))
                    r_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    r_json = json.loads(r_raw)
                    val_str = r_json.get("result", {}).get("result", {}).get("value", "{}")
                    nav_data = json.loads(val_str)
                    verb = "back" if "back" in action else "forward"
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action=action,
                        message=f"Navigated {verb} to {nav_data.get('title') or nav_data.get('url')}.",
                        data={
                            "browser": target.browser_name,
                            "url": nav_data.get("url"),
                            "title": nav_data.get("title"),
                            "tab_id": active_tab.get("id")
                        }
                    )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"History navigation failed: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 7. ACTION: REFRESH / RELOAD
        # -------------------------------------------------------------
        if action in ["refresh", "reload"]:
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab or not active_tab.get("webSocketDebuggerUrl"):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No active browser tab found to refresh.",
                    error="No active tab"
                )
            ws_url = active_tab.get("webSocketDebuggerUrl")
            try:
                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                    await ws.send(json.dumps({
                        "id": 1,
                        "method": "Page.reload",
                        "params": {"ignoreCache": True}
                    }))
                    await asyncio.sleep(0.5)
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action=action,
                        message=f"Refreshed page '{active_tab.get('title') or active_tab.get('url')}'.",
                        data={
                            "browser": target.browser_name,
                            "url": active_tab.get("url"),
                            "title": active_tab.get("title"),
                            "tab_id": active_tab.get("id")
                        }
                    )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"Failed to refresh page: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 8. ACTION: STOP LOADING
        # -------------------------------------------------------------
        if action in ["stop_loading", "stop"]:
            active_tab = await self._get_active_tab(cdp_port)
            if active_tab and active_tab.get("webSocketDebuggerUrl"):
                try:
                    async with websockets.connect(active_tab.get("webSocketDebuggerUrl"), close_timeout=2.0) as ws:
                        await ws.send(json.dumps({
                            "id": 1,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "window.stop()"}
                        }))
                except Exception:
                    pass
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message="Stopped page loading.",
                data={"stopped": True}
            )

        # -------------------------------------------------------------
        # 9. ACTION: GET CURRENT PAGE
        # -------------------------------------------------------------
        if action in ["get_current_page", "current_page", "status"]:
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No active browser tab found.",
                    error="No active tab"
                )
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=action,
                message=f"Current Page: **{active_tab.get('title')}**\nURL: {active_tab.get('url')}",
                data={
                    "browser": target.browser_name,
                    "url": active_tab.get("url"),
                    "title": active_tab.get("title"),
                    "tab_id": active_tab.get("id")
                }
            )

        # -------------------------------------------------------------
        # 10. ACTION: SEARCH PAGE (DOM IN-PAGE FIND)
        # -------------------------------------------------------------
        if action in ["search_page", "find_in_page"]:
            search_query = arguments.get("query") or arguments.get("target") or ""
            if not search_query:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="Please provide a search term to find on this page.",
                    error="Empty search query"
                )
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab or not active_tab.get("webSocketDebuggerUrl"):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message="No active browser tab found to search.",
                    error="No active tab"
                )
            ws_url = active_tab.get("webSocketDebuggerUrl")
            try:
                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                    q_json = json.dumps(search_query)
                    find_expr = f"""
                    (() => {{
                        const query = {q_json}.toLowerCase();
                        const bodyText = document.body ? document.body.innerText.toLowerCase() : "";
                        let count = 0;
                        let pos = 0;
                        while ((pos = bodyText.indexOf(query, pos)) !== -1) {{
                            count++;
                            pos += query.length;
                        }}
                        return {{ found: count > 0, count: count, query: {q_json} }};
                    }})()
                    """
                    await ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": find_expr, "returnByValue": True}
                    }))
                    r_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    r_data = json.loads(r_raw).get("result", {}).get("result", {}).get("value", {})
                    found_count = r_data.get("count", 0)
                    if found_count > 0:
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action=action,
                            message=f"Found {found_count} occurrence(s) of '{search_query}' on this page.",
                            data={"found": True, "count": found_count, "query": search_query}
                        )
                    else:
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action=action,
                            message=f"'{search_query}' was not found on the current page.",
                            data={"found": False, "count": 0, "query": search_query}
                        )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=action,
                    message=f"In-page search failed: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 11. ACTION: DOM CLICK
        # -------------------------------------------------------------
        if action == "click":
            selector = (arguments.get("selector") or arguments.get("element") or arguments.get("target") or "").strip()
            if not selector:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="click",
                    message="Click target or selector cannot be empty.",
                    error="Missing element identifier"
                )
            active_tab = await self._get_active_tab(cdp_port)
            if not active_tab or not active_tab.get("webSocketDebuggerUrl"):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="click",
                    message="No active browser tab found to click element.",
                    error="No active tab"
                )
            ws_url = active_tab.get("webSocketDebuggerUrl")
            try:
                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                    sel_json = json.dumps(selector)
                    click_expr = f"""
                    (() => {{
                        const sel = {sel_json};
                        let el = document.querySelector(sel);
                        if (!el) {{
                            const items = Array.from(document.querySelectorAll("button, a, input, [role='button']"));
                            el = items.find(e => e.innerText && e.innerText.trim().toLowerCase() === sel.toLowerCase());
                        }}
                        if (el) {{
                            el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            el.click();
                            return {{ clicked: true, tag: el.tagName }};
                        }}
                        return {{ clicked: false }};
                    }})()
                    """
                    await ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": click_expr, "returnByValue": True}
                    }))
                    r_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    c_res = json.loads(r_raw).get("result", {}).get("result", {}).get("value", {})
                    if c_res.get("clicked"):
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action="click",
                            message=f"Clicked '{selector}' on webpage.",
                            data={"clicked": True, "selector": selector}
                        )
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="click",
                        message=f"Element '{selector}' not found on webpage.",
                        error="Element not found"
                    )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="click",
                    message=f"Click failed: {e}",
                    error=str(e)
                )

        # -------------------------------------------------------------
        # 12. ACTION: NAVIGATE / OPEN URL (DEFAULT NEW TAB SEMANTICS)
        # -------------------------------------------------------------
        raw_destination = arguments.get("url") or arguments.get("target") or arguments.get("query") or ""
        is_val, target_url, display_title = self._normalize_destination(raw_destination)
        if not is_val:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="navigate",
                message=f"Navigation rejected: {target_url}",
                error="Invalid destination"
            )

        is_ready, pid, hwnd = await self._ensure_browser_ready(target)
        if not is_ready:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="navigate",
                message=f"Could not connect to {target.display_name}.",
                error="Browser connection failed"
            )

        # Check for explicit in-place / current tab navigation request
        is_explicit_current = (
            bool(arguments.get("current_tab"))
            or action in ["navigate_current", "navigate_this_tab", "replace_tab", "replace_current_tab"]
            or bool(re.search(r"\b(?:this\s+tab|the\s+current\s+tab|current\s+tab|active\s+tab|replace\s+this|reuse\s+this)\b", raw_text, flags=re.IGNORECASE))
        )

        pages = await self._get_page_tabs(cdp_port)
        active_tab = await self._get_active_tab(cdp_port)

        if is_explicit_current:
            # -------------------------------------------------------------
            # Explicit Current Tab In-Place Navigation
            # -------------------------------------------------------------
            tab_to_use = active_tab or (pages[0] if pages else None)
            if not tab_to_use:
                # No tab exists: create one
                async with httpx.AsyncClient(timeout=2.5) as client:
                    encoded = urllib.parse.quote(target_url, safe=":/#?=&%@+")
                    r = await client.put(f"http://127.0.0.1:{cdp_port}/json/new?{encoded}")
                    tab_to_use = r.json()
                    tab_id = tab_to_use.get("id")
                    await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{tab_id}")
            else:
                ws_url = tab_to_use.get("webSocketDebuggerUrl")
                if ws_url:
                    try:
                        async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                            await ws.send(json.dumps({
                                "id": 1,
                                "method": "Page.navigate",
                                "params": {"url": target_url}
                            }))
                            await asyncio.sleep(0.5)
                            await ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))
                    except Exception:
                        pass
                tab_id = tab_to_use.get("id")
                if tab_id:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{tab_id}")

            permissions.verify_application_window(target.browser_name)
            updated_pages = await self._get_page_tabs(cdp_port)
            idx = next((i for i, p in enumerate(updated_pages, 1) if p.get("id") == tab_id), 1)

            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="navigate",
                message=f"{display_title} opened in current tab.",
                data={
                    "browser": target.browser_name,
                    "url": target_url,
                    "destination": display_title,
                    "title": display_title,
                    "pid": pid,
                    "hwnd": hwnd,
                    "cdp_port": cdp_port,
                    "tab_id": tab_id,
                    "index": idx,
                    "current_tab": True
                }
            )

        # -------------------------------------------------------------
        # DEFAULT: Open In A New Browser Tab (Preserving Active Tab / ByteX)
        # -------------------------------------------------------------
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                encoded = urllib.parse.quote(target_url, safe=":/#?=&%@+")
                r = await client.put(f"http://127.0.0.1:{cdp_port}/json/new?{encoded}")
                if r.status_code == 200:
                    new_tab = r.json()
                    tab_id = new_tab.get("id")
                    # Activate the newly created tab
                    await client.get(f"http://127.0.0.1:{cdp_port}/json/activate/{tab_id}")

                    # Connect to WebSocket to bringToFront and verify resulting URL
                    ws_url = new_tab.get("webSocketDebuggerUrl")
                    resulting_title = display_title
                    resulting_url = target_url
                    if ws_url:
                        try:
                            async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                                await ws.send(json.dumps({"id": 1, "method": "Page.bringToFront"}))
                                await asyncio.sleep(0.3)
                                await ws.send(json.dumps({
                                    "id": 2,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": "JSON.stringify({url: window.location.href, title: document.title})", "returnByValue": True}
                                }))
                                r_raw = await asyncio.wait_for(ws.recv(), timeout=2.5)
                                r_json = json.loads(r_raw)
                                val_str = r_json.get("result", {}).get("result", {}).get("value", "{}")
                                page_info = json.loads(val_str)
                                if page_info.get("title") and page_info.get("title") not in ["about:blank", ""]:
                                    resulting_title = page_info.get("title")
                                if page_info.get("url") and page_info.get("url") not in ["about:blank", ""]:
                                    resulting_url = page_info.get("url")
                        except Exception:
                            pass

                    permissions.verify_application_window(target.browser_name)
                    updated_pages = await self._get_page_tabs(cdp_port)
                    idx = next((i for i, p in enumerate(updated_pages, 1) if p.get("id") == tab_id), len(updated_pages))

                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="navigate",
                        message=f"{display_title} opened successfully in a new tab.",
                        data={
                            "browser": target.browser_name,
                            "url": resulting_url,
                            "destination": display_title,
                            "title": resulting_title or display_title,
                            "pid": pid,
                            "hwnd": hwnd,
                            "cdp_port": cdp_port,
                            "tab_id": tab_id,
                            "index": idx,
                            "is_new_tab": True
                        }
                    )
        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="navigate",
                message=f"Failed to open {display_title} in a new tab: {e}",
                error=str(e)
            )

# Backward-compatibility alias
OpenWebsiteSkill = BrowserControlSkill
browser_skill = BrowserControlSkill()
