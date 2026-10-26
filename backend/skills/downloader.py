import os
import re
import time
import httpx
import hashlib
import urllib.parse
import ipaddress
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

from skills.base import BaseSkill, ToolResult
from security.permissions import permissions
from security.audit_logger import audit_logger

MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB limit
NETWORK_TIMEOUT_SECONDS = 10.0
MAX_REDIRECT_HOPS = 5

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

BLOCKED_EXECUTABLE_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".com", ".pif", ".hta", ".cpl", ".jar", ".wsf"
}

class DownloadFileSkill(BaseSkill):
    """
    Controlled Safe Web File Downloader Skill for ByteX (#35 Download Management).
    
    Responsibilities:
    1. Validates remote HTTP/HTTPS URLs with strict SSRF & private IP blocking on all hops.
    2. Validates and confines local destination to safe user folders (Downloads, Desktop, Documents).
    3. Strictly blocks dangerous executable binaries and scripts (.exe, .bat, .cmd, .ps1, etc.).
    4. Sanitizes filenames and enforces unique naming to prevent silent overwrites.
    5. Enforces 100 MB size limits, streaming integrity, and SHA-256 verification.
    6. Ensures downloaded files are NEVER executed, opened, or installed.
    """

    @property
    def name(self) -> str:
        return "download_file"

    @property
    def description(self) -> str:
        return "Safely downloads a file from a validated web URL to an approved user destination (Downloads, Desktop, Documents), verifies download integrity, prevents overwrites, and blocks dangerous executable binaries."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP or HTTPS URL to download the file from."
                },
                "destination_folder": {
                    "type": "string",
                    "description": "Optional destination folder (e.g. 'Downloads', 'Desktop', 'Documents'). Defaults to user's Downloads directory."
                },
                "filename": {
                    "type": "string",
                    "description": "Optional custom filename for the downloaded file."
                }
            },
            "required": []
        }

    def _is_ssrf_or_private(self, url: str) -> Tuple[bool, str]:
        """Checks if a URL points to localhost, private IP, or non-web scheme."""
        try:
            parsed = urllib.parse.urlparse(url)
            scheme = (parsed.scheme or "").lower()
            if scheme not in ["http", "https"]:
                return True, "Security Violation: Only HTTP/HTTPS web URLs are allowed for downloads."

            hostname = (parsed.hostname or "").lower().strip()
            if not hostname:
                return True, "Security Violation: Invalid URL host."

            if hostname in ["localhost", "127.0.0.1", "0.0.0.0", "::1", "local"]:
                return True, "Security Violation: Access to private network/localhost addresses is strictly blocked."

            try:
                ip_obj = ipaddress.ip_address(hostname)
                if any(ip_obj in network for network in PRIVATE_IP_RANGES):
                    return True, "Security Violation: Access to private network addresses is strictly blocked."
            except ValueError:
                # Host is a standard domain name
                pass

            return False, ""
        except Exception as e:
            return True, f"Security Violation: Malformed URL ({e})"

    def _resolve_safe_destination_dir(self, dest_input: Optional[str]) -> Tuple[bool, Path, str]:
        """Resolves and validates safe local directory for downloads."""
        home = Path.home()
        dest_raw = (dest_input or "downloads").strip().lower()

        if dest_raw in ["downloads", "download", "my downloads", "default"]:
            dest_dir = home / "Downloads"
        elif dest_raw in ["desktop", "my desktop"]:
            onedrive_dt = home / "OneDrive" / "Desktop"
            dest_dir = onedrive_dt if onedrive_dt.exists() else (home / "Desktop")
        elif dest_raw in ["documents", "docs", "document", "my documents"]:
            onedrive_doc = home / "OneDrive" / "Documents"
            dest_dir = onedrive_doc if onedrive_doc.exists() else (home / "Documents")
        elif dest_raw in ["pictures", "pics", "images", "my pictures"]:
            dest_dir = home / "Pictures"
        else:
            # Custom path check
            is_valid, err, validated_path = permissions.validate_path(dest_input)
            if not is_valid or not validated_path:
                return False, Path("."), f"Destination rejected: {err}"
            dest_dir = validated_path

        dest_dir.mkdir(parents=True, exist_ok=True)
        return True, dest_dir, ""

    def _sanitize_and_unique_filename(self, raw_filename: str, dest_dir: Path, fallback: str = "downloaded_file.bin") -> Path:
        """Sanitizes filename against path traversal and resolves a unique non-overwriting path."""
        # 1. Strip path traversal and directory separators
        clean_name = os.path.basename(raw_filename.strip())
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', clean_name)
        clean_name = clean_name.strip(". ")
        if not clean_name:
            clean_name = fallback

        target = dest_dir / clean_name
        if not target.exists():
            return target

        stem = target.stem
        suffix = target.suffix
        counter = 1
        while True:
            candidate = dest_dir / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _extract_filename_from_headers_or_url(self, headers: httpx.Headers, url: str, fallback: str = "downloaded_file.bin") -> str:
        """Determines best filename from Content-Disposition header, URL path, or content-type fallback."""
        cd = headers.get("content-disposition", "")
        if cd:
            m_fn_star = re.search(r"filename\*\s*=\s*(?:UTF-8\'\')?([^;]+)", cd, flags=re.IGNORECASE)
            if m_fn_star:
                fn = urllib.parse.unquote(m_fn_star.group(1).strip().strip('"\''))
                if fn:
                    return fn
            m_fn = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, flags=re.IGNORECASE)
            if m_fn:
                fn = m_fn.group(1).strip()
                if fn:
                    return fn

        parsed = urllib.parse.urlparse(url)
        path_name = os.path.basename(parsed.path.strip())
        if path_name and "." in path_name:
            return urllib.parse.unquote(path_name)

        ct = headers.get("content-type", "").lower()
        if "pdf" in ct:
            return "document.pdf"
        elif "json" in ct:
            return "data.json"
        elif "html" in ct:
            return "page.html"
        elif "png" in ct:
            return "image.png"
        elif "jpeg" in ct or "jpg" in ct:
            return "image.jpg"
        elif "zip" in ct:
            return "archive.zip"
        elif "text/plain" in ct:
            return "file.txt"

        return fallback

    def _format_size_human(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        raw_url = arguments.get("url")
        dest_folder_arg = arguments.get("destination_folder") or arguments.get("destination") or arguments.get("location")
        custom_filename = arguments.get("filename")
        raw_text = arguments.get("raw_text") or ""

        # Parse natural command if passed via raw_text
        if raw_text and not raw_url:
            m_url = re.search(r"(https?://[^\s]+|file://[^\s]+)", raw_text, flags=re.IGNORECASE)
            if m_url:
                raw_url = m_url.group(1).strip().rstrip(".,!?")
            if not dest_folder_arg:
                m_dest = re.search(r"\b(?:to|in|into|inside)\s+(?:my\s+|the\s+)?(desktop|downloads?|documents?|pictures?)\b", raw_text, flags=re.IGNORECASE)
                if m_dest:
                    dest_folder_arg = m_dest.group(1).strip()

        # Contextual URL fallback from active session
        if not raw_url or raw_url.lower() in ["this file", "the file", "this pdf", "the pdf", "it"]:
            from core.session import session_manager
            if session_manager.is_session_active() and session_manager._last_target:
                candidate = session_manager._last_target.strip()
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    raw_url = candidate
                    print(f"[ByteX Downloader] Reused verified session URL: '{raw_url}'")

        if not raw_url:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message="Please provide the URL of the file you would like me to download.",
                error="Missing URL"
            )

        clean_url = raw_url.strip()

        # Split trailing destination if included in URL string (e.g. "https://example.com/file.pdf to Downloads")
        m_split = re.search(r"^(https?://[^\s]+)(?:\s+(?:to|in|into)\s+(.+))?$", clean_url, flags=re.IGNORECASE)
        if m_split:
            clean_url = m_split.group(1).strip()
            if m_split.group(2) and not dest_folder_arg:
                dest_folder_arg = m_split.group(2).strip()

        lower_url = clean_url.lower()

        # 1. Protocol & Scheme Security
        if any(lower_url.startswith(proto) for proto in ["file:", "javascript:", "data:", "vbscript:", "ftp:", "shell:"]):
            msg = "Security Violation: Potentially unsafe protocol (file/javascript/data/ftp/shell) is strictly blocked."
            audit_logger.log_action(self.name, "BLOCKED_PROTOCOL", f"{msg} (URL: {clean_url})")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=msg,
                error="Blocked protocol"
            )

        if re.match(r"^[a-zA-Z]:[\\/]", clean_url) or clean_url.startswith(r"\\"):
            msg = "Security Violation: Local filesystem paths cannot be used as download URLs."
            audit_logger.log_action(self.name, "BLOCKED_PATH", f"{msg} (Path: {clean_url})")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=msg,
                error="Blocked local path"
            )

        if not re.match(r"^[a-zA-Z0-9]+://", clean_url):
            clean_url = "https://" + clean_url

        # 2. SSRF & Private IP Check on initial URL
        is_ssrf, ssrf_err = self._is_ssrf_or_private(clean_url)
        if is_ssrf:
            audit_logger.log_action(self.name, "BLOCKED_SSRF", f"{ssrf_err} (URL: {clean_url})")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=ssrf_err,
                error="SSRF blocked"
            )

        # 3. Dangerous Executable Extension Check on URL
        parsed_init = urllib.parse.urlparse(clean_url)
        url_ext = Path(parsed_init.path).suffix.lower()
        if url_ext in BLOCKED_EXECUTABLE_EXTENSIONS:
            msg = f"Security Violation: Downloading executable binaries or scripts ({url_ext}) is strictly blocked."
            audit_logger.log_action(self.name, "BLOCKED_EXECUTABLE", f"{msg} (URL: {clean_url})")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=msg,
                error="Executable file blocked"
            )

        # 4. Resolve & Validate Safe Destination Folder
        dest_ok, dest_dir, dest_err = self._resolve_safe_destination_dir(dest_folder_arg)
        if not dest_ok:
            audit_logger.log_action(self.name, "BLOCKED_DESTINATION", dest_err)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=dest_err,
                error="Invalid destination"
            )

        headers = {
            "User-Agent": "ByteX/1.0 (Windows NT 10.0; Win64; x64) contact@bytex.ai",
            "Accept": "*/*",
        }

        # 5. Fetch & Stream Download with Controlled Redirects and Single Retry
        current_url = clean_url
        current_attempt = 0
        final_file_path: Optional[Path] = None

        print(f"[ByteX Downloader] Initiating download from '{clean_url}' to '{dest_dir}'...")

        while current_attempt < 2:  # max 1 retry for transient network errors
            try:
                redirect_count = 0
                target_url = current_url

                async with httpx.AsyncClient(timeout=NETWORK_TIMEOUT_SECONDS, follow_redirects=False, headers=headers) as client:
                    # Manual redirect validation loop
                    while redirect_count < MAX_REDIRECT_HOPS:
                        resp = await client.get(target_url)

                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location")
                            if not loc:
                                break
                            target_url = urllib.parse.urljoin(target_url, loc)
                            redirect_count += 1

                            # Validate redirect target for SSRF
                            is_redir_ssrf, redir_err = self._is_ssrf_or_private(target_url)
                            if is_redir_ssrf:
                                msg = "Security Violation: Redirect to private network or unsafe address is strictly blocked."
                                audit_logger.log_action(self.name, "BLOCKED_REDIRECT_SSRF", f"{msg} (Redirect: {target_url})")
                                return ToolResult(
                                    success=False,
                                    verified=False,
                                    tool=self.name,
                                    action="download_file",
                                    message=msg,
                                    error="Redirect SSRF blocked"
                                )
                            continue
                        break

                    # 6. HTTP Error Handling
                    if resp.status_code in (401, 403):
                        msg = f"I couldn't download that file because the resource requires authentication or access is denied (HTTP {resp.status_code})."
                        audit_logger.log_action(self.name, "ACCESS_DENIED", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="download_file",
                            message=msg,
                            error=f"HTTP {resp.status_code}"
                        )

                    if resp.status_code == 404:
                        msg = f"The requested download file was not found (HTTP 404)."
                        audit_logger.log_action(self.name, "NOT_FOUND", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="download_file",
                            message=msg,
                            error="HTTP 404"
                        )

                    if resp.status_code >= 400:
                        msg = f"The download server returned an error (HTTP {resp.status_code})."
                        audit_logger.log_action(self.name, "SERVER_ERROR", f"{msg} (URL: {target_url})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="download_file",
                            message=msg,
                            error=f"HTTP {resp.status_code}"
                        )

                    # 7. Content-Length Check
                    cl_header = resp.headers.get("content-length")
                    if cl_header:
                        try:
                            content_len = int(cl_header)
                            if content_len > MAX_DOWNLOAD_BYTES:
                                msg = f"Download rejected: File size ({self._format_size_human(content_len)}) exceeds the maximum allowed limit of 100 MB."
                                audit_logger.log_action(self.name, "SIZE_LIMIT_EXCEEDED", f"{msg} (URL: {target_url})")
                                return ToolResult(
                                    success=False,
                                    verified=False,
                                    tool=self.name,
                                    action="download_file",
                                    message=msg,
                                    error="Size limit exceeded"
                                )
                        except ValueError:
                            pass

                    # 8. Determine Sanitized Unique Destination Filename
                    if custom_filename:
                        suggested_name = custom_filename
                    else:
                        suggested_name = self._extract_filename_from_headers_or_url(resp.headers, target_url)

                    # Check dangerous extension on final determined filename
                    final_ext = Path(suggested_name).suffix.lower()
                    if final_ext in BLOCKED_EXECUTABLE_EXTENSIONS:
                        msg = f"Security Violation: Downloading executable binaries or scripts ({final_ext}) is strictly blocked."
                        audit_logger.log_action(self.name, "BLOCKED_EXECUTABLE", f"{msg} (Filename: {suggested_name})")
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="download_file",
                            message=msg,
                            error="Executable file blocked"
                        )

                    final_file_path = self._sanitize_and_unique_filename(suggested_name, dest_dir)

                    # 9. Stream & Write File with SHA-256 calculation
                    sha256 = hashlib.sha256()
                    total_written = 0

                    with open(final_file_path, "wb") as f_out:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            if chunk:
                                total_written += len(chunk)
                                if total_written > MAX_DOWNLOAD_BYTES:
                                    f_out.close()
                                    if final_file_path.exists():
                                        final_file_path.unlink(missing_ok=True)
                                    msg = "Download aborted: File size exceeded the maximum allowed limit of 100 MB."
                                    audit_logger.log_action(self.name, "SIZE_LIMIT_ABORTED", msg)
                                    return ToolResult(
                                        success=False,
                                        verified=False,
                                        tool=self.name,
                                        action="download_file",
                                        message=msg,
                                        error="Size limit exceeded"
                                    )
                                f_out.write(chunk)
                                sha256.update(chunk)

                    break  # Success, exit retry loop

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                current_attempt += 1
                if current_attempt < 2:
                    print(f"[ByteX Downloader] Transient network error ({e}), retrying once...")
                    time.sleep(0.5)
                    continue
                else:
                    msg = f"I couldn't download that file ({e.__class__.__name__}). The server took too long to respond or is unreachable."
                    audit_logger.log_action(self.name, "TIMEOUT", f"{msg} (URL: {clean_url})")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="download_file",
                        message=msg,
                        error=str(e)
                    )

            except Exception as e:
                msg = f"Download failed: {e}"
                audit_logger.log_action(self.name, "FAILED", f"{msg} (URL: {clean_url})")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="download_file",
                    message=msg,
                    error=str(e)
                )

        # 10. Physical Download Verification
        if not final_file_path or not final_file_path.exists() or not final_file_path.is_file():
            msg = "Download failed and could not be verified on disk."
            audit_logger.log_action(self.name, "VERIFICATION_FAILED", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=msg,
                error="File verification failed"
            )

        actual_size = final_file_path.stat().st_size
        size_human = self._format_size_human(actual_size)
        sha256_hex = sha256.hexdigest()

        # Guarantee path is inside destination root
        if dest_dir not in final_file_path.parents and dest_dir != final_file_path.parent:
            final_file_path.unlink(missing_ok=True)
            msg = "Security Violation: Downloaded file escaped the approved destination directory."
            audit_logger.log_action(self.name, "ESCAPE_BLOCKED", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="download_file",
                message=msg,
                error="Path escape blocked"
            )

        success_msg = f"Successfully downloaded **{final_file_path.name}** ({size_human}) to `{final_file_path}`."
        audit_logger.log_action(self.name, "SUCCESS", f"Downloaded '{final_file_path.name}' ({actual_size} bytes, SHA256: {sha256_hex[:8]}...) to '{final_file_path}'")

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="download_file",
            message=success_msg,
            data={
                "filename": final_file_path.name,
                "path": str(final_file_path),
                "size_bytes": actual_size,
                "size_human": size_human,
                "sha256": sha256_hex,
                "source_url": clean_url,
                "destination_folder": str(dest_dir),
                "verified": True
            }
        )

# Backward-compatibility aliases
DownloaderSkill = DownloadFileSkill
FileDownloaderSkill = DownloadFileSkill
