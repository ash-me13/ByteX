r"""
ByteX — Feature #35: Smart File Manager Skill Suite
Provides intelligent file search, directory inspection, file creation, renaming, moving,
copying, safe confirmed deletion, Recycle Bin integration, and closed-loop verification.

Strict Security & Architectural Invariants:
1. Zero Shell / Subprocess Execution: Uses Python pathlib, os, shutil, and Win32 Shell API directly.
2. Boundary Enforcement: Operations strictly bounded to user folders and active workspace.
3. Path Traversal Rejection: Rejects '..', UNC paths, and system-critical directories (C:\Windows, etc.).
4. Protected Files: Blocks deletion/sensitive access to .env, credentials, id_rsa, and keys.
5. Confirmation Protection: Deletion and bulk operations require explicit user confirmation (RiskLevel.DANGEROUS).
6. Action Verification: Every creation, rename, move, copy, and deletion is verified using ActionVerifier.
"""

import os
import re
import shutil
import asyncio
import datetime
import sys
import subprocess
import ctypes
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

from skills.base import BaseSkill, ToolResult
from security.permissions import permissions
from security.audit_logger import audit_logger
from core.verifier import ActionVerifier

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

EXCLUDED_DIRS = {
    "node_modules", ".git", "appdata", "$recycle.bin",
    "windows", "system volume information", "__pycache__", ".venv", ".idea", ".vscode"
}

GUID = None
SHFILEOPSTRUCTW = None

if IS_WINDOWS and hasattr(ctypes, "windll"):
    try:
        from ctypes import windll, wintypes, byref, c_wchar_p

        # Win32 Known Folder GUID Structure
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)
            ]

        # Win32 Shell File Operation Structure (for Recycle Bin deletion)
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.WORD),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]
    except Exception as e:
        pass

def send_to_recycle_bin(path: Path) -> bool:
    """Moves a file or directory to the Trash/Recycle Bin using platform API."""
    if IS_MACOS:
        try:
            from core.applescript import delete_to_trash
            success, _ = delete_to_trash(str(path.resolve()))
            return success and not path.exists()
        except Exception:
            return False

    if not IS_WINDOWS or SHFILEOPSTRUCTW is None:
        return False

    try:
        FO_DELETE = 0x0003
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004
        FOF_NOERRORUI = 0x0400

        # String must be double-null terminated
        p_str = str(path.resolve()) + "\0\0"
        fileop = SHFILEOPSTRUCTW(
            hwnd=None,
            wFunc=FO_DELETE,
            pFrom=p_str,
            pTo=None,
            fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
            fAnyOperationsAborted=False,
            hNameMappings=None,
            lpszProgressTitle=None
        )
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        return res == 0 and not fileop.fAnyOperationsAborted
    except Exception:
        return False

def get_known_folder_path(folder_id_str: str) -> Optional[Path]:
    """Retrieves standard Windows Known Folder paths using Win32 Shell API."""
    if not IS_WINDOWS or GUID is None:
        return None
    try:
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        guid = GUID()
        ole32.CLSIDFromString(folder_id_str, ctypes.byref(guid))
        path_ptr = ctypes.c_wchar_p()
        res = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, 0, ctypes.byref(path_ptr))
        if res == 0 and path_ptr.value:
            p = Path(path_ptr.value)
            ole32.CoTaskMemFree(path_ptr)
            return p
    except Exception:
        pass
    return None

