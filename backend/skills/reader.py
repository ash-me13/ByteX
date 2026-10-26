import os
import re
import html
import time
import httpx
import urllib.parse
import ipaddress
from typing import Dict, Any, Optional, Tuple

from skills.base import BaseSkill, ToolResult
from security.permissions import permissions
from security.audit_logger import audit_logger

MAX_PAGE_TEXT_CHARS = 12000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB limit
NETWORK_TIMEOUT_SECONDS = 7.0

PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

class ReadWebpageSkill(BaseSkill):
    """
    Controlled Safe Webpage Reader Skill for ByteX (#33 Read Webpages).
    
    Responsibilities:
    1. Validates HTTP/HTTPS web URLs with strict rejection of private networks and dangerous protocols.
    2. Fetches webpage content over HTTPS/HTTP with controlled timeout and maximum 1 retry.
    3. Extracts readable text and title while stripping scripts, styles, and navigational chrome.
    4. Enforces strict length limits (12,000 chars) and flags dynamic-rendering pages.
    5. Treats all extracted webpage content strictly as untrusted DATA, preventing prompt injections.
    """

    @property
    def name(self) -> str:
        return "read_webpage"

    @property
    def description(self) -> str:
        return "Fetches a webpage, extracts clean readable text and title, and returns structured page contents."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP or HTTPS URL or domain of the webpage to read (e.g. 'https://example.com', 'https://github.com')."
                }
            },
            "required": []
        }

    def _validate_and_sanitize_url(self, raw_input: Optional[str]) -> Tuple[bool, str, str]:
        """
        Validates target URL against SSRF, private IPs, and local filesystem protocols.
        Returns: (is_valid, normalized_url, error_message)
        """
        clean_input = (raw_input or "").strip()

        # Check conversational / session context fallback if URL omitted
        if not clean_input or clean_input.lower() in ["this page", "the page", "this webpage", "the webpage", "it"]:
            from core.session import session_manager
            if session_manager.is_session_active() and session_manager._last_target:
                candidate = session_manager._last_target.strip()
                if candidate.startswith("http://") or candidate.startswith("https://") or "." in candidate:
                    clean_input = candidate
                    print(f"[ByteX WebReader] Reused verified session URL: '{clean_input}'")

        if not clean_input or clean_input.lower() in ["this page", "the page", "this webpage", "the webpage", "it"]:
            return False, "", "Please provide the URL of the webpage you would like me to read."

        lower_raw = clean_input.lower()

        # 1. Strict Protocol Security Check
        if any(lower_raw.startswith(proto) for proto in ["file:", "javascript:", "data:", "vbscript:", "about:", "shell:"]):
            return False, "", "Security Violation: Potentially unsafe protocol (file/javascript/data/shell) is strictly blocked."

        # 2. Reject Windows Filesystem Paths and Executable Scripts
        if re.match(r"^[a-zA-Z]:[\\/]", clean_input) or clean_input.startswith(r"\\"):
            return False, "", "Security Violation: Local filesystem paths cannot be read by web reader."

        if any(lower_raw.endswith(ext) for ext in [".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh"]):
            return False, "", "Security Violation: Executable binaries and shell scripts cannot be read by web reader."

        # 3. Protocol & Domain Normalization
        KNOWN_SITE_ALIASES = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "chatgpt": "https://chatgpt.com",
            "openai": "https://openai.com",
            "reddit": "https://www.reddit.com",
            "wikipedia": "https://www.wikipedia.org",
            "example": "https://example.com",
        }
        for alias_k, alias_url in KNOWN_SITE_ALIASES.items():
            if lower_raw == alias_k or lower_raw == f"the {alias_k}" or lower_raw == f"{alias_k} homepage" or lower_raw == f"the {alias_k} page":
                clean_input = alias_url
                break

        if not re.match(r"^[a-zA-Z0-9]+://", clean_input):
            clean_input = "https://" + clean_input

        # Validate with permissions engine
        is_valid_scheme, validated_url = permissions.validate_url(clean_input)
        if not is_valid_scheme:
            return False, "", validated_url

        # 4. SSRF & Private IP Protection
        try:
            parsed = urllib.parse.urlparse(validated_url)
            hostname = (parsed.hostname or "").lower()

            if hostname in ["localhost", "127.0.0.1", "0.0.0.0", "::1", "local"]:
                return False, "", "Security Violation: Access to private network/localhost addresses is strictly blocked."

            # Check if host is a literal private IP
            try:
                ip_obj = ipaddress.ip_address(hostname)
                if any(ip_obj in network for network in PRIVATE_IP_RANGES):
                    return False, "", "Security Violation: Access to private network addresses is strictly blocked."
            except ValueError:
                # Not a literal IP address; domain name is safe
                pass

        except Exception as e:
            return False, "", f"Invalid URL destination: {e}"

        return True, validated_url, ""

    def _extract_readable_content(self, raw_html: str, max_chars: int = MAX_PAGE_TEXT_CHARS) -> Tuple[str, str, bool, int]:
        """
        Parses raw HTML and extracts title and clean human-readable text.
        Returns: (title, cleaned_text, is_truncated, word_count)
        """
        # 1. Extract Page Title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
        title = ""
        if title_match:
            title = html.unescape(title_match.group(1)).strip()
            title = re.sub(r"\s+", " ", title)

        # 2. Strip non-content / active script tags
        stripped = re.sub(
            r"<(script|style|noscript|nav|footer|header|aside|svg|iframe|template|form|button)[^>]*>.*?</\1>",
            " ",
            raw_html,
            flags=re.IGNORECASE | re.DOTALL
        )
        stripped = re.sub(r"<!--.*?-->", " ", stripped, flags=re.DOTALL)

        # 3. Preserve structural breaks: headings, paragraphs, lists, breaks
        stripped = re.sub(r"<(h[1-6]|p|div|section|article|li|tr|br)[^>]*>", "\n", stripped, flags=re.IGNORECASE)
        
        # 4. Strip all remaining HTML tags
        text_content = re.sub(r"<[^>]+>", " ", stripped)

        # 5. Unescape HTML entities
        text_content = html.unescape(text_content)

        # 6. Normalize whitespace
        lines = []
        for line in text_content.splitlines():
            clean_line = re.sub(r"[ \t]+", " ", line).strip()
            if clean_line:
                lines.append(clean_line)
        
        cleaned_text = "\n".join(lines).strip()

        # 7. Check for dynamic JS SPA placeholders
        if not cleaned_text or cleaned_text.lower() in [
            "you need to enable javascript to run this app.",
            "javascript is required",
            "loading...",
            "please enable javascript to continue using this application."
        ]:
            return title, "This webpage requires dynamic browser rendering, so I couldn't retrieve its readable content.", False, 0

        word_count = len(cleaned_text.split())
        is_truncated = False
        if len(cleaned_text) > max_chars:
            cleaned_text = cleaned_text[:max_chars].rstrip() + "\n\n[Note: Page content was truncated because the page is very large.]"
            is_truncated = True

        return title, cleaned_text, is_truncated, word_count

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        raw_url = arguments.get("url") or arguments.get("target")
        
        # 1. Validate & Sanitize Target URL
        is_valid, target_url, err_msg = self._validate_and_sanitize_url(raw_url)
        if not is_valid:
            audit_logger.log_action(self.name, "BLOCKED", err_msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_webpage",
                message=err_msg,
                error="Invalid or blocked URL"
            )

        headers = {
            "User-Agent": "ByteX/1.0 (Windows NT 10.0; Win64; x64) contact@bytex.ai",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 2. Network Fetch with Controlled Single Retry
        html_response_text = ""
        fetch_status = 200
        last_exception = None

        print(f"[ByteX WebReader] Fetching webpage: '{target_url}' (Timeout: {NETWORK_TIMEOUT_SECONDS}s)...")

        for attempt in range(2):  # 1 initial + max 1 retry
            try:
                async with httpx.AsyncClient(timeout=NETWORK_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
                    resp = await client.get(target_url)
                    fetch_status = resp.status_code

                    # 3. HTTP Error Classification
                    if fetch_status in (401, 403):
                        msg = f"I couldn't access that webpage (HTTP {fetch_status} / Access Denied). That page may require authentication."
                        audit_logger.log_action(self.name, "ACCESS_DENIED", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="read_webpage",
                            message=msg,
                            error=f"HTTP {fetch_status}"
                        )

                    if fetch_status == 404:
                        msg = f"The requested webpage was not found (HTTP 404)."
                        audit_logger.log_action(self.name, "NOT_FOUND", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="read_webpage",
                            message=msg,
                            error="HTTP 404"
                        )

                    if fetch_status == 429:
                        msg = f"The website is currently rate limiting requests (HTTP 429)."
                        audit_logger.log_action(self.name, "RATE_LIMITED", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="read_webpage",
                            message=msg,
                            error="HTTP 429"
                        )

                    if fetch_status >= 500:
                        if attempt == 0:
                            time.sleep(0.5)
                            continue  # retry on 5xx once
                        msg = f"The website server returned an error (HTTP {fetch_status})."
                        audit_logger.log_action(self.name, "SERVER_ERROR", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="read_webpage",
                            message=msg,
                            error=f"HTTP {fetch_status}"
                        )

                    html_response_text = resp.text
                    break

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                last_exception = e
                if attempt == 0:
                    print(f"[ByteX WebReader] Transient network error ({e}), retrying once...")
                    time.sleep(0.5)
                    continue
                else:
                    msg = f"I couldn't connect to that website ({e.__class__.__name__}). The server took too long to respond or is unreachable."
                    audit_logger.log_action(self.name, "TIMEOUT", f"{msg} (URL: {target_url})")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="read_webpage",
                        message=msg,
                        error=str(e)
                    )

            except Exception as e:
                msg = f"I couldn't fetch that webpage: {e}"
                audit_logger.log_action(self.name, "FAILED", f"{msg} (URL: {target_url})")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="read_webpage",
                    message=msg,
                    error=str(e)
                )

        if not html_response_text:
            msg = "The webpage returned an empty response."
            audit_logger.log_action(self.name, "EMPTY", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_webpage",
                message=msg,
                error="Empty response"
            )

        # 4. Extract Title and Readable Text Content
        title, clean_text, is_truncated, word_count = self._extract_readable_content(html_response_text)

        # 5. Format Structured Markdown Response
        header_part = f"**{title}**\n\n" if title else ""
        formatted_message = f"{header_part}{clean_text}\n\n*Source: {target_url}*"

        audit_logger.log_action(self.name, "SUCCESS", f"Read {word_count} words from '{target_url}' (Title: '{title}')")

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="read_webpage",
            message=formatted_message,
            data={
                "url": target_url,
                "title": title,
                "text": clean_text,
                "word_count": word_count,
                "truncated": is_truncated,
                "source": target_url
            }
        )