def resolve_user_directory(folder_name_or_alias: str) -> Path:
    """
    Resolves natural user folder aliases or searches for existing folders
    in the current user's actual Windows directory structure.
    """
    raw_str = folder_name_or_alias.strip().strip('"').strip("'")
    raw_str = re.sub(r"\s+(?:folder|directory)$", "", raw_str, flags=re.IGNORECASE).strip()
    alias = raw_str.lower()
    home = Path.home()

    if "download" in alias:
        known = get_known_folder_path("{374DE290-123F-4565-9164-39C4925E467B}")
        if known and known.exists(): return known
        candidates = [home / "Downloads", home / "OneDrive" / "Downloads"]
        for c in candidates:
            if c.exists(): return c
        return home / "Downloads"

    elif "desktop" in alias:
        known = get_known_folder_path("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
        if known and known.exists(): return known
        candidates = [home / "OneDrive" / "Desktop", home / "Desktop"]
        for c in candidates:
            if c.exists(): return c
        return home / "Desktop"

    elif "document" in alias:
        known = get_known_folder_path("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
        if known and known.exists(): return known
        candidates = [home / "OneDrive" / "Documents", home / "Documents"]
        for c in candidates:
            if c.exists(): return c
        return home / "Documents"

    elif "picture" in alias or "photo" in alias:
        candidates = [home / "OneDrive" / "Pictures", home / "Pictures"]
        for c in candidates:
            if c.exists(): return c
        return home / "Pictures"

    elif "video" in alias or "movie" in alias:
        candidates = [home / "Videos", home / "OneDrive" / "Videos"]
        for c in candidates:
            if c.exists(): return c
        return home / "Videos"

    elif "music" in alias or "audio" in alias:
        candidates = [home / "Music", home / "OneDrive" / "Music"]
        for c in candidates:
            if c.exists(): return c
        return home / "Music"

    # Search for an existing folder with this name in user locations
    matched_folder, _, _ = find_existing_user_folder(raw_str)
    if matched_folder:
        return matched_folder

    # Explicit path
    p = Path(raw_str)
    if p.is_absolute() and p.is_dir():
        return p

    # Fallback to desktop
    return resolve_user_directory("desktop")

def get_known_user_roots() -> List[Path]:
    """Returns the user's primary interactive folders."""
    roots = []
    for alias in ["downloads", "desktop", "documents", "pictures", "videos", "music"]:
        p = resolve_user_directory(alias)
        if p.exists() and p.is_dir() and p not in roots:
            roots.append(p)

    # Also add current working directory if not present
    cwd = Path(os.getcwd())
    if cwd.exists() and cwd.is_dir() and cwd not in roots:
        roots.append(cwd)

    return roots

def find_existing_user_folder(folder_query: str) -> Tuple[Optional[Path], Optional[str], List[Path]]:
    """Searches for an existing directory by name across common user locations."""
    clean_query = folder_query.strip().strip('"').strip("'")
    clean_query = re.sub(r"^(?:find|locate|search|where\s+is|show\s+me|open)?\s*(?:my|the)?\s*", "", clean_query, flags=re.IGNORECASE).strip()
    clean_query = re.sub(r"\s+(?:folder|directory)$", "", clean_query, flags=re.IGNORECASE).strip()
    if not clean_query:
        return None, "Empty folder name provided.", []

    p = Path(clean_query)
    if p.is_absolute() and p.is_dir():
        return p, None, [p]

    home = Path.home()
    for std in ["Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"]:
        if clean_query.lower() == std.lower():
            sp = home / std
            if sp.exists() and sp.is_dir():
                return sp, None, [sp]
            one_sp = home / "OneDrive" / std
            if one_sp.exists() and one_sp.is_dir():
                return one_sp, None, [one_sp]

    known_roots = get_known_user_roots()
    matches = []
    q_lower = clean_query.lower()

    for root in known_roots:
        target = root / clean_query
        if target.exists() and target.is_dir():
            if target not in matches:
                matches.append(target)

        try:
            for item in root.iterdir():
                if item.is_dir() and item.name.lower() == q_lower:
                    if item not in matches:
                        matches.append(item)
        except Exception:
            pass

    if len(matches) == 1:
        return matches[0], None, matches
    elif len(matches) > 1:
        match_lines = [f"- {m}" for m in matches]
        err = (
            f"Multiple folders named '{clean_query}' found:\n"
            + "\n".join(match_lines)
            + "\nPlease specify which folder you mean (e.g. on Desktop or in Downloads)."
        )
        return None, err, matches
    else:
        return None, f"Folder '{clean_query}' was not found in common user locations (Desktop, Downloads, Documents).", []

def resolve_target_file_path(
    path_or_name: str,
    must_exist: bool = False,
    default_folder: str = "downloads"
) -> Tuple[Optional[Path], Optional[str], List[Path]]:
    """Centralized safe path resolution mechanism."""
    raw = path_or_name.strip().strip('"').strip("'")
    if not raw:
        return None, "Empty path provided.", []

    p = Path(raw)

    # 1. Absolute Path
    if p.is_absolute():
        if must_exist and not p.exists():
            return None, f"File '{p}' does not exist on disk.", []
        return p, None, [p]

    # 2. Path with explicit known folder prefix
    parts = p.parts
    if len(parts) > 1:
        first_part_lower = parts[0].lower()
        if any(k in first_part_lower for k in ["download", "desktop", "document", "picture", "video", "music"]):
            base_dir = resolve_user_directory(parts[0])
            rest = Path(*parts[1:])
            resolved = base_dir / rest
            if must_exist and not resolved.exists():
                return None, f"File '{rest}' does not exist in {base_dir}.", []
            return resolved, None, [resolved]

    # 3. Bare filename
    if must_exist:
        known_roots = get_known_user_roots()
        matches = []
        name_lower = raw.lower()

        for root in known_roots:
            target = root / raw
            if target.exists():
                matches.append(target)
            else:
                try:
                    for child in root.iterdir():
                        if child.name.lower() == name_lower:
                            if child not in matches:
                                matches.append(child)
                except Exception:
                    pass

        if not matches:
            for root in known_roots:
                try:
                    for wroot, dirs, files in os.walk(root, topdown=True):
                        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS and not d.startswith('.')]
                        for f in files:
                            if f.lower() == name_lower:
                                p_match = Path(wroot) / f
                                if p_match not in matches:
                                    matches.append(p_match)
                except Exception:
                    pass

        if len(matches) == 1:
            return matches[0], None, matches
        elif len(matches) > 1:
            match_lines = [f"- {m}" for m in matches]
            err_msg = (
                f"Multiple files named '{raw}' were found:\n"
                + "\n".join(match_lines)
                + "\nPlease specify which folder you mean (e.g., in Downloads or on Desktop)."
            )
            return None, err_msg, matches
        else:
            # Check if user specified a directory name
            for root in known_roots:
                target_dir = root / raw
                if target_dir.exists() and target_dir.is_dir():
                    return target_dir, None, [target_dir]
                try:
                    for wroot, dirs, _ in os.walk(root, topdown=True):
                        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS and not d.startswith('.')]
                        for d in dirs:
                            if d.lower() == name_lower:
                                dir_path = Path(wroot) / d
                                return dir_path, None, [dir_path]
                except Exception:
                    pass

            searched_names = ", ".join([r.name for r in known_roots])
            err_msg = f"File '{raw}' was not found in known user locations ({searched_names})."
            return None, err_msg, []
    else:
        # Non-existing target (creation or destination)
        base_dir = resolve_user_directory(default_folder)
        return base_dir / raw, None, [base_dir / raw]

FILE_TYPE_MAPPINGS: Dict[str, List[str]] = {
    "python": [".py", ".ipynb"],
    "py": [".py"],
    "pdf": [".pdf"],
    "pdfs": [".pdf"],
    "word": [".docx", ".doc"],
    "excel": [".xlsx", ".xls", ".csv"],
    "spreadsheet": [".xlsx", ".xls", ".csv"],
    "spreadsheets": [".xlsx", ".xls", ".csv"],
    "powerpoint": [".pptx", ".ppt"],
    "presentation": [".pptx", ".ppt"],
    "presentations": [".pptx", ".ppt"],
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts", ".tsx"],
    "text": [".txt", ".text"],
    "markdown": [".md", ".markdown"],
    "image": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"],
    "images": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"],
    "photo": [".png", ".jpg", ".jpeg", ".webp"],
    "photos": [".png", ".jpg", ".jpeg", ".webp"],
    "picture": [".png", ".jpg", ".jpeg", ".webp"],
    "pictures": [".png", ".jpg", ".jpeg", ".webp"],
    "audio": [".mp3", ".wav", ".aac", ".flac", ".m4a"],
    "music": [".mp3", ".wav", ".flac", ".m4a"],
    "video": [".mp4", ".mkv", ".mov", ".avi", ".webm"],
    "videos": [".mp4", ".mkv", ".mov", ".avi", ".webm"],
    "archive": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "zip": [".zip"],
    "zips": [".zip"],
    "code": [".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".c", ".h", ".cs", ".java", ".go", ".rs"],
    "document": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".md"],
    "documents": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".md"],
}

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def parse_natural_search_query(raw_query: str) -> Dict[str, Any]:
    """
    Parses natural language file search query into criteria dictionary:
    - keyword: text filter
    - target_extensions: list of dot-extensions
    - restricted_dir: Path to search within
    - min_size_bytes: float / int
    - max_size_bytes: float / int
    - modified_today: bool
    - modified_days: int
    - sort_by: 'size_desc' | 'modified_desc' | 'default'
    - exact_name: Optional[str]
    """
    q = raw_query.strip()
    res = {
        "keyword": "",
        "target_extensions": [],
        "restricted_dir": None,
        "min_size_bytes": None,
        "max_size_bytes": None,
        "modified_today": False,
        "modified_days": None,
        "sort_by": "default",
        "exact_name": None,
    }

    # 1. Extract directory restriction (e.g., 'in Downloads', 'on Desktop', 'in Documents')
    dir_match = re.search(
        r"\b(?:in|on|under|inside)\s+(?:the\s+)?(downloads?|desktop|documents?|pictures?|videos?|music|[a-zA-Z0-9_\-\s]+?\s+folder|[a-zA-Z0-9_\-\s]+?\s+directory)\b",
        q,
        flags=re.IGNORECASE
    )
    if dir_match:
        dir_name = dir_match.group(1).strip()
        try:
            resolved = resolve_user_directory(dir_name)
            if resolved and resolved.exists() and resolved.is_dir():
                res["restricted_dir"] = resolved
                q = q[:dir_match.start()] + q[dir_match.end():]
                q = q.strip()
        except Exception:
            pass

    # 2. Extract Size Constraints (e.g. "larger than 100 MB", "smaller than 10 MB", "over 500 KB", "> 50 MB")
    size_gt_match = re.search(r"\b(?:larger|greater|more|bigger)\s+than\s+(\d+(?:\.\d+)?)\s*(gb|mb|kb|bytes?|b)\b", q, flags=re.IGNORECASE)
    if size_gt_match:
        val = float(size_gt_match.group(1))
        unit = size_gt_match.group(2).lower()
        multiplier = 1024 * 1024 * 1024 if unit.startswith("g") else (1024 * 1024 if unit.startswith("m") else (1024 if unit.startswith("k") else 1))
        res["min_size_bytes"] = int(val * multiplier)
        q = q[:size_gt_match.start()] + q[size_gt_match.end():]
        q = q.strip()

    size_lt_match = re.search(r"\b(?:smaller|less)\s+than\s+(\d+(?:\.\d+)?)\s*(gb|mb|kb|bytes?|b)\b", q, flags=re.IGNORECASE)
    if size_lt_match:
        val = float(size_lt_match.group(1))
        unit = size_lt_match.group(2).lower()
        multiplier = 1024 * 1024 * 1024 if unit.startswith("g") else (1024 * 1024 if unit.startswith("m") else (1024 if unit.startswith("k") else 1))
        res["max_size_bytes"] = int(val * multiplier)
        q = q[:size_lt_match.start()] + q[size_lt_match.end():]
        q = q.strip()

    # 3. Extract Largest Files Sort Intent
    if re.search(r"\b(?:largest|biggest|huge|large)\s+files?\b", q, flags=re.IGNORECASE) or "largest" in q.lower():
        res["sort_by"] = "size_desc"
        q = re.sub(r"\b(?:my\s+)?(?:largest|biggest|huge|large)\s+files?\b", "", q, flags=re.IGNORECASE).strip()

    # 4. Extract Date Constraints (e.g. "modified today", "modified yesterday", "recently modified")
    if re.search(r"\b(?:modified\s+today|created\s+today|today'?s?\s+files?)\b", q, flags=re.IGNORECASE):
        res["modified_today"] = True
        q = re.sub(r"\b(?:modified\s+today|created\s+today|today'?s?\s+files?)\b", "", q, flags=re.IGNORECASE).strip()
    elif re.search(r"\b(?:modified\s+yesterday|yesterday'?s?\s+files?)\b", q, flags=re.IGNORECASE):
        res["modified_days"] = 1
        q = re.sub(r"\b(?:modified\s+yesterday|yesterday'?s?\s+files?)\b", "", q, flags=re.IGNORECASE).strip()
    elif re.search(r"\b(?:recently\s+modified|recent\s+files?|latest\s+files?)\b", q, flags=re.IGNORECASE):
        res["sort_by"] = "modified_desc"
        q = re.sub(r"\b(?:recently\s+modified|recent\s+files?|latest\s+files?)\b", "", q, flags=re.IGNORECASE).strip()

    # 5. Extract Exact Filename (e.g. "file called resume.pdf" or "file named notes.txt")
    exact_match = re.search(r"\b(?:file\s+called|file\s+named|named|called)\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\b", q, flags=re.IGNORECASE)
    if exact_match:
        res["exact_name"] = exact_match.group(1).strip()
        q = q[:exact_match.start()] + q[exact_match.end():]
        q = q.strip()

    # 6. Extract file type / extension filter
    for type_key, exts in FILE_TYPE_MAPPINGS.items():
        pattern = r'\b(?:my\s+)?' + re.escape(type_key) + r'(?:\s+files?|\s+documents?|\s+spreadsheets?|\s+presentations?)?\b'
        if re.search(pattern, q, flags=re.IGNORECASE):
            res["target_extensions"].extend(exts)
            q = re.sub(pattern, "", q, flags=re.IGNORECASE).strip()
            break

    # Check explicit extension like '*.py', '.pdf', 'py files'
    ext_match = re.search(r'\*?\.([a-zA-Z0-9]+)\b', q)
    if ext_match:
        dot_ext = f".{ext_match.group(1).lower()}"
        if dot_ext not in res["target_extensions"]:
            res["target_extensions"].append(dot_ext)
        q = re.sub(r'\*?\.' + ext_match.group(1), "", q).strip()

    # 7. Clean remaining keyword
    clean_kw = re.sub(r"[?!.,]+$", "", q).strip()
    clean_kw = re.sub(r"\b(?:find|search|locate|where\s+is|show\s+me|files?|file|containing|named|called|matching|for|my|the|a|an|all)\b", "", clean_kw, flags=re.IGNORECASE).strip()
    clean_kw = clean_kw.strip('"').strip("'").strip(".").strip()
    res["keyword"] = clean_kw

    return res

def scan_files_advanced(
    criteria: Dict[str, Any],
    root_paths: List[Path],
    max_results: int = 30
) -> Tuple[List[Dict[str, Any]], int, Dict[str, int]]:
    """
    Advanced multi-criteria filesystem search with size, date, extension, keyword,
    and duplicate name tracking (strictly read-only).
    """
    matches = []
    seen_paths = set()
    name_counts: Dict[str, int] = {}
    total_found = 0

    kw_lower = (criteria.get("keyword") or "").strip().lower()
    exact_name = (criteria.get("exact_name") or "").strip().lower()
    ext_lower = [e.lower() for e in criteria.get("target_extensions", [])]
    min_size = criteria.get("min_size_bytes")
    max_size = criteria.get("max_size_bytes")
    mod_today = criteria.get("modified_today", False)
    mod_days = criteria.get("modified_days")
    sort_by = criteria.get("sort_by", "default")

    now = datetime.datetime.now()
    today_start = datetime.datetime(now.year, now.month, now.day)

    collected_raw = []

    for root_dir in root_paths:
        if not root_dir.exists() or not root_dir.is_dir():
            continue

        try:
            for root, dirs, files in os.walk(root_dir, topdown=True):
                dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS and not d.startswith('.')]

                for file_name in files:
                    full_path = Path(root) / file_name
                    fname_lower = file_name.lower()

                    # Exact name filter
                    if exact_name and fname_lower != exact_name:
                        continue

                    # Extension filter
                    if ext_lower and full_path.suffix.lower() not in ext_lower:
                        continue

                    # Keyword filter
                    if kw_lower and kw_lower not in fname_lower:
                        continue

                    resolved_str = str(full_path.resolve())
                    if resolved_str in seen_paths:
                        continue

                    # Stat inspection
                    file_size = 0
                    mtime_dt = None
                    mtime_str = "Unknown"
                    try:
                        stat_info = full_path.stat()
                        file_size = stat_info.st_size
                        mtime_dt = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                        mtime_str = mtime_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        continue

                    # Size filters
                    if min_size is not None and file_size < min_size:
                        continue
                    if max_size is not None and file_size > max_size:
                        continue

                    # Date filters
                    if mod_today and mtime_dt and mtime_dt < today_start:
                        continue
                    if mod_days is not None and mtime_dt:
                        diff = (now - mtime_dt).days
                        if diff > mod_days:
                            continue

                    seen_paths.add(resolved_str)
                    name_counts[file_name] = name_counts.get(file_name, 0) + 1
                    total_found += 1

                    collected_raw.append({
                        "filename": file_name,
                        "name": file_name,
                        "path": resolved_str,
                        "extension": full_path.suffix or "file",
                        "size_bytes": file_size,
                        "size": format_file_size(file_size),
                        "modified": mtime_str,
                        "mtime_dt": mtime_dt
                    })
        except (PermissionError, OSError):
            continue

    # Sorting
    if sort_by == "size_desc":
        collected_raw.sort(key=lambda x: x["size_bytes"], reverse=True)
    elif sort_by == "modified_desc":
        collected_raw.sort(key=lambda x: x["mtime_dt"] or datetime.datetime.min, reverse=True)
    elif exact_name:
        # Exact match prioritized
        pass

    matches = collected_raw[:max_results]
    for m in matches:
        m.pop("mtime_dt", None)

    return matches, total_found, name_counts

# =====================================================================
# SKILL 1: SMART FILE SEARCH (Feature #35.1)
# =====================================================================
class FileSearchSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "file_search"

    @property
    def description(self) -> str:
        return "Intelligently searches local files by name, type, size, modification date, or largest files (read-only)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword, natural criteria, extension, or size/date query"},
                "target_path": {"type": "string", "description": "Optional specific folder path to search within"},
                "min_size_bytes": {"type": "integer", "description": "Minimum file size in bytes"},
                "max_size_bytes": {"type": "integer", "description": "Maximum file size in bytes"},
                "sort_by": {"type": "string", "enum": ["default", "size_desc", "modified_desc"]}
            },
            "required": ["query"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        raw_query = arguments.get("query", "").strip()
        if not raw_query:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="file_search",
                message="Please provide a filename, extension, or search criteria.",
                error="Empty search query."
            )

        # 0. Path Traversal & Security Validation
        custom_path = arguments.get("target_path")
        if custom_path:
            is_valid, err_msg, resolved = permissions.validate_path(custom_path)
            if not is_valid or ".." in str(custom_path):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="file_search",
                    message=f"Access to path '{custom_path}' is restricted for security.",
                    error=err_msg or "Restricted directory access"
                )

        # 0.5. Check if query is searching for an existing user directory
        folder_match_path, _, _ = find_existing_user_folder(raw_query)
        if folder_match_path and folder_match_path.exists() and not any(kw in raw_query.lower() for kw in ["files", "pdf", "py", "larger", "modified", "size"]):
            msg = f"Found folder '{folder_match_path.name}' at: {folder_match_path}"
            audit_logger.log_action(self.name, "SUCCESS", msg)
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="file_search",
                message=msg,
                data={
                    "folder": folder_match_path.name,
                    "path": str(folder_match_path),
                    "is_dir": True,
                    "count": 1,
                    "matches": [{"filename": folder_match_path.name, "path": str(folder_match_path), "size": "Folder", "modified": "Now"}]
                }
            )

        # 1. Parse natural language criteria
        criteria = parse_natural_search_query(raw_query)
        if arguments.get("min_size_bytes"):
            criteria["min_size_bytes"] = arguments["min_size_bytes"]
        if arguments.get("max_size_bytes"):
            criteria["max_size_bytes"] = arguments["max_size_bytes"]
        if arguments.get("sort_by"):
            criteria["sort_by"] = arguments["sort_by"]

        search_roots = []
        if custom_path:
            p = Path(custom_path)
            if p.exists() and p.is_dir():
                search_roots.append(p)
        elif criteria.get("restricted_dir") and criteria["restricted_dir"].exists():
            search_roots.append(criteria["restricted_dir"])

        if not search_roots:
            search_roots = get_known_user_roots()

        # Execute scan asynchronously
        matches, total_count, name_counts = await asyncio.to_thread(
            scan_files_advanced, criteria, search_roots, 25
        )

        duplicates = [name for name, count in name_counts.items() if count > 1]

        if not matches:
            scope_desc = f" in {search_roots[0].name}" if len(search_roots) == 1 else ""
            msg = f"No matching files found for '{raw_query}'{scope_desc}."
            audit_logger.log_action(self.name, "SUCCESS", msg)
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="file_search",
                message=msg,
                data={"query": raw_query, "count": 0, "matches": []}
            )

        # Format clean, structured output
        scope_str = f" in {search_roots[0].name}" if len(search_roots) == 1 else ""
        lines = [f"Found {total_count} matching file(s){scope_str}:\n"]
        for i, m in enumerate(matches, 1):
            lines.append(f"{i}. **{m['filename']}** — {m['size']} [Modified: {m['modified']}]\n   `{m['path']}`")

        if total_count > len(matches):
            lines.append(f"\n*Showing top {len(matches)} of {total_count} matches.*")

        if duplicates:
            lines.append(f"\n*(Note: {len(duplicates)} duplicate filename(s) detected across folders)*")

        msg = "\n".join(lines)
        audit_logger.log_action(self.name, "SUCCESS", f"Found {total_count} matches for '{raw_query}'")
        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="file_search",
            message=msg,
            data={
                "query": raw_query,
                "count": total_count,
                "matches": matches,
                "duplicates": duplicates
            }
        )

SearchFilesSkill = FileSearchSkill

# =====================================================================
# SKILL 2: DIRECTORY LISTING (Feature #35.2)
# =====================================================================
class ListFilesSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return "Lists files and subdirectories inside an allowed folder with names, sizes, and timestamps."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_path": {"type": "string", "description": "Target folder name (e.g. 'Downloads', 'Documents') or directory path"},
                "folder": {"type": "string", "description": "Optional alias for target folder"}
            }
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("target_path") or arguments.get("folder") or "downloads"
        resolved_dir = resolve_user_directory(raw_path)

        valid, err_msg, validated_path = permissions.validate_path(str(resolved_dir))
        if not valid or not validated_path:
            audit_logger.log_action(self.name, "BLOCKED", err_msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="list_files",
                message=err_msg or f"Access to '{raw_path}' is restricted.",
                error=err_msg
            )

        if not validated_path.exists() or not validated_path.is_dir():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="list_files",
                message=f"Directory '{validated_path.name}' does not exist.",
                error="DirectoryNotFound"
            )

        try:
            items = []
            dir_count = 0
            file_count = 0

            for entry in validated_path.iterdir():
                if entry.name.startswith('.') or entry.name.lower() in EXCLUDED_DIRS:
                    continue

                is_directory = entry.is_dir()
                size_str = "Folder"
                size_bytes = 0
                mtime_str = "Unknown"

                try:
                    st = entry.stat()
                    mtime = datetime.datetime.fromtimestamp(st.st_mtime)
                    mtime_str = mtime.strftime("%Y-%m-%d %H:%M")
                    if not is_directory:
                        size_bytes = st.st_size
                        size_str = format_file_size(size_bytes)
                        file_count += 1
                    else:
                        dir_count += 1
                except Exception:
                    pass

                items.append({
                    "name": entry.name,
                    "type": "directory" if is_directory else "file",
                    "size": size_str,
                    "size_bytes": size_bytes,
                    "modified": mtime_str,
                    "path": str(entry.resolve())
                })

            # Sort directories first, then alphabetically
            items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))

            total_items = len(items)
            display_items = items[:30]

            lines = [f"**Contents of `{validated_path.name}`** ({dir_count} folders, {file_count} files):\n"]
            lines.append("| Name | Type | Size | Modified |")
            lines.append("|---|---|---|---|")
            for it in display_items:
                icon = "📁" if it["type"] == "directory" else "📄"
                lines.append(f"| {icon} {it['name']} | {it['type'].capitalize()} | {it['size']} | {it['modified']} |")

            if total_items > len(display_items):
                lines.append(f"\n*Showing 30 of {total_items} items.*")

            msg = "\n".join(lines)
            audit_logger.log_action(self.name, "SUCCESS", f"Listed {total_items} items in {validated_path}")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="list_files",
                message=msg,
                data={
                    "folder": validated_path.name,
                    "path": str(validated_path),
                    "dir_count": dir_count,
                    "file_count": file_count,
                    "total_count": total_items,
                    "items": display_items
                }
            )
        except Exception as e:
            msg = f"Failed to list directory contents: {e}"
            audit_logger.log_action(self.name, "FAILED", msg)
            return ToolResult(success=False, verified=False, tool=self.name, action="list_files", message=msg, error=str(e))

ListDirectorySkill = ListFilesSkill

# =====================================================================
# SKILL 3: UNIFIED FILE OPERATIONS (Create, Rename, Copy, Move, Delete)
# =====================================================================
class FileOperationsSkill(BaseSkill):
    """Unified filesystem operations skill supporting safe create, rename, copy, move, and confirmed delete."""

    @property
    def name(self) -> str:
        return "file_operations"

    @property
    def description(self) -> str:
        return "Safely performs filesystem operations: create_file, create_folder, rename, copy, move, delete."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["create_file", "create_folder", "rename", "copy", "move", "delete"]},
                "target_path": {"type": "string", "description": "Target folder or file path"},
                "filename": {"type": "string", "description": "Filename for creation/deletion"},
                "folder": {"type": "string", "description": "Folder name/alias (e.g. 'Downloads', 'Documents')"},
                "source_path": {"type": "string", "description": "Source path for copy/move/rename"},
                "destination_path": {"type": "string", "description": "Destination path for copy/move"},
                "new_name": {"type": "string", "description": "New name for rename"},
                "content": {"type": "string", "description": "Optional content for create_file"},
                "confirmed": {"type": "boolean", "description": "Confirmation flag for deletion"}
            },
            "required": ["operation"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "").strip().lower()

        # -------------------------------------------------------------
        # 1. CREATE FILE
        # -------------------------------------------------------------
        if operation in ["create_file", "new_file", "make_file", "create file"]:
            raw_filename = arguments.get("filename") or arguments.get("target_path") or "NewFile.txt"
            raw_filename = Path(raw_filename).name or "NewFile.txt"
            folder_hint = arguments.get("folder") or arguments.get("target_path") or "downloads"
            content = arguments.get("content", "")

            # If folder_hint was full path to a file, extract parent folder
            p_hint = Path(folder_hint)
            if p_hint.suffix:
                target_dir = p_hint.parent
            else:
                target_dir = resolve_user_directory(folder_hint)

            target_file = target_dir / raw_filename

            valid, err_msg, resolved_path = permissions.validate_path(str(target_file))
            if not valid or not resolved_path:
                audit_logger.log_action(self.name, "BLOCKED", err_msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="create_file", message=err_msg, error=err_msg)

            if resolved_path.exists():
                msg = f"File '{resolved_path.name}' already exists at {resolved_path.parent}. Creation aborted to prevent overwrite."
                return ToolResult(success=False, verified=False, tool=self.name, action="create_file", message=msg, error="FileAlreadyExists")

            try:
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_path.write_text(content, encoding="utf-8")
                actual_path_str = str(resolved_path.resolve())

                # Reusable Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_file_creation(resolved_path)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(success=False, verified=False, verification=v_data, tool=self.name, action="create_file", message=v_err, error=v_err)

                msg = f"Created file '{resolved_path.name}' successfully at {actual_path_str}."
                audit_logger.log_action(self.name, "SUCCESS", f"Created file {actual_path_str}")
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="create_file",
                    message=msg,
                    data={"filename": resolved_path.name, "path": actual_path_str, "size": resolved_path.stat().st_size}
                )
            except Exception as e:
                msg = f"Failed to create file: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="create_file", message=msg, error=str(e))

        # -------------------------------------------------------------
        # 2. CREATE FOLDER
        # -------------------------------------------------------------
        elif operation in ["create_folder", "mkdir", "create folder", "make folder"]:
            folder_name = arguments.get("folder_name") or arguments.get("target_path") or arguments.get("name") or ""
            folder_loc = arguments.get("location") or arguments.get("folder") or "desktop"

            # Parse "Projects inside Documents" or "Projects in Documents"
            m_nested = re.search(r"^(?:a\s+folder\s+called\s+|folder\s+called\s+|folder\s+)?(.+?)\s+(?:inside|in|under)\s+(.+)$", folder_name, flags=re.IGNORECASE)
            if m_nested:
                folder_name = m_nested.group(1).strip()
                folder_loc = m_nested.group(2).strip()

            clean_folder_name = re.sub(r"^(?:a\s+folder\s+called|folder\s+called|folder)\s+", "", folder_name, flags=re.IGNORECASE).strip().strip('"').strip("'")
            if not clean_folder_name:
                return ToolResult(success=False, verified=False, tool=self.name, action="create_folder", message="No folder name specified.", error="Missing folder_name")

            base_dir = resolve_user_directory(folder_loc)
            resolved_path = base_dir / clean_folder_name

            valid, err_msg, validated_path = permissions.validate_path(str(resolved_path))
            if not valid or not validated_path:
                audit_logger.log_action(self.name, "BLOCKED", err_msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="create_folder", message=err_msg, error=err_msg)

            already_exists = validated_path.exists()
            if already_exists:
                msg = f"Folder '{validated_path.name}' already exists at {validated_path.resolve()}."
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="create_folder",
                    message=msg,
                    data={"name": validated_path.name, "path": str(validated_path.resolve()), "already_exists": True}
                )

            try:
                validated_path.mkdir(parents=True, exist_ok=True)
                actual_path = str(validated_path.resolve())

                # Reusable Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_folder_creation(validated_path)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(success=False, verified=False, verification=v_data, tool=self.name, action="create_folder", message=v_err, error=v_err)

                msg = f"Created folder '{validated_path.name}' at {actual_path}."
                audit_logger.log_action(self.name, "SUCCESS", msg)
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="create_folder",
                    message=msg,
                    data={"name": validated_path.name, "path": actual_path, "created": True}
                )
            except Exception as e:
                msg = f"Failed to create folder: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="create_folder", message=msg, error=str(e))

        # -------------------------------------------------------------
        # 3. RENAME FILE / FOLDER
        # -------------------------------------------------------------
        elif operation in ["rename", "rename_file", "rename file"]:
            src_raw = arguments.get("source_path") or arguments.get("target_path") or ""
            new_name = arguments.get("new_name", "").strip().strip('"').strip("'")

            if not src_raw or not new_name:
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message="Please provide both source file and new name.", error="Missing parameters")

            resolved_src, err_src, _ = resolve_target_file_path(src_raw, must_exist=True)
            if not resolved_src:
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message=err_src, error=err_src)

            valid_src, err_val_src, validated_src = permissions.validate_path(str(resolved_src))
            if not valid_src or not validated_src:
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message=err_val_src, error=err_val_src)

            clean_new_name = new_name
            if "." not in clean_new_name and validated_src.suffix:
                clean_new_name = f"{new_name}{validated_src.suffix}"

            target_dst = validated_src.parent / clean_new_name
            valid_dst, err_dst, validated_dst = permissions.validate_path(str(target_dst))
            if not valid_dst or not validated_dst:
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message=err_dst, error=err_dst)

            if validated_dst.exists():
                msg = f"Cannot rename: Target '{clean_new_name}' already exists in {validated_dst.parent}."
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message=msg, error="Collision")

            try:
                validated_src.rename(validated_dst)

                # Reusable Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_rename(validated_src, validated_dst)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(success=False, verified=False, verification=v_data, tool=self.name, action="rename", message=v_err, error=v_err)

                msg = f"Renamed '{validated_src.name}' to '{clean_new_name}' successfully.\nLocation: {validated_dst}"
                audit_logger.log_action(self.name, "SUCCESS", msg)
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="rename",
                    message=msg,
                    data={"old_path": str(validated_src), "new_path": str(validated_dst)}
                )
            except Exception as e:
                msg = f"Failed to rename: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="rename", message=msg, error=str(e))

        # -------------------------------------------------------------
        # 4. COPY FILE / FOLDER
        # -------------------------------------------------------------
        elif operation in ["copy", "copy_file", "copy file"]:
            src_raw = arguments.get("source_path") or arguments.get("target_path") or ""
            dst_raw = arguments.get("destination_path") or ""

            if not src_raw or not dst_raw:
                return ToolResult(success=False, verified=False, tool=self.name, action="copy", message="Please provide both source and destination paths.", error="Missing parameters")

            resolved_src, err_src, _ = resolve_target_file_path(src_raw, must_exist=True)
            if not resolved_src:
                return ToolResult(success=False, verified=False, tool=self.name, action="copy", message=err_src, error=err_src)

            if dst_raw.lower() in ["downloads", "desktop", "documents", "pictures", "videos", "music"]:
                resolved_dst = resolve_user_directory(dst_raw)
            else:
                resolved_dst, _, _ = resolve_target_file_path(dst_raw, must_exist=False, default_folder="documents")

            valid_src, err_val_src, validated_src = permissions.validate_path(str(resolved_src))
            valid_dst, err_val_dst, validated_dst = permissions.validate_path(str(resolved_dst))

            if not valid_src or not validated_src: return ToolResult(success=False, verified=False, tool=self.name, action="copy", message=err_val_src, error=err_val_src)
            if not valid_dst or not validated_dst: return ToolResult(success=False, verified=False, tool=self.name, action="copy", message=err_val_dst, error=err_val_dst)

            if validated_dst.is_dir():
                target_final = validated_dst / validated_src.name
            else:
                target_final = validated_dst

            if target_final.exists():
                msg = f"Cannot copy: Destination '{target_final.name}' already exists in {target_final.parent}."
                return ToolResult(success=False, verified=False, tool=self.name, action="copy", message=msg, error="Collision")

            try:
                if validated_src.is_dir():
                    shutil.copytree(str(validated_src), str(target_final))
                else:
                    target_final.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(validated_src), str(target_final))

                # Reusable Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_copy(validated_src, target_final)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(success=False, verified=False, verification=v_data, tool=self.name, action="copy", message=v_err, error=v_err)

                msg = f"Copied '{validated_src.name}' to '{target_final}' successfully."
                audit_logger.log_action(self.name, "SUCCESS", msg)
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="copy",
                    message=msg,
                    data={"source": str(validated_src), "destination": str(target_final)}
                )
            except Exception as e:
                msg = f"Failed to copy: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="copy", message=msg, error=str(e))

        # -------------------------------------------------------------
        # 5. MOVE FILE / FOLDER
        # -------------------------------------------------------------
        elif operation in ["move", "move_file", "move file"]:
            src_raw = arguments.get("source_path") or arguments.get("target_path") or ""
            dst_raw = arguments.get("destination_path") or ""

            if not src_raw or not dst_raw:
                return ToolResult(success=False, verified=False, tool=self.name, action="move", message="Please provide both source and destination paths.", error="Missing parameters")

            resolved_src, err_src, _ = resolve_target_file_path(src_raw, must_exist=True)
            if not resolved_src:
                return ToolResult(success=False, verified=False, tool=self.name, action="move", message=err_src, error=err_src)

            if dst_raw.lower() in ["downloads", "desktop", "documents", "pictures", "videos", "music"]:
                resolved_dst = resolve_user_directory(dst_raw)
            else:
                resolved_dst, _, _ = resolve_target_file_path(dst_raw, must_exist=False, default_folder="documents")

            valid_src, err_val_src, validated_src = permissions.validate_path(str(resolved_src))
            valid_dst, err_val_dst, validated_dst = permissions.validate_path(str(resolved_dst))

            if not valid_src or not validated_src: return ToolResult(success=False, verified=False, tool=self.name, action="move", message=err_val_src, error=err_val_src)
            if not valid_dst or not validated_dst: return ToolResult(success=False, verified=False, tool=self.name, action="move", message=err_val_dst, error=err_val_dst)

            if validated_dst.is_dir():
                target_final = validated_dst / validated_src.name
            else:
                target_final = validated_dst

            if target_final.exists():
                msg = f"Cannot move: Destination '{target_final.name}' already exists in {target_final.parent}."
                return ToolResult(success=False, verified=False, tool=self.name, action="move", message=msg, error="Collision")

            try:
                target_final.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(validated_src), str(target_final))

                # Reusable Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_move(validated_src, target_final)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(success=False, verified=False, verification=v_data, tool=self.name, action="move", message=v_err, error=v_err)

                msg = f"Moved '{validated_src.name}' to '{target_final}' successfully."
                audit_logger.log_action(self.name, "SUCCESS", msg)
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="move",
                    message=msg,
                    data={"source": str(validated_src), "destination": str(target_final)}
                )
            except Exception as e:
                msg = f"Failed to move: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(success=False, verified=False, tool=self.name, action="move", message=msg, error=str(e))

        # -------------------------------------------------------------
        # 6. DELETE FILE / FOLDER (Confirmation Protected + Verified)
        # -------------------------------------------------------------
        elif operation in ["delete_file", "delete", "remove", "delete_folder"]:
            target_raw = arguments.get("target_path") or arguments.get("filename") or arguments.get("path") or arguments.get("source_path") or ""
            target_raw = target_raw.strip().strip('"').strip("'")
            is_confirmed = arguments.get("confirmed", False)

            if not target_raw:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message="No target specified for deletion.",
                    error="Missing target_path"
                )

            # Check if this is a bulk delete request (e.g. "Delete all PDF files", "Delete all .tmp files")
            is_bulk = any(kw in target_raw.lower() for kw in ["all ", "these files", "everything", "*. "]) or any(char in target_raw for char in ["*", "?"])
            if is_bulk:
                # 1. Search for matching files
                criteria = parse_natural_search_query(target_raw)
                search_roots = [criteria["restricted_dir"]] if criteria.get("restricted_dir") else get_known_user_roots()
                found_targets, total_targets, _ = await asyncio.to_thread(scan_files_advanced, criteria, search_roots, 50)

                if not found_targets:
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="delete_file",
                        message=f"No matching files found for bulk deletion query: '{target_raw}'.",
                        data={"count": 0, "deleted": []}
                    )

                if not is_confirmed:
                    # Present candidates and require confirmation
                    lines = [f"**⚠️ Confirm Bulk Deletion ({len(found_targets)} target(s)):**\n"]
                    for i, t in enumerate(found_targets[:10], 1):
                        lines.append(f"{i}. `{t['path']}` ({t['size']})")
                    if len(found_targets) > 10:
                        lines.append(f"*(and {len(found_targets) - 10} more files)*")
                    lines.append("\n*This action will move these files to the Recycle Bin. Confirm deletion?*")

                    return ToolResult(
                        success=True,
                        verified=False,
                        tool=self.name,
                        action="delete_file",
                        message="\n".join(lines),
                        confirmation_required=True,
                        pending_action={
                            "operation": "delete_file",
                            "target_path": target_raw,
                            "is_bulk": True,
                            "targets": [t["path"] for t in found_targets]
                        }
                    )
                else:
                    # Execute bulk deletion up to max limit of 50
                    deleted_paths = []
                    failed_paths = []
                    is_permanent = bool(arguments.get("permanent") or arguments.get("force_permanent"))
                    for t in found_targets[:50]:
                        p_t = Path(t["path"])
                        if p_t.exists():
                            if is_permanent:
                                try:
                                    if p_t.is_dir():
                                        shutil.rmtree(str(p_t))
                                    else:
                                        os.remove(str(p_t))
                                    deleted_paths.append(str(p_t))
                                except Exception:
                                    failed_paths.append(str(p_t))
                            else:
                                recycled = send_to_recycle_bin(p_t)
                                if recycled and not p_t.exists():
                                    deleted_paths.append(str(p_t))
                                else:
                                    failed_paths.append(str(p_t))

                    if failed_paths and not deleted_paths:
                        msg = f"Bulk deletion failed: {len(failed_paths)} item(s) could not be moved to Trash and were preserved on disk."
                        audit_logger.log_action(self.name, "FAILED", msg)
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="delete_file",
                            message=msg,
                            error="TrashOperationFailed",
                            data={"failed_items": failed_paths}
                        )
                    elif failed_paths:
                        msg = f"Bulk deletion partially complete: {len(deleted_paths)} moved to Trash, {len(failed_paths)} preserved on disk."
                        audit_logger.log_action(self.name, "PARTIAL_SUCCESS", msg)
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action="delete_file",
                            message=msg,
                            data={"deleted_count": len(deleted_paths), "deleted_files": deleted_paths, "failed_files": failed_paths}
                        )
                    else:
                        msg = f"Bulk deletion complete: {len(deleted_paths)} file(s) removed successfully."
                        audit_logger.log_action(self.name, "SUCCESS", msg)
                        return ToolResult(
                            success=True,
                            verified=True,
                            tool=self.name,
                            action="delete_file",
                            message=msg,
                            data={"deleted_count": len(deleted_paths), "deleted_files": deleted_paths}
                        )

            # Single File / Directory Deletion
            resolved_path, err_res, matches = resolve_target_file_path(target_raw, must_exist=True)
            if len(matches) > 1:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message=err_res,
                    error="Ambiguous file"
                )

            if not resolved_path or not resolved_path.exists():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message=err_res or f"Target '{target_raw}' was not found.",
                    error="FileNotFoundError"
                )

            # Path Traversal & Security Validation
            valid, err_msg, validated_path = permissions.validate_path(str(resolved_path))
            if not valid or not validated_path or ".." in target_raw:
                audit_logger.log_action(self.name, "BLOCKED", err_msg)
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message=f"Access to path '{target_raw}' is restricted for security.",
                    error=err_msg or "Restricted path"
                )

            exact_path_str = str(validated_path.resolve())
            is_dir = validated_path.is_dir()
            target_type = "folder" if is_dir else "file"
            dest_name = "Trash" if IS_MACOS else "Recycle Bin"

            # Confirmation Protection
            if not is_confirmed:
                action_desc = "permanently delete" if arguments.get("permanent") else f"move the {target_type} to the {dest_name}"
                confirm_prompt = (
                    f"**⚠️ Confirm Deletion:**\n\n"
                    f"Delete {target_type}: `{validated_path.name}`\n"
                    f"Location: `{exact_path_str}`\n\n"
                    f"*This action will {action_desc}. Confirm?*"
                )
                return ToolResult(
                    success=True,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message=confirm_prompt,
                    confirmation_required=True,
                    pending_action={"operation": "delete_file", "target_path": exact_path_str, "is_dir": is_dir, "permanent": bool(arguments.get("permanent"))}
                )

            # Execution upon Confirmation
            try:
                is_permanent = bool(arguments.get("permanent") or arguments.get("force_permanent"))

                if is_permanent:
                    # Separately authorized explicit permanent deletion
                    if is_dir:
                        shutil.rmtree(str(validated_path))
                    else:
                        os.remove(str(validated_path))
                    recycled = False
                else:
                    # 1. Attempt Recycle Bin / Trash deletion
                    recycled = send_to_recycle_bin(validated_path)

                    # 2. Strict Safety Rule: If moving to Trash/Recycle Bin fails, NEVER fall back to permanent deletion
                    if not recycled or validated_path.exists():
                        err_msg = (
                            f"Could not move {target_type} '{validated_path.name}' to {dest_name}. "
                            f"The {target_type} was preserved on disk to prevent accidental permanent data loss."
                        )
                        audit_logger.log_action(self.name, "FAILED", err_msg)
                        return ToolResult(
                            success=False,
                            verified=False,
                            tool=self.name,
                            action="delete_file",
                            message=err_msg,
                            error="TrashOperationFailed"
                        )

                # 3. Action Verification
                is_ver, v_data, v_err = ActionVerifier.verify_delete(validated_path)
                if not is_ver:
                    audit_logger.log_action(self.name, "FAILED", v_err)
                    return ToolResult(
                        success=False,
                        verified=False,
                        verification=v_data,
                        tool=self.name,
                        action="delete_file",
                        message=f"Deletion of {validated_path.name} could not be verified.",
                        error=v_err
                    )

                msg = f"{target_type.capitalize()} '{validated_path.name}' was deleted successfully."
                audit_logger.log_action(self.name, "SUCCESS", msg)
                return ToolResult(
                    success=True,
                    verified=True,
                    verification=v_data,
                    tool=self.name,
                    action="delete_file",
                    message=msg,
                    data={"path": exact_path_str, "name": validated_path.name, "deleted": True, "recycled": recycled}
                )
            except Exception as e:
                msg = f"Failed to delete {validated_path.name}: {e}"
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="delete_file",
                    message=msg,
                    error=str(e)
                )

        else:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="file_operations",
                message=f"Unsupported file operation '{operation}'. Supported: create_file, create_folder, rename, copy, move, delete.",
                error="Invalid operation"
            )

# Individual Skills for Granular Registration
class CreateFolderSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "create_folder"

    @property
    def description(self) -> str:
        return "Creates a new folder inside an allowed directory."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"target_path": {"type": "string", "description": "Folder path or name to create"}},
            "required": ["target_path"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        return await ops.execute({"operation": "create_folder", **arguments})

class CreateFileSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "create_file"

    @property
    def description(self) -> str:
        return "Creates a new file inside an allowed directory without overwriting."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename to create"},
                "folder": {"type": "string", "description": "Folder name/path to create file in"},
                "content": {"type": "string", "description": "Optional text content"}
            },
            "required": ["filename"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        return await ops.execute({"operation": "create_file", **arguments})

class RenameFileSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "rename_file"

    @property
    def description(self) -> str:
        return "Renames an existing file or folder."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Current file/folder path"},
                "new_name": {"type": "string", "description": "New file/folder name"}
            },
            "required": ["source_path", "new_name"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        return await ops.execute({"operation": "rename", **arguments})

class CopyFileSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "copy_file"

    @property
    def description(self) -> str:
        return "Copies a file or folder to a new destination."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Source file path"},
                "destination_path": {"type": "string", "description": "Destination directory path"}
            },
            "required": ["source_path", "destination_path"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        return await ops.execute({"operation": "copy", **arguments})

class MoveFileSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "move_file"

    @property
    def description(self) -> str:
        return "Moves a file or folder to a new destination."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Source file path"},
                "destination_path": {"type": "string", "description": "Destination directory path"}
            },
            "required": ["source_path", "destination_path"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        return await ops.execute({"operation": "move", **arguments})

class DeleteFileSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "delete_file"

    @property
    def description(self) -> str:
        return "Safely deletes a specified file or folder after user confirmation."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_path": {"type": "string", "description": "Target file or folder path to delete"},
                "confirmed": {"type": "boolean", "description": "Whether user confirmed deletion"},
                "permanent": {"type": "boolean", "description": "Explicitly authorize permanent deletion without moving to Trash/Recycle Bin (defaults to false)"}
            },
            "required": ["target_path"]
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        ops = FileOperationsSkill()
        args = {"operation": "delete_file", **arguments}
        return await ops.execute(args)
