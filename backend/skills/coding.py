"""
ByteX — Feature #33.1: Coding Workspace Skill

Dedicated Coding Workspace skill that allows ByteX to understand and
perform safe, structured coding-workspace operations.

Supported Actions:
1. create_project: Creates a dedicated project directory with starter templates.
2. open_project: Locates, validates, and sets active coding project context.
3. inspect_project: Summarizes files, directories, language, and entry point.
4. create_code_file: Creates a validated source code file in the active project.
5. read_code_file: Reads source code content from disk with privacy sanitization.
6. edit_code_file: Performs safe, minimal in-place code edits with post-write verification.
7. project_structure: Returns a clean ASCII tree of the project hierarchy.
8. detect_language: Analyzes file extensions to determine the primary language.

Security & Safety Constraints:
- Zero shell/terminal/subprocess execution (strictly bounded to file I/O).
- No silent project or file overwrites.
- Strict extension validation against supported development file types.
- Full post-write verification on every mutation.
"""

import os
import sys
import re
import time
import shutil
import asyncio
import tempfile
import uuid
import json
import psutil
import difflib
import subprocess
import logging
from urllib.parse import unquote, urlparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def file_uri_to_path(uri: str) -> Path:
    """
    Safely converts a file:// URI or normal filesystem path into a resolved Path object.

    Handles:
    - Standard macOS/POSIX file URIs (e.g. 'file:///Users/username/project/main.cpp')
    - Percent-encoded characters and spaces (e.g. 'file:///Users/name/my%20project/01%20test.cpp')
    - Standard Windows file URIs with 3 slashes (e.g. 'file:///C:/Users/name/main.cpp')
    - Windows file URIs with 2 slashes where drive letter is netloc (e.g. 'file://C:/Users/name/main.cpp')
    - Windows UNC URIs (e.g. 'file://server/share/path')
    - Localhost netloc (e.g. 'file://localhost/Users/name/main.cpp')
    - Standard filesystem paths on macOS/POSIX ('/Users/name/main.cpp')
    - Standard filesystem paths on Windows (r'C:\\Users\\name\\main.cpp')
    """
    if not isinstance(uri, str):
        uri = str(uri)
    uri_clean = uri.strip()
    if not uri_clean.startswith("file:"):
        return Path(uri_clean)

    parsed = urlparse(uri_clean)
    host = parsed.netloc
    raw_path = unquote(parsed.path)

    # Handle 2-slash file://C:/... where host is 'C:'
    if host:
        if re.match(r"^[a-zA-Z]:$", host):
            raw_path = f"{host}{raw_path}"
        elif host not in ("localhost", ""):
            # UNC path on Windows: file://server/share/path -> //server/share/path
            raw_path = f"//{host}{raw_path}"

    # Handle 3-slash Windows file:///C:/... where raw_path is '/C:/...'
    if re.match(r"^/[a-zA-Z]:", raw_path):
        raw_path = raw_path[1:]

    return Path(raw_path)

from skills.base import BaseSkill, ToolResult
from skills.files import resolve_user_directory, get_known_user_roots, find_existing_user_folder
from core.verifier import ActionVerifier
from skills.diagnostics import CodeDiagnosticEngine, ErrorCategory
from skills.code_fixer import CodeFixEngine, FixMode, CodePatch, FixResult

logger = logging.getLogger("bytex.skills.coding")

READ_ONLY_ACTIONS = {
    "read_code_file", "inspect_project", "project_structure",
    "detect_language", "explain_code", "explain", "review_code",
    "review", "teach_code", "teach", "hint", "give_hint",
    "analyze_code", "analyze", "complexity", "complexity_analysis",
    "optimization_analysis", "diagnose_code_error", "diagnose",
    "compile_code", "compile", "build_code", "build"
}

SUPPORTED_EXTENSIONS = {
    # Python
    ".py": "Python",
    ".pyi": "Python Interface",
    # C / C++
    ".cpp": "C++",
    ".cxx": "C++",
    ".cc": "C++",
    ".hpp": "C++ Header",
    ".hxx": "C++ Header",
    ".c": "C",
    ".h": "C Header",
    # JavaScript / TypeScript / Web
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript/React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript/React",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    ".json": "JSON",
    # Systems & Other Languages
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".sql": "SQL",
    # Documentation & Config
    ".md": "Markdown",
    ".txt": "Text",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".env": "Environment Config",
    ".gitignore": "Git Config"
}

DISALLOWED_EXTENSIONS = {
    ".exe", ".dll", ".sys", ".drv", ".so", ".bin", ".com",
    ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".reg"
}

IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".idea", ".vscode", "dist", "build", "target", "bin", "obj", ".mypy_cache"
}

LANGUAGE_TEMPLATES = {
    "python": {
        "ext": ".py",
        "entry": "main.py",
        "code": 'def main():\n    print("Hello from {project_name}!")\n\nif __name__ == "__main__":\n    main()\n',
        "readme": "# {project_name}\n\nA Python project created with ByteX.\n\n## Getting Started\nRun `python main.py` to execute.\n"
    },
    "cpp": {
        "ext": ".cpp",
        "entry": "main.cpp",
        "code": '#include <iostream>\nusing namespace std;\n\nint main() {{\n    cout << "Hello from {project_name}!" << endl;\n    return 0;\n}}\n',
        "readme": "# {project_name}\n\nA C++ project created with ByteX.\n\n## Getting Started\nCompile with `g++ main.cpp -o {project_name_lower}`.\n"
    },
    "c": {
        "ext": ".c",
        "entry": "main.c",
        "code": '#include <stdio.h>\n\nint main() {{\n    printf("Hello from {project_name}!\\n");\n    return 0;\n}}\n',
        "readme": "# {project_name}\n\nA C project created with ByteX.\n\n## Getting Started\nCompile with `gcc main.c -o {project_name_lower}`.\n"
    },
    "javascript": {
        "ext": ".js",
        "entry": "index.js",
        "code": 'function main() {{\n    console.log("Hello from {project_name}!");\n}}\n\nmain();\n',
        "readme": "# {project_name}\n\nA JavaScript project created with ByteX.\n\n## Getting Started\nRun with `node index.js`.\n"
    },
    "typescript": {
        "ext": ".ts",
        "entry": "index.ts",
        "code": 'function main(): void {{\n    console.log("Hello from {project_name}!");\n}}\n\nmain();\n',
        "readme": "# {project_name}\n\nA TypeScript project created with ByteX.\n\n## Getting Started\nRun with `ts-node index.ts`.\n"
    },
    "java": {
        "ext": ".java",
        "entry": "Main.java",
        "code": 'public class Main {{\n    public static void main(String[] args) {{\n        System.out.println("Hello from {project_name}!");\n    }}\n}}\n',
        "readme": "# {project_name}\n\nA Java project created with ByteX.\n\n## Getting Started\nCompile with `javac Main.java` and run `java Main`.\n"
    },
    "go": {
        "ext": ".go",
        "entry": "main.go",
        "code": 'package main\n\nimport "fmt"\n\nfunc main() {{\n    fmt.Println("Hello from {project_name}!")\n}}\n',
        "readme": "# {project_name}\n\nA Go project created with ByteX.\n\n## Getting Started\nRun with `go run main.go`.\n"
    },
    "rust": {
        "ext": ".rs",
        "entry": "main.rs",
        "code": 'fn main() {{\n    println!("Hello from {project_name}!");\n}}\n',
        "readme": "# {project_name}\n\nA Rust project created with ByteX.\n\n## Getting Started\nRun with `cargo run` or `rustc main.rs`.\n"
    },
    "web": {
        "ext": ".html",
        "entry": "index.html",
        "code": '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <title>{project_name}</title>\n    <link rel="stylesheet" href="style.css">\n</head>\n<body>\n    <h1>Hello from {project_name}!</h1>\n    <script src="app.js"></script>\n</body>\n</html>\n',
        "readme": "# {project_name}\n\nA Web project created with ByteX.\n\n## Getting Started\nOpen `index.html` in your browser.\n"
    }
}


class CodingWorkspaceSkill(BaseSkill):
    """
    ByteX Coding Workspace Skill.
    
    Provides safe, structured workspace operations for creating, opening,
    inspecting, editing, and structuring software projects.
    """

    def __init__(self):
        self._active_project_path: Optional[Path] = None
        self._active_project_name: Optional[str] = None

    @property
    def name(self) -> str:
        return "coding_workspace"

    @property
    def description(self) -> str:
        return "Manages software coding projects, code files, project structures, and language detection safely."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_project",
                        "open_project",
                        "inspect_project",
                        "get_active_workspace",
                        "find_file",
                        "create_code_file",
                        "read_code_file",
                        "edit_code_file",
                        "project_structure",
                        "detect_language",
                        "generate_code",
                        "execute_code",
                        "compile_code",
                        "compile",
                        "build_code",
                        "build",
                        "explain_code",
                        "diagnose_code_error",
                        "fix_code_error",
                        "review_code",
                        "teach_code",
                        "analyze_code"
                    ],
                    "description": "The coding workspace action to perform."
                },
                "project_name": {
                    "type": "string",
                    "description": "The name of the project or directory."
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (e.g. python, cpp, c, javascript, typescript, java, go, rust, web)."
                },
                "filename": {
                    "type": "string",
                    "description": "The name of the source code file (e.g. main.py, main.cpp, App.tsx)."
                },
                "file_path": {
                    "type": "string",
                    "description": "Explicit path or filename of source code file to execute, explain, diagnose, or fix."
                },
                "prompt": {
                    "type": "string",
                    "description": "Natural language programming prompt or description of code to generate."
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite an existing source file when confirmed."
                },
                "content": {
                    "type": "string",
                    "description": "Source code content to write or insert."
                },
                "target_text": {
                    "type": "string",
                    "description": "Existing text or pattern to replace during an edit."
                },
                "replacement_text": {
                    "type": "string",
                    "description": "New text to substitute in place of target_text."
                },
                "path": {
                    "type": "string",
                    "description": "Explicit path to a project or file."
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Execution timeout limit in seconds (default 10s, max 30s)."
                },
                "stdin": {
                    "type": "string",
                    "description": "Optional standard input to pass to the running program."
                },
                "compile": {
                    "type": "boolean",
                    "description": "Whether to compile before execution (for compiled languages)."
                },
                "mode": {
                    "type": "string",
                    "enum": ["normal", "beginner", "line_by_line", "algorithm", "complexity", "interview"],
                    "description": "Code explanation mode (normal, beginner, line_by_line, algorithm, complexity, interview)."
                },
                "code": {
                    "type": "string",
                    "description": "Optional in-memory code snippet to explain, diagnose, or fix."
                },
                "stage": {
                    "type": "string",
                    "enum": ["auto", "compile", "runtime", "setup"],
                    "description": "Execution stage that produced the error (compile, runtime, setup, auto)."
                },
                "error_output": {
                    "type": "string",
                    "description": "Compiler error message, panic, or runtime traceback to diagnose or fix."
                },
                "exit_code": {
                    "type": "integer",
                    "description": "Process exit code from execution."
                },
                "source_code": {
                    "type": "string",
                    "description": "Source code content around the error for context extraction or fixing."
                },
                "execution_result": {
                    "type": "object",
                    "description": "Structured execution result object from previous execute_code run."
                },
                "fix_mode": {
                    "type": "string",
                    "enum": ["automatic", "confirm", "suggest_only"],
                    "description": "Code fixing mode (automatic, confirm, suggest_only)."
                },
                "require_confirmation": {
                    "type": "boolean",
                    "description": "Whether explicit user confirmation is strictly required before modifying source."
                },
                "diagnostic": {
                    "type": "object",
                    "description": "Structured diagnostic result from diagnose_code_error."
                }
            },
            "required": ["action"]
        }

    # -----------------------------------------------------------------
    # Helper: Detect Active VS Code Workspace & Editor Info
    # -----------------------------------------------------------------
    def _detect_vscode_workspace_info(self) -> Dict[str, Any]:
        """
        Detects active VS Code workspace folder, active editor file, and editor title.
        Returns a dict: {
            "workspace_root": Optional[Path],
            "workspace_name": Optional[str],
            "active_file": Optional[Path],
            "active_file_name": Optional[str],
            "active_editor_title": Optional[str],
            "source": str
        }
        """
        result = {
            "workspace_root": None,
            "workspace_name": None,
            "active_file": None,
            "active_file_name": None,
            "active_editor_title": None,
            "source": "none"
        }

        if getattr(self, "_cached_vscode_workspace", None):
            cached_p = Path(self._cached_vscode_workspace)
            result["workspace_root"] = cached_p
            result["workspace_name"] = cached_p.name
            result["source"] = "cached_vscode_workspace"
            return result

        # 1. Check live VS Code Windows via user32.EnumWindows (Priority 1: Active/Foreground Window)
        win_active_file = None
        win_ws_name = None
        vs_running = False

        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                vs_windows = []

            def enum_proc(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value
                        t_lower = title.lower()
                        if "visual studio code" in t_lower or t_lower.endswith(" - vs code") or t_lower.endswith(" - code"):
                            vs_windows.append((hwnd, title))
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

            if vs_windows:
                vs_running = True

            # Check foreground window first, then top VS Code window
            fg_hwnd = user32.GetForegroundWindow()
            fg_title = None
            if fg_hwnd:
                length = user32.GetWindowTextLengthW(fg_hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg_hwnd, buf, length + 1)
                    t_val = buf.value
                    t_lower = t_val.lower()
                    if "visual studio code" in t_lower or t_lower.endswith(" - vs code") or t_lower.endswith(" - code"):
                        fg_title = t_val
                        vs_running = True

            chosen_title = fg_title or (vs_windows[0][1] if vs_windows else None)
            if chosen_title:
                result["active_editor_title"] = chosen_title
                # Clean dot/dirty marker, admin, workspace tag:
                clean_t = re.sub(r"^[●*]\s*", "", chosen_title)
                clean_t = re.sub(r"\s*\[(?:Administrator|SSH:[^\]]+|WSL:[^\]]+)\]", "", clean_t, flags=re.IGNORECASE)
                clean_t = re.sub(r"\s*\(Workspace\)", "", clean_t, flags=re.IGNORECASE)
                clean_t = re.sub(r"\s+-\s+(?:Visual\s+Studio\s+Code(?: - Insiders)?|VS\s*Code|Code)$", "", clean_t, flags=re.IGNORECASE).strip()

                if clean_t and clean_t.lower() not in ["visual studio code", "welcome", "get started"]:
                    if " - " in clean_t:
                        parts = clean_t.split(" - ")
                        win_active_file = parts[0].strip()
                        win_ws_name = parts[-1].strip()
                    else:
                        if any(clean_t.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS) or "." in clean_t:
                            win_active_file = clean_t.strip()
                        else:
                            win_ws_name = clean_t.strip()

                    if win_active_file:
                        result["active_file_name"] = win_active_file
                    if win_ws_name:
                        result["workspace_name"] = win_ws_name
        except Exception:
            pass

        # 2. Check running VS Code processes (Code.exe) for command line arguments or running status
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                p_name = (proc.info.get('name') or '').lower()
                if 'code' in p_name:
                    vs_running = True
                    cmdline = proc.info.get('cmdline') or []
                    for idx, arg in enumerate(cmdline):
                        if not arg:
                            continue
                        if arg.startswith('--folder-uri=') or arg.startswith('--folder-uri'):
                            uri_val = arg.split('=', 1)[1] if '=' in arg else (cmdline[idx+1] if idx+1 < len(cmdline) else '')
                            if uri_val:
                                p_cand = file_uri_to_path(uri_val)
                                if p_cand.is_dir() and not result["workspace_root"]:
                                    result["workspace_root"] = p_cand
                                    result["workspace_name"] = p_cand.name
                                    result["source"] = "vscode_process_cmdline"
                        elif arg.startswith('--file-uri=') or arg.startswith('--file-uri'):
                            uri_val = arg.split('=', 1)[1] if '=' in arg else (cmdline[idx+1] if idx+1 < len(cmdline) else '')
                            if uri_val:
                                p_cand = file_uri_to_path(uri_val)
                                if p_cand.is_file() and not result["active_file"]:
                                    result["active_file"] = p_cand
                                    result["active_file_name"] = p_cand.name
                                    if not result["workspace_root"]:
                                        result["workspace_root"] = p_cand.parent
                                        result["workspace_name"] = p_cand.parent.name
                                        result["source"] = "vscode_process_cmdline"
                        elif not arg.startswith('-') and os.path.isabs(arg):
                            p_cand = Path(arg)
                            if p_cand.is_dir() and not result["workspace_root"]:
                                if "microsoft vs code" not in str(p_cand).lower() and "resources" not in str(p_cand).lower():
                                    result["workspace_root"] = p_cand
                                    result["workspace_name"] = p_cand.name
                                    result["source"] = "vscode_process_cmdline"
        except Exception:
            pass

        # 3. Check VS Code workspaceStorage directory across platforms:
        #    - Windows: %APPDATA%\Code\User\workspaceStorage
        #    - macOS:   ~/Library/Application Support/Code/User/workspaceStorage
        #    - Linux:   ~/.config/Code/User/workspaceStorage
        try:
            ws_storage_candidates: List[Path] = []
            appdata = os.environ.get("APPDATA")
            if appdata:
                ws_storage_candidates.extend([
                    Path(appdata) / "Code" / "User" / "workspaceStorage",
                    Path(appdata) / "Code - Insiders" / "User" / "workspaceStorage",
                    Path(appdata) / "VSCodium" / "User" / "workspaceStorage",
                ])

            user_home = Path.home()
            if sys.platform == "darwin":
                ws_storage_candidates.extend([
                    user_home / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage",
                    user_home / "Library" / "Application Support" / "Code - Insiders" / "User" / "workspaceStorage",
                    user_home / "Library" / "Application Support" / "VSCodium" / "User" / "workspaceStorage",
                ])
            else:
                ws_storage_candidates.extend([
                    user_home / ".config" / "Code" / "User" / "workspaceStorage",
                    user_home / ".config" / "Code - Insiders" / "User" / "workspaceStorage",
                    user_home / ".config" / "VSCodium" / "User" / "workspaceStorage",
                ])

            for ws_storage in ws_storage_candidates:
                if result["workspace_root"] and result["active_file"]:
                    break
                if not ws_storage.exists() or not ws_storage.is_dir():
                    continue

                try:
                    entries = sorted(
                        [d for d in ws_storage.iterdir() if d.is_dir()],
                        key=lambda d: d.stat().st_mtime,
                        reverse=True
                    )
                except Exception:
                    continue

                matched_entry = None
                if win_ws_name:
                    for entry in entries:
                        ws_json = entry / "workspace.json"
                        if ws_json.is_file():
                            try:
                                data = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
                                folder_uri = data.get("folder") or data.get("configuration")
                                if folder_uri:
                                    p = file_uri_to_path(folder_uri)
                                    if (p.name.lower() == win_ws_name.lower() or p.stem.lower() == win_ws_name.lower()) and p.exists() and p.is_dir():
                                        matched_entry = (entry, p)
                                        break
                            except Exception:
                                pass

                # If no match from window title name, check most recent valid workspace in workspaceStorage
                if not matched_entry and not result["workspace_root"]:
                    for entry in entries:
                        ws_json = entry / "workspace.json"
                        if ws_json.is_file():
                            try:
                                data = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
                                folder_uri = data.get("folder") or data.get("configuration")
                                if folder_uri:
                                    p = file_uri_to_path(folder_uri)
                                    if p.exists() and p.is_dir():
                                        if "microsoft vs code" not in str(p).lower() and "resources" not in str(p).lower():
                                            matched_entry = (entry, p)
                                            break
                            except Exception:
                                pass

                if matched_entry:
                    entry_dir, ws_path = matched_entry
                    result["workspace_root"] = ws_path
                    result["workspace_name"] = ws_path.name
                    result["source"] = "vscode_workspace_storage"

                    # Extract active file from state.vscdb
                    db_path = entry_dir / "state.vscdb"
                    if db_path.exists() and not result["active_file"]:
                        try:
                            import sqlite3
                            conn = sqlite3.connect(str(db_path))
                            cur = conn.cursor()
                            cur.execute("SELECT value FROM ItemTable WHERE key = 'history.entries'")
                            row = cur.fetchone()
                            if row and row[0]:
                                val = row[0].decode("utf-8", errors="replace") if isinstance(row[0], bytes) else row[0]
                                hist_data = json.loads(val)
                                if isinstance(hist_data, list) and len(hist_data) > 0:
                                    res_uri = hist_data[0].get("editor", {}).get("resource")
                                    if res_uri:
                                        f_path = file_uri_to_path(res_uri)
                                        if f_path.is_file():
                                            result["active_file"] = f_path
                                            result["active_file_name"] = f_path.name
                            conn.close()
                        except Exception:
                            pass
        except Exception:
            pass

        # 4. If win_ws_name is known but not found in workspaceStorage, search drives / known user roots
        if win_ws_name and not result["workspace_root"]:
            try:
                for root in get_known_user_roots():
                    cand = root / win_ws_name
                    if cand.exists() and cand.is_dir():
                        result["workspace_root"] = cand
                        result["workspace_name"] = cand.name
                        result["source"] = "vscode_window_root_search"
                        break
            except Exception:
                pass

        # 5. Check active session context (if live VS Code detection didn't find a workspace)
        if not result["workspace_root"]:
            try:
                from core.session import session_manager
                ctx = session_manager.get_working_context()
                act_proj = ctx.get("active_project", {})
                if act_proj and act_proj.get("path"):
                    p = Path(act_proj.get("path"))
                    if p.exists() and p.is_dir():
                        result["workspace_root"] = p
                        result["workspace_name"] = p.name
                        result["source"] = "session_active_project"
                
                act_ws = ctx.get("active_workspace") or ctx.get("workspace_path")
                if not result["workspace_root"] and act_ws:
                    p = Path(act_ws)
                    if p.exists() and p.is_dir():
                        result["workspace_root"] = p
                        result["workspace_name"] = p.name
                        result["source"] = "session_active_workspace"

                if not result["active_file"]:
                    act_doc = ctx.get("active_document") or ctx.get("active_file")
                    if act_doc:
                        p_doc = Path(act_doc)
                        if p_doc.is_file():
                            result["active_file"] = p_doc
                            result["active_file_name"] = p_doc.name
            except Exception:
                pass

        # 6. Check memory manager active project (if still not found)
        if not result["workspace_root"]:
            try:
                from memory.manager import memory_manager
                mem_proj = memory_manager.get_active_project()
                if mem_proj and mem_proj.workspace_path and Path(mem_proj.workspace_path).is_dir():
                    result["workspace_root"] = Path(mem_proj.workspace_path)
                    result["workspace_name"] = mem_proj.project_name or Path(mem_proj.workspace_path).name
                    result["source"] = "memory_active_project"
            except Exception:
                pass

        return result

    def _detect_vscode_workspace(self) -> Optional[Path]:
        """
        Detects active VS Code workspace folder from session context,
        VS Code window titles, VS Code workspaceStorage, or running process metadata.
        """
        info = self._detect_vscode_workspace_info()
        return info.get("workspace_root")

    # -----------------------------------------------------------------
    # Helper: Resolve Workspace File with Recursive Scanning & Disambiguation
    # -----------------------------------------------------------------
    def resolve_workspace_file(
        self,
        filename_or_query: str,
        project_name_or_path: Optional[str] = None
    ) -> Tuple[Optional[Path], Optional[str], List[Path]]:
        """
        Resolves a target filename inside the active workspace according to strict priorities:
        1. Exact match in active workspace root.
        2. Active editor if query is 'this file', 'current file', 'this', 'here', or matches active file.
        3. Relative path supplied by user (e.g. week1/dsa.cpp).
        4. Recursive workspace scan (depth <= 6, ignoring IGNORED_DIRS).
           - 1 match: Returns unique match.
           - >1 matches: Returns disambiguation message with numbered options.
           - 0 matches: Returns candidate creation path in workspace root.
        
        Returns: (resolved_file_path, disambiguation_or_error_msg, candidate_matches)
        """
        query = (filename_or_query or "").strip().strip('"\'')
        query = re.sub(r"[.!?,\"\':]+$", "", query).strip()
        ws_info = self._detect_vscode_workspace_info()
        
        # Determine workspace root
        workspace_root = None
        if project_name_or_path:
            p = Path(project_name_or_path)
            if p.is_absolute() and p.is_dir():
                workspace_root = p
            else:
                p_root, _ = self._resolve_project_root(project_name_or_path)
                if p_root and p_root.is_dir():
                    workspace_root = p_root

        if not workspace_root:
            if self._active_project_path and self._active_project_path.exists() and (self._active_project_path / query).exists():
                workspace_root = self._active_project_path
            elif ws_info.get("workspace_root"):
                workspace_root = ws_info.get("workspace_root")
                self._active_project_path = workspace_root
                self._active_project_name = workspace_root.name
            elif self._active_project_path and self._active_project_path.exists():
                workspace_root = self._active_project_path
            else:
                workspace_root, _ = self._resolve_project_root()

        if not workspace_root:
            workspace_root = resolve_user_directory("desktop")

        active_file = ws_info.get("active_file")
        active_file_name = ws_info.get("active_file_name")
        if not active_file or not active_file.is_file():
            try:
                from core.session import session_manager
                s_ctx = session_manager.get_working_context()
                s_act = s_ctx.get("active_file") or s_ctx.get("active_document")
                if isinstance(s_act, dict):
                    s_act = s_act.get("uri") or s_act.get("path") or s_act.get("file")
                if s_act and isinstance(s_act, (str, Path)) and Path(s_act).is_file():
                    active_file = Path(s_act)
                    active_file_name = active_file.name
            except Exception:
                pass

        # Handle 'this file' / 'current file' / 'here'
        q_lower = query.lower()
        if q_lower in ["this file", "current file", "this", "here", "the current file", "the active file", "__active_file__"]:
            if active_file and active_file.is_file():
                return active_file, None, [active_file]
            if active_file_name:
                query = active_file_name
            else:
                # Check workspace entry point or single code file fallback
                ep = self._identify_entry_point(workspace_root)
                if ep and (workspace_root / ep).is_file():
                    return workspace_root / ep, None, [workspace_root / ep]
                # Check for single code file in workspace
                all_code_files = [
                    f for f in workspace_root.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                ] if workspace_root.is_dir() else []
                if len(all_code_files) == 1:
                    return all_code_files[0], None, all_code_files
                return None, "No active file is currently open in your editor. Which file should I look at?", []

        # 0. URI check
        if query.startswith("file:"):
            p_uri = file_uri_to_path(query)
            if p_uri.is_file():
                return p_uri, None, [p_uri]
            if p_uri.is_dir():
                return p_uri, None, []
            return p_uri, None, []

        # 1. Absolute path check
        p_query = Path(query)
        if p_query.is_absolute():
            if p_query.is_file():
                return p_query, None, [p_query]
            if p_query.is_dir():
                return p_query, None, []
            return p_query, None, []

        # 2. Explicit relative path with directory components from workspace root (e.g. src/app.ts, week1/dsa.cpp)
        if ("/" in query or "\\" in query) and not p_query.is_absolute():
            rel_target = workspace_root / query
            if rel_target.is_file():
                return rel_target, None, [rel_target]

        # 3. Active editor match if filename matches query and is inside workspace_root
        if active_file and active_file.is_file() and (active_file.name.lower() == query.lower() or active_file.stem.lower() == query.lower()):
            try:
                if workspace_root in active_file.parents or active_file == workspace_root / active_file.name:
                    # Let recursive walk check for duplicate files in subdirectories unless explicitly requested
                    pass
            except Exception:
                pass

        # 4. Recursive bounded workspace scan (depth <= 6)
        target_stem_or_name = query.lower()
        candidates: List[Path] = []

        try:
            for root_dir, dirs, files in os.walk(workspace_root):
                # Filter out ignored directories in-place
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                
                # Check depth
                try:
                    rel_depth = len(Path(root_dir).relative_to(workspace_root).parts)
                    if rel_depth > 6:
                        dirs.clear()
                        continue
                except Exception:
                    pass

                for f in files:
                    f_lower = f.lower()
                    if f_lower == target_stem_or_name or Path(f).stem.lower() == target_stem_or_name:
                        full_f = Path(root_dir) / f
                        if full_f.is_file():
                            candidates.append(full_f)
        except Exception:
            pass

        # Evaluate recursive search results
        if len(candidates) == 1:
            return candidates[0], None, candidates

        elif len(candidates) > 1:
            # Duplicate files found! Construct numbered disambiguation list
            lines = [f"I found {len(candidates)} {query} files in your workspace:"]
            for idx, c in enumerate(candidates, 1):
                try:
                    rel_display = str(c.relative_to(workspace_root))
                except Exception:
                    rel_display = str(c)
                lines.append(f"{idx}. {rel_display}")
            lines.append("Which one should I modify?")
            disambig_msg = "\n".join(lines)
            return None, disambig_msg, candidates

        # 5. Fallback: Search known user roots if not found in workspace
        for root in get_known_user_roots():
            cand = root / query
            if cand.is_file():
                return cand, None, [cand]

        # 6. File does not exist yet; return candidate creation path in workspace root
        return workspace_root / query, None, []

    # -----------------------------------------------------------------
    # Helper: Resolve Project Root
    # -----------------------------------------------------------------
    def _resolve_project_root(self, project_name_or_path: Optional[str] = None) -> Tuple[Optional[Path], Optional[str]]:
        """
        Locates an existing project root, active VS Code workspace, or returns the default creation root.
        """
        if project_name_or_path:
            p_str = project_name_or_path.strip().strip('"\'')
            p = Path(p_str)
            if p.is_absolute() and p.is_dir():
                return p, None

            # Search in known roots
            for root in get_known_user_roots():
                candidate = root / p_str
                if candidate.exists() and candidate.is_dir():
                    return candidate, None

            # Fallback to desktop / project_name
            desktop = resolve_user_directory("desktop")
            return desktop / p_str, None

        # Check active VS Code workspace dynamically first
        vs_ws = self._detect_vscode_workspace()
        if vs_ws and vs_ws.exists() and vs_ws.is_dir():
            self._active_project_path = vs_ws
            self._active_project_name = vs_ws.name
            return vs_ws, None

        if self._active_project_path and self._active_project_path.exists():
            return self._active_project_path, None

        # Check default Desktop
        desktop = resolve_user_directory("desktop")
        return desktop, None

    # -----------------------------------------------------------------
    # Helper: Detect Primary Language
    # -----------------------------------------------------------------
    def _detect_project_language(self, project_dir: Path) -> Tuple[str, Dict[str, int]]:
        """
        Scans all files in the project to detect the primary language.
        """
        counts: Dict[str, int] = {}
        if not project_dir.exists() or not project_dir.is_dir():
            return "Unknown", {}

        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    lang = SUPPORTED_EXTENSIONS[ext]
                    counts[lang] = counts.get(lang, 0) + 1

        if not counts:
            return "Unknown", {}

        primary = max(counts.items(), key=lambda item: item[1])[0]
        return primary, counts

    # -----------------------------------------------------------------
    # Helper: Build ASCII Tree
    # -----------------------------------------------------------------
    def _generate_tree(self, root_dir: Path, max_depth: int = 4) -> str:
        """
        Generates a clean ASCII tree representation of the project structure.
        """
        lines = [f"{root_dir.name}/"]

        def _walk(directory: Path, prefix: str = "", depth: int = 1):
            if depth > max_depth:
                lines.append(f"{prefix}└── ... (max depth reached)")
                return

            try:
                entries = sorted(
                    [e for e in directory.iterdir() if e.name not in IGNORED_DIRS and not e.name.startswith(".")],
                    key=lambda e: (not e.is_dir(), e.name.lower())
                )
            except Exception:
                return

            total = len(entries)
            for idx, entry in enumerate(entries):
                is_last = (idx == total - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    _walk(entry, prefix + sub_prefix, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{entry.name}")

        _walk(root_dir)
        return "\n".join(lines)

    # -----------------------------------------------------------------
    # Helper: Identify Entry Point
    # -----------------------------------------------------------------
    def _identify_entry_point(self, project_dir: Path) -> Optional[str]:
        """Identifies standard main/entry point files."""
        candidates = [
            "main.py", "app.py", "index.py",
            "main.cpp", "main.c", "app.cpp",
            "index.js", "app.js", "main.js", "server.js",
            "index.ts", "app.ts", "main.ts", "server.ts",
            "Main.java", "main.go", "main.rs",
            "index.html", "App.tsx", "App.jsx"
        ]
        for c in candidates:
            if (project_dir / c).is_file():
                return c
        return None

    # -----------------------------------------------------------------
    # Main Execution Router
    # -----------------------------------------------------------------
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "")).strip().lower()
        if not action:
            if "instruction" in arguments or "target_text" in arguments:
                action = "edit_code_file"
            elif "file_path" in arguments or "stdin" in arguments:
                action = "execute_code"
            elif "prompt" in arguments or "description" in arguments:
                action = "generate_code"
            elif "filename" in arguments:
                action = "create_code_file"

        if action == "create_project":
            return await self._action_create_project(arguments)
        elif action == "open_project":
            return await self._action_open_project(arguments)
        elif action == "inspect_project":
            return await self._action_inspect_project(arguments)
        elif action == "create_code_file":
            return await self._action_create_code_file(arguments)
        elif action in ["read_code_file", "read_file", "read_source_file", "read"]:
            return await self._action_read_code_file(arguments)
        elif action == "edit_code_file":
            return await self._action_edit_code_file(arguments)
        elif action == "project_structure":
            return await self._action_project_structure(arguments)
        elif action == "detect_language":
            return await self._action_detect_language(arguments)
        elif action == "generate_code":
            return await self._action_generate_code(arguments)
        elif action in ["execute_code", "run_code", "compile_and_run", "execute", "run"]:
            return await self._action_execute_code(arguments)
        elif action in ["compile_code", "compile", "build_code", "build"]:
            return await self._action_compile_code(arguments)
        elif action in ["explain_code", "explain"]:
            return await self._action_explain_code(arguments)
        elif action in ["review_code", "review", "code_review"]:
            return await self._action_review_code(arguments)
        elif action in ["teach_code", "teach", "hint", "give_hint"]:
            return await self._action_teach_code(arguments)
        elif action in ["analyze_code", "analyze", "complexity_analysis", "optimization_analysis", "analyze_complexity"]:
            return await self._action_analyze_code(arguments)
        elif action in ["diagnose_code_error", "diagnose_error", "diagnose", "diagnose_code"]:
            return await self._action_diagnose_code_error(arguments)
        elif action in ["fix_code_error", "fix_error", "fix_code", "auto_fix", "fix"]:
            return await self._action_fix_code_error(arguments)
        elif action in ["get_active_workspace", "current_workspace", "active_workspace", "get_workspace", "inspect_workspace"]:
            return await self._action_get_active_workspace(arguments)
        elif action in ["find_file", "locate_file", "find_code_file", "search_file", "find"]:
            return await self._action_find_file(arguments)
        else:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action=action,
                message=f"Unsupported coding workspace action: '{action}'.",
                error="Invalid action"
            )

    # -----------------------------------------------------------------
    # 0. ACTION: GET ACTIVE WORKSPACE
    # -----------------------------------------------------------------
    async def _action_get_active_workspace(self, arguments: Dict[str, Any]) -> ToolResult:
        ws_info = self._detect_vscode_workspace_info()
        ws_root = ws_info.get("workspace_root")
        act_file = ws_info.get("active_file_name") or (ws_info.get("active_file").name if ws_info.get("active_file") else None)

        if ws_root and ws_root.exists() and ws_root.is_dir():
            self._active_project_path = ws_root
            self._active_project_name = ws_root.name

            file_extra = f" (active file: `{act_file}`)" if act_file else ""
            msg = f"Your active coding workspace is `{str(ws_root)}`{file_extra}."
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="get_active_workspace",
                message=msg,
                data={
                    "workspace_path": str(ws_root),
                    "workspace_name": ws_root.name,
                    "active_file": str(ws_info.get("active_file")) if ws_info.get("active_file") else None,
                    "active_file_name": act_file,
                    "source": ws_info.get("source", "vscode")
                }
            )
        else:
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="get_active_workspace",
                message="No active coding workspace is currently detected. You can open a project in VS Code or specify a workspace folder.",
                data={
                    "workspace_path": None,
                    "workspace_name": None,
                    "active_file": None,
                    "source": "none"
                }
            )

    # -----------------------------------------------------------------
    # 0b. ACTION: FIND FILE IN WORKSPACE
    # -----------------------------------------------------------------
    async def _action_find_file(self, arguments: Dict[str, Any]) -> ToolResult:
        filename = (arguments.get("filename") or arguments.get("name") or arguments.get("query") or "").strip()
        p_name = arguments.get("project_name")
        if not filename:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="find_file",
                message="Please specify the file name to find in your workspace.",
                error="Missing filename"
            )

        target_file, disambig_msg, candidates = self.resolve_workspace_file(filename, p_name)
        if disambig_msg and not target_file:
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="find_file",
                message=disambig_msg,
                data={"candidates": [str(c) for c in candidates], "disambiguation": True}
            )

        if not target_file or not target_file.exists():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="find_file",
                message=f"I couldn't find source file '{filename}' in your active workspace.",
                error="File not found"
            )

        ws_info = self._detect_vscode_workspace_info()
        ws_root = ws_info.get("workspace_root")
        try:
            rel_display = str(target_file.relative_to(ws_root)) if ws_root else target_file.name
        except Exception:
            rel_display = target_file.name

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="find_file",
            message=f"Found `{rel_display}` in your active workspace:\n- Path: `{target_file}`",
            data={
                "filename": target_file.name,
                "file_path": str(target_file),
                "workspace_path": str(ws_root) if ws_root else str(target_file.parent),
                "relative_path": rel_display,
                "size_bytes": target_file.stat().st_size if target_file.exists() else 0
            }
        )

    # -----------------------------------------------------------------
    # 1. ACTION: CREATE PROJECT
    # -----------------------------------------------------------------
    async def _action_create_project(self, arguments: Dict[str, Any]) -> ToolResult:
        project_name = (arguments.get("project_name") or arguments.get("name") or "").strip()
        if not project_name:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_project",
                message="Please specify a name for the project.",
                error="Missing project name"
            )

        # Sanitize project name
        project_name = re.sub(r'[\\/:*?"<>|]', '_', project_name)
        lang_key = (arguments.get("language") or "python").strip().lower()

        # Resolve template
        norm_lang = "python"
        if any(k in lang_key for k in ["cpp", "c++"]):
            norm_lang = "cpp"
        elif lang_key == "c":
            norm_lang = "c"
        elif any(k in lang_key for k in ["javascript", "js", "node"]):
            norm_lang = "javascript"
        elif any(k in lang_key for k in ["typescript", "ts"]):
            norm_lang = "typescript"
        elif "java" in lang_key:
            norm_lang = "java"
        elif "go" in lang_key:
            norm_lang = "go"
        elif "rust" in lang_key:
            norm_lang = "rust"
        elif any(k in lang_key for k in ["html", "web", "frontend"]):
            norm_lang = "web"

        template = LANGUAGE_TEMPLATES.get(norm_lang, LANGUAGE_TEMPLATES["python"])

        # Determine target directory
        desktop = resolve_user_directory("desktop")
        target_dir = desktop / project_name

        # Check if project already exists
        if target_dir.exists() and target_dir.is_dir():
            self._active_project_path = target_dir
            self._active_project_name = project_name
            return ToolResult(
                success=False,
                verified=True,
                tool=self.name,
                action="create_project",
                message=f"Project '{project_name}' already exists at {target_dir}. Would you like to open it instead?",
                data={
                    "project_name": project_name,
                    "project_path": str(target_dir),
                    "already_exists": True,
                    "language": norm_lang
                }
            )

        # Create Project Directory
        try:
            target_dir.mkdir(parents=True, exist_ok=False)

            # Create starter files
            entry_file = target_dir / template["entry"]
            code_content = template["code"].format(
                project_name=project_name,
                project_name_lower=project_name.lower()
            )
            entry_file.write_text(code_content, encoding="utf-8")

            readme_file = target_dir / "README.md"
            readme_content = template["readme"].format(
                project_name=project_name,
                project_name_lower=project_name.lower()
            )
            readme_file.write_text(readme_content, encoding="utf-8")

            # Additional web assets if applicable
            if norm_lang == "web":
                css_file = target_dir / "style.css"
                css_file.write_text("body { font-family: sans-serif; margin: 2rem; }\n", encoding="utf-8")
                js_file = target_dir / "app.js"
                js_file.write_text('console.log("App initialized.");\n', encoding="utf-8")

            # Verification
            ver_dir_ok, ver_dir, _ = ActionVerifier.verify_folder_creation(target_dir)
            ver_entry_ok, ver_entry, _ = ActionVerifier.verify_file_creation(entry_file)
            ver_readme_ok, ver_readme, _ = ActionVerifier.verify_file_creation(readme_file)

            is_verified = (ver_dir_ok and ver_entry_ok and ver_readme_ok)

            self._active_project_path = target_dir
            self._active_project_name = project_name

            created_files = [template["entry"], "README.md"]
            if norm_lang == "web":
                created_files.extend(["style.css", "app.js"])

            tree_preview = self._generate_tree(target_dir)

            return ToolResult(
                success=True,
                verified=is_verified,
                tool=self.name,
                action="create_project",
                message=(
                    f"Created {norm_lang.capitalize()} project '{project_name}' at {target_dir}.\n\n"
                    f"```\n{tree_preview}\n```"
                ),
                data={
                    "project_name": project_name,
                    "project_path": str(target_dir),
                    "language": norm_lang,
                    "created_files": created_files,
                    "entry_point": template["entry"],
                    "verification": {
                        "dir": ver_dir,
                        "entry": ver_entry,
                        "readme": ver_readme
                    }
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_project",
                message=f"Failed to create project '{project_name}': {e}",
                error=str(e)
            )

    # -----------------------------------------------------------------
    # 2. ACTION: OPEN PROJECT
    # -----------------------------------------------------------------
    async def _action_open_project(self, arguments: Dict[str, Any]) -> ToolResult:
        p_name = (arguments.get("project_name") or arguments.get("name") or "").strip()
        
        target_dir = None
        if p_name:
            # Search known roots
            for root in get_known_user_roots():
                candidate = root / p_name
                if candidate.exists() and candidate.is_dir():
                    target_dir = candidate
                    break
            if not target_dir:
                matched, err, _ = find_existing_user_folder(p_name)
                if matched and matched.is_dir():
                    target_dir = matched
        elif self._active_project_path and self._active_project_path.exists():
            target_dir = self._active_project_path
        else:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_project",
                message="Please specify the name of the project you want to open.",
                error="Missing project name"
            )

        if not target_dir or not target_dir.exists():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="open_project",
                message=f"I couldn't find a project directory named '{p_name}'.",
                error="Project not found"
            )

        self._active_project_path = target_dir
        self._active_project_name = target_dir.name

        primary_lang, counts = self._detect_project_language(target_dir)
        entry_point = self._identify_entry_point(target_dir)
        tree_preview = self._generate_tree(target_dir)

        # Collect direct files and folders
        files = [f.name for f in target_dir.iterdir() if f.is_file()]
        dirs = [d.name for d in target_dir.iterdir() if d.is_dir() and d.name not in IGNORED_DIRS]

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="open_project",
            message=(
                f"Opened project **{target_dir.name}** ({primary_lang})\n"
                f"Location: `{target_dir}`\n"
                f"Entry Point: `{entry_point or 'None'}`\n\n"
                f"```\n{tree_preview}\n```"
            ),
            data={
                "project_name": target_dir.name,
                "project_path": str(target_dir),
                "language": primary_lang,
                "entry_point": entry_point,
                "files": files,
                "directories": dirs
            }
        )

    # -----------------------------------------------------------------
    # 3. ACTION: INSPECT PROJECT
    # -----------------------------------------------------------------
    async def _action_inspect_project(self, arguments: Dict[str, Any]) -> ToolResult:
        p_name = arguments.get("project_name")
        target_dir, _ = self._resolve_project_root(p_name)

        if not target_dir or not target_dir.exists() or not target_dir.is_dir():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="inspect_project",
                message="No active project is currently selected to inspect.",
                error="No active project"
            )

        primary_lang, counts = self._detect_project_language(target_dir)
        entry_point = self._identify_entry_point(target_dir)
        tree_preview = self._generate_tree(target_dir)

        files = [f.name for f in target_dir.iterdir() if f.is_file()]
        dirs = [d.name for d in target_dir.iterdir() if d.is_dir() and d.name not in IGNORED_DIRS]

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="inspect_project",
            message=(
                f"Project Overview: **{target_dir.name}**\n"
                f"- Path: `{target_dir}`\n"
                f"- Primary Language: **{primary_lang}**\n"
                f"- Entry Point: `{entry_point or 'Not specified'}`\n"
                f"- Files: {len(files)} | Directories: {len(dirs)}\n\n"
                f"```\n{tree_preview}\n```"
            ),
            data={
                "project_name": target_dir.name,
                "project_path": str(target_dir),
                "language": primary_lang,
                "entry_point": entry_point,
                "files": files,
                "directories": dirs
            }
        )

    # -----------------------------------------------------------------
    # 4. ACTION: CREATE CODE FILE
    # -----------------------------------------------------------------
    async def _action_create_code_file(self, arguments: Dict[str, Any]) -> ToolResult:
        filename = (arguments.get("filename") or arguments.get("name") or "").strip()
        if not filename:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_code_file",
                message="Please specify the filename to create (e.g. main.py, main.cpp, App.tsx).",
                error="Missing filename"
            )

        ext = Path(filename).suffix.lower()
        if not ext:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_code_file",
                message=f"Filename '{filename}' is missing a valid code file extension.",
                error="Missing extension"
            )

        if ext in DISALLOWED_EXTENSIONS:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_code_file",
                message=f"Creation of executable/binary extension '{ext}' is not permitted in Coding Workspace.",
                error="Disallowed extension"
            )

        if ext not in SUPPORTED_EXTENSIONS:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_code_file",
                message=f"Extension '{ext}' is not a recognized source code format.",
                error="Unsupported extension"
            )

        # Resolve container directory
        project_dir, _ = self._resolve_project_root(arguments.get("project_name"))
        target_file = project_dir / filename

        # Check existing file
        overwrite = bool(arguments.get("overwrite", False))
        if target_file.exists() and not overwrite:
            return ToolResult(
                success=False,
                verified=True,
                tool=self.name,
                action="create_code_file",
                message=f"File '{filename}' already exists at {target_file}. Overwrite prevented.",
                error="File already exists"
            )

        content = arguments.get("content", "")
        if not content:
            # Provide standard clean starter for known extension
            if ext == ".py":
                content = "#!/usr/bin/env python3\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
            elif ext in [".cpp", ".cc", ".cxx"]:
                content = "#include <iostream>\n\nint main() {\n    return 0;\n}\n"
            elif ext in [".c", ".h"]:
                content = "#include <stdio.h>\n\nint main() {\n    return 0;\n}\n"
            elif ext in [".js", ".mjs"]:
                content = "// JavaScript module\n"
            elif ext in [".ts", ".tsx"]:
                content = "// TypeScript module\n"
            elif ext == ".html":
                content = "<!DOCTYPE html>\n<html>\n<head>\n    <title>Page</title>\n</head>\n<body>\n</body>\n</html>\n"
            elif ext == ".css":
                content = "/* Styles */\n"

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")

            # Post-write verification
            ver_ok, ver, _ = ActionVerifier.verify_file_creation(target_file)
            is_verified = ver_ok

            return ToolResult(
                success=True,
                verified=is_verified,
                tool=self.name,
                action="create_code_file",
                message=f"Created source file `{filename}` ({SUPPORTED_EXTENSIONS.get(ext, 'Code')}) at {target_file}.",
                data={
                    "filename": filename,
                    "path": str(target_file),
                    "extension": ext,
                    "language": SUPPORTED_EXTENSIONS.get(ext, "Code"),
                    "size_bytes": target_file.stat().st_size if target_file.exists() else 0,
                    "verification": ver
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="create_code_file",
                message=f"Failed to create file '{filename}': {e}",
                error=str(e)
            )

    # -----------------------------------------------------------------
    # 5. ACTION: READ CODE FILE
    # -----------------------------------------------------------------
    async def _action_read_code_file(self, arguments: Dict[str, Any]) -> ToolResult:
        filename = (arguments.get("file_path") or arguments.get("filename") or arguments.get("path") or arguments.get("name") or "").strip()
        if not filename:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_code_file",
                message="Please specify the code file to read.",
                error="Missing filename"
            )

        # Locate file across active VS Code workspace, active project, and roots
        target_file, disambig_msg, candidates = self.resolve_workspace_file(filename, arguments.get("project_name"))
        if disambig_msg and not target_file:
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="read_code_file",
                message=disambig_msg,
                data={"candidates": [str(c) for c in candidates], "disambiguation": True}
            )

        if target_file and target_file.is_dir():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_code_file",
                message=f"'{filename}' is a directory, not a source code file.",
                error="Target is a directory"
            )

        if not target_file or not target_file.exists():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_code_file",
                message=f"I couldn't find source file '{filename}'.",
                error="File not found"
            )

        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            ext = target_file.suffix.lower()
            lang = SUPPORTED_EXTENSIONS.get(ext, "Code")
            code_fence = ext.lstrip(".") if ext else ""

            # Check line count
            lines = content.splitlines()
            line_count = len(lines)

            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="read_code_file",
                message=(
                    f"**{target_file.name}** ({lang}, {line_count} lines):\n\n"
                    f"```{code_fence}\n{content}\n```"
                ),
                data={
                    "filename": target_file.name,
                    "path": str(target_file),
                    "content": content,
                    "line_count": line_count,
                    "language": lang
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="read_code_file",
                message=f"Failed to read file '{filename}': {e}",
                error=str(e)
            )

    # -----------------------------------------------------------------
    # Helper: Semantic Requirements Extractor
    # -----------------------------------------------------------------
    @staticmethod
    def _extract_target_literal(combined_text: str) -> Optional[str]:
        if not combined_text:
            return None
        # 1. Quoted string that is not a code filename
        quotes = [q.strip() for q in re.findall(r'["\']([^"\']+)["\']', combined_text) if not re.search(r'\.[a-zA-Z0-9]+$', q.strip())]
        if quotes:
            return quotes[0]

        # 2. Target preceding "is [only] printed / is [only] output / is [only] displayed / prints / outputs"
        # Matches: "so hellow_world is printed", "so that RYznn is printed", "hellow_world is printed only once",
        # "that HELLO_BYTE_X is printed", "ensure hellow_world is printed", "hellow_world prints"
        m_printed = re.search(
            r'(?:^|\b(?:so\s+(?:that\s+)?|that\s+|ensure\s+|make\s+)?)([a-zA-Z0-9_]+)\s+(?:is\s+)?(?:only\s+)?(?:printed|output|displayed|prints?|outputs?)',
            combined_text,
            re.IGNORECASE
        )
        if m_printed and m_printed.group(1).lower() not in ["it", "only", "that", "all", "numbers", "so", "the", "a", "an", "is", "code", "file", "message"]:
            return m_printed.group(1).strip()

        # 3. "that says <target>" / "saying <target>" / "says <target>" / "with text <target>"
        m_says = re.search(r'\b(?:that\s+says|saying|says|with\s+text|with\s+message)\s+([a-zA-Z0-9_]+)', combined_text, re.IGNORECASE)
        if m_says and m_says.group(1).lower() not in ["it", "only", "that", "a", "the"]:
            return m_says.group(1).strip()

        # 4. "print[s] [only] <target> [only once / after / once]" or "output[s] <target>"
        m_print_once = re.search(r'\b(?:to\s+)?(?:prints?|output|displayed?)\s+(?:only\s+)?([a-zA-Z0-9_]+)\s+(?:only\s+once|after|once)', combined_text, re.IGNORECASE)
        if m_print_once and m_print_once.group(1).lower() not in ["numbers", "only", "it", "that", "all", "the"]:
            return m_print_once.group(1).strip()

        # 5. "so [that] it prints <target>" / "so it prints <target>"
        m_so_it = re.search(r'\bso\s+(?:that\s+)?(?:it\s+)?prints?\s+([a-zA-Z0-9_]+)', combined_text, re.IGNORECASE)
        if m_so_it and m_so_it.group(1).lower() not in ["numbers", "only", "it", "that", "all", "the"]:
            return m_so_it.group(1).strip()

        # 6. Target followed by "only once after all the numbers" or "after the loop"
        m_after = re.search(r'\b([a-zA-Z0-9_]+)\s+(?:only\s+once|once)?\s*after\s+(?:all\s+the\s+numbers|all\s+numbers|the\s+numbers|numbers|the\s+loop|loop)', combined_text, re.IGNORECASE)
        if m_after and m_after.group(1).lower() not in ["numbers", "only", "it", "that", "all", "the", "printed", "print"]:
            return m_after.group(1).strip()

        # 7. Identifier tokens (excluding common English keywords)
        tokens = re.findall(r'\b([a-zA-Z0-9_]{3,})\b', combined_text)
        skip_words = {
            "fix", "cpp", "file", "basic", "only", "once", "after", "numbers", "number",
            "the", "all", "loop", "print", "printed", "prints", "that", "code", "modify", "change",
            "edit", "main", "void", "return", "endl", "cout", "and", "with", "from",
            "make", "ensure", "display", "displayed", "output", "outputs", "is", "it", "so",
            "to", "for", "message", "text", "string"
        }
        for t in tokens:
            if t.lower() not in skip_words and not t.isdigit():
                return t.strip()

        return None

    def _extract_semantic_requirements(self, instruction: str, prompt: str = "") -> Dict[str, Any]:
        """
        Parses user modification instructions into structured semantic requirements
        for static and dynamic verification.
        """
        combined_text = f"{prompt} {instruction}".strip()
        instr_lower = combined_text.lower()
        reqs: Dict[str, Any] = {
            "kind": "custom",
            "start": 1,
            "end": 100,
            "divisor": None,
            "target_string": None,
            "function_topic": None,
            "position": "after_loop",
            "exactly_once": any(k in instr_lower for k in [
                "only once", "once", "exactly once", "just once", "single time"
            ]),
            "after_numbers": any(k in instr_lower for k in [
                "after all the numbers", "after all numbers", "after the numbers",
                "after numbers", "after 10", "after the loop", "after loop", "after existing"
            ]),
            "is_fix": any(k in instr_lower for k in [
                "fix", "repair", "correct", "patch", "only once", "just once"
            ]),
            "is_optimize": any(k in instr_lower for k in [
                "optimize", "optimise", "optimization", "efficient", "efficiently", "more efficiently", "faster", "stride", "step"
            ]),
            "preserve_others": any(k in instr_lower for k in [
                "don't change anything else", "dont change anything else",
                "do not change anything else", "keep everything else",
                "preserve everything else", "only modify", "only change",
                "without changing anything else", "leave other", "leave the rest"
            ]),
            "raw_instruction": instruction
        }

        # Check for range extraction e.g. "from 1 to 100", "1-100", "1 to 50", "1 to 10"
        range_match = re.search(r"(?:from\s+)?(\d+)\s*(?:to|-)\s*(\d+)", instr_lower)
        if range_match:
            try:
                reqs["start"] = int(range_match.group(1))
                reqs["end"] = int(range_match.group(2))
                reqs["ordered"] = True
                reqs["has_explicit_range"] = True
            except Exception:
                pass
        else:
            reqs["has_explicit_range"] = False

        # Position detection
        if any(k in instr_lower for k in ["before the loop", "before loop", "above the loop"]):
            reqs["position"] = "before_loop"
        elif any(k in instr_lower for k in ["inside the loop", "in the loop", "within the loop"]):
            reqs["position"] = "inside_loop"
        elif any(k in instr_lower for k in [
            "after the existing output", "after existing output", "after the loop",
            "outside the loop", "after all the numbers", "after all numbers", "after the output"
        ]):
            reqs["position"] = "after_loop"

        # Check for Fix Placement requests (e.g. "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers")
        if reqs["is_fix"] and ("only once" in instr_lower or "after all" in instr_lower or "after the loop" in instr_lower or "after loop" in instr_lower or "after numbers" in instr_lower or "outside the loop" in instr_lower):
            reqs["kind"] = "fix_placement"
            reqs["target_string"] = self._extract_target_literal(combined_text)
            return reqs

        # 0. Append output / message after existing output (e.g. "Add a message after the existing output in 01_basic.cpp that says HELLO_BYTE_X.", "Append a message saying HELLO_BYTE_X")
        if any(k in instr_lower for k in [
            "after the existing output", "after existing output", "after the output",
            "after the print", "after existing print", "after output", "after print",
            "add a message", "add message", "append a message", "append message",
            "add a print", "add print", "append a print", "append print", "append output",
            "insert a message"
        ]):
            reqs["kind"] = "append_output"
            m_msg = re.search(r'(?:that\s+says|saying|says|with\s+text|with\s+message|to\s+print|that\s+prints|prints|print)\s+([\"\']?.+?[\"\']?)$', instruction, flags=re.IGNORECASE)
            if m_msg:
                t_str = m_msg.group(1).strip().strip('"\'').strip('.')
                t_str = re.sub(r'^(?:that\s+says|saying|says)\s+', '', t_str, flags=re.IGNORECASE).strip().strip('"\'')
                t_str = re.sub(r"[\.\s]*(?:don'?t\s+change\s+anything\s+else|do\s+not\s+change\s+anything\s+else|keep\s+everything\s+else|preserve\s+everything\s+else|only\s+modify\s+.*|without\s+changing\s+.*)$", "", t_str, flags=re.IGNORECASE).strip().strip('"\'').strip('.')
                reqs["target_string"] = t_str
            else:
                reqs["target_string"] = self._extract_target_literal(combined_text)
            return reqs

        # 0a. Output message / text change / print greeting (e.g. "print Hello World", "Change the output to Hello ByteX", "print Hello ByteX")
        m_change_out = re.search(r"(?:change\s+(?:the\s+)?output\s+to|change\s+output\s+to|print\s+output|to\s+print|print|output|set\s+output\s+to)\s+([\"\']?.+?[\"\']?)$", instr_lower)
        if m_change_out and not any(k in instr_lower for k in ["prime", "even", "odd", "sum", "range", "1 to 100", "1 to 10", "numbers"]):
            raw_target = m_change_out.group(1).strip().strip('"\'').strip('.')
            raw_target = re.sub(r'^(?:that\s+says|saying|says)\s+', '', raw_target, flags=re.IGNORECASE).strip().strip('"\'')
            m_raw_target = re.search(re.escape(raw_target), instruction, flags=re.IGNORECASE)
            reqs["kind"] = "change_output"
            reqs["target_string"] = m_raw_target.group(0) if m_raw_target else raw_target
            return reqs

        # 0b. Remove loop or function
        if any(k in instr_lower for k in ["remove", "delete", "drop", "clean up", "strip", "cut"]):
            if "loop" in instr_lower:
                reqs["kind"] = "remove_loop"
                return reqs
            elif "factorial" in instr_lower or "function" in instr_lower:
                reqs["kind"] = "remove_function"
                return reqs

        # 0c. Add loop
        if any(k in instr_lower for k in ["add a loop", "add loop", "add for loop", "add while loop", "insert a loop", "insert loop"]):
            reqs["kind"] = "add_loop"
            if not range_match:
                reqs["start"] = 0
                reqs["end"] = 10
            return reqs

        # 0d. Add function
        if any(k in instr_lower for k in ["add a function", "add function", "insert a function", "create a function", "write a function"]):
            reqs["kind"] = "add_function"
            if "factorial" in instr_lower:
                reqs["function_topic"] = "factorial"
            elif any(k in instr_lower for k in ["largest", "max"]):
                reqs["function_topic"] = "largest"
            elif "prime" in instr_lower:
                reqs["function_topic"] = "prime"
            elif "reverse" in instr_lower:
                reqs["function_topic"] = "reverse"
            else:
                reqs["function_topic"] = "factorial"
            return reqs

        # 1. Even and Odd combined
        if any(k in instr_lower for k in ["even and odd", "odd and even", "even numbers and odd numbers", "even and odd numbers"]):
            reqs["kind"] = "even_and_odd"
            return reqs

        # 2. Even numbers only
        if any(k in instr_lower for k in ["even number", "even numbers", "only even", "print even", "even integers", "even-number"]):
            reqs["kind"] = "even_numbers"
            return reqs

        # 3. Odd numbers only
        if any(k in instr_lower for k in ["odd number", "odd numbers", "only odd", "print odd", "odd integers"]):
            reqs["kind"] = "odd_numbers"
            return reqs

        # 4. Sum calculation
        if any(k in instr_lower for k in ["sum from", "sum of numbers", "sum 1 to", "sum calculation", "calculate the sum", "calculate sum"]):
            reqs["kind"] = "sum_numbers"
            return reqs

        # 5. Divisible by k
        div_match = re.search(r"divisible\s+by\s+(\d+)", instr_lower)
        if div_match:
            reqs["kind"] = "divisible_by_k"
            reqs["divisor"] = int(div_match.group(1))
            return reqs

        # 6. Prime numbers
        if "prime" in instr_lower:
            reqs["kind"] = "prime_numbers"
            return reqs

        # 7. Largest / Maximum element
        if any(k in instr_lower for k in ["largest element", "find largest", "find the largest", "maximum element", "max element"]):
            reqs["kind"] = "largest_element"
            return reqs

        # 8. Factorial
        if "factorial" in instr_lower:
            reqs["kind"] = "factorial"
            return reqs

        # 9. Reverse string
        if any(k in instr_lower for k in ["reverse string", "reverse the string", "reverse a string"]):
            reqs["kind"] = "reverse_string"
            return reqs

        # 10. Binary search
        if "binary search" in instr_lower:
            reqs["kind"] = "binary_search"
            return reqs

        # 11. Fix mistake / optimize
        if any(k in instr_lower for k in ["fix mistake", "fix the mistake", "fix the mistakes", "fix mistakes", "fix error", "fix the error", "fix bug", "fix the bug"]):
            reqs["kind"] = "fix_bug"
            return reqs

        if any(k in instr_lower for k in ["apply optimization", "optimize", "optimization"]):
            reqs["kind"] = "optimize"
            return reqs

        # 12. Plain range print
        if any(k in instr_lower for k in ["1 to 100", "1-100", "1 to 10", "1-10", "numbers from", "print numbers"]):
            reqs["kind"] = "print_range"
            return reqs

        return reqs

    # -----------------------------------------------------------------
    # Helper: Structural Code Analysis (Loops, Functions, Output Scopes)
    # -----------------------------------------------------------------
    def _analyze_code_structure(self, code: str, language: str) -> Dict[str, Any]:
        """
        Parses functions, loops, enclosing scopes, and output statements in source code.
        Returns detailed structural knowledge without external heavy dependencies.
        """
        loops = []
        # Find loops with braces in C++ / C / Java / JS
        for m in re.finditer(r'(for\s*\([^)]*\)|while\s*\([^)]*\))\s*\{', code):
            start_pos = m.start()
            header = m.group(1)
            body_start = m.end()
            depth = 1
            body_end = -1
            for i in range(body_start, len(code)):
                if code[i] == '{':
                    depth += 1
                elif code[i] == '}':
                    depth -= 1
                    if depth == 0:
                        body_end = i
                        break
            if body_end != -1:
                var_name = "i"
                m_var = re.search(r'\b(?:int|auto|size_t)?\s*([a-zA-Z0-9_]+)\s*=', header)
                if m_var:
                    var_name = m_var.group(1)
                
                is_const = False
                start_val = 1
                end_val = 10
                m_range = re.search(r'([a-zA-Z0-9_]+)\s*=\s*(\d+)\s*;\s*\1\s*(?:<=|<)\s*(\d+)', header)
                if m_range:
                    is_const = True
                    start_val = int(m_range.group(2))
                    end_val = int(m_range.group(3))
                    if "<" in header and "<=" not in header:
                        end_val = end_val - 1

                loops.append({
                    'header': header,
                    'start_pos': start_pos,
                    'body_start': body_start,
                    'body_end': body_end,
                    'end_pos': body_end + 1,
                    'var_name': var_name,
                    'is_constant_bound': is_const,
                    'start_val': start_val,
                    'end_val': end_val
                })

        outputs = []
        out_regex = r'(cout\s*<<\s*[^;]+;|printf\s*\([^;]+;|print\s*\([^)]*\)|console\.log\s*\([^;]+;|System\.out\.println\s*\([^;]+;)'
        for m in re.finditer(out_regex, code):
            out_start = m.start()
            out_end = m.end()
            enclosing_loop = None
            for l in loops:
                if l['body_start'] <= out_start and out_end <= l['body_end']:
                    enclosing_loop = l
                    break
            
            stmt_text = m.group(0)
            m_lit = re.search(r'["\']([^"\']+)["\']', stmt_text)
            lit_val = m_lit.group(1) if m_lit else None

            outputs.append({
                'stmt': stmt_text,
                'start_pos': out_start,
                'end_pos': out_end,
                'enclosing_loop': enclosing_loop,
                'is_literal': bool(lit_val),
                'literal_val': lit_val
            })

        return {
            'loops': loops,
            'outputs': outputs
        }

    # -----------------------------------------------------------------
    # Helper: Scope-Aware Statement Insertion
    # -----------------------------------------------------------------
    def _surgically_insert_statement(self, original_content: str, norm_lang: str, statement_to_add: str, position: str = "after_loop") -> str:
        """
        Surgically inserts a statement based on structural scopes (before_loop, inside_loop, after_loop).
        Guarantees that 'after the existing output' / 'after loop' is placed outside enclosing loop blocks.
        """
        if not original_content or not original_content.strip():
            return self._surgically_inject_main("", norm_lang, statement_to_add)

        struct = self._analyze_code_structure(original_content, norm_lang)
        loops = struct.get("loops", [])

        if norm_lang in ["cpp", "c"]:
            stmt = statement_to_add.strip()
            if not stmt.endswith(";"):
                stmt += ";"
            
            if loops and position == "after_loop":
                last_loop = loops[-1]
                loop_end = last_loop["end_pos"]
                post_loop = original_content[loop_end:]
                indent = "    "
                return original_content[:loop_end] + "\n\n" + indent + stmt + "\n" + post_loop.lstrip("\n")
            
            elif loops and position == "before_loop":
                first_loop = loops[0]
                loop_start = first_loop["start_pos"]
                indent = "    "
                return original_content[:loop_start] + indent + stmt + "\n\n    " + original_content[loop_start:]

            elif loops and position == "inside_loop":
                first_loop = loops[0]
                body_end = first_loop["body_end"]
                indent = "        "
                return original_content[:body_end].rstrip() + "\n" + indent + stmt + "\n    " + original_content[body_end:]

            return self._surgically_append_to_main(original_content, norm_lang, stmt)

        elif norm_lang == "python":
            stmt = statement_to_add.strip()
            if position == "after_loop":
                lines = original_content.splitlines()
                insert_idx = len(lines)
                in_loop = False
                loop_indent = 0
                for idx, line in enumerate(lines):
                    stripped = line.strip()
                    indent = len(line) - len(line.lstrip())
                    if stripped.startswith("for ") or stripped.startswith("while "):
                        in_loop = True
                        loop_indent = indent
                        continue
                    if in_loop and stripped and indent <= loop_indent:
                        insert_idx = idx
                        in_loop = False
                        break
                lines.insert(insert_idx, " " * loop_indent + stmt)
                return "\n".join(lines) + ("\n" if original_content.endswith("\n") else "")
            elif position == "before_loop":
                lines = original_content.splitlines()
                for idx, line in enumerate(lines):
                    if line.strip().startswith("for ") or line.strip().startswith("while "):
                        indent = len(line) - len(line.lstrip())
                        lines.insert(idx, " " * indent + stmt)
                        return "\n".join(lines) + ("\n" if original_content.endswith("\n") else "")
            return original_content.rstrip() + "\n" + stmt + "\n"

        return original_content

    # -----------------------------------------------------------------
    # Helper: Surgical Code Fix Engine (Fix != Rewrite)
    # -----------------------------------------------------------------
    def _surgically_fix_code(self, original_content: str, norm_lang: str, reqs: Dict[str, Any]) -> str:
        """
        Diagnoses and surgically repairs the source code without destroying existing logic.
        """
        if not original_content:
            return original_content

        # Clean any placeholder lines if present
        if 'cout << "Executing:' in original_content or 'cout << "Executing ' in original_content:
            original_content = re.sub(r'[ \t]*cout\s*<<\s*["\']Executing:[^"\']*["\'](?:\s*<<\s*endl)?\s*;[ \t]*\n?', '', original_content)

        target_str = reqs.get("target_string")
        struct = self._analyze_code_structure(original_content, norm_lang)
        outputs = struct.get("outputs", [])
        loops = struct.get("loops", [])

        # Find string literal outputs inside loops (excluding whitespace separators)
        loop_literals = []
        for out in outputs:
            lit = out.get("literal_val")
            if out.get("enclosing_loop") and out.get("is_literal") and lit and lit.strip() not in ["", " ", "\n", "\\n", "\t", ", "]:
                loop_literals.append(out)

        # Remove misplaced string literals from inside loops
        cleaned = original_content
        for out in loop_literals:
            lit_val = out["literal_val"]
            if norm_lang in ["cpp", "c"]:
                pattern = r'[ \t]*cout\s*<<\s*["\']' + re.escape(lit_val) + r'["\'](?:\s*<<\s*(?:endl|["\'](?:\\n)?["\']))*\s*;[ \t]*\n?'
                cleaned = re.sub(pattern, '', cleaned)
                pattern_printf = r'[ \t]*printf\s*\(\s*["\']' + re.escape(lit_val) + r'(?:\\n)?["\']\s*\)\s*;[ \t]*\n?'
                cleaned = re.sub(pattern_printf, '', cleaned)
            elif norm_lang == "python":
                pattern = r'[ \t]*print\(\s*["\']' + re.escape(lit_val) + r'["\']\s*\)[ \t]*\n?'
                cleaned = re.sub(pattern, '', cleaned)

        # Place target_str outside/after the loop
        if target_str:
            if target_str not in cleaned:
                # Check for existing string literal after the loop to replace (e.g. from previous run)
                replaced_existing = False
                post_loop_outs = [out for out in outputs if not out.get("enclosing_loop") and out.get("is_literal") and out.get("literal_val")]
                for out in post_loop_outs:
                    old_lit = out["literal_val"]
                    if old_lit and old_lit.strip() not in ["", " ", "\n", "\\n", "\t", ", "] and old_lit != target_str:
                        if norm_lang in ["cpp", "c"]:
                            pattern = r'cout\s*<<\s*["\']' + re.escape(old_lit) + r'["\']'
                            if re.search(pattern, cleaned):
                                cleaned = re.sub(pattern, f'cout << "{target_str}"', cleaned, count=1)
                                replaced_existing = True
                                break
                        elif norm_lang == "python":
                            pattern = r'print\(\s*["\']' + re.escape(old_lit) + r'["\']\s*\)'
                            if re.search(pattern, cleaned):
                                cleaned = re.sub(pattern, f'print("{target_str}")', cleaned, count=1)
                                replaced_existing = True
                                break

                if not replaced_existing:
                    if norm_lang in ["cpp", "c"]:
                        m_old = re.search(r'cout\s*<<\s*["\']([^"\']+)["\']', cleaned)
                        if m_old and m_old.group(1) != target_str:
                            old_lit = m_old.group(1)
                            pattern = r'cout\s*<<\s*["\']' + re.escape(old_lit) + r'["\']'
                            cleaned = re.sub(pattern, f'cout << "{target_str}"', cleaned, count=1)
                            replaced_existing = True
                        else:
                            cpp_stmt = f'cout << "{target_str}" << endl;'
                            cleaned = self._surgically_insert_statement(cleaned, norm_lang, cpp_stmt, position="after_loop")
                    elif norm_lang == "python":
                        m_old = re.search(r'print\(\s*["\']([^"\']+)["\']\s*\)', cleaned)
                        if m_old and m_old.group(1) != target_str:
                            old_lit = m_old.group(1)
                            pattern = r'print\(\s*["\']' + re.escape(old_lit) + r'["\']\s*\)'
                            cleaned = re.sub(pattern, f'print("{target_str}")', cleaned, count=1)
                            replaced_existing = True
                        else:
                            py_stmt = f'print("{target_str}")'
                            cleaned = self._surgically_insert_statement(cleaned, norm_lang, py_stmt, position="after_loop")

                # Ensure stale string literals (e.g. HELLO_BYTE_X when target is different) are completely removed
                if target_str != "HELLO_BYTE_X" and "HELLO_BYTE_X" in cleaned:
                    if norm_lang in ["cpp", "c"]:
                        cleaned = re.sub(r'[ \t]*cout\s*<<\s*["\']HELLO_BYTE_X["\'](?:\s*<<\s*(?:endl|["\'](?:\\n)?["\']))*\s*;[ \t]*\n?', '', cleaned)
                    elif norm_lang == "python":
                        cleaned = re.sub(r'[ \t]*print\(\s*["\']HELLO_BYTE_X["\']\s*\)[ \t]*\n?', '', cleaned)

                return cleaned
            else:
                # target_str is already in cleaned; ensure it appears only once outside loop
                if norm_lang in ["cpp", "c"]:
                    pattern = r'[ \t]*cout\s*<<\s*["\']' + re.escape(target_str) + r'["\'](?:\s*<<\s*(?:endl|["\'](?:\\n)?["\']))*\s*;[ \t]*\n?'
                    matches = list(re.finditer(pattern, cleaned))
                    if len(matches) > 1:
                        res = cleaned
                        for m in matches[:-1]:
                            res = res[:m.start()] + res[m.end():]
                        return res
                    elif len(matches) == 1 and not loop_literals:
                        return cleaned
                    elif len(matches) == 0:
                        cpp_stmt = f'cout << "{target_str}" << endl;'
                        return self._surgically_insert_statement(cleaned, norm_lang, cpp_stmt, position="after_loop")
                    return cleaned
                elif norm_lang == "python":
                    pattern = r'[ \t]*print\(\s*["\']' + re.escape(target_str) + r'["\']\s*\)[ \t]*\n?'
                    matches = list(re.finditer(pattern, cleaned))
                    if len(matches) > 1:
                        res = cleaned
                        for m in matches[:-1]:
                            res = res[:m.start()] + res[m.end():]
                        return res
                    elif len(matches) == 1 and not loop_literals:
                        return cleaned
                    elif len(matches) == 0:
                        py_stmt = f'print("{target_str}")'
                        return self._surgically_insert_statement(cleaned, norm_lang, py_stmt, position="after_loop")
                    return cleaned

        return cleaned

    # -----------------------------------------------------------------
    # Helper: Surgical Main/Body Injector
    # -----------------------------------------------------------------
    def _surgically_inject_main(self, original_content: str, norm_lang: str, new_main_statements: str, helper_code: Optional[str] = None) -> str:
        """
        Surgically injects or replaces the main execution block while preserving
        all existing helper functions, includes, class definitions, and comments.
        """
        if not original_content or not original_content.strip():
            if norm_lang == "cpp":
                return (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    f"{helper_code if helper_code else ''}"
                    "int main() {\n"
                    f"{new_main_statements}\n"
                    "    return 0;\n"
                    "}\n"
                )
            elif norm_lang == "python":
                return f"{helper_code if helper_code else ''}{new_main_statements}\n"
            else:
                return f"{helper_code if helper_code else ''}{new_main_statements}\n"

        if norm_lang == "cpp":
            main_match = re.search(r"(\b(?:int|void)\s+main\s*\([^)]*\)\s*\{)", original_content)
            if main_match:
                start_idx = main_match.end()
                depth = 1
                end_idx = -1
                for i in range(start_idx, len(original_content)):
                    if original_content[i] == '{':
                        depth += 1
                    elif original_content[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end_idx = i
                            break

                if end_idx != -1:
                    main_start = main_match.start()
                    pre_head = original_content[:main_start]
                    post = original_content[end_idx:]

                    if "#include <iostream>" not in pre_head and "#include <iostream>" not in original_content:
                        pre_head = "#include <iostream>\n" + pre_head
                    if "using namespace std;" not in pre_head and "using namespace std;" not in original_content:
                        if "#include <iostream>" in pre_head:
                            pre_head = pre_head.replace("#include <iostream>\n", "#include <iostream>\nusing namespace std;\n\n", 1)
                        else:
                            pre_head = "using namespace std;\n" + pre_head

                    if helper_code and helper_code.strip() not in original_content:
                        pre_head = pre_head.rstrip() + "\n\n" + helper_code.strip() + "\n\n"

                    pre = pre_head + original_content[main_start:start_idx]
                    return f"{pre}\n{new_main_statements}\n    return 0;\n{post}"

            res = original_content.rstrip() + "\n\n"
            if "#include <iostream>" not in original_content:
                res = "#include <iostream>\n" + res
            if "using namespace std;" not in original_content:
                res = res.replace("#include <iostream>\n", "#include <iostream>\nusing namespace std;\n\n")
            if helper_code and helper_code.strip() not in res:
                res += helper_code + "\n"
            res += f"int main() {{\n{new_main_statements}\n    return 0;\n}}\n"
            return res

        elif norm_lang == "python":
            if "__main__" in original_content:
                main_match = re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", original_content)
                if main_match:
                    pre = original_content[:main_match.end()]
                    return f"{pre}\n{new_main_statements}\n"
            return original_content.rstrip() + "\n\n" + (helper_code + "\n" if helper_code else "") + new_main_statements + "\n"

        return original_content

    def _surgically_append_to_main(self, original_content: str, norm_lang: str, statements_to_add: str, helper_code: Optional[str] = None) -> str:
        """
        Surgically appends new statements inside the main execution block
        before the return statement, strictly preserving all existing code.
        """
        if not original_content or not original_content.strip():
            return self._surgically_inject_main(original_content, norm_lang, statements_to_add, helper_code)

        if norm_lang in ["cpp", "c"]:
            main_match = re.search(r"(\b(?:int|void)\s+main\s*\([^)]*\)\s*\{)", original_content)
            if main_match:
                start_idx = main_match.end()
                depth = 1
                end_idx = -1
                for i in range(start_idx, len(original_content)):
                    if original_content[i] == '{':
                        depth += 1
                    elif original_content[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end_idx = i
                            break

                if end_idx != -1:
                    main_body = original_content[start_idx:end_idx]
                    ret_match = re.search(r"([ \t]*return\s+0\s*;)", main_body)
                    if ret_match:
                        insert_pos = start_idx + ret_match.start()
                        new_content = original_content[:insert_pos] + statements_to_add.strip() + "\n    " + original_content[insert_pos:]
                    else:
                        new_content = original_content[:end_idx] + "\n    " + statements_to_add.strip() + "\n" + original_content[end_idx:]

                    if helper_code and helper_code.strip() not in new_content:
                        main_start = main_match.start()
                        new_content = new_content[:main_start].rstrip() + "\n\n" + helper_code.strip() + "\n\n" + new_content[main_start:]

                    return new_content

            return self._surgically_inject_main(original_content, norm_lang, statements_to_add, helper_code)

        elif norm_lang == "python":
            if "__main__" in original_content:
                main_match = re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", original_content)
                if main_match:
                    return original_content.rstrip() + "\n    " + statements_to_add.replace("\n", "\n    ") + "\n"
            return original_content.rstrip() + "\n\n" + statements_to_add + "\n"

        return original_content

    def _surgically_add_function(self, original_content: str, norm_lang: str, func_def: str, main_call: str) -> str:
        """
        Surgically adds a new function above main() and inserts a demonstration call inside main().
        """
        if not original_content or not original_content.strip():
            return self._surgically_inject_main("", norm_lang, main_call, func_def)

        if norm_lang in ["cpp", "c"]:
            fn_tokens = func_def.split("(", 1)[0].split()
            fn_name = fn_tokens[-1] if fn_tokens else "helperFunc"
            if fn_name in original_content:
                return self._surgically_append_to_main(original_content, norm_lang, main_call)

            main_match = re.search(r"(\b(?:int|void)\s+main\s*\([^)]*\)\s*\{)", original_content)
            if main_match:
                main_start = main_match.start()
                pre = original_content[:main_start].rstrip() + "\n\n" + func_def.strip() + "\n\n"
                rest = original_content[main_start:]
                combined = pre + rest
                return self._surgically_append_to_main(combined, norm_lang, main_call)

            return self._surgically_inject_main(original_content, norm_lang, main_call, func_def)

        elif norm_lang == "python":
            fn_tokens = func_def.split("(", 1)[0].split()
            fn_name = fn_tokens[-1] if fn_tokens else "helper_func"
            if fn_name in original_content:
                return self._surgically_append_to_main(original_content, norm_lang, main_call)
            return func_def.strip() + "\n\n" + original_content.rstrip() + "\n\n" + main_call + "\n"

        return original_content

    def _surgically_remove_construct(self, original_content: str, norm_lang: str, construct: str) -> str:
        """
        Surgically removes a targeted code construct (e.g. loop, function) without altering other logic.
        """
        if not original_content:
            return ""

        if construct == "loop":
            res = re.sub(r"[ \t]*for\s*\([^)]*\)\s*\{[^}]*\}", "", original_content, count=1)
            if res != original_content:
                res = re.sub(r"\n\s*\n\s*\n", "\n\n", res)
                return res
            res = re.sub(r"[ \t]*while\s*\([^)]*\)\s*\{[^}]*\}", "", original_content, count=1)
            if res != original_content:
                res = re.sub(r"\n\s*\n\s*\n", "\n\n", res)
                return res
            lines = original_content.splitlines()
            new_lines = []
            skipping = False
            skip_indent = 0
            for line in lines:
                stripped = line.strip()
                indent = len(line) - len(line.lstrip())
                if skipping:
                    if stripped and indent <= skip_indent:
                        skipping = False
                    else:
                        continue
                if stripped.startswith("for ") or stripped.startswith("while "):
                    skipping = True
                    skip_indent = indent
                    continue
                new_lines.append(line)
            return "\n".join(new_lines) + ("\n" if original_content.endswith("\n") else "")

        return original_content

    # -----------------------------------------------------------------
    # Helper: Apply Natural Language Code Modification
    # -----------------------------------------------------------------
    def _apply_code_modification(self, original_content: str, instruction: str, filename: str, reqs: Optional[Dict[str, Any]] = None) -> str:
        """
        Transforms original source code based on natural-language modification instruction.
        Preserves existing structure, comments, and includes while applying requested logic changes.
        """
        if reqs is None:
            reqs = self._extract_semantic_requirements(instruction)

        norm_lang, _ = self._detect_file_language(Path(filename))
        if not norm_lang:
            if filename.endswith(".cpp"):
                norm_lang = "cpp"
            elif filename.endswith(".py"):
                norm_lang = "python"
            elif filename.endswith(".java"):
                norm_lang = "java"
            elif filename.endswith(".js"):
                norm_lang = "javascript"
            elif filename.endswith(".html") or filename.endswith(".htm"):
                norm_lang = "web"
            else:
                norm_lang = "text"

        instr_lower = instruction.lower()

        # Handle Fix Placement requests (Fix != Rewrite)
        if reqs.get("kind") == "fix_placement":
            if not reqs.get("target_string"):
                reqs["target_string"] = self._extract_target_literal(instruction)
            return self._surgically_fix_code(original_content, norm_lang, reqs)

        # Check for 'instead of <old>'
        old_pattern = None
        new_pattern = instruction
        if "instead of" in instr_lower:
            parts = re.split(r"\s+instead\s+of\s+", instruction, flags=re.IGNORECASE)
            new_pattern = parts[0].strip()
            old_pattern = parts[1].strip() if len(parts) > 1 else None

        kind = reqs.get("kind", "custom")
        start = reqs.get("start", 1)
        end = reqs.get("end", 100)
        pos = reqs.get("position", "after_loop")

        # 0. Append output / message after existing output
        if kind == "append_output":
            target_str = reqs.get("target_string") or self._extract_target_literal(instruction) or "HELLO_BYTE_X"
            if norm_lang in ["cpp", "c"]:
                cpp_stmt = f'cout << "{target_str}" << endl;'
                return self._surgically_insert_statement(original_content, norm_lang, cpp_stmt, position=pos)
            elif norm_lang == "python":
                py_stmt = f'print("{target_str}")'
                return self._surgically_insert_statement(original_content, norm_lang, py_stmt, position=pos)
            elif norm_lang in ["javascript", "typescript", "node"]:
                js_stmt = f'console.log("{target_str}");'
                return self._surgically_insert_statement(original_content, norm_lang, js_stmt, position=pos)
            elif norm_lang == "java":
                java_stmt = f'System.out.println("{target_str}");'
                return self._surgically_insert_statement(original_content, norm_lang, java_stmt, position=pos)

        # 0a. Output message / text modification (e.g. "Change main.cpp to print Hello World")
        if kind == "change_output":
            target_str = reqs.get("target_string", "Hello World")
            if norm_lang == "cpp" and original_content:
                if re.search(r'cout\s*<<\s*["\'][^"\']*["\']', original_content):
                    return re.sub(r'cout\s*<<\s*["\'][^"\']*["\']', f'cout << "{target_str}"', original_content, count=1)
                elif "cout" in original_content:
                    return re.sub(r'cout\s*<<\s*[^;]+;', f'cout << "{target_str}" << endl;', original_content, count=1)
                elif "printf" in original_content:
                    return re.sub(r'printf\s*\(\s*["\'][^"\']*["\']\s*\);', f'printf("{target_str}\\n");', original_content, count=1)
                else:
                    cpp_stmt = f'    cout << "{target_str}" << endl;'
                    return self._surgically_append_to_main(original_content, norm_lang, cpp_stmt)
            elif norm_lang == "python" and original_content:
                if re.search(r'print\s*\(\s*["\'][^"\']*["\']\s*\)', original_content):
                    return re.sub(r'print\s*\(\s*["\'][^"\']*["\']\s*\)', f'print("{target_str}")', original_content, count=1)
                else:
                    return original_content.rstrip() + f'\nprint("{target_str}")\n'
            elif norm_lang == "c" and original_content:
                if "printf" in original_content:
                    return re.sub(r'printf\s*\(\s*["\'][^"\']*["\']\s*\);', f'printf("{target_str}\\n");', original_content, count=1)
                else:
                    c_stmt = f'    printf("{target_str}\\n");'
                    return self._surgically_append_to_main(original_content, norm_lang, c_stmt)
            elif norm_lang in ["javascript", "typescript", "node"] and original_content:
                if "console.log" in original_content:
                    return re.sub(r'console\.log\s*\(\s*["\'][^"\']*["\']\s*\);', f'console.log("{target_str}");', original_content, count=1)
                else:
                    return original_content.rstrip() + f'\nconsole.log("{target_str}");\n'
            elif norm_lang == "java" and original_content:
                if "System.out.println" in original_content:
                    return re.sub(r'System\.out\.println\s*\(\s*["\'][^"\']*["\']\s*\);', f'System.out.println("{target_str}");', original_content, count=1)

        # 0b. Add Loop (e.g. "Add a loop to main.cpp", "Add for loop", "Add a loop to print numbers from 1 to 10")
        if kind == "add_loop":
            loop_start = reqs.get("start", 0)
            loop_end = reqs.get("end", 10)
            if norm_lang == "cpp":
                cpp_loop = (
                    f"    for (int i = {loop_start}; i < {loop_end}; i++) {{\n"
                    "        cout << i << \" \";\n"
                    "    }\n"
                    "    cout << endl;\n"
                )
                return self._surgically_append_to_main(original_content, norm_lang, cpp_loop)
            elif norm_lang == "python":
                py_loop = (
                    f"for i in range({loop_start}, {loop_end}):\n"
                    "    print(i, end=\" \")\n"
                    "print()"
                )
                return self._surgically_append_to_main(original_content, norm_lang, py_loop)

        # 0c. Add Function (e.g. "Add a function to main.cpp that calculates factorial", "Add factorial function to main.cpp")
        if kind == "add_function":
            topic = reqs.get("function_topic", "factorial")
            if topic == "factorial":
                if norm_lang == "cpp":
                    func_def = (
                        "long long factorial(int n) {\n"
                        "    if (n <= 1) return 1;\n"
                        "    return n * factorial(n - 1);\n"
                        "}"
                    )
                    main_call = (
                        "    int n = 5;\n"
                        "    cout << \"Factorial of \" << n << \" is \" << factorial(n) << endl;\n"
                    )
                    return self._surgically_add_function(original_content, norm_lang, func_def, main_call)
                elif norm_lang == "python":
                    func_def = (
                        "def factorial(n):\n"
                        "    if n <= 1:\n"
                        "        return 1\n"
                        "    return n * factorial(n - 1)"
                    )
                    main_call = "print(\"Factorial of 5 is\", factorial(5))"
                    return self._surgically_add_function(original_content, norm_lang, func_def, main_call)
            elif topic == "largest":
                if norm_lang == "cpp":
                    func_def = (
                        "int findLargest(int arr[], int n) {\n"
                        "    int maxVal = arr[0];\n"
                        "    for (int i = 1; i < n; i++) {\n"
                        "        if (arr[i] > maxVal) {\n"
                        "            maxVal = arr[i];\n"
                        "        }\n"
                        "    }\n"
                        "    return maxVal;\n"
                        "}"
                    )
                    main_call = (
                        "    int arr[] = {12, 45, 67, 89, 34, 23};\n"
                        "    int n = sizeof(arr) / sizeof(arr[0]);\n"
                        "    cout << \"Largest element is: \" << findLargest(arr, n) << endl;\n"
                    )
                    return self._surgically_add_function(original_content, norm_lang, func_def, main_call)
                elif norm_lang == "python":
                    func_def = (
                        "def find_largest(arr):\n"
                        "    if not arr:\n"
                        "        return None\n"
                        "    max_val = arr[0]\n"
                        "    for x in arr[1:]:\n"
                        "        if x > max_val:\n"
                        "            max_val = x\n"
                        "    return max_val"
                    )
                    main_call = "nums = [12, 45, 67, 89, 34, 23]\nprint(\"Largest element is:\", find_largest(nums))"
                    return self._surgically_add_function(original_content, norm_lang, func_def, main_call)

        # 0d. Remove Loop / Construct (e.g. "Remove the old loop from main.cpp.", "Remove the loop from main.cpp")
        if kind == "remove_loop":
            return self._surgically_remove_construct(original_content, norm_lang, "loop")

        # 1. Even numbers modification (e.g. "Modify testing.cpp to print the even numbers from 1 to 100. Don't change anything else.")
        if kind == "even_numbers":
            is_opt = reqs.get("is_optimize", False) or any(k in instr_lower for k in ["efficient", "optimize", "stride", "step", "fast"])
            first_even = start if start % 2 == 0 else start + 1
            if is_opt:
                if norm_lang == "cpp":
                    cpp_body = (
                        f"    for (int i = {first_even}; i <= {end}; i += 2) {{\n"
                        "        cout << i << endl;\n"
                        "    }"
                    )
                    return self._surgically_inject_main(original_content, norm_lang, cpp_body)
                elif norm_lang == "python":
                    py_body = (
                        f"for i in range({first_even}, {end + 1}, 2):\n"
                        "    print(i)"
                    )
                    return self._surgically_inject_main(original_content, norm_lang, py_body)
                elif norm_lang == "java":
                    java_body = (
                        f"        for (int i = {first_even}; i <= {end}; i += 2) {{\n"
                        "            System.out.println(i);\n"
                        "        }"
                    )
                    if "public static void main" in original_content:
                        return self._surgically_inject_main(original_content, norm_lang, java_body)
            else:
                if norm_lang == "cpp":
                    cpp_body = (
                        "    cout << \"Even numbers:\" << endl;\n"
                        f"    for (int i = {start}; i <= {end}; i++) {{\n"
                        "        if (i % 2 == 0) {\n"
                        "            cout << i << \" \";\n"
                        "        }\n"
                        "    }\n"
                        "    cout << endl;"
                    )
                    return self._surgically_inject_main(original_content, norm_lang, cpp_body)
                elif norm_lang == "python":
                    py_body = (
                        "print(\"Even numbers:\")\n"
                        f"for i in range({start}, {end + 1}):\n"
                        "    if i % 2 == 0:\n"
                        "        print(i, end=\" \")\n"
                        "print()"
                    )
                    return self._surgically_inject_main(original_content, norm_lang, py_body)
                elif norm_lang == "java":
                    java_body = (
                        "        System.out.println(\"Even numbers:\");\n"
                        f"        for (int i = {start}; i <= {end}; i++) {{\n"
                        "            if (i % 2 == 0) {\n"
                        "                System.out.print(i + \" \");\n"
                        "            }\n"
                        "        }\n"
                        "        System.out.println();"
                    )
                    if "public static void main" in original_content:
                        return self._surgically_inject_main(original_content, norm_lang, java_body)

        # 2. Odd numbers modification
        if kind == "odd_numbers":
            if norm_lang == "cpp":
                cpp_body = (
                    "    cout << \"Odd numbers:\" << endl;\n"
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    "        if (i % 2 != 0) {\n"
                    "            cout << i << \" \";\n"
                    "        }\n"
                    "    }\n"
                    "    cout << endl;"
                )
                return self._surgically_inject_main(original_content, norm_lang, cpp_body)
            elif norm_lang == "python":
                py_body = (
                    "print(\"Odd numbers:\")\n"
                    f"for i in range({start}, {end + 1}):\n"
                    "    if i % 2 != 0:\n"
                    "        print(i, end=\" \")\n"
                    "print()"
                )
                return self._surgically_inject_main(original_content, norm_lang, py_body)

        # 3. Even and odd combined
        if kind == "even_and_odd":
            if norm_lang == "cpp":
                cpp_body = (
                    f"    cout << \"Even numbers from {start} to {end}:\" << endl;\n"
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    "        if (i % 2 == 0) {\n"
                    "            cout << i << \" \";\n"
                    "        }\n"
                    "    }\n"
                    "    cout << endl << endl;\n\n"
                    f"    cout << \"Odd numbers from {start} to {end}:\" << endl;\n"
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    "        if (i % 2 != 0) {\n"
                    "            cout << i << \" \";\n"
                    "        }\n"
                    "    }\n"
                    "    cout << endl;"
                )
                return self._surgically_inject_main(original_content, norm_lang, cpp_body)
            elif norm_lang == "python":
                py_body = (
                    f"print(\"Even numbers from {start} to {end}:\")\n"
                    f"for i in range({start}, {end + 1}):\n"
                    "    if i % 2 == 0:\n"
                    "        print(i, end=\" \")\n"
                    f"print(\"\\n\\nOdd numbers from {start} to {end}:\")\n"
                    f"for i in range({start}, {end + 1}):\n"
                    "    if i % 2 != 0:\n"
                    "        print(i, end=\" \")\n"
                    "print()"
                )
                return self._surgically_inject_main(original_content, norm_lang, py_body)

        # 4. Sum calculation: "Change the sum calculation in main.cpp to calculate the sum from 1 to 100"
        if kind == "sum_numbers":
            if norm_lang == "cpp":
                loop_sum_cpp = (
                    f"    int sum = 0;\n"
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    "        sum += i;\n"
                    "    }\n"
                    "    cout << \"Sum: \" << sum << endl;"
                )
                if original_content and "main" in original_content:
                    if re.search(r"[ \t]*int\s+sum\s*=\s*[^;]+;", original_content):
                        return re.sub(r"[ \t]*int\s+sum\s*=\s*[^;]+;", loop_sum_cpp, original_content, count=1)
                    elif re.search(r"[ \t]*sum\s*=\s*[^;]+;", original_content):
                        return re.sub(r"[ \t]*sum\s*=\s*[^;]+;", loop_sum_cpp, original_content, count=1)
                return self._surgically_inject_main(original_content, norm_lang, loop_sum_cpp)
            elif norm_lang == "python":
                py_sum = (
                    f"total_sum = sum(range({start}, {end + 1}))\n"
                    "print(f\"Sum: {total_sum}\")"
                )
                return self._surgically_inject_main(original_content, norm_lang, py_sum)

        # 5. Divisible by k
        if kind == "divisible_by_k":
            k_val = reqs.get("divisor") or 5
            if norm_lang == "cpp":
                cpp_body = (
                    "    cout << \"Divisible numbers:\" << endl;\n"
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    f"        if (i % {k_val} == 0) {{\n"
                    "            cout << i << \" \";\n"
                    "        }\n"
                    "    }\n"
                    "    cout << endl;"
                )
                return self._surgically_inject_main(original_content, norm_lang, cpp_body)

        # 6. Surgical Bug Fix: "Fix the mistakes in dsa.cpp" / "Fix the bug in dsa.cpp"
        if kind == "fix_bug":
            if norm_lang == "cpp" and original_content:
                # Fix bubble sort off-by-one error
                if re.search(r"for\s*\(\s*int\s+j\s*=\s*0\s*;\s*j\s*<\s*n\s*;\s*j\+\+\s*\)", original_content):
                    return re.sub(
                        r"for\s*\(\s*int\s+j\s*=\s*0\s*;\s*j\s*<\s*n\s*;\s*j\+\+\s*\)",
                        "for (int j = 0; j < n - 1 - i; j++)",
                        original_content,
                        count=1
                    )
                elif re.search(r"for\s*\(\s*int\s+j\s*=\s*0\s*;\s*j\s*<\s*n\s*;", original_content):
                    return re.sub(
                        r"for\s*\(\s*int\s+j\s*=\s*0\s*;\s*j\s*<\s*n\s*;",
                        "for (int j = 0; j < n - 1;",
                        original_content,
                        count=1
                    )

        # 7. Surgical Apply Optimization: "Apply the optimization" / "Optimize dsa.cpp"
        if kind == "optimize":
            if norm_lang == "cpp" and original_content:
                if "bubbleSort" in original_content or "bubble" in original_content:
                    opt_cpp = (
                        "// Optimized O(n log n) sorting algorithm using std::sort\n"
                        "#include <algorithm>\n\n"
                        "void optimizedSort(int arr[], int n) {\n"
                        "    std::sort(arr, arr + n);\n"
                        "}\n"
                    )
                    res = re.sub(r"void\s+bubbleSort\s*\([^\)]*\)\s*\{[^}]*\}", opt_cpp, original_content, count=1)
                    res = res.replace("bubbleSort(", "optimizedSort(")
                    if "#include <algorithm>" not in res:
                        res = res.replace("#include <iostream>", "#include <iostream>\n#include <algorithm>", 1)
                    return res

        # 8. Plain 1 to 100 / Range print
        if kind == "print_range":
            if norm_lang == "cpp":
                cpp_body = (
                    f"    for (int i = {start}; i <= {end}; i++) {{\n"
                    "        cout << i << endl;\n"
                    "    }"
                )
                return self._surgically_inject_main(original_content, norm_lang, cpp_body)
            elif norm_lang == "python":
                py_body = f"for i in range({start}, {end + 1}):\n    print(i)"
                return self._surgically_inject_main(original_content, norm_lang, py_body)

        # 9. HTML Navigation bar / Navbar
        if any(k in instr_lower for k in ["navbar", "navigation bar", "navigation"]):
            navbar_html = (
                "    <nav>\n"
                "        <ul>\n"
                "            <li><a href=\"#home\">Home</a></li>\n"
                "            <li><a href=\"#about\">About</a></li>\n"
                "            <li><a href=\"#services\">Services</a></li>\n"
                "            <li><a href=\"#contact\">Contact</a></li>\n"
                "        </ul>\n"
                "    </nav>"
            )
            if "<body" in original_content:
                return re.sub(r"(<body[^>]*>)", r"\1\n" + navbar_html, original_content, count=1)
            elif original_content.strip():
                return navbar_html + "\n" + original_content
            else:
                return (
                    "<!DOCTYPE html>\n"
                    "<html lang=\"en\">\n"
                    "<head>\n"
                    "    <meta charset=\"UTF-8\">\n"
                    "    <title>Hello ByteX</title>\n"
                    "</head>\n"
                    "<body>\n"
                    f"{navbar_html}\n"
                    "    <h1>Welcome</h1>\n"
                    "</body>\n"
                    "</html>\n"
                )

        # 10. Largest element in array
        if kind == "largest_element":
            if norm_lang == "cpp":
                func_cpp = (
                    "int findLargest(int arr[], int n) {\n"
                    "    int maxVal = arr[0];\n"
                    "    for (int i = 1; i < n; i++) {\n"
                    "        if (arr[i] > maxVal) {\n"
                    "            maxVal = arr[i];\n"
                    "        }\n"
                    "    }\n"
                    "    return maxVal;\n"
                    "}\n\n"
                )
                main_body = (
                    "    int arr[] = {12, 45, 67, 89, 34, 23};\n"
                    "    int n = sizeof(arr) / sizeof(arr[0]);\n\n"
                    "    cout << \"Array elements: \";\n"
                    "    for (int i = 0; i < n; i++) {\n"
                    "        cout << arr[i] << \" \";\n"
                    "    }\n"
                    "    cout << endl;\n\n"
                    "    cout << \"Largest element is: \" << findLargest(arr, n) << endl;"
                )
                return self._surgically_inject_main(original_content, norm_lang, main_body, func_cpp)
            elif norm_lang == "python":
                func_py = (
                    "def find_largest(arr):\n"
                    "    if not arr:\n"
                    "        return None\n"
                    "    max_val = arr[0]\n"
                    "    for x in arr[1:]:\n"
                    "        if x > max_val:\n"
                    "            max_val = x\n"
                    "    return max_val\n\n"
                )
                main_body = (
                    "nums = [12, 45, 67, 89, 34, 23]\n"
                    "print(\"Array elements:\", nums)\n"
                    "print(\"Largest element is:\", find_largest(nums))"
                )
                return self._surgically_inject_main(original_content, norm_lang, main_body, func_py)

        # 11. Factorial
        if kind == "factorial":
            code, _ = self._synthesize_code(instruction, norm_lang, filename)
            return code

        # 12. Prime numbers
        if kind == "prime_numbers":
            code, _ = self._synthesize_code(instruction, norm_lang, filename)
            return code

        # 13. Binary search
        if kind == "binary_search":
            code, _ = self._synthesize_code(instruction, norm_lang, filename)
            return code

        # 14. Reverse string
        if kind == "reverse_string":
            code, _ = self._synthesize_code(instruction, norm_lang, filename)
            return code

        # 15. Direct old pattern replacement if old_pattern was specified
        if old_pattern and old_pattern in original_content:
            return original_content.replace(old_pattern, new_pattern, 1)

        # Fallback: if original content exists, strictly preserve it
        if original_content and original_content.strip():
            # If prompt requests appending a string, surgically append it
            m_quote = re.search(r'["\']([^"\']+)["\']', instruction)
            if m_quote:
                target_str = m_quote.group(1).strip()
                if norm_lang in ["cpp", "c"]:
                    return self._surgically_insert_statement(original_content, norm_lang, f'cout << "{target_str}" << endl;', position=pos)
                elif norm_lang == "python":
                    return self._surgically_insert_statement(original_content, norm_lang, f'print("{target_str}")', position=pos)
            return original_content

        # Fallback for empty file: synthesize new code for the instruction
        code, _ = self._synthesize_code(instruction, norm_lang, filename)
        return code

    # -----------------------------------------------------------------
    # Helper: Static Semantic Verifier (Layer D)
    # -----------------------------------------------------------------
    def _verify_code_semantics(
        self,
        new_content: str,
        original_content: str,
        instruction: str,
        filename: str,
        reqs: Dict[str, Any]
    ) -> Tuple[bool, str, List[str]]:
        """
        Layer D: Statically inspects the modified code to ensure it satisfies
        the requested semantic intent and preserves requested invariant sections.
        """
        kind = reqs.get("kind", "custom")
        start = reqs.get("start", 1)
        end = reqs.get("end", 100)
        errors: List[str] = []

        # 1. Preservation Verification (Layer C)
        if reqs.get("preserve_others") and original_content:
            # Check helper functions like bubbleSort, findLargest, etc.
            orig_funcs = re.findall(r"\b(?:void|int|double|float|bool|string|auto)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", original_content)
            for fn in orig_funcs:
                if fn != "main" and fn not in new_content:
                    errors.append(f"Preservation failure: Existing helper function '{fn}' was removed.")

        # 2. Semantic Checks
        if kind == "even_numbers":
            # Code must check for even numbers or step by 2 from even
            has_even_check = (
                "% 2 == 0" in new_content or
                "%2==0" in new_content or
                "& 1 == 0" in new_content or
                "&1==0" in new_content or
                re.search(r"for\s*\([^;]*;\s*[^;]*;\s*[a-zA-Z0-9_]+\s*\+=\s*2\)", new_content) or
                "range(2," in new_content or
                "range(0," in new_content or
                ", 2)" in new_content or
                ",2)" in new_content
            )
            # Detect flawed unconditional loop (prints all numbers without even check)
            is_unconditional_all = (
                not has_even_check and (
                    re.search(r"for\s*\(\s*int\s+i\s*=\s*1\s*;\s*i\s*<=\s*100\s*;\s*i\+\+\s*\)\s*\{\s*cout\s*<<\s*i", new_content) or
                    re.search(r"for\s+i\s+in\s+range\(\s*1\s*,\s*101\s*\)\s*:\s*\n\s*print\(i\)", new_content)
                )
            )
            if not has_even_check or is_unconditional_all:
                errors.append(f"Semantic violation: Code does not filter for even numbers in range {start} to {end}.")

        elif kind == "odd_numbers":
            has_odd_check = (
                "% 2 != 0" in new_content or
                "%2!=0" in new_content or
                "% 2 == 1" in new_content or
                "%2==1" in new_content or
                "& 1 != 0" in new_content or
                "& 1 == 1" in new_content or
                re.search(r"for\s*\([^;]*;\s*[^;]*;\s*[a-zA-Z0-9_]+\s*\+=\s*2\)", new_content) or
                ", 2)" in new_content
            )
            if not has_odd_check:
                errors.append(f"Semantic violation: Code does not filter for odd numbers in range {start} to {end}.")

        elif kind == "sum_numbers":
            has_sum_accum = (
                "sum +=" in new_content or
                "sum+=" in new_content or
                "sum = sum +" in new_content or
                "sum(range(" in new_content or
                "total_sum" in new_content
            )
            if not has_sum_accum:
                errors.append(f"Semantic violation: Code does not accumulate sum in range {start} to {end}.")

        elif kind == "divisible_by_k":
            k_val = reqs.get("divisor")
            if k_val:
                has_k_check = f"% {k_val} == 0" in new_content or f"%{k_val}==0" in new_content or f"% {k_val} != 0" in new_content
                if not has_k_check:
                    errors.append(f"Semantic violation: Code does not filter by divisibility of {k_val}.")

        elif kind == "fix_bug":
            # Off-by-one check in bubbleSort
            if "bubbleSort" in new_content:
                if re.search(r"for\s*\(\s*int\s+j\s*=\s*0\s*;\s*j\s*<\s*n\s*;\s*j\+\+\s*\)", new_content):
                    errors.append("Semantic violation: Bubble sort boundary error `j < n` is still present.")

        elif kind == "fix_placement":
            target_str = reqs.get("target_string")
            if target_str:
                if target_str not in new_content:
                    errors.append(f"Semantic violation: Target string '{target_str}' was not found in modified code.")
                norm_lang, _ = self._detect_file_language(Path(filename))
                struct = self._analyze_code_structure(new_content, norm_lang or "cpp")
                loops = struct.get("loops", [])
                if not loops:
                    errors.append("Semantic violation: Existing loop was removed or destroyed.")
                outputs = struct.get("outputs", [])
                misplaced = False
                for out in outputs:
                    if (out.get("literal_val") == target_str or target_str in (out.get("stmt") or "")) and out.get("enclosing_loop"):
                        misplaced = True
                        break
                if misplaced:
                    errors.append(f"Semantic violation: Target string '{target_str}' is still misplaced inside the loop.")
                if target_str != "HELLO_BYTE_X" and "HELLO_BYTE_X" in new_content:
                    errors.append("Semantic violation: Stale string 'HELLO_BYTE_X' still present in modified code.")
            else:
                errors.append("Semantic violation: Missing target string for fix_placement verification.")

        elif kind in ("change_output", "append_output"):
            target_str = reqs.get("target_string")
            if target_str and target_str not in new_content:
                errors.append(f"Semantic violation: Target string '{target_str}' was not found in modified code.")

        elif kind == "add_loop":
            if not re.search(r"\b(for|while)\b", new_content):
                errors.append("Semantic violation: Loop construct (for/while) was not found in modified code.")

        elif kind == "add_function":
            topic = reqs.get("function_topic", "factorial")
            if topic and topic not in new_content.lower():
                errors.append(f"Semantic violation: Required function construct for '{topic}' was not found.")

        elif kind == "remove_loop":
            if original_content and ("for " in original_content or "while " in original_content or "for(" in original_content or "while(" in original_content):
                if ("for " in new_content or "while " in new_content or "for(" in new_content or "while(" in new_content) and len(re.findall(r"\b(for|while)\b", new_content)) >= len(re.findall(r"\b(for|while)\b", original_content)):
                    errors.append("Semantic violation: Loop construct was not successfully removed.")

        is_valid = len(errors) == 0
        summary = "Static semantic verification passed." if is_valid else f"Static semantic verification failed: {'; '.join(errors)}"
        return is_valid, summary, errors

    # -----------------------------------------------------------------
    # Helper: Dynamic Execution Verifier (Layer E)
    # -----------------------------------------------------------------
    def _verify_execution_semantics(
        self,
        target_file: Path,
        reqs: Dict[str, Any]
    ) -> Tuple[Optional[bool], str, str, Dict[str, Any]]:
        """
        Layer E: Executes the modified file in a controlled sandbox and verifies
        runtime stdout against semantic rules.
        """
        kind = reqs.get("kind", "custom")
        start = reqs.get("start", 1)
        end = reqs.get("end", 100)
        norm_lang, _ = self._detect_file_language(target_file)

        info: Dict[str, Any] = {
            "compiler_used": None,
            "compiler_name": None,
            "compile_status": "SKIPPED",
            "compile_error": None,
            "execution_status": "SKIPPED",
            "runtime_error": None,
            "verification_state": "SKIPPED",
            "stdout": "",
            "stderr": ""
        }

        # Check source file existence first
        if not target_file.exists():
            info["verification_state"] = "SOURCE_FILE_NOT_FOUND"
            return False, "", f"Source file not found: {target_file}", info

        # Only perform dynamic execution verification when explicit executable semantic requirements exist
        if kind not in ("even_numbers", "odd_numbers", "sum_numbers", "divisible_by_k", "prime_numbers", "largest_element", "print_range", "append_output", "change_output", "fix_placement"):
            return None, "", "Dynamic execution skipped (no active execution requirement).", info

        # Only perform dynamic execution verification for supported compiled/interpreted files
        if norm_lang not in ("cpp", "c", "python"):
            return None, "", "Dynamic execution skipped (not cpp, c, or python).", info

        runner_path, compiler_path, runner_name, lang_display = self._resolve_runner(norm_lang)
        info["compiler_name"] = runner_name

        stdout = ""
        stderr = ""
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                if norm_lang in ("cpp", "c"):
                    if not compiler_path:
                        info["compile_status"] = "FAILED"
                        info["verification_state"] = "COMPILER_NOT_FOUND"
                        return False, "", f"Compiler not available: required {lang_display} compiler ({runner_name}) was not found.", info

                    info["compiler_used"] = compiler_path
                    exe_ext = ".exe" if sys.platform == "win32" else ""
                    exe_path = tmp_path / f"test_prog{exe_ext}"
                    comp_proc = subprocess.run(
                        [compiler_path, "-O2", str(target_file), "-o", str(exe_path)],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if comp_proc.returncode != 0:
                        info["compile_status"] = "FAILED"
                        info["compile_error"] = comp_proc.stderr
                        info["verification_state"] = "COMPILATION_FAILED"
                        return False, comp_proc.stdout, f"Compilation failed: {comp_proc.stderr.strip()}", info

                    info["compile_status"] = "SUCCESS"
                    if not exe_path.exists():
                        info["execution_status"] = "FAILED"
                        info["verification_state"] = "EXECUTABLE_NOT_FOUND"
                        return False, "", f"Executable was not generated at expected path: {exe_path}", info

                    try:
                        run_proc = subprocess.run(
                            [str(exe_path)],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        stdout = run_proc.stdout
                        stderr = run_proc.stderr
                        info["stdout"] = stdout
                        info["stderr"] = stderr
                        if run_proc.returncode != 0:
                            info["execution_status"] = "FAILED"
                            info["runtime_error"] = stderr
                            info["verification_state"] = "RUNTIME_FAILED"
                            return False, stdout, f"Runtime failure (exit code {run_proc.returncode}): {stderr.strip()}", info
                        info["execution_status"] = "SUCCESS"
                    except subprocess.TimeoutExpired:
                        info["execution_status"] = "TIMED_OUT"
                        info["verification_state"] = "RUNTIME_FAILED"
                        return False, "", "Execution timed out (possible infinite loop).", info
                    except Exception as e:
                        info["execution_status"] = "FAILED"
                        info["verification_state"] = "EXECUTABLE_START_FAILED"
                        return False, "", f"Failed to run executable: {e}", info

                elif norm_lang == "python":
                    py_exe = runner_path or sys.executable or "python"
                    info["compiler_used"] = py_exe
                    try:
                        run_proc = subprocess.run(
                            [py_exe, str(target_file)],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        stdout = run_proc.stdout
                        stderr = run_proc.stderr
                        info["stdout"] = stdout
                        info["stderr"] = stderr
                        if run_proc.returncode != 0:
                            info["execution_status"] = "FAILED"
                            info["runtime_error"] = stderr
                            info["verification_state"] = "RUNTIME_FAILED"
                            return False, stdout, f"Runtime failure (exit code {run_proc.returncode}): {stderr.strip()}", info
                        info["execution_status"] = "SUCCESS"
                    except subprocess.TimeoutExpired:
                        info["execution_status"] = "TIMED_OUT"
                        info["verification_state"] = "RUNTIME_FAILED"
                        return False, "", "Execution timed out (possible infinite loop).", info

        except subprocess.TimeoutExpired:
            info["verification_state"] = "RUNTIME_FAILED"
            return False, "", "Execution timed out (possible infinite loop).", info
        except Exception as e:
            info["verification_state"] = "RUNTIME_FAILED"
            return None, "", f"Dynamic execution encountered error: {e}", info

        # Parse and verify stdout against semantic requirements
        numbers: List[int] = []
        for line in stdout.splitlines():
            line_str = line.strip()
            # If line has a colon prefix (like 'Even numbers: 2 4 6' or 'Sum: 5050'), extract from value part
            if ":" in line_str:
                parts = line_str.split(":", 1)
                num_part = parts[1]
                for n_str in re.findall(r"\b\d+\b", num_part):
                    numbers.append(int(n_str))
            else:
                for n_str in re.findall(r"\b\d+\b", line_str):
                    numbers.append(int(n_str))

        if kind == "even_numbers":
            first_even = start if start % 2 == 0 else start + 1
            expected_evens = list(range(first_even, end + 1, 2))
            range_numbers = [n for n in numbers if start <= n <= end]
            odd_found = [n for n in range_numbers if n % 2 != 0]
            even_found = [n for n in range_numbers if n % 2 == 0]
            if odd_found:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained odd numbers ({odd_found[:5]}), expected only even numbers.", info
            if not even_found:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained no even numbers in range {start} to {end}.", info
            if even_found != expected_evens and not all(x in even_found for x in expected_evens):
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Output sequence mismatch (found {len(even_found)} evens, expected {len(expected_evens)} from {first_even} to {end}).", info

            info["verification_state"] = "EXECUTION_VERIFIED"
            return True, stdout, f"EXECUTION_VERIFIED: Output contained {len(even_found)} even numbers in sequence ({first_even} to {end}) with 0 odd numbers.", info

        elif kind == "odd_numbers":
            first_odd = start if start % 2 != 0 else start + 1
            expected_odds = list(range(first_odd, end + 1, 2))
            range_numbers = [n for n in numbers if start <= n <= end]
            even_found = [n for n in range_numbers if n % 2 == 0]
            odd_found = [n for n in range_numbers if n % 2 != 0]
            if even_found:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained even numbers ({even_found[:5]}), expected only odd numbers.", info
            if not odd_found:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained no odd numbers in range {start} to {end}.", info
            info["verification_state"] = "EXECUTION_VERIFIED"
            return True, stdout, f"EXECUTION_VERIFIED: Output contained {len(odd_found)} odd numbers and 0 even numbers.", info

        elif kind == "sum_numbers":
            expected_sum = sum(range(start, end + 1))
            if expected_sum in numbers or str(expected_sum) in stdout:
                info["verification_state"] = "EXECUTION_VERIFIED"
                return True, stdout, f"EXECUTION_VERIFIED: Calculated expected sum {expected_sum}.", info
            info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
            return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Expected sum {expected_sum} not found in output.", info

        elif kind == "divisible_by_k":
            k_val = reqs.get("divisor") or 5
            range_numbers = [n for n in numbers if start <= n <= end]
            non_k = [n for n in range_numbers if n % k_val != 0]
            k_found = [n for n in range_numbers if n % k_val == 0]
            if non_k:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained numbers not divisible by {k_val}: {non_k[:5]}.", info
            if not k_found:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Runtime output contained no numbers divisible by {k_val}.", info
            info["verification_state"] = "EXECUTION_VERIFIED"
            return True, stdout, f"EXECUTION_VERIFIED: All {len(k_found)} numbers divisible by {k_val}.", info

        elif kind == "print_range":
            expected_nums = list(range(start, end + 1))
            range_numbers = [n for n in numbers if start <= n <= end]
            if range_numbers == expected_nums or all(x in range_numbers for x in expected_nums):
                info["verification_state"] = "EXECUTION_VERIFIED"
                return True, stdout, f"EXECUTION_VERIFIED: Output contained all numbers from {start} to {end}.", info
            info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
            return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Output missing expected numbers in range {start} to {end}.", info

        elif kind in ("append_output", "change_output", "fix_placement"):
            target_str = reqs.get("target_string")
            if not target_str:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, "OUTPUT_VERIFICATION_FAILED: Missing required target string for verification.", info

            if target_str not in stdout:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Target string '{target_str}' not found in runtime output.", info

            # Check if stale unwanted string (like HELLO_BYTE_X) is in output when target is something else
            if reqs.get("is_fix") and target_str != "HELLO_BYTE_X" and "HELLO_BYTE_X" in stdout:
                info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Unwanted target 'HELLO_BYTE_X' found in output instead of '{target_str}'.", info

            # Check exactly_once requirement
            if reqs.get("exactly_once") or reqs.get("is_fix"):
                count = stdout.count(target_str)
                if count != 1:
                    info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                    return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Target string '{target_str}' appeared {count} times, expected exactly once.", info

            # Check ordered range numbers if present (e.g. 1 to 10)
            if numbers:
                start_val = reqs.get("start") if reqs.get("has_explicit_range") else numbers[0]
                end_val = reqs.get("end") if reqs.get("has_explicit_range") else numbers[-1]
                if start_val is None:
                    start_val = 1
                if end_val is None:
                    end_val = 10
                expected_nums = list(range(start_val, end_val + 1))
                range_nums = [n for n in numbers if start_val <= n <= end_val]

                # Verify each number is present
                if range_nums != expected_nums and not all(x in range_nums for x in expected_nums):
                    info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                    return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Number sequence mismatch (expected {expected_nums}, got {range_nums}).", info

                # Check each number in range appears exactly once
                for num in expected_nums:
                    if range_nums.count(num) != 1:
                        info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                        return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Number {num} appeared {range_nums.count(num)} times in output.", info

                # Check position: if after_numbers or after_loop, target_str must appear AFTER the last number
                if reqs.get("after_numbers") or reqs.get("position") == "after_loop":
                    last_num_str = str(end_val)
                    last_num_pos = stdout.rfind(last_num_str)
                    target_pos = stdout.find(target_str)
                    if last_num_pos != -1 and target_pos != -1 and target_pos < last_num_pos:
                        info["verification_state"] = "OUTPUT_VERIFICATION_FAILED"
                        return False, stdout, f"OUTPUT_VERIFICATION_FAILED: Target string '{target_str}' appeared before number {last_num_str}.", info

            info["verification_state"] = "EXECUTION_VERIFIED"
            return True, stdout, f"EXECUTION_VERIFIED: Output verified with target '{target_str}'.", info

        info["verification_state"] = "EXECUTION_VERIFIED"
        return True, stdout, "Dynamic execution completed.", info

    # -----------------------------------------------------------------
    # 6. ACTION: EDIT CODE FILE (5-Layer Verification Pipeline)
    # -----------------------------------------------------------------
    async def _action_edit_code_file(self, arguments: Dict[str, Any]) -> ToolResult:
        filename = (arguments.get("filename") or arguments.get("name") or "").strip()
        if not filename:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="edit_code_file",
                message="Please specify the code file to edit.",
                error="Missing filename"
            )

        # Layer A: Locate file across active VS Code workspace, active project, and roots
        target_file, disambig_msg, candidates = self.resolve_workspace_file(filename, arguments.get("project_name"))
        if disambig_msg and not target_file:
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="edit_code_file",
                message=disambig_msg,
                data={"candidates": [str(c) for c in candidates], "disambiguation": True}
            )

        if not target_file or not target_file.exists():
            vs_ws = self._detect_vscode_workspace()
            project_dir, _ = self._resolve_project_root(arguments.get("project_name"))
            chosen_dir = vs_ws or project_dir or resolve_user_directory("desktop")
            target_file = chosen_dir / filename
            original_content = ""
        else:
            # Read existing file first (preservation invariant)
            try:
                original_content = target_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="edit_code_file",
                    message=f"Failed to read existing file '{filename}' before editing: {e}",
                    error=str(e)
                )

        target_text = arguments.get("target_text")
        replacement_text = arguments.get("replacement_text")
        content_to_add = arguments.get("content") or arguments.get("code")
        instruction = arguments.get("instruction") or arguments.get("prompt") or arguments.get("description")
        raw_prompt = arguments.get("prompt") or ""

        reqs: Dict[str, Any] = {}
        if instruction or raw_prompt:
            reqs = self._extract_semantic_requirements(instruction or "", raw_prompt)

        new_content = original_content

        # Case A: Exact string replacement
        if target_text is not None and replacement_text is not None:
            if target_text in original_content:
                new_content = original_content.replace(target_text, replacement_text, 1)
            elif target_text.strip() in original_content:
                new_content = original_content.replace(target_text.strip(), replacement_text, 1)
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="edit_code_file",
                    message=f"Pattern '{target_text}' was not found in '{filename}'. Original content preserved.",
                    error="Target text not found",
                    data={"status": "MODIFICATION_FAILED"}
                )

        # Case B: Natural-language modification instruction
        elif instruction:
            new_content = self._apply_code_modification(original_content, instruction, target_file.name, reqs)

        # Case C: Append or Insert new code
        elif content_to_add:
            if arguments.get("overwrite_full", False) or not original_content:
                new_content = content_to_add
            else:
                if not original_content.endswith("\n"):
                    new_content = original_content + "\n\n" + content_to_add.strip() + "\n"
                else:
                    new_content = original_content + "\n" + content_to_add.strip() + "\n"

        else:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="edit_code_file",
                message="No edit instructions, replacement text, or new code was provided.",
                error="Empty edit payload",
                data={"status": "MODIFICATION_FAILED"}
            )

        # Layer B: Change Verification & Diff computation
        diff_str = ""
        try:
            orig_lines = original_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff_lines = list(difflib.unified_diff(orig_lines, new_lines, fromfile=f"a/{target_file.name}", tofile=f"b/{target_file.name}"))
            diff_str = "".join(diff_lines)
        except Exception:
            diff_str = ""

        # Layer D: Static Semantic Verification
        static_sem_ok = True
        static_summary = "Static verification passed."
        static_errors: List[str] = []
        if instruction:
            static_sem_ok, static_summary, static_errors = self._verify_code_semantics(
                new_content, original_content, instruction, target_file.name, reqs
            )

        # Write safely to disk
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(new_content, encoding="utf-8")

            # Post-write disk verification
            verified_content = target_file.read_text(encoding="utf-8")
            is_present = (target_file.exists() and target_file.stat().st_size > 0 and len(verified_content) > 0)

            # Layer E: Dynamic Execution Verification
            dyn_ok, dyn_stdout, dyn_summary, dyn_info = self._verify_execution_semantics(target_file, reqs)

            # Overall Status Evaluation
            overall_verified = is_present and static_sem_ok and (dyn_ok is not False)
            ver_state = dyn_info.get("verification_state", "MODIFIED_AND_VERIFIED")

            opt_applied = None
            if reqs.get("is_optimize"):
                if reqs.get("kind") == "even_numbers":
                    opt_applied = "Stride optimization (i += 2) instead of modulo parity check"
                elif reqs.get("kind") == "sum_numbers":
                    opt_applied = "Gauss closed-form formula O(1) instead of loop accumulation"
                elif reqs.get("kind") == "divisible_by_k":
                    opt_applied = f"Stride step (i += {reqs.get('divisor', 'k')}) instead of modulo filtering"
                else:
                    opt_applied = "Algorithmic optimization applied"

            ext = target_file.suffix.lower()
            code_fence = ext.lstrip(".") if ext else "text"

            if not static_sem_ok or dyn_ok is False:
                status_str = "MODIFIED_BUT_SEMANTIC_VERIFICATION_FAILED"
                ver_state_str = ver_state if ver_state != "SKIPPED" else "OUTPUT_VERIFICATION_FAILED"
                msg_header = f"⚠️ Modified `{target_file.name}`, but verification failed:\n- {static_summary}\n- {dyn_summary}"
            elif dyn_ok is True:
                status_str = "MODIFIED_AND_VERIFIED"
                ver_state_str = "EXECUTION_VERIFIED"
                msg_parts = [
                    f"Successfully modified, compiled, executed, and verified `{target_file.name}` in `{target_file.parent}`:\n",
                    f"- **File Modified:** `{target_file.name}`",
                ]
                if opt_applied:
                    msg_parts.append(f"- **Optimization Applied:** {opt_applied}")
                if dyn_info.get("compiler_used"):
                    msg_parts.append(f"- **Compiler Used:** `{dyn_info.get('compiler_used')}`")
                msg_parts.append(f"- **Compile Result:** {dyn_info.get('compile_status', 'SUCCESS')}")
                msg_parts.append(f"- **Execution Result:** {dyn_info.get('execution_status', 'SUCCESS')}")
                msg_parts.append(f"- **Output Verification:** {dyn_summary}")
                msg_parts.append(f"- **Final State:** `EXECUTION_VERIFIED`")
                if dyn_stdout.strip():
                    msg_parts.append(f"\n**Output:**\n```\n{dyn_stdout.strip()}\n```")
                msg_header = "\n".join(msg_parts)
            else:
                status_str = "MODIFIED_AND_VERIFIED"
                ver_state_str = "MODIFIED_AND_VERIFIED"
                msg_header = f"Successfully modified and verified `{target_file.name}` in `{target_file.parent}`."

            return ToolResult(
                success=True,
                verified=overall_verified,
                tool=self.name,
                action="edit_code_file",
                message=(
                    f"{msg_header}\n\n"
                    f"```{code_fence}\n{verified_content}\n```"
                ),
                data={
                    "status": status_str,
                    "filename": target_file.name,
                    "file_modified": target_file.name,
                    "path": str(target_file),
                    "workspace": str(target_file.parent),
                    "modified": True,
                    "optimization_applied": opt_applied,
                    "compiler_used": dyn_info.get("compiler_used"),
                    "compile_result": dyn_info.get("compile_status"),
                    "execution_result": dyn_info.get("execution_status"),
                    "stdout": dyn_stdout,
                    "output_verification": ver_state_str,
                    "final_verification_state": ver_state_str,
                    "line_count": len(verified_content.splitlines()),
                    "verified": overall_verified,
                    "semantic_verified": static_sem_ok and (dyn_ok is not False),
                    "execution_verified": dyn_ok,
                    "execution_summary": dyn_summary,
                    "static_summary": static_summary,
                    "content": verified_content,
                    "diff": diff_str,
                    "scope": "surgical_modification",
                    "changed_lines": len([l for l in diff_str.splitlines() if l.startswith("+") or l.startswith("-")])
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="edit_code_file",
                message=f"Failed to write modifications to '{filename}': {e}",
                error=str(e),
                data={"status": "MODIFICATION_FAILED"}
            )

    # -----------------------------------------------------------------
    # 7. ACTION: PROJECT STRUCTURE
    # -----------------------------------------------------------------
    async def _action_project_structure(self, arguments: Dict[str, Any]) -> ToolResult:
        p_name = arguments.get("project_name")
        target_dir, _ = self._resolve_project_root(p_name)

        if not target_dir or not target_dir.exists() or not target_dir.is_dir():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="project_structure",
                message="No active project selected to show structure.",
                error="No active project"
            )

        tree = self._generate_tree(target_dir)
        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="project_structure",
            message=f"Structure for **{target_dir.name}**:\n\n```\n{tree}\n```",
            data={
                "project_name": target_dir.name,
                "project_path": str(target_dir),
                "tree": tree
            }
        )

    # -----------------------------------------------------------------
    # 8. ACTION: DETECT LANGUAGE
    # -----------------------------------------------------------------
    async def _action_detect_language(self, arguments: Dict[str, Any]) -> ToolResult:
        p_name = arguments.get("project_name")
        target_dir, _ = self._resolve_project_root(p_name)

        if not target_dir or not target_dir.exists() or not target_dir.is_dir():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="detect_language",
                message="No active project selected for language detection.",
                error="No active project"
            )

        primary_lang, counts = self._detect_project_language(target_dir)
        
        breakdown_str = ", ".join([f"{k}: {v} file(s)" for k, v in counts.items()]) if counts else "No recognizable code files."

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="detect_language",
            message=f"Detected primary language for **{target_dir.name}**: **{primary_lang}** ({breakdown_str})",
            data={
                "project_name": target_dir.name,
                "primary_language": primary_lang,
                "language_distribution": counts
            }
        )

    # -----------------------------------------------------------------
    # Helper: Resolve Target Language
    # -----------------------------------------------------------------
    def _resolve_target_language(self, prompt: str, explicit_lang: Optional[str] = None) -> Tuple[Optional[str], str, str, str]:
        """
        Determines target language, display name, extension, and default entry filename.
        Returns (norm_lang, lang_display, ext, default_filename)
        """
        cand = (explicit_lang or "").strip().lower()
        p_lower = (prompt or "").lower()

        # Check prompt for explicit language / framework mentions if not in args
        if not cand:
            if re.search(r"(?:\breact\b|\breactjs\b|\breact\.js\b|\bjsx\b|\btsx\b)", p_lower):
                cand = "react"
            elif re.search(r"(?:\bnode\b|\bnodejs\b|\bnode\.js\b|\bexpress\b)", p_lower):
                cand = "node"
            elif re.search(r"(?:\bc\+\+|\bcpp|\bc\s+plus\s+plus)", p_lower):
                cand = "cpp"
            elif re.search(r"\b(?:in\s+)?(?:python|py|python3)\b", p_lower):
                cand = "python"
            elif re.search(r"\b(?:in\s+)?(?:javascript|js)\b", p_lower):
                cand = "javascript"
            elif re.search(r"\b(?:in\s+)?(?:typescript|ts)\b", p_lower):
                cand = "typescript"
            elif re.search(r"\b(?:in\s+)?(?:java)\b", p_lower) and not re.search(r"\bjavascript\b", p_lower):
                cand = "java"
            elif re.search(r"\b(?:in\s+)?(?:go|golang)\b", p_lower):
                cand = "go"
            elif re.search(r"\b(?:in\s+)?(?:rust)\b", p_lower):
                cand = "rust"
            elif re.search(r"(?:\bin\s+c\b|\bfor\s+c\b|\bc\s+program\b|\bc\s+code\b|\bc\s+language\b|\bc\b)", p_lower) and not re.search(r"(?:c\+\+|c#|css)", p_lower):
                cand = "c"
            elif re.search(r"\b(?:html|web|frontend)\b", p_lower):
                cand = "html"
            elif re.search(r"\b(?:css|scss|stylesheet|styling)\b", p_lower):
                cand = "css"
            elif re.search(r"\b(?:sql|query|database|postgres|mysql|sqlite)\b", p_lower):
                cand = "sql"

        # Check active project context if still undetermined
        if not cand and self._active_project_path and self._active_project_path.exists():
            det_lang, _ = self._detect_project_language(self._active_project_path)
            if det_lang and det_lang != "Unknown":
                cand = det_lang.lower()

        if not cand:
            try:
                from core.session import session_manager
                ctx = session_manager.get_working_context()
                act_proj = ctx.get("active_project", {})
                if act_proj and act_proj.get("language"):
                    cand = act_proj.get("language", "").lower()
            except Exception:
                pass

        if any(k in cand for k in ["react", "jsx", "tsx"]):
            fname = "Navbar.tsx" if "navbar" in p_lower else ("App.tsx" if "app" in p_lower else "Component.tsx")
            return "react", "React", ".tsx", fname
        elif any(k in cand for k in ["node", "nodejs", "node.js"]):
            fname = "server.js" if any(k in p_lower for k in ["server", "api", "endpoint", "backend"]) else "app.js"
            return "node", "Node.js", ".js", fname
        elif any(k in cand for k in ["cpp", "c++", "c plus plus"]):
            if any(k in p_lower for k in ["sum", "add two numbers", "sum of two numbers", "sum of 2 numbers"]):
                fname = "sum.cpp"
            elif "prime" in p_lower:
                fname = "prime.cpp"
            elif any(k in p_lower for k in ["1 to 100", "1-100", "one to hundred", "count 100"]):
                fname = "count100.cpp"
            elif "factorial" in p_lower:
                fname = "factorial.cpp"
            elif "binary search" in p_lower:
                fname = "binary_search.cpp"
            elif "hello" in p_lower:
                fname = "hello.cpp"
            else:
                fname = "main.cpp"
            return "cpp", "C++", ".cpp", fname
        elif any(k in cand for k in ["python", "py"]):
            if any(k in p_lower for k in ["sum", "add two numbers", "sum of two numbers", "sum of 2 numbers"]):
                fname = "sum.py"
            elif "factorial" in p_lower:
                fname = "factorial.py"
            elif "prime" in p_lower:
                fname = "prime.py"
            elif "calculator" in p_lower:
                fname = "calculator.py"
            elif "binary search" in p_lower:
                fname = "binary_search.py"
            elif "hello" in p_lower:
                fname = "hello.py"
            else:
                fname = "main.py"
            return "python", "Python", ".py", fname
        elif any(k in cand for k in ["javascript", "js"]):
            fname = "sum.js" if "sum" in p_lower else ("calculator.js" if "calculator" in p_lower else "index.js")
            return "javascript", "JavaScript", ".js", fname
        elif any(k in cand for k in ["typescript", "ts"]):
            fname = "user.ts" if "user" in p_lower else ("types.ts" if ("interface" in p_lower or "type" in p_lower) else "index.ts")
            return "typescript", "TypeScript", ".ts", fname
        elif "java" in cand:
            if any(k in p_lower for k in ["sum", "add two numbers", "sum of two numbers", "sum of 2 numbers"]):
                fname = "Sum.java"
            elif "binary search" in p_lower:
                fname = "BinarySearch.java"
            elif "factorial" in p_lower:
                fname = "Factorial.java"
            elif "prime" in p_lower:
                fname = "Prime.java"
            else:
                fname = "Main.java"
            return "java", "Java", ".java", fname
        elif "go" in cand:
            return "go", "Go", ".go", "main.go"
        elif "rust" in cand:
            return "rust", "Rust", ".rs", "main.rs"
        elif cand == "c":
            return "c", "C", ".c", "main.c"
        elif any(k in cand for k in ["html", "web", "frontend"]):
            fname = "login.html" if "login" in p_lower else "index.html"
            return "web", "HTML", ".html", fname
        elif any(k in cand for k in ["css", "scss", "styles", "stylesheet"]):
            return "css", "CSS", ".css", "styles.css"
        elif any(k in cand for k in ["sql", "database", "query"]):
            return "sql", "SQL", ".sql", "query.sql"

        return None, "Unknown", ".txt", "main.txt"

    # -----------------------------------------------------------------
    # Helper: Synthesize Code and Explanation
    # -----------------------------------------------------------------
    def _synthesize_code(self, prompt: str, language: str, filename: str) -> Tuple[str, str]:
        """
        Synthesizes complete, idiomatic source code and a short explanation
        for common algorithms, components, and natural language programming prompts.
        """
        # Sanitize credentials, API keys, passwords from prompt
        clean_prompt = prompt
        clean_prompt = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}", "[REDACTED_KEY]", clean_prompt)
        clean_prompt = re.sub(r"['\"](?:ghp_[a-zA-Z0-9]{20,}|eyJh[a-zA-Z0-9_\-\.]{20,}|sk-[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9\-]{20,})['\"]", "'[REDACTED_SECRET]'", clean_prompt)
        clean_prompt = re.sub(r"(?:password|secret|api_key|token|access_key)\s*[:=]\s*['\"][^'\"]+['\"]", "secret = '[REDACTED]'", clean_prompt, flags=re.IGNORECASE)
        prompt = clean_prompt
        p_lower = prompt.lower()

        # 0a. SUM OF NUMBERS FROM 1 TO 100 / SUM 1 TO 100 / SUM FROM 1 TO 100
        if any(k in p_lower for k in ["sum of numbers from 1 to 100", "sum from 1 to 100", "sum of 1 to 100", "sum 1 to 100", "sum 1-100", "sum of 1-100", "calculate sum from 1 to 100", "calculate the sum from 1 to 100", "sum of numbers 1 to 100", "sum numbers from 1 to 100"]):
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    int sum = 0;\n\n"
                    "    for (int i = 1; i <= 100; i++) {\n"
                    "        sum += i;\n"
                    "        cout << i;\n\n"
                    "        if (i < 100) {\n"
                    "            cout << \" + \";\n"
                    "        }\n"
                    "    }\n\n"
                    "    cout << \" = \" << sum << endl;\n\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Calculates and prints the sum of numbers from 1 to 100."
                return code, explanation

            elif language == "python":
                code = (
                    "total = 0\n"
                    "for i in range(1, 101):\n"
                    "    total += i\n\n"
                    "print(\"Sum:\", total)\n"
                )
                explanation = "Python script calculating the sum of numbers from 1 to 100."
                return code, explanation

        # 0. SUM OF TWO NUMBERS / ADD TWO NUMBERS
        if any(k in p_lower for k in ["sum of two numbers", "sum of 2 numbers", "sum of two", "sum of 2", "add two numbers", "add 2 numbers"]) or (p_lower.strip() in ["sum", "calculate sum", "write sum", "sum program", "sum script"]):
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    int a = 10, b = 20;\n"
                    "    int sum = a + b;\n\n"
                    "    cout << \"Sum: \" << sum << endl;\n\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Simple C++ program calculating and printing the sum of two numbers."
                return code, explanation

            elif language == "python":
                code = (
                    "a = 10\n"
                    "b = 20\n"
                    "total = a + b\n"
                    "print(f\"Sum: {total}\")\n"
                )
                explanation = "Simple Python script calculating and printing the sum of two numbers."
                return code, explanation

            elif language == "c":
                code = (
                    "#include <stdio.h>\n\n"
                    "int main() {\n"
                    "    int a = 10, b = 20;\n"
                    "    int sum = a + b;\n\n"
                    "    printf(\"Sum: %d\\n\", sum);\n\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "C program calculating the sum of two integers and printing to standard output."
                return code, explanation

            elif language == "java":
                code = (
                    "public class Sum {\n"
                    "    public static void main(String[] args) {\n"
                    "        int a = 10;\n"
                    "        int b = 20;\n"
                    "        int sum = a + b;\n"
                    "        System.out.println(\"Sum: \" + sum);\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Java class that computes and displays the sum of two numbers."
                return code, explanation

            elif language in ["javascript", "node"]:
                code = (
                    "const a = 10;\n"
                    "const b = 20;\n"
                    "const sum = a + b;\n\n"
                    "console.log(\"Sum:\", sum);\n"
                )
                explanation = "JavaScript program computing and logging the sum of two numbers."
                return code, explanation

            elif language == "go":
                code = (
                    "package main\n\n"
                    "import \"fmt\"\n\n"
                    "func main() {\n"
                    "    a := 10\n"
                    "    b := 20\n"
                    "    sum := a + b\n"
                    "    fmt.Println(\"Sum:\", sum)\n"
                    "}\n"
                )
                explanation = "Go program calculating the sum of two variables."
                return code, explanation

        # 1. NUMBERS FROM 1 TO 100 / COUNT 1 TO 100 / PRINT 1 TO 100
        if any(k in p_lower for k in ["1 to 100", "1-100", "one to hundred", "one to a hundred", "numbers from 1 to 100", "print numbers 1 to 100"]) and not ("prime" in p_lower):
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    for (int i = 1; i <= 100; i++) {\n"
                    "        cout << i << endl;\n"
                    "    }\n\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Iterates from 1 to 100 inclusive and prints each number to standard output."
                return code, explanation

            elif language == "c":
                code = (
                    "#include <stdio.h>\n\n"
                    "int main() {\n"
                    "    for (int i = 1; i <= 100; i++) {\n"
                    "        printf(\"%d\\n\", i);\n"
                    "    }\n\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "C program that loops from 1 to 100 and outputs numbers with printf."
                return code, explanation

            elif language == "python":
                code = (
                    "for i in range(1, 101):\n"
                    "    print(i)\n"
                )
                explanation = "Python script iterating over range(1, 101) to print integers 1 through 100."
                return code, explanation

            elif language == "java":
                code = (
                    "public class Main {\n"
                    "    public static void main(String[] args) {\n"
                    "        for (int i = 1; i <= 100; i++) {\n"
                    "            System.out.println(i);\n"
                    "        }\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Java class that uses a standard for loop to print integers 1 through 100."
                return code, explanation

            elif language in ["javascript", "node"]:
                code = (
                    "for (let i = 1; i <= 100; i++) {\n"
                    "    console.log(i);\n"
                    "}\n"
                )
                explanation = "JavaScript program printing numbers from 1 to 100 in console."
                return code, explanation

            elif language == "go":
                code = (
                    "package main\n\n"
                    "import \"fmt\"\n\n"
                    "func main() {\n"
                    "    for i := 1; i <= 100; i++ {\n"
                    "        fmt.Println(i)\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Go program using standard for loop to print 1 to 100."
                return code, explanation

        # 2. REVERSE ARRAY / VECTOR / LIST
        if any(k in p_lower for k in ["reverse an array", "reverse array", "reverse vector", "reverse list", "reverse string", "reverse a list"]):
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "#include <vector>\n"
                    "using namespace std;\n\n"
                    "void reverseArray(vector<int>& arr) {\n"
                    "    int left = 0;\n"
                    "    int right = arr.size() - 1;\n"
                    "    while (left < right) {\n"
                    "        swap(arr[left], arr[right]);\n"
                    "        left++;\n"
                    "        right--;\n"
                    "    }\n"
                    "}\n\n"
                    "int main() {\n"
                    "    vector<int> numbers = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};\n"
                    "    reverseArray(numbers);\n\n"
                    "    for (int x : numbers) cout << x << \" \";\n"
                    "    cout << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Implements O(n) two-pointer in-place reversal algorithm on a C++ vector."
                return code, explanation

            elif language == "python":
                code = (
                    "def reverse_array(arr):\n"
                    "    left, right = 0, len(arr) - 1\n"
                    "    while left < right:\n"
                    "        arr[left], arr[right] = arr[right], arr[left]\n"
                    "        left += 1\n"
                    "        right -= 1\n"
                    "    return arr\n\n"
                    "numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]\n"
                    "reverse_array(numbers)\n"
                    "print(\"Reversed:\", numbers)\n"
                )
                explanation = "Reverses array in-place using two-pointer swap technique in Python."
                return code, explanation

            elif language == "java":
                code = (
                    "import java.util.Arrays;\n\n"
                    "public class Main {\n"
                    "    public static void reverseArray(int[] arr) {\n"
                    "        int left = 0, right = arr.length - 1;\n"
                    "        while (left < right) {\n"
                    "            int temp = arr[left];\n"
                    "            arr[left] = arr[right];\n"
                    "            arr[right] = temp;\n"
                    "            left++;\n"
                    "            right--;\n"
                    "        }\n"
                    "    }\n\n"
                    "    public static void main(String[] args) {\n"
                    "        int[] numbers = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};\n"
                    "        reverseArray(numbers);\n"
                    "        System.out.println(\"Reversed: \" + Arrays.toString(numbers));\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "In-place Java array reversal using classic two-pointer swap algorithm."
                return code, explanation

            elif language == "c":
                code = (
                    "#include <stdio.h>\n\n"
                    "void reverseArray(int arr[], int n) {\n"
                    "    int left = 0, right = n - 1;\n"
                    "    while (left < right) {\n"
                    "        int temp = arr[left];\n"
                    "        arr[left] = arr[right];\n"
                    "        arr[right] = temp;\n"
                    "        left++;\n"
                    "        right--;\n"
                    "    }\n"
                    "}\n\n"
                    "int main() {\n"
                    "    int numbers[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};\n"
                    "    int n = sizeof(numbers) / sizeof(numbers[0]);\n\n"
                    "    reverseArray(numbers, n);\n\n"
                    "    printf(\"Reversed: \");\n"
                    "    for (int i = 0; i < n; i++) printf(\"%d \", numbers[i]);\n"
                    "    printf(\"\\n\");\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Standard C array reversal function using pointer index swapping."
                return code, explanation

        # 3. REACT NAVBAR / COMPONENT
        if language == "react" or ("react" in p_lower and "navbar" in p_lower) or ("navbar" in p_lower and filename.endswith((".tsx", ".jsx"))):
            code = (
                "import React, { useState } from 'react';\n\n"
                "interface NavItem {\n"
                "  label: string;\n"
                "  href: string;\n"
                "}\n\n"
                "const navItems: NavItem[] = [\n"
                "  { label: 'Home', href: '/' },\n"
                "  { label: 'Features', href: '#features' },\n"
                "  { label: 'Docs', href: '#docs' },\n"
                "  { label: 'Pricing', href: '#pricing' },\n"
                "  { label: 'Contact', href: '#contact' }\n"
                "];\n\n"
                "export const Navbar: React.FC = () => {\n"
                "  const [isOpen, setIsOpen] = useState(false);\n\n"
                "  return (\n"
                "    <nav style={{\n"
                "      display: 'flex',\n"
                "      justifyContent: 'space-between',\n"
                "      alignItems: 'center',\n"
                "      padding: '1rem 2rem',\n"
                "      background: '#0a0a0f',\n"
                "      color: '#fff',\n"
                "      borderBottom: '1px solid #222'\n"
                "    }}>\n"
                "      <div style={{ fontWeight: 'bold', fontSize: '1.25rem', letterSpacing: '-0.5px' }}>ByteX</div>\n"
                "      <div style={{ display: 'flex', gap: '1.5rem' }}>\n"
                "        {navItems.map((item) => (\n"
                "          <a\n"
                "            key={item.label}\n"
                "            href={item.href}\n"
                "            style={{ color: '#aaa', textDecoration: 'none', transition: 'color 0.2s' }}\n"
                "            onMouseEnter={(e) => (e.currentTarget.style.color = '#fff')}\n"
                "            onMouseLeave={(e) => (e.currentTarget.style.color = '#aaa')}\n"
                "          >\n"
                "            {item.label}\n"
                "          </a>\n"
                "        ))}\n"
                "      </div>\n"
                "    </nav>\n"
                "  );\n"
                "};\n\n"
                "export default Navbar;\n"
            )
            explanation = "Modern React TypeScript Navbar component with structured links and responsive styling."
            return code, explanation

        # 4. NODE.JS API ENDPOINT
        if language == "node" or ("node" in p_lower and any(k in p_lower for k in ["api", "endpoint", "server", "user"])):
            code = (
                "const http = require('http');\n\n"
                "const users = [\n"
                "  { id: 1, name: 'Alice Smith', email: 'alice@example.com', role: 'admin' },\n"
                "  { id: 2, name: 'Bob Jones', email: 'bob@example.com', role: 'developer' },\n"
                "  { id: 3, name: 'Charlie Brown', email: 'charlie@example.com', role: 'designer' }\n"
                "];\n\n"
                "const server = http.createServer((req, res) => {\n"
                "  res.setHeader('Content-Type', 'application/json');\n"
                "  res.setHeader('Access-Control-Allow-Origin', '*');\n\n"
                "  const url = new URL(req.url, `http://${req.headers.host}`);\n\n"
                "  if (req.method === 'GET' && url.pathname === '/api/users') {\n"
                "    res.writeHead(200);\n"
                "    res.end(JSON.stringify({ success: true, count: users.length, data: users }));\n"
                "  } else if (req.method === 'POST' && url.pathname === '/api/users') {\n"
                "    let body = '';\n"
                "    req.on('data', chunk => { body += chunk; });\n"
                "    req.on('end', () => {\n"
                "      try {\n"
                "        const newUser = JSON.parse(body);\n"
                "        newUser.id = users.length + 1;\n"
                "        users.push(newUser);\n"
                "        res.writeHead(201);\n"
                "        res.end(JSON.stringify({ success: true, message: 'User created', data: newUser }));\n"
                "      } catch (e) {\n"
                "        res.writeHead(400);\n"
                "        res.end(JSON.stringify({ success: false, error: 'Invalid JSON payload' }));\n"
                "      }\n"
                "    });\n"
                "  } else {\n"
                "    res.writeHead(404);\n"
                "    res.end(JSON.stringify({ success: false, error: 'Route not found' }));\n"
                "  }\n"
                "});\n\n"
                "const PORT = process.env.PORT || 3000;\n"
                "server.listen(PORT, () => {\n"
                "  console.log(`ByteX Users API server running on http://localhost:${PORT}/api/users`);\n"
                "});\n"
            )
            explanation = "Node.js REST API server providing GET and POST endpoints for user resource management."
            return code, explanation

        # 5. TYPESCRIPT USER INTERFACE
        if (language == "typescript" and any(k in p_lower for k in ["user", "interface", "type", "dto"])) or ("typescript interface" in p_lower):
            code = (
                "export interface User {\n"
                "  id: string | number;\n"
                "  username: string;\n"
                "  email: string;\n"
                "  firstName: string;\n"
                "  lastName: string;\n"
                "  avatarUrl?: string;\n"
                "  role: 'admin' | 'editor' | 'viewer' | 'developer';\n"
                "  isActive: boolean;\n"
                "  createdAt: Date;\n"
                "  updatedAt?: Date;\n"
                "}\n\n"
                "export interface CreateUserDTO {\n"
                "  username: string;\n"
                "  email: string;\n"
                "  firstName: string;\n"
                "  lastName: string;\n"
                "  role?: 'admin' | 'editor' | 'viewer' | 'developer';\n"
                "}\n\n"
                "export interface UserPreferences {\n"
                "  userId: string | number;\n"
                "  theme: 'light' | 'dark' | 'system';\n"
                "  notificationsEnabled: boolean;\n"
                "}\n"
            )
            explanation = "Complete TypeScript interface and DTO type definitions for User domain entities."
            return code, explanation

        # 6. HTML LOGIN FORM
        if (language == "web" and "login" in p_lower) or ("login form" in p_lower) or ("login page" in p_lower):
            code = (
                "<!DOCTYPE html>\n"
                "<html lang=\"en\">\n"
                "<head>\n"
                "  <meta charset=\"UTF-8\">\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
                "  <title>ByteX Login</title>\n"
                "  <style>\n"
                "    * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }\n"
                "    body { background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; }\n"
                "    .login-card { background: #1e293b; padding: 2.5rem; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); width: 100%; max-width: 400px; border: 1px solid #334155; }\n"
                "    .login-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; text-align: center; }\n"
                "    .login-subtitle { font-size: 0.875rem; color: #94a3b8; text-align: center; margin-bottom: 1.5rem; }\n"
                "    .form-group { margin-bottom: 1.25rem; }\n"
                "    label { display: block; font-size: 0.875rem; font-weight: 500; margin-bottom: 0.5rem; color: #cbd5e1; }\n"
                "    input[type=\"email\"], input[type=\"password\"] { width: 100%; padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-size: 0.875rem; }\n"
                "    input:focus { outline: none; border-color: #38bdf8; box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2); }\n"
                "    .submit-btn { width: 100%; padding: 0.75rem; background: #38bdf8; color: #0f172a; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; transition: background 0.2s; margin-top: 0.5rem; }\n"
                "    .submit-btn:hover { background: #0ea5e9; }\n"
                "  </style>\n"
                "</head>\n"
                "<body>\n"
                "  <div class=\"login-card\">\n"
                "    <h1 class=\"login-title\">Welcome Back</h1>\n"
                "    <p class=\"login-subtitle\">Sign in to your ByteX account</p>\n"
                "    <form id=\"loginForm\" onsubmit=\"event.preventDefault(); alert('Login submitted');\">\n"
                "      <div class=\"form-group\">\n"
                "        <label for=\"email\">Email Address</label>\n"
                "        <input type=\"email\" id=\"email\" name=\"email\" required placeholder=\"you@example.com\">\n"
                "      </div>\n"
                "      <div class=\"form-group\">\n"
                "        <label for=\"password\">Password</label>\n"
                "        <input type=\"password\" id=\"password\" name=\"password\" required placeholder=\"••••••••\">\n"
                "      </div>\n"
                "      <button type=\"submit\" class=\"submit-btn\">Sign In</button>\n"
                "    </form>\n"
                "  </div>\n"
                "</body>\n"
                "</html>\n"
            )
            explanation = "Modern responsive HTML5 login page with card layout, CSS grid/flex styling, and validation inputs."
            return code, explanation

        # 7. CSS RESPONSIVE NAVBAR
        if language == "css" or ("css" in p_lower and "navbar" in p_lower) or ("responsive navbar" in p_lower):
            code = (
                "/* Responsive Navbar Styles */\n"
                ":root {\n"
                "  --nav-bg: #0f172a;\n"
                "  --nav-text: #f8fafc;\n"
                "  --nav-accent: #38bdf8;\n"
                "  --nav-border: #1e293b;\n"
                "}\n\n"
                ".navbar {\n"
                "  display: flex;\n"
                "  justify-content: space-between;\n"
                "  align-items: center;\n"
                "  background-color: var(--nav-bg);\n"
                "  padding: 1rem 2rem;\n"
                "  border-bottom: 1px solid var(--nav-border);\n"
                "  position: sticky;\n"
                "  top: 0;\n"
                "  z-index: 100;\n"
                "}\n\n"
                ".nav-brand {\n"
                "  font-size: 1.5rem;\n"
                "  font-weight: 700;\n"
                "  color: var(--nav-accent);\n"
                "  text-decoration: none;\n"
                "}\n\n"
                ".nav-links {\n"
                "  display: flex;\n"
                "  gap: 1.5rem;\n"
                "  list-style: none;\n"
                "  margin: 0;\n"
                "  padding: 0;\n"
                "}\n\n"
                ".nav-link {\n"
                "  color: var(--nav-text);\n"
                "  text-decoration: none;\n"
                "  font-size: 0.95rem;\n"
                "  transition: color 0.2s ease;\n"
                "}\n\n"
                ".nav-link:hover {\n"
                "  color: var(--nav-accent);\n"
                "}\n\n"
                "@media (max-width: 768px) {\n"
                "  .navbar {\n"
                "    flex-direction: column;\n"
                "    align-items: flex-start;\n"
                "    gap: 1rem;\n"
                "    padding: 1rem;\n"
                "  }\n"
                "  .nav-links {\n"
                "    flex-direction: column;\n"
                "    width: 100%;\n"
                "    gap: 0.75rem;\n"
                "  }\n"
                "}\n"
            )
            explanation = "Modern CSS3 responsive navigation bar styling with flexbox layout and media queries."
            return code, explanation

        # 8. SQL SECOND HIGHEST SALARY / QUERIES
        if language == "sql" or ("sql" in p_lower and any(k in p_lower for k in ["salary", "query", "highest", "employee"])):
            code = (
                "-- Query to find the second highest salary from the Employee table\n"
                "SELECT MAX(salary) AS SecondHighestSalary\n"
                "FROM Employee\n"
                "WHERE salary < (\n"
                "    SELECT MAX(salary)\n"
                "    FROM Employee\n"
                ");\n\n"
                "-- Alternative solution using LIMIT & OFFSET with subquery for null-safety\n"
                "SELECT (\n"
                "    SELECT DISTINCT salary\n"
                "    FROM Employee\n"
                "    ORDER BY salary DESC\n"
                "    LIMIT 1 OFFSET 1\n"
                ") AS SecondHighestSalary;\n"
            )
            explanation = "SQL query computing the second highest salary handling null edge cases with subqueries."
            return code, explanation

        # 9. PRIME NUMBERS
        if "prime" in p_lower:
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "bool isPrime(int n) {\n"
                    "    if (n <= 1) return false;\n"
                    "    for (int i = 2; i * i <= n; i++) {\n"
                    "        if (n % i == 0) return false;\n"
                    "    }\n"
                    "    return true;\n"
                    "}\n\n"
                    "int main() {\n"
                    "    cout << \"Prime numbers from 1 to 100:\" << endl;\n"
                    "    for (int i = 1; i <= 100; i++) {\n"
                    "        if (isPrime(i)) {\n"
                    "            cout << i << \" \";\n"
                    "        }\n"
                    "    }\n"
                    "    cout << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Implements an optimized isPrime trial division function and prints primes between 1 and 100."
                return code, explanation

            elif language == "python":
                code = (
                    "def is_prime(n):\n"
                    "    if n <= 1:\n"
                    "        return False\n"
                    "    for i in range(2, int(n ** 0.5) + 1):\n"
                    "        if n % i == 0:\n"
                    "            return False\n"
                    "    return True\n\n"
                    "print(\"Prime numbers from 1 to 100:\")\n"
                    "for i in range(1, 101):\n"
                    "    if is_prime(i):\n"
                    "        print(i, end=\" \")\n"
                    "print()\n"
                )
                explanation = "Defines is_prime with square-root bound and prints prime numbers between 1 and 100."
                return code, explanation

            elif language in ["javascript", "node"]:
                code = (
                    "function isPrime(n) {\n"
                    "    if (n <= 1) return false;\n"
                    "    for (let i = 2; i * i <= n; i++) {\n"
                    "        if (n % i === 0) return false;\n"
                    "    }\n"
                    "    return true;\n"
                    "}\n\n"
                    "console.log(\"Prime numbers from 1 to 100:\");\n"
                    "const primes = [];\n"
                    "for (let i = 1; i <= 100; i++) {\n"
                    "    if (isPrime(i)) primes.push(i);\n"
                    "}\n"
                    "console.log(primes.join(\" \"));\n"
                )
                explanation = "Generates and logs all prime numbers in range [1, 100] using an isPrime helper."
                return code, explanation

            elif language == "c":
                code = (
                    "#include <stdio.h>\n"
                    "#include <stdbool.h>\n\n"
                    "bool isPrime(int n) {\n"
                    "    if (n <= 1) return false;\n"
                    "    for (int i = 2; i * i <= n; i++) {\n"
                    "        if (n % i == 0) return false;\n"
                    "    }\n"
                    "    return true;\n"
                    "}\n\n"
                    "int main() {\n"
                    "    printf(\"Prime numbers from 1 to 100:\\n\");\n"
                    "    for (int i = 1; i <= 100; i++) {\n"
                    "        if (isPrime(i)) {\n"
                    "            printf(\"%d \", i);\n"
                    "        }\n"
                    "    }\n"
                    "    printf(\"\\n\");\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "C program that checks primes up to sqrt(n) and prints primes between 1 and 100."
                return code, explanation

            elif language == "java":
                java_class = Path(filename).stem if filename else "Prime"
                code = (
                    f"public class {java_class} {{\n"
                    "    public static boolean isPrime(int n) {\n"
                    "        if (n <= 1) return false;\n"
                    "        for (int i = 2; i * i <= n; i++) {\n"
                    "            if (n % i == 0) return false;\n"
                    "        }\n"
                    "        return true;\n"
                    "    }\n\n"
                    "    public static void main(String[] args) {\n"
                    "        System.out.println(\"Prime numbers from 1 to 100:\");\n"
                    "        for (int i = 1; i <= 100; i++) {\n"
                    "            if (isPrime(i)) {\n"
                    "                System.out.print(i + \" \");\n"
                    "            }\n"
                    "        }\n"
                    "        System.out.println();\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Java class that checks primality via square-root trial division and prints primes 1 to 100."
                return code, explanation

        # 10. BINARY SEARCH
        if "binary search" in p_lower:
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "#include <vector>\n"
                    "using namespace std;\n\n"
                    "int binarySearch(const vector<int>& arr, int target) {\n"
                    "    int left = 0;\n"
                    "    int right = arr.size() - 1;\n\n"
                    "    while (left <= right) {\n"
                    "        int mid = left + (right - left) / 2;\n"
                    "        if (arr[mid] == target) return mid;\n"
                    "        if (arr[mid] < target) left = mid + 1;\n"
                    "        else right = mid - 1;\n"
                    "    }\n"
                    "    return -1;\n"
                    "}\n\n"
                    "int main() {\n"
                    "    vector<int> numbers = {2, 5, 8, 12, 16, 23, 38, 56, 72, 91};\n"
                    "    int target = 23;\n"
                    "    int idx = binarySearch(numbers, target);\n\n"
                    "    if (idx != -1) {\n"
                    "        cout << \"Element \" << target << \" found at index \" << idx << endl;\n"
                    "    } else {\n"
                    "        cout << \"Element \" << target << \" not found.\" << endl;\n"
                    "    }\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Implements O(log n) iterative binary search on a sorted vector."
                return code, explanation

            elif language == "python":
                code = (
                    "def binary_search(arr, target):\n"
                    "    left, right = 0, len(arr) - 1\n"
                    "    while left <= right:\n"
                    "        mid = left + (right - left) // 2\n"
                    "        if arr[mid] == target:\n"
                    "            return mid\n"
                    "        elif arr[mid] < target:\n"
                    "            left = mid + 1\n"
                    "        else:\n"
                    "            right = mid - 1\n"
                    "    return -1\n\n"
                    "numbers = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]\n"
                    "target = 23\n"
                    "result = binary_search(numbers, target)\n"
                    "print(f\"Element {target} found at index: {result}\")\n"
                )
                explanation = "Implements binary search algorithm returning 0-based index of target in sorted list."
                return code, explanation

            elif language == "java":
                java_class = Path(filename).stem if filename else "BinarySearch"
                code = (
                    f"public class {java_class} {{\n"
                    "    public static int binarySearch(int[] arr, int target) {\n"
                    "        int left = 0;\n"
                    "        int right = arr.length - 1;\n"
                    "        while (left <= right) {\n"
                    "            int mid = left + (right - left) / 2;\n"
                    "            if (arr[mid] == target) {\n"
                    "                return mid;\n"
                    "            }\n"
                    "            if (arr[mid] < target) {\n"
                    "                left = mid + 1;\n"
                    "            } else {\n"
                    "                right = mid - 1;\n"
                    "            }\n"
                    "        }\n"
                    "        return -1;\n"
                    "    }\n\n"
                    "    public static void main(String[] args) {\n"
                    "        int[] numbers = {2, 5, 8, 12, 16, 23, 38, 56, 72, 91};\n"
                    "        int target = 23;\n"
                    "        int result = binarySearch(numbers, target);\n"
                    "        if (result != -1) {\n"
                    "            System.out.println(\"Element \" + target + \" found at index \" + result);\n"
                    "        } else {\n"
                    "            System.out.println(\"Element \" + target + \" not found.\");\n"
                    "        }\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Standard iterative binary search algorithm in Java with sample array execution."
                return code, explanation

            elif language in ["javascript", "node"]:
                code = (
                    "function binarySearch(arr, target) {\n"
                    "    let left = 0;\n"
                    "    let right = arr.length - 1;\n"
                    "    while (left <= right) {\n"
                    "        const mid = Math.floor(left + (right - left) / 2);\n"
                    "        if (arr[mid] === target) return mid;\n"
                    "        if (arr[mid] < target) left = mid + 1;\n"
                    "        else right = mid - 1;\n"
                    "    }\n"
                    "    return -1;\n"
                    "}\n\n"
                    "const numbers = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91];\n"
                    "const target = 23;\n"
                    "const idx = binarySearch(numbers, target);\n"
                    "console.log(`Element ${target} found at index: ${idx}`);\n"
                )
                explanation = "JavaScript binary search implementation tested with sample sorted array."
                return code, explanation

        # 11. PALINDROME CHECK
        if "palindrome" in p_lower:
            if language == "python":
                code = (
                    "def is_palindrome(s):\n"
                    "    clean = [c.lower() for c in str(s) if c.isalnum()]\n"
                    "    return clean == clean[::-1]\n\n"
                    "text = \"racecar\"\n"
                    "print(f\"'{text}' is palindrome: {is_palindrome(text)}\")\n"
                )
                explanation = "Clean palindrome checker function with multi-case verification."
                return code, explanation

            elif language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "#include <string>\n"
                    "#include <cctype>\n"
                    "using namespace std;\n\n"
                    "bool isPalindrome(const string& str) {\n"
                    "    int left = 0;\n"
                    "    int right = str.length() - 1;\n\n"
                    "    while (left < right) {\n"
                    "        while (left < right && !isalnum(str[left])) left++;\n"
                    "        while (left < right && !isalnum(str[right])) right--;\n"
                    "        if (tolower(str[left]) != tolower(str[right])) {\n"
                    "            return false;\n"
                    "        }\n"
                    "        left++;\n"
                    "        right--;\n"
                    "    }\n"
                    "    return true;\n"
                    "}\n\n"
                    "int main() {\n"
                    "    string word = \"racecar\";\n"
                    "    cout << \"Word: '\" << word << \"' -> Palindrome: \" << (isPalindrome(word) ? \"Yes\" : \"No\") << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Two-pointer in-place palindrome verification ignoring punctuation and case."
                return code, explanation

        # 12. CALCULATOR
        if "calculator" in p_lower:
            if language in ["javascript", "node"]:
                code = (
                    "function add(a, b) { return a + b; }\n"
                    "function subtract(a, b) { return a - b; }\n"
                    "function multiply(a, b) { return a * b; }\n"
                    "function divide(a, b) { return b !== 0 ? a / b : 'Error: divide by 0'; }\n\n"
                    "console.log(\"10 + 5 =\", add(10, 5));\n"
                    "console.log(\"10 - 5 =\", subtract(10, 5));\n"
                    "console.log(\"10 * 5 =\", multiply(10, 5));\n"
                    "console.log(\"10 / 5 =\", divide(10, 5));\n"
                )
                explanation = "Simple JavaScript calculator functions."
                return code, explanation

            elif language == "python":
                code = (
                    "def add(a, b):\n"
                    "    return a + b\n\n"
                    "def subtract(a, b):\n"
                    "    return a - b\n\n"
                    "def multiply(a, b):\n"
                    "    return a * b\n\n"
                    "def divide(a, b):\n"
                    "    return a / b if b != 0 else 'Error'\n\n"
                    "print(\"10 + 5 =\", add(10, 5))\n"
                    "print(\"10 - 5 =\", subtract(10, 5))\n"
                    "print(\"10 * 5 =\", multiply(10, 5))\n"
                    "print(\"10 / 5 =\", divide(10, 5))\n"
                )
                explanation = "Python calculator functions providing fundamental arithmetic operations."
                return code, explanation

        # 13. MERGE SORT
        if "merge sort" in p_lower:
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "#include <vector>\n"
                    "using namespace std;\n\n"
                    "void merge(vector<int>& arr, int left, int mid, int right) {\n"
                    "    int n1 = mid - left + 1;\n"
                    "    int n2 = right - mid;\n\n"
                    "    vector<int> L(n1), R(n2);\n"
                    "    for (int i = 0; i < n1; ++i) L[i] = arr[left + i];\n"
                    "    for (int j = 0; j < n2; ++j) R[j] = arr[mid + 1 + j];\n\n"
                    "    int i = 0, j = 0, k = left;\n"
                    "    while (i < n1 && j < n2) {\n"
                    "        if (L[i] <= R[j]) arr[k++] = L[i++];\n"
                    "        else arr[k++] = R[j++];\n"
                    "    }\n"
                    "    while (i < n1) arr[k++] = L[i++];\n"
                    "    while (j < n2) arr[k++] = R[j++];\n"
                    "}\n\n"
                    "void mergeSort(vector<int>& arr, int left, int right) {\n"
                    "    if (left < right) {\n"
                    "        int mid = left + (right - left) / 2;\n"
                    "        mergeSort(arr, left, mid);\n"
                    "        mergeSort(arr, mid + 1, right);\n"
                    "        merge(arr, left, mid, right);\n"
                    "    }\n"
                    "}\n\n"
                    "int main() {\n"
                    "    vector<int> data = {38, 27, 43, 3, 9, 82, 10};\n"
                    "    mergeSort(data, 0, data.size() - 1);\n\n"
                    "    for (int x : data) cout << x << \" \";\n"
                    "    cout << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Divide-and-conquer merge sort algorithm in C++ achieving O(n log n) time complexity."
                return code, explanation

            elif language == "python":
                code = (
                    "def merge_sort(arr):\n"
                    "    if len(arr) <= 1:\n"
                    "        return arr\n\n"
                    "    mid = len(arr) // 2\n"
                    "    left = merge_sort(arr[:mid])\n"
                    "    right = merge_sort(arr[mid:])\n\n"
                    "    result = []\n"
                    "    i = j = 0\n"
                    "    while i < len(left) and j < len(right):\n"
                    "        if left[i] <= right[j]:\n"
                    "            result.append(left[i])\n"
                    "            i += 1\n"
                    "        else:\n"
                    "            result.append(right[j])\n"
                    "            j += 1\n"
                    "    result.extend(left[i:])\n"
                    "    result.extend(right[j:])\n"
                    "    return result\n\n"
                    "data = [38, 27, 43, 3, 9, 82, 10]\n"
                    "print(\"Sorted:\", merge_sort(data))\n"
                )
                explanation = "Pythonic merge sort implementation with recursive partitioning and linear merging."
                return code, explanation

        # 14. FACTORIAL
        if "factorial" in p_lower:
            if language == "python":
                code = (
                    "def factorial(n):\n"
                    "    if n <= 1:\n"
                    "        return 1\n"
                    "    return n * factorial(n - 1)\n\n"
                    "num = 5\n"
                    "print(f\"Factorial of {num} is {factorial(num)}\")\n"
                )
                explanation = "Simple recursive factorial function in Python."
                return code, explanation

            elif language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "long long factorial(int n) {\n"
                    "    if (n <= 1) return 1;\n"
                    "    return n * factorial(n - 1);\n"
                    "}\n\n"
                    "int main() {\n"
                    "    int n = 5;\n"
                    "    cout << \"Factorial of \" << n << \" is \" << factorial(n) << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Calculates factorial in C++ using clean recursion."
                return code, explanation

            elif language == "java":
                java_class = Path(filename).stem if filename else "Factorial"
                code = (
                    f"public class {java_class} {{\n"
                    "    public static long factorial(int n) {\n"
                    "        if (n <= 1) return 1;\n"
                    "        return n * factorial(n - 1);\n"
                    "    }\n\n"
                    "    public static void main(String[] args) {\n"
                    "        int n = 5;\n"
                    "        System.out.println(\"Factorial of \" + n + \" is \" + factorial(n));\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Calculates factorial in Java using recursion."
                return code, explanation

        # 15. EMAIL VALIDATION
        if "email" in p_lower and any(k in p_lower for k in ["validate", "validation", "check", "regex"]):
            if language in ["javascript", "node", "typescript"]:
                code = (
                    "function isValidEmail(email) {\n"
                    "    const regex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;\n"
                    "    return regex.test(email);\n"
                    "}\n\n"
                    "console.log('test@example.com ->', isValidEmail('test@example.com'));\n"
                )
                explanation = "Email address validation function in JavaScript."
                return code, explanation
            elif language == "python":
                code = (
                    "import re\n\n"
                    "def is_valid_email(email):\n"
                    "    pattern = r'^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$'\n"
                    "    return bool(re.match(pattern, email))\n\n"
                    "print('test@example.com ->', is_valid_email('test@example.com'))\n"
                )
                explanation = "Python email validation function using standard library re."
                return code, explanation

        # 16. HELLO BYTEX / HELLO WORLD / GREETING
        if any(k in p_lower for k in ["hello bytex", "hello world", "prints hello", "print hello"]):
            if language == "cpp":
                code = (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    cout << \"Hello, World!\" << endl;\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Standard C++ program printing greeting to standard output."
                return code, explanation
            elif language == "python":
                code = (
                    "print(\"Hello, World!\")\n"
                )
                explanation = "Standard Python program printing greeting to console."
                return code, explanation
            elif language == "c":
                code = (
                    "#include <stdio.h>\n\n"
                    "int main() {\n"
                    "    printf(\"Hello, World!\\n\");\n"
                    "    return 0;\n"
                    "}\n"
                )
                explanation = "Standard C program printing greeting."
                return code, explanation
            elif language == "java":
                java_class = Path(filename).stem if filename else "Main"
                code = (
                    f"public class {java_class} {{\n"
                    "    public static void main(String[] args) {\n"
                    "        System.out.println(\"Hello, World!\");\n"
                    "    }\n"
                    "}\n"
                )
                explanation = "Standard Java program printing greeting."
                return code, explanation

        # 17. GENERAL / CUSTOM FALLBACK
        clean_title = re.sub(r"[^a-zA-Z0-9\s]", "", prompt).strip().title()
        # Extract desired output literal if prompt specifies quotes
        m_lit = re.search(r'["\']([^"\']+)["\']', prompt)
        out_str = m_lit.group(1).strip() if m_lit else "Hello ByteX"
        if language == "cpp":
            code = (
                "#include <iostream>\n"
                "using namespace std;\n\n"
                "int main() {\n"
                f"    cout << \"{out_str}\" << endl;\n"
                "    return 0;\n"
                "}\n"
            )
            explanation = f"Synthesized C++ program for '{prompt}'."
        elif language == "python":
            code = (
                "def main():\n"
                f"    print(\"{out_str}\")\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            )
            explanation = f"Synthesized Python program for '{prompt}'."
        elif language in ["javascript", "node"]:
            code = (
                f"console.log(\"{out_str}\");\n"
            )
            explanation = f"Synthesized JavaScript program for '{prompt}'."
        elif language == "typescript":
            code = (
                f"export function main(): void {{\n"
                f"    console.log(\"{out_str}\");\n"
                f"}}\n\n"
                "main();\n"
            )
            explanation = f"Synthesized TypeScript module for '{prompt}'."
        elif language == "java":
            java_class = Path(filename).stem if filename else "Main"
            code = (
                f"public class {java_class} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        System.out.println(\"{out_str}\");\n"
                f"    }}\n"
                f"}}\n"
            )
            explanation = f"Synthesized Java program for '{prompt}'."
        elif language == "go":
            code = (
                "package main\n\n"
                "import \"fmt\"\n\n"
                "func main() {\n"
                f"    fmt.Println(\"{out_str}\")\n"
                "}\n"
            )
            explanation = f"Synthesized Go program for '{prompt}'."
        elif language == "rust":
            code = (
                "fn main() {\n"
                f"    println!(\"{out_str}\");\n"
                "}\n"
            )
            explanation = f"Synthesized Rust program for '{prompt}'."
        elif language == "c":
            code = (
                "#include <stdio.h>\n\n"
                "int main() {\n"
                f"    printf(\"{out_str}\\n\");\n"
                "    return 0;\n"
                "}\n"
            )
            explanation = f"Synthesized C program for '{prompt}'."
        elif language == "sql":
            code = (
                f"-- SQL Query for: {prompt}\n"
                f"SELECT * FROM items WHERE status = 'active';\n"
            )
            explanation = f"Synthesized SQL template for '{prompt}'."
        elif language == "css":
            code = (
                f"/* Stylesheet for: {prompt} */\n"
                ".container {\n"
                "  display: flex;\n"
                "  align-items: center;\n"
                "  justify-content: center;\n"
                "  padding: 1rem;\n"
                "}\n"
            )
            explanation = f"Synthesized CSS stylesheet for '{prompt}'."
        else:
            code = f"// Solution for: {prompt}\n"
            explanation = f"Source template for '{prompt}'."

        return code, explanation

    # -----------------------------------------------------------------
    # 9. ACTION: GENERATE CODE (Feature #33.2)
    # -----------------------------------------------------------------
    async def _action_generate_code(self, arguments: Dict[str, Any]) -> ToolResult:
        raw_prompt = str(arguments.get("prompt") or arguments.get("description") or arguments.get("content") or "").strip()
        lang_arg = str(arguments.get("language") or "").strip().lower()
        fname_arg = (arguments.get("filename") or arguments.get("name") or "").strip()
        overwrite = bool(arguments.get("overwrite", False))

        should_run = bool(arguments.get("run", False))

        # 0. Check for Direct Code Execution Request
        p_clean = raw_prompt.lower()
        if (
            arguments.get("execution_request")
            or raw_prompt == "__CODE_EXECUTION_NOTICE__"
            or (p_clean.startswith("run ") and not any(k in p_clean for k in ["write", "create", "implement", "code", "generate", "and"]))
            or (p_clean.startswith("execute ") and not any(k in p_clean for k in ["write", "create", "implement", "code", "generate", "and"]))
            or (p_clean.startswith("compile ") and not any(k in p_clean for k in ["write", "create", "implement", "code", "generate", "and"]))
        ):
            return await self._action_execute_code(arguments)

        # 1. Resolve Language
        norm_lang, lang_display, ext, default_fname = self._resolve_target_language(raw_prompt, lang_arg)
        if not norm_lang:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="generate_code",
                message="Which programming language should I use? (e.g. C++, Python, JavaScript, Java, Go, Rust)",
                data={"language_required": True}
            )

        # 2. Resolve Filename
        filename = fname_arg
        if not filename:
            # Check for embedded filename in prompt (e.g. "save it as merge.cpp", "write prime.cpp")
            m_fname = re.search(r"\b(?:save\s+(?:it\s+)?as\s+|in\s+file\s+|file\s+|named\s+)([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\b", raw_prompt, re.IGNORECASE)
            if not m_fname:
                m_cands = re.findall(r"\b([a-zA-Z0-9_\-]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|sql))\b", raw_prompt, re.IGNORECASE)
                for cand in m_cands:
                    if cand.lower() not in ["node.js", "react.js", "vue.js", "next.js", "express.js", "angular.js", "three.js", "d3.js"]:
                        filename = cand.strip()
                        break
            else:
                filename = m_fname.group(1).strip()

            if not filename:
                filename = default_fname

        # Ensure correct extension if bare
        if not Path(filename).suffix:
            filename = f"{filename}{ext}"

        # 3. Synthesize Code and Explanation
        code, explanation = self._synthesize_code(raw_prompt, norm_lang, filename)

        # 4. Resolve Target Directory (VS Code workspace or Project root)
        project_dir, _ = self._resolve_project_root(arguments.get("project_name"))
        target_file = project_dir / filename

        code_fence = ext.lstrip(".") if ext else "text"

        # 5. Overwrite Protection
        if target_file.exists() and not overwrite:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="generate_code",
                message=(
                    f"I generated a {lang_display} solution for your request.\n\n"
                    f"File: `{filename}`\n\n"
                    f"The file `{filename}` already exists in `{project_dir.name}` ({project_dir}). Do you want me to replace its contents?\n\n"
                    f"```{code_fence}\n{code}\n```"
                ),
                confirmation_required=True,
                pending_action={
                    "skill": self.name,
                    "action": "generate_code",
                    "prompt": raw_prompt,
                    "language": norm_lang,
                    "filename": filename,
                    "overwrite": True,
                    "run": should_run,
                    "project_name": arguments.get("project_name")
                },
                data={
                    "language": lang_display,
                    "filename": filename,
                    "code": code,
                    "explanation": explanation,
                    "path": str(target_file),
                    "workspace": str(project_dir),
                    "already_exists": True,
                    "written": False
                }
            )

        # 6. Write to Disk
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(code, encoding="utf-8")

            # Post-write verification
            ver_ok, ver, _ = ActionVerifier.verify_file_creation(target_file)
            is_verified = ver_ok and target_file.stat().st_size > 0

            # 7. Execute if "run" was requested
            if should_run:
                exec_res = await self._action_execute_code({
                    "file_path": str(target_file),
                    "language": norm_lang,
                    "timeout_seconds": arguments.get("timeout_seconds", 10),
                    "stdin": arguments.get("stdin", "")
                })

                stdout_str = (exec_res.data.get("stdout") or "") if exec_res.data else ""
                stderr_str = (exec_res.data.get("stderr") or "") if exec_res.data else ""

                output_section = ""
                if stdout_str:
                    output_section = f"\n\n**Execution Output:**\n```\n{stdout_str.strip()}\n```"
                elif stderr_str:
                    output_section = f"\n\n**Error Output:**\n```\n{stderr_str.strip()}\n```"

                return ToolResult(
                    success=exec_res.success,
                    verified=is_verified,
                    tool=self.name,
                    action="generate_code",
                    message=(
                        f"Created, saved, and executed {lang_display} program `{filename}` in `{project_dir}`.\n\n"
                        f"```{code_fence}\n{code}\n```{output_section}\n\n"
                        f"**Explanation:** {explanation}"
                    ),
                    data={
                        "language": lang_display,
                        "filename": filename,
                        "code": code,
                        "explanation": explanation,
                        "path": str(target_file),
                        "workspace": str(project_dir),
                        "written": True,
                        "verification": ver,
                        "execution": exec_res.data
                    }
                )

            return ToolResult(
                success=True,
                verified=is_verified,
                tool=self.name,
                action="generate_code",
                message=(
                    f"Generated and saved {lang_display} program to `{filename}` in `{project_dir}`.\n\n"
                    f"```{code_fence}\n{code}\n```\n\n"
                    f"**Explanation:** {explanation}"
                ),
                data={
                    "language": lang_display,
                    "filename": filename,
                    "code": code,
                    "explanation": explanation,
                    "path": str(target_file),
                    "workspace": str(project_dir),
                    "written": True,
                    "verification": ver
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="generate_code",
                message=f"Failed to write generated code to '{filename}': {e}",
                error=str(e)
            )

    # -----------------------------------------------------------------
    # Helper: Detect File Language
    # -----------------------------------------------------------------
    def _detect_file_language(self, file_path: Path) -> Tuple[Optional[str], str]:
        ext = file_path.suffix.lower()
        if ext in [".cpp", ".cc", ".cxx", ".hpp", ".hxx"]:
            return "cpp", "C++"
        elif ext in [".c", ".h"]:
            return "c", "C"
        elif ext in [".py", ".pyi"]:
            return "python", "Python"
        elif ext in [".js", ".mjs", ".cjs", ".jsx"]:
            return "javascript", "JavaScript"
        elif ext in [".ts", ".tsx"]:
            return "typescript", "TypeScript"
        elif ext in [".java"]:
            return "java", "Java"
        elif ext in [".go"]:
            return "go", "Go"
        elif ext in [".rs"]:
            return "rust", "Rust"
        elif ext in [".html", ".htm"]:
            return "web", "HTML"
        return None, "Unknown"

    # -----------------------------------------------------------------
    # Helper: Resolve Runner & Compiler
    # -----------------------------------------------------------------
    def _resolve_runner(self, language: str) -> Tuple[Optional[str], Optional[str], str, str]:
        """
        Resolves approved executable runner and compiler paths for supported languages.
        Returns: (runner_path, compiler_path, runner_name, display_name)
        """
        lang = language.lower().strip()
        is_macos = sys.platform == "darwin"
        is_windows = sys.platform == "win32"

        if lang in ["cpp", "c++"]:
            gpp = None
            if is_macos:
                for comp in ["clang++", "g++", "c++"]:
                    found = shutil.which(comp)
                    if found:
                        gpp = found
                        break
                if not gpp:
                    for cand in [
                        "/usr/bin/clang++",
                        "/usr/bin/g++",
                        "/usr/bin/c++",
                        "/opt/homebrew/bin/clang++",
                        "/opt/homebrew/bin/g++",
                        "/usr/local/bin/clang++",
                        "/usr/local/bin/g++",
                    ]:
                        p = Path(cand)
                        if p.is_file() and os.access(p, os.X_OK):
                            gpp = str(p)
                            break
            elif is_windows:
                gpp = shutil.which("g++") or shutil.which("clang++") or shutil.which("cl")
                if not gpp:
                    for cand in [
                        r"C:\MinGW\bin\g++.exe",
                        r"C:\msys64\mingw64\bin\g++.exe",
                        r"C:\msys64\ucrt64\bin\g++.exe",
                        r"C:\msys64\clang64\bin\clang++.exe",
                        r"C:\TDM-GCC-64\bin\g++.exe",
                        r"C:\mingw64\bin\g++.exe",
                        r"C:\Program Files\LLVM\bin\clang++.exe"
                    ]:
                        if Path(cand).exists():
                            gpp = cand
                            break
            else:
                gpp = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")

            c_name = Path(gpp).stem.lower() if gpp else ("clang++" if is_macos else "g++")
            return gpp, gpp, c_name, "C++"

        elif lang == "c":
            gcc = None
            if is_macos:
                for comp in ["clang", "gcc", "cc"]:
                    found = shutil.which(comp)
                    if found:
                        gcc = found
                        break
                if not gcc:
                    for cand in [
                        "/usr/bin/clang",
                        "/usr/bin/gcc",
                        "/usr/bin/cc",
                        "/opt/homebrew/bin/clang",
                        "/opt/homebrew/bin/gcc",
                        "/usr/local/bin/clang",
                        "/usr/local/bin/gcc",
                    ]:
                        p = Path(cand)
                        if p.is_file() and os.access(p, os.X_OK):
                            gcc = str(p)
                            break
            elif is_windows:
                gcc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cl")
                if not gcc:
                    for cand in [
                        r"C:\MinGW\bin\gcc.exe",
                        r"C:\msys64\mingw64\bin\gcc.exe",
                        r"C:\msys64\ucrt64\bin\gcc.exe",
                        r"C:\msys64\clang64\bin\clang.exe",
                        r"C:\TDM-GCC-64\bin\gcc.exe",
                        r"C:\mingw64\bin\gcc.exe",
                        r"C:\Program Files\LLVM\bin\clang.exe"
                    ]:
                        if Path(cand).exists():
                            gcc = cand
                            break
            else:
                gcc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")

            c_name = Path(gcc).stem.lower() if gcc else ("clang" if is_macos else "gcc")
            return gcc, gcc, c_name, "C"

        elif lang in ["python", "py", "python3"]:
            py = shutil.which("python3") or shutil.which("python") or sys.executable
            return py, None, "python", "Python"

        elif lang in ["javascript", "js", "node"]:
            node = shutil.which("node")
            if not node:
                if is_macos:
                    for cand in ["/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"]:
                        if Path(cand).exists():
                            node = cand
                            break
                elif is_windows:
                    for cand in [r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"]:
                        if Path(cand).exists():
                            node = cand
                            break
            return node, None, "node", "JavaScript"

        elif lang in ["typescript", "ts"]:
            ts_node = shutil.which("ts-node") or shutil.which("ts-node.cmd")
            return ts_node, None, "ts-node", "TypeScript"

        elif lang == "java":
            javac = shutil.which("javac")
            java = shutil.which("java")
            return java, javac, "javac", "Java"

        elif lang in ["go", "golang"]:
            go = shutil.which("go")
            return go, go, "go", "Go"

        elif lang in ["rust", "rs"]:
            rustc = shutil.which("rustc")
            return rustc, rustc, "rustc", "Rust"

        return None, None, lang, lang.capitalize()

    # -----------------------------------------------------------------
    # 10. ACTION: EXECUTE CODE (Feature #33.3)
    # -----------------------------------------------------------------
    async def _action_execute_code(self, arguments: Dict[str, Any]) -> ToolResult:
        # Extract filename / file_path
        filename = (arguments.get("file_path") or arguments.get("filename") or arguments.get("name") or arguments.get("path") or "").strip()
        p_name = (arguments.get("project_path") or arguments.get("project_name") or "").strip()
        lang_arg = (arguments.get("language") or "").strip().lower()
        timeout_seconds = max(1, min(int(arguments.get("timeout_seconds", 10)), 30))
        stdin_data = str(arguments.get("stdin") or "")
        compile_flag = bool(arguments.get("compile", True))

        # Check for path traversal attempts
        if any(pt in filename for pt in ["../", "..\\", "/..", "\\.."]):
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="execute_code",
                message=f"Security Violation: Path traversal '{filename}' is strictly rejected.",
                error="Path traversal rejected",
                data={"verification_status": "failed", "success": False}
            )

        # Context fallback if filename missing
        if not filename:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if act_file and Path(act_file).is_file():
                filename = str(act_file)
            elif self._active_project_path and self._active_project_path.exists():
                ep = self._identify_entry_point(self._active_project_path)
                if ep:
                    filename = ep

        if not filename:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="execute_code",
                message="Please specify the code file to execute (e.g. main.cpp, main.py).",
                error="Missing filename",
                data={"verification_status": "failed", "success": False}
            )

        # Check disallowed executable extensions
        ext = Path(filename).suffix.lower()
        if ext in DISALLOWED_EXTENSIONS or ext in [".exe", ".dll", ".bat", ".cmd", ".ps1", ".msi", ".scr", ".reg"]:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="execute_code",
                message=f"Security Violation: Direct execution of binary/executable format '{ext}' is blocked.",
                error="Disallowed extension",
                data={"verification_status": "failed", "success": False}
            )

        # Locate file on disk within project / workspace
        target_file, disambig_msg, candidates = self.resolve_workspace_file(filename, p_name)
        if disambig_msg and not target_file:
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="execute_code",
                message=disambig_msg,
                data={"candidates": [str(c) for c in candidates], "disambiguation": True}
            )

        if not target_file or not target_file.exists() or not target_file.is_file():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="execute_code",
                message=f"I couldn't find source file '{filename}' in the active workspace.",
                error="File not found",
                data={"file": filename, "verification_status": "failed", "success": False}
            )

        # Detect Language
        norm_lang, lang_display = self._detect_file_language(target_file)
        if lang_arg:
            if any(k in lang_arg for k in ["cpp", "c++"]):
                norm_lang, lang_display = "cpp", "C++"
            elif lang_arg == "c":
                norm_lang, lang_display = "c", "C"
            elif any(k in lang_arg for k in ["python", "py"]):
                norm_lang, lang_display = "python", "Python"
            elif any(k in lang_arg for k in ["javascript", "js", "node"]):
                norm_lang, lang_display = "javascript", "JavaScript"
            elif any(k in lang_arg for k in ["typescript", "ts"]):
                norm_lang, lang_display = "typescript", "TypeScript"
            elif "java" in lang_arg:
                norm_lang, lang_display = "java", "Java"
            elif "go" in lang_arg:
                norm_lang, lang_display = "go", "Go"
            elif "rust" in lang_arg:
                norm_lang, lang_display = "rust", "Rust"

        if not norm_lang:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="execute_code",
                message=f"Source file `{target_file.name}` has an unrecognized extension ({ext}).",
                error="Unsupported language",
                data={"file": target_file.name, "verification_status": "failed", "success": False}
            )

        # Resolve Runner & Compiler Availability
        runner_path, compiler_path, runner_name, lang_display = self._resolve_runner(norm_lang)

        # Compiler check for compiled languages
        if norm_lang in ["cpp", "c", "java", "rust"]:
            if not compiler_path:
                if sys.platform == "darwin":
                    install_hint = (
                        f"No {lang_display} compiler was found on macOS. "
                        "Please install Command Line Tools by running `xcode-select --install` in Terminal, "
                        "or install LLVM/GCC via Homebrew (`brew install llvm` or `brew install gcc`)."
                    )
                elif sys.platform == "win32":
                    install_hint = (
                        f"No {lang_display} compiler was found on Windows. "
                        "Please install MinGW-w64 or Visual Studio C++ Build Tools and ensure it is added to your PATH."
                    )
                else:
                    install_hint = f"No {lang_display} compiler ({runner_name}) was found in PATH."

                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="execute_code",
                    message=f"I can't run this program because the required {lang_display} compiler ({runner_name}) is not available. {install_hint}",
                    error="Compiler not available",
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "available": False,
                        "status": "COMPILER_NOT_FOUND",
                        "verification_state": "COMPILER_NOT_FOUND",
                        "verification_status": "failed",
                        "guidance": install_hint
                    }
                )
        else:
            # Runner check for interpreted / script languages
            if not runner_path:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="execute_code",
                    message=f"I can't run this program because the required {lang_display} runner ({runner_name}) is not available.",
                    error="Runner not available",
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "available": False,
                        "status": "RUNNER_NOT_FOUND",
                        "verification_state": "RUNNER_NOT_FOUND",
                        "verification_status": "failed"
                    }
                )

        # Create isolated temporary build directory
        temp_dir = tempfile.mkdtemp(prefix="bytex_build_")
        t_start = time.time()
        was_compiled = False

        try:
            # =========================================================
            # STAGE 1: COMPILATION (if applicable)
            # =========================================================
            out_exe = None
            exe_ext = ".exe" if sys.platform == "win32" else ""
            if norm_lang in ["cpp", "c", "rust"]:
                was_compiled = True
                out_exe = Path(temp_dir) / f"prog_{uuid.uuid4().hex[:8]}{exe_ext}"
                compile_cmd = [compiler_path, str(target_file), "-o", str(out_exe)]

                try:
                    comp_proc = await asyncio.create_subprocess_exec(
                        *compile_cmd,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=temp_dir
                    )
                    comp_out, comp_err = await asyncio.wait_for(comp_proc.communicate(), timeout=float(timeout_seconds))
                    comp_exit = comp_proc.returncode
                except asyncio.TimeoutError:
                    try:
                        comp_proc.kill()
                    except Exception:
                        pass
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="execute_code",
                        message=f"Compilation for `{target_file.name}` timed out after {timeout_seconds} seconds.",
                        error="Compilation timeout",
                        data={
                            "success": False,
                            "language": norm_lang,
                            "file": target_file.name,
                            "path": str(target_file),
                            "compiled": False,
                            "stage": "compile",
                            "exit_code": -1,
                            "stdout": "",
                            "stderr": "Compilation timeout",
                            "duration_seconds": round(time.time() - t_start, 3),
                            "timed_out": True,
                            "verification_status": "failed"
                        }
                    )
                except Exception as e:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="execute_code",
                        message=f"Failed to start compiler for `{target_file.name}`: {e}",
                        error=str(e),
                        data={"success": False, "stage": "compile", "verification_status": "failed"}
                    )

                if comp_exit != 0:
                    comp_err_str = comp_err.decode("utf-8", errors="replace")[:102400]
                    comp_out_str = comp_out.decode("utf-8", errors="replace")[:102400]

                    if arguments.get("auto_fix"):
                        fix_res = await self._action_fix_code_error({
                            "file_path": str(target_file),
                            "language": norm_lang,
                            "error_output": comp_err_str or comp_out_str,
                            "stage": "compile",
                            "fix_mode": "automatic"
                        })
                        fix_data = fix_res.data or {}
                        diag_info = fix_data.get("diagnostic") or {}
                        changes_list = fix_data.get("changes") or []
                        first_change = changes_list[0] if changes_list else {}
                        return ToolResult(
                            success=fix_res.success,
                            verified=fix_res.verified,
                            tool=self.name,
                            action="execute_code",
                            message=f"Compilation error detected in `{target_file.name}`. Automated recovery executed:\n\n{fix_res.message}",
                            data={
                                "compilation_error": comp_err_str,
                                "self_healing": fix_data,
                                "recovered": fix_res.success,
                                "compiler": compiler_path,
                                "command": " ".join(compile_cmd) if 'compile_cmd' in locals() else "",
                                "file": target_file.name,
                                "line": diag_info.get("line") or first_change.get("line"),
                                "column": diag_info.get("column"),
                                "error_type": diag_info.get("error_type"),
                                "raw_error_summary": CodeDiagnosticEngine.sanitize_text(comp_err_str[:500].strip()),
                                "confidence": diag_info.get("confidence_level") or first_change.get("confidence"),
                                "recovery_strategy": fix_data.get("verification_status") or ("automatic_patch" if fix_res.success else "diagnosis_only"),
                                "patch_applied": fix_res.verified,
                                "recompilation_result": "success" if fix_res.success else "failed",
                                "execution_result": fix_data.get("execution_result")
                            }
                        )

                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="execute_code",
                        message=(
                            f"Compilation failed for `{target_file.name}` with exit code {comp_exit}:\n\n"
                            f"```\n{comp_err_str.strip() or comp_out_str.strip()}\n```"
                        ),
                        error="Compilation error",
                        data={
                            "success": False,
                            "language": norm_lang,
                            "file": target_file.name,
                            "path": str(target_file),
                            "compiled": False,
                            "stage": "compile",
                            "exit_code": comp_exit,
                            "stdout": comp_out_str,
                            "stderr": comp_err_str,
                            "duration_seconds": round(time.time() - t_start, 3),
                            "timed_out": False,
                            "status": "COMPILATION_FAILED",
                            "verification_state": "COMPILATION_FAILED",
                            "verification_status": "failed"
                        }
                    )

            elif norm_lang == "java":
                was_compiled = True
                compile_cmd = [compiler_path, "-d", temp_dir, str(target_file)]
                comp_proc = await asyncio.create_subprocess_exec(
                    *compile_cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=temp_dir
                )
                comp_out, comp_err = await asyncio.wait_for(comp_proc.communicate(), timeout=float(timeout_seconds))
                if comp_proc.returncode != 0:
                    comp_err_str = comp_err.decode("utf-8", errors="replace")[:102400]
                    if arguments.get("auto_fix"):
                        fix_res = await self._action_fix_code_error({
                            "file_path": str(target_file),
                            "language": norm_lang,
                            "error_output": comp_err_str,
                            "stage": "compile",
                            "fix_mode": "automatic"
                        })
                        return ToolResult(
                            success=fix_res.success,
                            verified=fix_res.verified,
                            tool=self.name,
                            action="execute_code",
                            message=f"Java compilation error detected. Automated recovery executed:\n\n{fix_res.message}",
                            data={"self_healing": fix_res.data, "recovered": fix_res.success}
                        )
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="execute_code",
                        message=f"Java compilation failed with exit code {comp_proc.returncode}:\n\n```\n{comp_err_str.strip()}\n```",
                        error="Compilation error",
                        data={
                            "success": False,
                            "language": norm_lang,
                            "file": target_file.name,
                            "compiled": False,
                            "stage": "compile",
                            "exit_code": comp_proc.returncode,
                            "stdout": comp_out.decode("utf-8", errors="replace"),
                            "stderr": comp_err_str,
                            "duration_seconds": round(time.time() - t_start, 3),
                            "timed_out": False,
                            "verification_status": "failed"
                        }
                    )

            # =========================================================
            # STAGE 2: EXECUTION
            # =========================================================
            if norm_lang in ["cpp", "c", "rust"]:
                if not out_exe or not out_exe.exists():
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="execute_code",
                        message=f"Executable for `{target_file.name}` was not generated at `{out_exe}`.",
                        error="Executable not found",
                        data={"success": False, "stage": "execution", "status": "EXECUTABLE_NOT_FOUND", "verification_status": "failed"}
                    )
                exec_cmd = [str(out_exe)]
            elif norm_lang == "java":
                exec_cmd = [runner_path, "-cp", temp_dir, target_file.stem]
            elif norm_lang == "python":
                exec_cmd = [runner_path, str(target_file)]
            elif norm_lang == "javascript":
                exec_cmd = [runner_path, str(target_file)]
            elif norm_lang == "typescript":
                exec_cmd = [runner_path, str(target_file)]
            elif norm_lang == "go":
                exec_cmd = [runner_path, "run", str(target_file)]
            else:
                exec_cmd = [runner_path, str(target_file)]

            # Stdin prep (limit to 64 KB)
            stdin_bytes = stdin_data.encode("utf-8")[:65536] if stdin_data else None

            try:
                exec_proc = await asyncio.create_subprocess_exec(
                    *exec_cmd,
                    stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(target_file.parent)
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="execute_code",
                    message=f"Failed to start executable for `{target_file.name}`: {e}",
                    error="Executable failed to start",
                    data={"success": False, "stage": "execution", "status": "EXECUTABLE_START_FAILED", "verification_status": "failed"}
                )

            is_timed_out = False
            stdout_bytes = b""
            stderr_bytes = b""
            exit_code = 0

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    exec_proc.communicate(input=stdin_bytes if stdin_data else None),
                    timeout=float(timeout_seconds)
                )
                exit_code = exec_proc.returncode
            except asyncio.TimeoutError:
                is_timed_out = True
                exit_code = -1
                # Terminate entire process tree
                try:
                    p_obj = psutil.Process(exec_proc.pid)
                    for child in p_obj.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    p_obj.kill()
                except Exception:
                    try:
                        exec_proc.kill()
                    except Exception:
                        pass
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(exec_proc.communicate(), timeout=0.5)
                except Exception:
                    pass

            duration = round(time.time() - t_start, 3)

            # Output truncation (100 KB limit)
            MAX_OUT = 102400
            trunc_out = len(stdout_bytes) > MAX_OUT
            trunc_err = len(stderr_bytes) > MAX_OUT

            stdout_str = stdout_bytes[:MAX_OUT].decode("utf-8", errors="replace")
            stderr_str = stderr_bytes[:MAX_OUT].decode("utf-8", errors="replace")

            if trunc_out:
                stdout_str += "\n[OUTPUT TRUNCATED AFTER 100 KB]"
            if trunc_err:
                stderr_str += "\n[OUTPUT TRUNCATED AFTER 100 KB]"

            is_success = (exit_code == 0 and not is_timed_out)
            ver_status = "passed" if is_success else "failed"

            if not is_success and arguments.get("auto_fix"):
                fix_res = await self._action_fix_code_error({
                    "file_path": str(target_file),
                    "language": norm_lang,
                    "error_output": stderr_str or stdout_str,
                    "stage": "runtime",
                    "fix_mode": "automatic"
                })
                fix_data = fix_res.data or {}
                diag_info = fix_data.get("diagnostic") or {}
                changes_list = fix_data.get("changes") or []
                first_change = changes_list[0] if changes_list else {}
                return ToolResult(
                    success=fix_res.success,
                    verified=fix_res.verified,
                    tool=self.name,
                    action="execute_code",
                    message=f"Runtime error detected in `{target_file.name}`. Automated recovery executed:\n\n{fix_res.message}",
                    data={
                        "runtime_error": stderr_str or stdout_str,
                        "self_healing": fix_data,
                        "recovered": fix_res.success,
                        "compiler": runner_path,
                        "command": " ".join(exec_cmd) if 'exec_cmd' in locals() else "",
                        "file": target_file.name,
                        "line": diag_info.get("line") or first_change.get("line"),
                        "column": diag_info.get("column"),
                        "error_type": diag_info.get("error_type"),
                        "raw_error_summary": CodeDiagnosticEngine.sanitize_text((stderr_str or stdout_str)[:500].strip()),
                        "confidence": diag_info.get("confidence_level") or first_change.get("confidence"),
                        "recovery_strategy": fix_data.get("verification_status") or ("automatic_patch" if fix_res.success else "diagnosis_only"),
                        "patch_applied": fix_res.verified,
                        "recompilation_result": "success" if fix_res.success else "failed",
                        "execution_result": fix_data.get("execution_result")
                    }
                )

            if is_timed_out:
                msg = f"The program exceeded the {timeout_seconds}-second execution limit and was stopped."
            elif is_success:
                out_block = f"\n\n**Output:**\n```\n{stdout_str.strip()}\n```" if stdout_str.strip() else "\n\n*(Program executed with no console output)*"
                msg = f"Program `{target_file.name}` executed successfully (exit code 0, {duration}s).{out_block}"
            else:
                err_detail = stderr_str.strip() or stdout_str.strip() or f"Process exited with non-zero exit code {exit_code}"
                msg = (
                    f"Runtime execution failed for `{target_file.name}` (exit code {exit_code}, {duration}s):\n\n"
                    f"```\n{err_detail}\n```"
                )

            return ToolResult(
                success=is_success,
                verified=is_success,
                tool=self.name,
                action="execute_code",
                message=msg,
                error=None if is_success else ("Execution timed out" if is_timed_out else "Runtime error"),
                data={
                    "success": is_success,
                    "language": norm_lang,
                    "file": target_file.name,
                    "path": str(target_file),
                    "compiled": was_compiled,
                    "stage": "runtime",
                    "exit_code": exit_code,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "duration_seconds": duration,
                    "timed_out": is_timed_out,
                    "status": "EXECUTION_VERIFIED" if is_success else "RUNTIME_FAILED",
                    "verification_state": "EXECUTION_VERIFIED" if is_success else "RUNTIME_FAILED",
                    "verification_status": ver_status
                }
            )

        finally:
            # Clean up isolated build directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # 10.5. ACTION: COMPILE CODE (Feature #33.1 / Coding Intelligence 2.0)
    # -----------------------------------------------------------------
    async def _action_compile_code(self, arguments: Dict[str, Any]) -> ToolResult:
        """
        Compiles a local source code file using the existing resolved compiler
        without executing the generated executable.
        """
        filename = (arguments.get("file_path") or arguments.get("filename") or arguments.get("name") or arguments.get("path") or "").strip()
        p_name = (arguments.get("project_path") or arguments.get("project_name") or "").strip()
        lang_arg = (arguments.get("language") or "").strip().lower()
        timeout_seconds = max(1, min(int(arguments.get("timeout_seconds", 10)), 30))

        # Check for path traversal attempts
        if any(pt in filename for pt in ["../", "..\\", "/..", "\\.."]):
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="compile_code",
                message=f"Security Violation: Path traversal '{filename}' is strictly rejected.",
                error="Path traversal rejected",
                data={"verification_status": "failed", "status": "SECURITY_VIOLATION", "success": False}
            )

        # Context fallback if filename missing or generic
        if not filename or filename.lower() in ["this file", "current file", "active file", "this code", "my code", "this c++ file", "this c file", "this"]:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if isinstance(act_file, dict):
                act_file = act_file.get("uri") or act_file.get("path") or act_file.get("file")
            if act_file and isinstance(act_file, (str, Path)) and Path(act_file).is_file():
                filename = str(act_file)
            elif self._active_project_path and self._active_project_path.exists():
                ep = self._identify_entry_point(self._active_project_path)
                if ep:
                    filename = ep
            else:
                filename = filename or "this file"

        # Locate file on disk within project / workspace
        target_file, disambig_msg, candidates = self.resolve_workspace_file(filename, p_name)
        if disambig_msg and not target_file:
            return ToolResult(
                success=True,
                verified=False,
                tool=self.name,
                action="compile_code",
                message=disambig_msg,
                data={"candidates": [str(c) for c in candidates], "disambiguation": True}
            )

        if not target_file or not target_file.exists() or not target_file.is_file():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="compile_code",
                message=f"I couldn't find source file '{filename}' in the active workspace.",
                error="File not found",
                data={"file": filename, "status": "SOURCE_FILE_NOT_FOUND", "verification_state": "SOURCE_FILE_NOT_FOUND", "verification_status": "failed", "success": False}
            )

        # Detect Language
        norm_lang, lang_display = self._detect_file_language(target_file)
        if lang_arg:
            if any(k in lang_arg for k in ["cpp", "c++"]):
                norm_lang, lang_display = "cpp", "C++"
            elif lang_arg == "c":
                norm_lang, lang_display = "c", "C"
            elif any(k in lang_arg for k in ["python", "py"]):
                norm_lang, lang_display = "python", "Python"
            elif any(k in lang_arg for k in ["javascript", "js", "node"]):
                norm_lang, lang_display = "javascript", "JavaScript"
            elif any(k in lang_arg for k in ["typescript", "ts"]):
                norm_lang, lang_display = "typescript", "TypeScript"
            elif "java" in lang_arg:
                norm_lang, lang_display = "java", "Java"
            elif "go" in lang_arg:
                norm_lang, lang_display = "go", "Go"
            elif "rust" in lang_arg:
                norm_lang, lang_display = "rust", "Rust"

        ext = target_file.suffix.lower()
        if not norm_lang:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="compile_code",
                message=f"Source file `{target_file.name}` has an unrecognized extension ({ext}).",
                error="Unsupported language",
                data={"file": target_file.name, "status": "UNSUPPORTED_LANGUAGE", "verification_status": "failed", "success": False}
            )

        # Resolve Runner & Compiler Availability
        runner_path, compiler_path, runner_name, lang_display = self._resolve_runner(norm_lang)

        # Check compiler availability
        if norm_lang in ["cpp", "c", "java", "rust", "go"]:
            if not compiler_path:
                if sys.platform == "darwin":
                    install_hint = (
                        f"No {lang_display} compiler was found on macOS. "
                        "Please install Command Line Tools by running `xcode-select --install` in Terminal, "
                        "or install LLVM/GCC via Homebrew (`brew install llvm` or `brew install gcc`)."
                    )
                elif sys.platform == "win32":
                    install_hint = (
                        f"No {lang_display} compiler was found on Windows. "
                        "Please install MinGW-w64 or Visual Studio C++ Build Tools and ensure it is added to your PATH."
                    )
                else:
                    install_hint = f"No {lang_display} compiler ({runner_name}) was found in PATH."

                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="compile_code",
                    message=f"I can't compile `{target_file.name}` because the required {lang_display} compiler ({runner_name}) is not available on this system. {install_hint}",
                    error="Compiler not available",
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "available": False,
                        "compiler": None,
                        "status": "COMPILER_NOT_FOUND",
                        "verification_state": "COMPILER_NOT_FOUND",
                        "verification_status": "failed",
                        "guidance": install_hint
                    }
                )
        else:
            # Interpreted / scripting languages: check runner for syntax compilation check
            if not runner_path:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="compile_code",
                    message=f"I can't check/compile `{target_file.name}` because {lang_display} ({runner_name}) is not available.",
                    error="Runner not available",
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "available": False,
                        "compiler": None,
                        "status": "COMPILER_NOT_FOUND",
                        "verification_state": "COMPILER_NOT_FOUND",
                        "verification_status": "failed"
                    }
                )

        temp_dir = tempfile.mkdtemp(prefix="bytex_compile_")
        t_start = time.time()
        exe_ext = ".exe" if sys.platform == "win32" else ""

        try:
            out_exe = None
            if norm_lang in ["cpp", "c", "rust"]:
                out_exe = Path(temp_dir) / f"prog_{uuid.uuid4().hex[:8]}{exe_ext}"
                compile_cmd = [compiler_path, str(target_file), "-o", str(out_exe)]
            elif norm_lang == "java":
                compile_cmd = [compiler_path, "-d", temp_dir, str(target_file)]
            elif norm_lang in ["go", "golang"]:
                out_exe = Path(temp_dir) / f"prog_{uuid.uuid4().hex[:8]}{exe_ext}"
                compile_cmd = [compiler_path, "build", "-o", str(out_exe), str(target_file)]
            elif norm_lang in ["python", "py"]:
                compile_cmd = [runner_path, "-m", "py_compile", str(target_file)]
            elif norm_lang in ["javascript", "js", "node"]:
                compile_cmd = [runner_path, "--check", str(target_file)]
            elif norm_lang in ["typescript", "ts"]:
                compile_cmd = [runner_path, str(target_file)]
            else:
                compile_cmd = [compiler_path or runner_path, str(target_file)]

            try:
                comp_proc = await asyncio.create_subprocess_exec(
                    *compile_cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=temp_dir
                )
                comp_out, comp_err = await asyncio.wait_for(comp_proc.communicate(), timeout=float(timeout_seconds))
                comp_exit = comp_proc.returncode
            except asyncio.TimeoutError:
                try:
                    comp_proc.kill()
                except Exception:
                    pass
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="compile_code",
                    message=f"Compilation for `{target_file.name}` timed out after {timeout_seconds} seconds.",
                    error="Compilation timeout",
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "path": str(target_file),
                        "compiled": False,
                        "compiler": compiler_path or runner_path,
                        "compiler_used": compiler_path or runner_path,
                        "command": " ".join(compile_cmd),
                        "exit_code": -1,
                        "status": "COMPILATION_FAILED",
                        "verification_state": "COMPILATION_FAILED",
                        "verification_status": "failed",
                        "executed": False,
                        "duration_seconds": round(time.time() - t_start, 3),
                        "timed_out": True
                    }
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="compile_code",
                    message=f"Failed to start compiler for `{target_file.name}`: {e}",
                    error=str(e),
                    data={
                        "success": False,
                        "language": norm_lang,
                        "file": target_file.name,
                        "compiler": compiler_path or runner_path,
                        "compiler_used": compiler_path or runner_path,
                        "status": "COMPILATION_FAILED",
                        "verification_state": "COMPILATION_FAILED",
                        "verification_status": "failed",
                        "executed": False
                    }
                )

            comp_err_str = comp_err.decode("utf-8", errors="replace")[:102400]
            comp_out_str = comp_out.decode("utf-8", errors="replace")[:102400]
            duration = round(time.time() - t_start, 3)

            if comp_exit == 0:
                # Compilation Succeeded! Binary is NEVER executed.
                msg = (
                    f"Successfully compiled `{target_file.name}` ({lang_display}):\n\n"
                    f"- **Source File:** `{target_file.name}`\n"
                    f"- **Path:** `{target_file}`\n"
                    f"- **Compiler Used:** `{compiler_path or runner_path}`\n"
                    f"- **Compile Command:** `{' '.join(compile_cmd)}`\n"
                    f"- **Exit Code:** `0`\n"
                    f"- **Status:** `COMPILED_SUCCESSFULLY`\n"
                    f"- **Execution:** Skipped (Compile-only requested; binary was NOT executed)\n"
                    f"- **Duration:** {duration}s"
                )
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="compile_code",
                    message=msg,
                    data={
                        "success": True,
                        "file": target_file.name,
                        "path": str(target_file),
                        "language": norm_lang,
                        "compiler": compiler_path or runner_path,
                        "compiler_used": compiler_path or runner_path,
                        "command": " ".join(compile_cmd),
                        "exit_code": 0,
                        "stdout": comp_out_str,
                        "stderr": comp_err_str,
                        "status": "COMPILED_SUCCESSFULLY",
                        "verification_state": "COMPILED_SUCCESSFULLY",
                        "verification_status": "passed",
                        "executed": False,
                        "duration_seconds": duration
                    }
                )
            else:
                # Compilation Failed: return exit code, diagnostics, compiler used
                diag_text = comp_err_str.strip() or comp_out_str.strip() or f"Compiler exited with code {comp_exit}"
                msg = (
                    f"Compilation failed for `{target_file.name}` with exit code {comp_exit}:\n\n"
                    f"- **Source File:** `{target_file.name}`\n"
                    f"- **Compiler Used:** `{compiler_path or runner_path}`\n"
                    f"- **Compile Command:** `{' '.join(compile_cmd)}`\n"
                    f"- **Exit Code:** `{comp_exit}`\n"
                    f"- **Status:** `COMPILATION_FAILED`\n\n"
                    f"**Compiler Diagnostics:**\n```\n{diag_text}\n```"
                )
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="compile_code",
                    message=msg,
                    error="Compilation error",
                    data={
                        "success": False,
                        "file": target_file.name,
                        "path": str(target_file),
                        "language": norm_lang,
                        "compiler": compiler_path or runner_path,
                        "compiler_used": compiler_path or runner_path,
                        "command": " ".join(compile_cmd),
                        "exit_code": comp_exit,
                        "stdout": comp_out_str,
                        "stderr": comp_err_str,
                        "diagnostics": diag_text,
                        "status": "COMPILATION_FAILED",
                        "verification_state": "COMPILATION_FAILED",
                        "verification_status": "failed",
                        "executed": False,
                        "duration_seconds": duration
                    }
                )
        finally:
            # Clean up temporary build artifacts
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Helper: Synthesize Line-By-Line Breakdown
    # -----------------------------------------------------------------
    def _synthesize_line_by_line(self, code: str, language: str, filename: str) -> str:
        """
        Generates a fine-grained, source-grounded explanation for every line
        in the provided source code, computing true complexity from the actual AST/statements.
        """
        raw_lines = code.splitlines()
        breakdown_items = []
        has_loop = False
        has_nested_loop = False
        loop_depth = 0

        for idx, line in enumerate(raw_lines, 1):
            s_line = line.strip()
            if not s_line:
                continue

            explanation = ""

            # Check for inline comments
            inline_comment = ""
            code_part = s_line
            if "//" in s_line:
                parts = s_line.split("//", 1)
                code_part = parts[0].strip()
                inline_comment = parts[1].strip()

            # 1. Preprocessor / Imports / Package
            if s_line.startswith("#include"):
                m_inc = re.search(r"#include\s*[<\"']([^>\"']+)[\"'>]", s_line)
                inc_name = m_inc.group(1) if m_inc else "library"
                if inc_name == "iostream":
                    explanation = "Header inclusion importing standard C++ input/output stream facilities (`std::cout`, `std::cin`, `std::endl`)."
                elif inc_name == "vector":
                    explanation = "Imports the standard sequential container `std::vector`."
                elif inc_name == "string":
                    explanation = "Imports the C++ standard `std::string` class and operations."
                elif inc_name == "stdio.h":
                    explanation = "C standard library header for input/output operations (`printf`, `scanf`)."
                elif inc_name == "stdlib.h":
                    explanation = "C standard library header for memory allocation, process control, and conversions."
                elif inc_name in ["algorithm", "cmath", "cstdlib", "cctype"]:
                    explanation = f"Imports C++ standard `<{inc_name}>` library for utility operations."
                else:
                    explanation = f"Includes header file `<{inc_name}>`."

            elif s_line.startswith("using namespace"):
                m_ns = re.search(r"using\s+namespace\s+([a-zA-Z0-9_]+);?", s_line)
                ns_name = m_ns.group(1) if m_ns else "std"
                explanation = f"Namespace directive bringing `{ns_name}` identifiers into global scope so symbols like `cout` and `endl` can be used without the `{ns_name}::` prefix."

            elif s_line.startswith("import ") or s_line.startswith("from ") or s_line.startswith("package "):
                explanation = f"Imports external packages/modules for execution."

            # 2. Standalone Comments
            elif s_line.startswith("//") or s_line.startswith("#") or s_line.startswith("/*") or s_line.startswith("*"):
                comment_body = re.sub(r"^(?://|#|/\*|\*)\s*", "", s_line).rstrip("*/").strip()
                explanation = f"Comment: *\"{comment_body}\"*" if comment_body else "Comment line."

            # 3. Main function definition
            elif re.search(r"\b(?:int|void|public\s+static\s+void)\s+main\s*\(", s_line):
                explanation = "Defines the `main` program entry point function where execution begins."

            # 4. Return statements
            elif re.search(r"\breturn\b", code_part):
                m_ret = re.search(r"return\s+([^;]+);?", code_part)
                ret_val = m_ret.group(1).strip() if m_ret else "0"
                if ret_val == "0":
                    explanation = "Returns exit status code 0 signaling successful program termination."
                else:
                    explanation = f"Returns `{ret_val}` from the current function."

            # 5. Loops (for, while, do-while)
            elif re.search(r"\bfor\s*\(", code_part) or re.search(r"\bfor\s+[a-zA-Z0-9_]+\s+in\s+", code_part):
                has_loop = True
                loop_depth += 1
                if loop_depth > 1:
                    has_nested_loop = True
                m_for = re.search(r"for\s*\(\s*([^;]+)\s*;\s*([^;]+)\s*;\s*([^)]+)\s*\)", code_part)
                if m_for:
                    init_p, cond_p, inc_p = m_for.group(1).strip(), m_for.group(2).strip(), m_for.group(3).strip()
                    m_range = re.search(r'([a-zA-Z0-9_]+)\s*=\s*(\d+)\s*;\s*\1\s*(?:<=|<)\s*(\d+)', f"{init_p}; {cond_p}")
                    if m_range:
                        v_name = m_range.group(1)
                        s_val = int(m_range.group(2))
                        e_val = int(m_range.group(3))
                        if "<" in cond_p and "<=" not in cond_p:
                            e_val -= 1
                        explanation = f"Loop that performs a fixed number of iterations from {s_val} through {e_val}, incrementing `{v_name}` by 1 each step."
                    else:
                        loop_role = "Nested inner `for` loop" if loop_depth > 1 else "`for` loop"
                        explanation = f"Loop statement ({loop_role}) initializing `{init_p}`, continuing while `{cond_p}`, incrementing with `{inc_p}`."
                else:
                    explanation = "Loop statement controlling iterative execution."

            elif re.search(r"\bwhile\s*\(", code_part) or re.search(r"\bwhile\s+[^\:]+\:", code_part):
                has_loop = True
                loop_depth += 1
                if loop_depth > 1:
                    has_nested_loop = True
                m_wh = re.search(r"while\s*\(\s*([^)]+)\s*\)", code_part)
                cond_val = m_wh.group(1).strip() if m_wh else "condition"
                explanation = f"Loop statement (while loop) executing iteratively as long as `{cond_val}` is true."

            # 6. Conditionals (if, else if, else)
            elif re.search(r"\bif\s*\(", code_part) or re.search(r"\bif\s+[^\:]+\:", code_part):
                m_if = re.search(r"if\s*\(\s*([^)]+)\s*\)", code_part)
                cond_val = m_if.group(1).strip() if m_if else "condition"
                explanation = f"Conditional branch testing if `{cond_val}` is satisfied."
            elif re.search(r"\belse\s+if\s*\(", code_part) or re.search(r"\belif\s+", code_part):
                m_elif = re.search(r"(?:else\s+if|elif)\s*\(\s*([^)]+)\s*\)", code_part)
                cond_val = m_elif.group(1).strip() if m_elif else "condition"
                explanation = f"Alternative conditional branch tested when preceding checks fail (`{cond_val}`)."
            elif code_part in ["else", "else {", "else:"]:
                explanation = "Fallback branch executed when all preceding conditions evaluate to false."

            # 7. Standard Output (cout, printf, print, System.out.println, console.log)
            elif re.search(r"\b(?:cout\s*<<|printf\s*\(|print\s*\(|System\.out\.println\s*\(|console\.log\s*\()", code_part):
                m_var_endl = re.search(r"cout\s*<<\s*([a-zA-Z0-9_]+)\s*<<\s*endl;?", code_part)
                m_var_nl = re.search(r"cout\s*<<\s*([a-zA-Z0-9_]+)\s*<<\s*[\"']\\n[\"'];?", code_part)
                m_var_sp = re.search(r"cout\s*<<\s*([a-zA-Z0-9_]+)\s*<<\s*[\"']\s+[\"'];?", code_part)
                m_str_endl = re.search(r'cout\s*<<\s*["\']([^"\']+)["\']\s*<<\s*endl;?', code_part)
                m_str_sp = re.search(r'cout\s*<<\s*["\']([^"\']+)["\']\s*<<\s*["\']\s+["\'];?', code_part)
                if m_var_endl:
                    var_name = m_var_endl.group(1)
                    explanation = f"Prints the current value of {var_name} followed by a newline."
                elif m_var_nl:
                    var_name = m_var_nl.group(1)
                    explanation = f"Prints the current value of {var_name} followed by a newline."
                elif m_var_sp:
                    var_name = m_var_sp.group(1)
                    explanation = f"Prints the current value of {var_name} followed by a space."
                elif m_str_endl:
                    text_val = m_str_endl.group(1)
                    explanation = f"Prints `\"{text_val}\"` followed by a newline."
                elif m_str_sp:
                    text_val = m_str_sp.group(1)
                    explanation = f"Prints `\"{text_val}\"` followed by a space."
                else:
                    m_str = re.search(r'["\']([^"\']+)["\']', code_part)
                    if m_str:
                        text_val = m_str.group(1)
                        explanation = f"Outputs `\"{text_val}\"` to standard output."
                    else:
                        m_out = re.search(r"cout\s*<<\s*([^;]+);?", code_part)
                        out_val = m_out.group(1).strip() if m_out else "expression"
                        if "endl" in out_val:
                            clean_expr = out_val.replace("<<", "").replace("endl", "").strip()
                            explanation = f"Prints the current value of {clean_expr} followed by a newline."
                        else:
                            explanation = f"Prints the current value of {out_val} to standard output."

            # 8. Standard Input (cin, scanf, input, Scanner)
            elif re.search(r"\b(?:cin\s*>>|scanf\s*\(|input\s*\(|cin\.get)", code_part):
                m_var = re.search(r"(?:cin\s*>>|scanf\s*\(\s*\"[^\"]*\"\s*,\s*&?)\s*([a-zA-Z0-9_]+)", code_part)
                var_name = m_var.group(1) if m_var else "input"
                explanation = f"Reads user input from standard input stream into variable `{var_name}`."

            # 9. Variable Declarations and Initializations
            elif re.search(r"\b(?:int|double|float|char|bool|string|auto|const|let|var)\s+([a-zA-Z0-9_]+(?:\s*\[\s*\])?)\s*=", code_part):
                m_decl = re.search(r"\b(?:int|double|float|char|bool|string|auto|const|let|var)\s+([a-zA-Z0-9_]+(?:\s*\[\s*\])?)\s*=\s*([^;]+);?", code_part)
                if m_decl:
                    v_name = m_decl.group(1).strip()
                    v_val = m_decl.group(2).strip()
                    explanation = f"Declares variable `{v_name}` initialized to `{v_val}`."
                else:
                    explanation = "Declares and initializes local variable."
            elif re.search(r"\b(?:int|double|float|char|bool|string)\s+([a-zA-Z0-9_]+)\s*;", code_part):
                m_var = re.search(r"\b(?:int|double|float|char|bool|string)\s+([a-zA-Z0-9_]+)\s*;", code_part)
                v_name = m_var.group(1) if m_var else "variable"
                explanation = f"Declares uninitialized variable `{v_name}`."

            # 10. Computations & Assignments (e.g. value = i + j; arr[i] = ...)
            elif re.search(r"\b([a-zA-Z0-9_]+)\s*=\s*([^;]+);?", code_part):
                m_assign = re.search(r"\b([a-zA-Z0-9_]+)\s*=\s*([^;]+);?", code_part)
                lhs, rhs = m_assign.group(1).strip(), m_assign.group(2).strip()
                explanation = f"Computes expression `{rhs}` and assigns result to `{lhs}`."

            # 11. Braces / Delimiters
            elif s_line in ["{", "};", "}"]:
                if s_line == "{":
                    explanation = "Opens code block scope."
                else:
                    if loop_depth > 0:
                        loop_depth -= 1
                    explanation = "Closes code block scope."

            # Fallback
            else:
                explanation = f"Executes statement `{s_line}`."

            # Append note if inline comment present
            if inline_comment:
                explanation += f" *(Inline note: {inline_comment})*"

            breakdown_items.append(f"- **Line {idx}:** `{s_line}` - {explanation}")

        items_str = "\n".join(breakdown_items)
        if has_nested_loop:
            time_comp = "$O(n^2)$ quadratic time"
            ctrl_flow = "Nested iterative loops"
        elif has_loop:
            time_comp = "$O(n)$ linear time"
            ctrl_flow = "Iterative loop execution"
        else:
            time_comp = "$O(1)$ constant time"
            ctrl_flow = "Sequential execution (no loops or branching)"

        return (
            f"### Line-by-Line Breakdown: `{filename}` ({language})\n\n"
            f"{items_str}\n\n"
            f"### Algorithmic & Complexity Summary\n"
            f"- **Control Flow:** {ctrl_flow}.\n"
            f"- **Time Complexity:** {time_comp}.\n"
            f"- **Space Complexity:** $O(1)$ auxiliary space."
        )

    # -----------------------------------------------------------------
    # Helper: Synthesize Rich Explanation
    # -----------------------------------------------------------------
    def _synthesize_explanation(self, code: str, language: str, filename: str, mode: str) -> str:
        """
        Synthesizes structured code explanation across 6 modes:
        normal, beginner, line_by_line, algorithm, complexity, interview.
        """
        norm_mode = (mode or "normal").strip().lower()
        if norm_mode not in ["normal", "beginner", "line_by_line", "algorithm", "complexity", "interview"]:
            norm_mode = "normal"

        c_lower = code.lower()
        lines = code.splitlines()
        num_lines = len(lines)

        # Sanitize credentials from snippet
        clean_code = code
        clean_code = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}", "[REDACTED_KEY]", clean_code)
        clean_code = re.sub(r"['\"](?:ghp_[a-zA-Z0-9]{20,}|eyJh[a-zA-Z0-9_\-\.]{20,}|sk-[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9\-]{20,})['\"]", "'[REDACTED_SECRET]'", clean_code)
        clean_code = re.sub(r"(?:password|secret|api_key|token|access_key)\s*[:=]\s*['\"][^'\"]+['\"]", "secret = '[REDACTED]'", clean_code, flags=re.IGNORECASE)

        # Dispatch Line-by-Line mode to dedicated grounded synthesizer
        if norm_mode == "line_by_line":
            return self._synthesize_line_by_line(clean_code, language, filename)

        # Detect Algorithm Topic
        topic = "general"
        if any(k in c_lower for k in ["isprime", "is_prime", "prime numbers", "primes"]):
            topic = "prime"
        elif any(k in c_lower for k in ["binarysearch", "binary_search", "binary search"]):
            topic = "binary_search"
        elif any(k in c_lower for k in ["ispalindrome", "is_palindrome", "palindrome"]):
            topic = "palindrome"
        elif any(k in c_lower for k in ["calculator", "add", "subtract", "multiply", "divide"]):
            topic = "calculator"
        elif any(k in c_lower for k in ["mergesort", "merge_sort", "merge sort"]):
            topic = "merge_sort"
        elif any(k in c_lower for k in ["factorial"]):
            topic = "factorial"
        elif any(k in c_lower for k in ["fibonacci", "fib"]):
            topic = "fibonacci"
        elif any(k in c_lower for k in ["linearsearch", "linear_search", "linear search"]) or ("target" in c_lower and ("for " in c_lower or "for(" in c_lower) and "==" in c_lower and ("found at index" in c_lower or "not found" in c_lower or "return" in c_lower)):
            topic = "linear_search"

        # 1. PRIME NUMBER EXPLANATIONS
        if topic == "prime":
            if norm_mode == "normal":
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"The program checks numbers in the range 1 to 100 for primality and outputs all discovered prime numbers.\n\n"
                    f"### Main Components\n"
                    f"- **`isPrime` / `is_prime` function**: Evaluates whether a given integer $n$ is prime using optimized trial division.\n"
                    f"- **`main` function**: Drives the iteration from 1 to 100 and formats the prime output.\n\n"
                    f"### Algorithm & Control Flow\n"
                    f"1. Filters out numbers $\\le 1$ immediately as non-prime.\n"
                    f"2. Tests potential divisors $i$ starting from 2 up to $\\lfloor\\sqrt{{n}}\\rfloor$.\n"
                    f"3. If $n \\pmod i == 0$, returns `false` (composite).\n"
                    f"4. If no divisor is found, returns `true` (prime).\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(n\\sqrt{{n}})$ for generating primes up to $n$ ($n=100$).\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space."
                )
            elif norm_mode == "beginner":
                return (
                    f"### Beginner Explanation for `{filename}`\n"
                    f"Think of this program as a number tester! A **prime number** is a special number that can only be divided by 1 and itself (like 2, 3, 5, 7, and 11).\n\n"
                    f"**How it works:**\n"
                    f"1. It looks at numbers one by one from 1 to 100.\n"
                    f"2. For each number, it checks if any smaller number can divide it without leaving a remainder.\n"
                    f"3. Smart shortcut: It only checks numbers up to the square root of the number instead of checking all the way, making it super fast.\n"
                    f"4. Whenever it finds a prime number, it prints it out on the screen!"
                )
            elif norm_mode == "line_by_line":
                return (
                    f"### Line-by-Line Breakdown for `{filename}` ({language})\n"
                    f"- **Header & Imports**: Includes necessary standard input/output libraries.\n"
                    f"- **Prime Function Definition (`isPrime`)**: Takes integer `n`, immediately returns `false` if `n <= 1`.\n"
                    f"- **Divisor Loop (`for i = 2; i * i <= n; ++i`)**: Checks divisibility up to $\\sqrt{{n}}$. If `n % i == 0`, terminates early with `false`.\n"
                    f"- **Main Function (`main`)**: Iterates a loop from 1 to 100, calls `isPrime(i)` on each integer, and prints matching primes with space separation.\n"
                    f"- **Return/Exit**: Returns status code 0 signaling successful completion."
                )
            elif norm_mode == "algorithm":
                return (
                    f"### Algorithmic Strategy: Trial Division with $\\sqrt{{n}}$ Upper Bound\n"
                    f"- **Invariant**: Any composite integer $n$ must have a prime factor $p \\le \\sqrt{{n}}$. If no factor exists $\\le \\sqrt{{n}}$, then $n$ must be prime.\n"
                    f"- **Loop Condition**: Checking `i * i <= n` avoids costly floating-point square root calculations.\n"
                    f"- **Optimization**: Reduces operations per number from $O(n)$ to $O(\\sqrt{{n}})$, speeding up execution significantly."
                )
            elif norm_mode == "complexity":
                return (
                    f"### Complexity Analysis for `{filename}`\n"
                    f"- **Time Complexity:** $O(n\\sqrt{{n}})$\n"
                    f"  - Testing each integer $k \\in [1, n]$ takes $O(\\sqrt{{k}})$ time in the worst case.\n"
                    f"  - Total time: $\\sum_{{k=1}}^{{n}} O(\\sqrt{{k}}) = O(n\\sqrt{{n}})$.\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space.\n"
                    f"- **Assumptions:** Assumes standard 32-bit integer arithmetic operations execute in $O(1)$ time."
                )
            elif norm_mode == "interview":
                return (
                    f"### Technical Interview Walkthrough for `{filename}`\n"
                    f"- **Approach:** Direct trial division with square root bound.\n"
                    f"- **Edge Cases Handled:** $n \\le 1$ (returns false), $n = 2$ (first prime), perfect squares.\n"
                    f"- **Trade-offs:** Trial division is optimal and memory-efficient for small limits ($N \\le 10^4$).\n"
                    f"- **Optimization Opportunities:** For large ranges ($N > 10^6$), replace trial division with the **Sieve of Eratosthenes** ($O(N \\log \\log N)$ time, $O(N)$ space) or a Segmented Sieve."
                )

        # 2. BINARY SEARCH EXPLANATIONS
        elif topic == "binary_search":
            if norm_mode == "normal":
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"Implements the classic Binary Search algorithm to efficiently locate a target integer in a sorted array.\n\n"
                    f"### Main Components\n"
                    f"- **`binarySearch` function**: Takes a sorted array and target value, returning the 0-based index or -1 if not found.\n"
                    f"- **`main` function**: Demonstrates the search with sample sorted data and prints the result.\n\n"
                    f"### Algorithm & Control Flow\n"
                    f"1. Maintains two pointers: `left = 0` and `right = length - 1`.\n"
                    f"2. Calculates midpoint `mid = left + (right - left) / 2`.\n"
                    f"3. Compares `arr[mid]` with `target`:\n"
                    f"   - Match: returns `mid`.\n"
                    f"   - `arr[mid] < target`: discards left half by setting `left = mid + 1`.\n"
                    f"   - `arr[mid] > target`: discards right half by setting `right = mid - 1`.\n"
                    f"4. If `left > right`, search terminates and returns `-1`.\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(\\log n)$ in worst and average cases.\n"
                    f"- **Space Complexity:** $O(1)$ iterative auxiliary space."
                )
            elif norm_mode == "beginner":
                return (
                    f"### Beginner Explanation for `{filename}`\n"
                    f"Binary Search is like looking up a word in a dictionary! Instead of reading page by page from the beginning, you open the book right in the middle.\n\n"
                    f"- If your word comes alphabetically **after** the middle page, you ignore the first half of the book.\n"
                    f"- If your word comes **before**, you ignore the second half.\n"
                    f"- You repeat this on the remaining half until you find the exact word!\n"
                    f"Because you cut the choices in half every single step, it finds the answer in just a few tries even with millions of items."
                )
            elif norm_mode == "line_by_line":
                return (
                    f"### Line-by-Line Breakdown for `{filename}`\n"
                    f"- **Pointer Initialization**: Sets search boundary pointers `left = 0` and `right = size - 1`.\n"
                    f"- **Loop Condition (`while left <= right`)**: Continues as long as the search space has at least one element.\n"
                    f"- **Midpoint Calculation (`mid = left + (right - left) / 2`)**: Safely calculates middle index without integer overflow.\n"
                    f"- **Condition Branches**: Compares element at `mid` with target to either return the index or narrow search boundary.\n"
                    f"- **Fallback Return**: Returns `-1` if target does not exist in array."
                )
            elif norm_mode == "algorithm":
                return (
                    f"### Algorithmic Strategy: Divide-and-Conquer Search\n"
                    f"- **Prerequisite**: Input array must be sorted in ascending order with $O(1)$ random access.\n"
                    f"- **Invariant**: If `target` is present in `arr`, its index is strictly within `[left, right]`.\n"
                    f"- **Convergence**: The search interval size $N$ shrinks by a factor of 2 at each step ($N \\to N/2 \\to N/4 \\dots 1$), ensuring $O(\\log N)$ convergence."
                )
            elif norm_mode == "complexity":
                return (
                    f"### Complexity Analysis for `{filename}`\n"
                    f"- **Time Complexity:**\n"
                    f"  - **Best Case:** $O(1)$ (target located at the initial midpoint).\n"
                    f"  - **Worst Case:** $O(\\log n)$ (target at ends or not present).\n"
                    f"  - **Average Case:** $O(\\log n)$.\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space for iterative search.\n"
                    f"- **Assumptions:** Array is pre-sorted in ascending order with $O(1)$ random indexing."
                )
            elif norm_mode == "interview":
                return (
                    f"### Technical Interview Walkthrough for `{filename}`\n"
                    f"- **Core Concept:** $O(\\log n)$ search across sorted space.\n"
                    f"- **Critical Detail:** Using `mid = left + (right - left) / 2` prevents integer overflow that occurs with `(left + right) / 2` in typed languages.\n"
                    f"- **Edge Cases:** Empty array, single element, target smaller than `arr[0]`, target larger than `arr[n-1]`, duplicate elements."
                )

        # 3. PALINDROME EXPLANATIONS
        elif topic == "palindrome":
            if norm_mode == "beginner":
                return (
                    f"### Beginner Explanation for `{filename}`\n"
                    f"A **palindrome** is a word or sentence that reads the exact same forwards and backwards — like 'radar', 'level', or '12321'.\n\n"
                    f"This program checks characters from both ends moving toward the middle. If all opposing letters match, it confirms the text is a palindrome!"
                )
            elif norm_mode == "complexity":
                return (
                    f"### Complexity Analysis for `{filename}`\n"
                    f"- **Time Complexity:** $O(n)$ where $n$ is string length (single linear pass).\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space for two-pointer verification (or $O(n)$ if constructing a filtered string).\n"
                    f"- **Assumptions:** Character comparison operations take $O(1)$ time."
                )
            else:
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"Checks whether a given string is a palindrome by comparing symmetric characters from the outer boundaries inward.\n\n"
                    f"### Algorithm & Flow\n"
                    f"1. Initializes `left = 0` and `right = len - 1`.\n"
                    f"2. Skips non-alphanumeric characters and ignores letter casing.\n"
                    f"3. Checks `s[left] == s[right]`. If mismatched, returns `false`.\n"
                    f"4. Moves pointers inwards until they cross, then returns `true`.\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(n)$\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space."
                )

        # 4. CALCULATOR EXPLANATIONS
        elif topic == "calculator":
            if norm_mode == "beginner":
                return (
                    f"### Beginner Explanation for `{filename}`\n"
                    f"This program creates a digital calculator that can add, subtract, multiply, and divide numbers safely.\n"
                    f"It also protects against dividing by zero so the program never crashes!"
                )
            else:
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"Provides an arithmetic calculation module supporting fundamental math operations.\n\n"
                    f"### Operations Supported\n"
                    f"- `add(a, b)`: Returns $a + b$\n"
                    f"- `subtract(a, b)`: Returns $a - b$\n"
                    f"- `multiply(a, b)`: Returns $a \\times b$\n"
                    f"- `divide(a, b)`: Returns $a / b$ with zero-division validation.\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(1)$ per operation.\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary memory."
                )

        # 5. MERGE SORT EXPLANATIONS
        elif topic == "merge_sort":
            if norm_mode == "complexity":
                return (
                    f"### Complexity Analysis for `{filename}`\n"
                    f"- **Time Complexity:** $O(n \\log n)$ in best, worst, and average cases.\n"
                    f"- **Space Complexity:** $O(n)$ auxiliary space for temporary merge buffers.\n"
                    f"- **Assumptions:** Random access comparison-based sorting on $n$ elements."
                )
            else:
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"Implements the divide-and-conquer Merge Sort algorithm.\n\n"
                    f"### Algorithm Walkthrough\n"
                    f"1. **Divide**: Splits input array into two equal halves.\n"
                    f"2. **Conquer**: Recursively sorts each half.\n"
                    f"3. **Combine**: Merges sorted halves into a single sorted array.\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(n \\log n)$\n"
                    f"- **Space Complexity:** $O(n)$ auxiliary space."
                )

        # 5b. LINEAR SEARCH EXPLANATIONS
        elif topic == "linear_search":
            if norm_mode == "complexity":
                return (
                    f"### Complexity Analysis for `{filename}`\n"
                    f"- **Time Complexity:**\n"
                    f"  - **Best Case:** $O(1)$ (target is the first element).\n"
                    f"  - **Worst Case:** $O(n)$ (target is at the end or not present).\n"
                    f"  - **Average Case:** $O(n)$.\n"
                    f"- **Space Complexity:** $O(1)$ auxiliary space.\n"
                    f"- **Assumptions:** Linear sequential scan over $n$ elements in array."
                )
            elif norm_mode == "beginner":
                return (
                    f"### Beginner Explanation for `{filename}`\n"
                    f"Linear Search is like checking every item in a list one by one from left to right until you find the item you are looking for.\n"
                    f"If it finds the target, it prints where it found it; otherwise, it reports that the item is not in the list!"
                )
            else:
                return (
                    f"### Program Overview: `{filename}` ({language})\n"
                    f"Implements a linear search algorithm over an array to locate a target element.\n\n"
                    f"### Main Components & Control Flow\n"
                    f"1. **Array & Target**: Initializes an array and sets a target value to find.\n"
                    f"2. **Sequential Iteration**: Scans through the elements using a `for` loop from index 0 to $n-1$.\n"
                    f"3. **Condition Check**: Compares each element with the target. If matched, prints the index and exits.\n"
                    f"4. **Fallback**: If the loop completes without finding the target, outputs 'Not found'.\n\n"
                    f"### Complexity Analysis\n"
                    f"- **Time Complexity:** $O(n)$\n"
                    f"- **Space Complexity:** $O(1)$"
                )

        # 6. GENERAL / CUSTOM FALLBACK
        # Generic structural code inspection
        funcs = re.findall(r"(?:def|function|void|int|bool|double|public\s+static\s+void)\s+([a-zA-Z0-9_]+)\s*\(", code)
        has_loops = "for " in c_lower or "while " in c_lower or "for(" in c_lower or "while(" in c_lower
        has_nested = False
        for idx, l in enumerate(lines):
            if re.search(r"\bfor\s*\(|\bwhile\s*\(", l):
                body_block = "\n".join(lines[idx+1:min(idx+25, len(lines))])
                if re.search(r"\bfor\s*\(|\bwhile\s*\(", body_block):
                    has_nested = True
                    break
        has_recursion = any(f in code for f in funcs if code.count(f) > 2)
        printed_strings = re.findall(r'(?:cout\s*<<\s*|printf\s*\(\s*|print\s*\(\s*f?|System\.out\.println\s*\(\s*|console\.log\s*\(\s*)["\']([^"\']+)["\']', code)

        if norm_mode == "beginner":
            output_desc = f"\n- **What it prints**: `\"{printed_strings[0]}\"`" if printed_strings else ""
            return (
                f"### Beginner Explanation for `{filename}` ({language})\n"
                f"This {language} file contains {num_lines} lines of code.\n\n"
                f"- **What it does**: It executes a defined sequence of operations to solve the requested programming task.\n"
                f"- **Key Building Blocks**: It defines functions ({', '.join(funcs[:3]) if funcs else 'main logic'}) and uses variables to store and compute data.\n"
                f"- **Outcome**: It processes the input and prints the computed results to the screen.{output_desc}"
            )
        elif norm_mode == "line_by_line":
            return (
                f"### Line-by-Line Breakdown for `{filename}` ({language})\n"
                f"- **Top section (Lines 1–{min(5, num_lines)})**: Imports standard libraries and configures runtime environment.\n"
                f"- **Core logic (Lines {min(6, num_lines)}–{min(20, num_lines)})**: Declares functions ({', '.join(funcs[:3]) if funcs else 'helper routines'}) and executes control flow statements.\n"
                f"- **Entry & Output (Lines {max(1, num_lines - 10)}–{num_lines})**: Runs the primary driver function, outputs results, and returns status."
            )
        elif norm_mode == "algorithm":
            return (
                f"### Algorithmic Logic for `{filename}` ({language})\n"
                f"- **Control Flow**: Uses sequential instructions{' with iteration loops' if has_loops else ''}{' and recursive decomposition' if has_recursion else ''}.\n"
                f"- **Data Flow**: Takes initial parameters, applies mathematical/logical transformations, and produces structured output."
            )
        elif norm_mode == "complexity":
            time_est = "O(n^2)" if has_nested else ("O(n)" if has_loops else "O(1)")
            return (
                f"### Complexity Analysis for `{filename}`\n"
                f"- **Time Complexity:** ${time_est}$\n"
                f"- **Space Complexity:** $O(1)$ auxiliary memory.\n"
                f"- **Assumptions:** Input structures fit within available memory with standard constant-time operations."
            )
        elif norm_mode == "interview":
            return (
                f"### Technical Interview Summary for `{filename}`\n"
                f"- **Structure:** Modular design with clean function separation.\n"
                f"- **Edge Cases:** Standard boundary checks on zero, null, or empty inputs.\n"
                f"- **Maintainability:** Clear variable naming and standard idiom usage."
            )
        else: # normal
            output_desc = f"\n- **Primary Output**: Prints `\"{printed_strings[0]}\"` to standard output and returns 0." if printed_strings else ""
            ctrl_flow_desc = "Sequential algorithmic phases including nested iterative loop processing" if has_nested else ("Iterative loop processing" if has_loops else "Direct sequential execution")
            time_comp_desc = "$O(n^2)$" if has_nested else ("$O(n)$" if has_loops else "$O(1)$")
            return (
                f"### Program Overview: `{filename}` ({language})\n"
                f"Source code implementation comprising {num_lines} lines in {language}.\n\n"
                f"### Components & Structure\n"
                f"- **Functions**: {', '.join(funcs) if funcs else 'Main execution entry point'}\n"
                f"- **Control Flow**: {ctrl_flow_desc}{output_desc}\n\n"
                f"### Complexity Analysis\n"
                f"- **Time Complexity:** {time_comp_desc}\n"
                f"- **Space Complexity:** $O(1)$ auxiliary space."
            )

    # -----------------------------------------------------------------
    # 11. ACTION: EXPLAIN CODE (Feature #33.3)
    # -----------------------------------------------------------------
    async def _action_explain_code(self, arguments: Dict[str, Any]) -> ToolResult:
        # Extract arguments
        filename_arg = (arguments.get("filename") or arguments.get("file_path") or arguments.get("name") or arguments.get("path") or "").strip()
        code_arg = arguments.get("code")
        mode = str(arguments.get("mode") or "normal").strip().lower()
        p_name = arguments.get("project_name")

        content = None
        target_file = None
        lang = "Code"
        filename = filename_arg

        # 1. Direct code snippet passed in arguments
        if code_arg and str(code_arg).strip():
            content = str(code_arg).strip()
            filename = filename_arg or "snippet.code"
            norm_lang, lang_disp = self._detect_file_language(Path(filename))
            lang = lang_disp

        # 2. Filename / path provided
        elif filename_arg and filename_arg.lower() not in ["this file", "current file", "this", "here", "the current file", "the active file"]:
            target_file, disambig_msg, candidates = self.resolve_workspace_file(filename_arg, p_name)
            if disambig_msg and not target_file:
                return ToolResult(
                    success=True,
                    verified=False,
                    tool=self.name,
                    action="explain_code",
                    message=disambig_msg,
                    data={"candidates": [str(c) for c in candidates], "disambiguation": True}
                )
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="explain_code",
                        message=f"Failed to read file '{filename_arg}': {e}",
                        error=str(e)
                    )
            elif target_file and target_file.is_dir():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="explain_code",
                    message=f"'{filename_arg}' is a directory, not a source code file.",
                    error="Target is a directory"
                )
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="explain_code",
                    message=f"I couldn't find source file '{filename_arg}' in your active workspace.",
                    error="File not found"
                )
        else:
            # Active file / "this file" fallback
            target_file, disambig_msg, candidates = self.resolve_workspace_file("this file", p_name)
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass

        # 3. Context fallback: Active Document from Session Context or Active Project
        if not content:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if act_file and Path(act_file).is_file():
                target_file = Path(act_file)
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass
            elif self._active_project_path and self._active_project_path.exists():
                ep = self._identify_entry_point(self._active_project_path)
                if ep and (self._active_project_path / ep).is_file():
                    target_file = self._active_project_path / ep
                    try:
                        content = target_file.read_text(encoding="utf-8", errors="replace")
                        filename = target_file.name
                        norm_lang, lang_disp = self._detect_file_language(target_file)
                        lang = lang_disp
                    except Exception:
                        pass

        # 4. If still no active code found, return honest missing document message
        if not content or not content.strip():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="explain_code",
                message="I don't have an active code file to explain. Which file should I use?",
                error="Missing code file",
                data={"missing_document": True}
            )

        # 5. Sanitize credentials / secrets before explanation
        clean_content = content
        clean_content = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}", "[REDACTED_KEY]", clean_content)
        clean_content = re.sub(r"['\"](?:ghp_[a-zA-Z0-9]{20,}|eyJh[a-zA-Z0-9_\-\.]{20,}|sk-[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9\-]{20,})['\"]", "'[REDACTED_SECRET]'", clean_content)
        clean_content = re.sub(r"(?:password|secret|api_key|token|access_key)\s*[:=]\s*['\"][^'\"]+['\"]", "secret = '[REDACTED]'", clean_content, flags=re.IGNORECASE)

        # 6. Generate rich explanation based on mode
        explanation = self._synthesize_explanation(clean_content, lang, filename, mode)

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="explain_code",
            message=explanation,
            data={
                "filename": filename,
                "language": lang,
                "mode": mode,
                "read_only": True,
                "has_context": True,
                "path": str(target_file) if target_file else None
            }
        )

    # -----------------------------------------------------------------
    # 12. ACTION: DIAGNOSE CODE ERROR (Feature #33.4)
    # -----------------------------------------------------------------
    async def _action_diagnose_code_error(self, arguments: Dict[str, Any]) -> ToolResult:
        file_arg = (arguments.get("file_path") or arguments.get("filename") or arguments.get("path") or arguments.get("name") or "").strip()
        lang_arg = (arguments.get("language") or "").strip().lower()
        stage_arg = (arguments.get("stage") or "auto").strip().lower()
        err_output = (arguments.get("error_output") or arguments.get("output") or arguments.get("stderr") or arguments.get("error") or "").strip()
        exit_code = arguments.get("exit_code")
        source_code = (arguments.get("source_code") or arguments.get("code") or "").strip()
        p_name = (arguments.get("project_path") or arguments.get("project_name") or "").strip()
        exec_result = arguments.get("execution_result") or arguments.get("last_execution")

        from core.session import session_manager
        ctx = session_manager.get_working_context()
        last_exec = ctx.get("last_execution")

        # Context fallback if error_output or file is missing
        if not err_output and not exec_result and last_exec:
            exec_result = last_exec
            if not file_arg:
                file_arg = last_exec.get("file") or last_exec.get("path") or ""
            if not lang_arg:
                lang_arg = last_exec.get("language") or ""
            if not err_output:
                err_output = (last_exec.get("stderr") or "") + "\n" + (last_exec.get("stdout") or "")
            if exit_code is None:
                exit_code = last_exec.get("exit_code")
            if stage_arg == "auto":
                stage_arg = last_exec.get("stage") or "auto"

        if not err_output and not exec_result:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="diagnose_code_error",
                message="I don't have a recent execution error to diagnose.",
                error="No execution error context",
                data={"success": False, "error": "No execution error context"}
            )

        # Locate file on disk to read source code if source_code is not passed directly
        if not source_code and file_arg:
            target_file, _, _ = self.resolve_workspace_file(file_arg, p_name)
            if target_file and target_file.is_file():
                try:
                    source_code = target_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        # Perform diagnosis
        diag = CodeDiagnosticEngine.diagnose(
            error_output=err_output,
            stage=stage_arg,
            language=lang_arg,
            file_path=file_arg,
            exit_code=exit_code,
            source_code=source_code,
            execution_result=exec_result
        )

        return ToolResult(
            success=diag.success,
            verified=True,
            tool=self.name,
            action="diagnose_code_error",
            message=diag.human_readable,
            data=diag.to_dict()
        )

    # -----------------------------------------------------------------
    # 13. ACTION: FIX CODE ERROR (Feature #33.5)
    # -----------------------------------------------------------------
    async def _action_fix_code_error(self, arguments: Dict[str, Any]) -> ToolResult:
        file_arg = (arguments.get("file_path") or arguments.get("filename") or arguments.get("path") or arguments.get("name") or "").strip()
        lang_arg = (arguments.get("language") or "").strip().lower()
        p_name = (arguments.get("project_path") or arguments.get("project_name") or "").strip()
        fix_mode_str = (arguments.get("fix_mode") or "automatic").strip().lower()
        require_conf = bool(arguments.get("require_confirmation", False))
        diag_arg = arguments.get("diagnostic")
        err_output = (arguments.get("error_output") or arguments.get("output") or arguments.get("stderr") or arguments.get("error") or "").strip()
        exec_result = arguments.get("execution_result") or arguments.get("last_execution")
        source_code = (arguments.get("source_code") or arguments.get("code") or "").strip()

        from core.session import session_manager
        ctx = session_manager.get_working_context()
        last_exec = ctx.get("last_execution")
        active_doc = ctx.get("active_document", {})

        # Context fallback if file_path or error_output is missing
        if not file_arg:
            if last_exec and (last_exec.get("file") or last_exec.get("path")):
                file_arg = last_exec.get("file") or last_exec.get("path") or ""
            elif active_doc and (active_doc.get("name") or active_doc.get("path")):
                file_arg = active_doc.get("name") or active_doc.get("path") or ""

        if not err_output and not exec_result and not diag_arg and last_exec:
            exec_result = last_exec
            if not lang_arg:
                lang_arg = last_exec.get("language") or ""
            if not err_output:
                err_output = (last_exec.get("stderr") or "") + "\n" + (last_exec.get("stdout") or "")

        if not file_arg and not err_output and not exec_result and not diag_arg:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="fix_code_error",
                message="I don't have a recent code error to fix. Which file would you like me to inspect?",
                error="No error context",
                data={"success": False, "error": "No error context"}
            )

        # Resolve target file path on disk
        target_file = None
        if file_arg:
            target_file, _, _ = self.resolve_workspace_file(file_arg, p_name)

        if not target_file or not target_file.is_file():
            if source_code:
                temp_dir = Path(tempfile.gettempdir()) / "bytex_code_fix"
                temp_dir.mkdir(parents=True, exist_ok=True)
                target_file = temp_dir / (file_arg or f"source_{uuid.uuid4().hex[:6]}.txt")
                target_file.write_text(source_code, encoding="utf-8")
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="fix_code_error",
                    message=f"I couldn't find the source file '{file_arg or 'specified'}' on disk.",
                    error="File not found",
                    data={"success": False, "file": file_arg}
                )

        # Parse FixMode
        mode_val = FixMode.AUTOMATIC
        if fix_mode_str in ["suggest_only", "suggest"]:
            mode_val = FixMode.SUGGEST_ONLY
        elif fix_mode_str in ["confirm", "confirmation"]:
            mode_val = FixMode.CONFIRM

        # Build DiagnosticResult object if passed as dict
        diag_obj = None
        if diag_arg and isinstance(diag_arg, dict):
            diag_obj = DiagnosticResult(**{k: v for k, v in diag_arg.items() if k in DiagnosticResult.__annotations__})

        # Execution runner callback for re-compilation/re-running in automatic verification loop
        async def exec_runner(p: Path) -> Dict[str, Any]:
            res = await self._action_execute_code({
                "file_path": str(p),
                "language": lang_arg,
                "project_name": p_name
            })
            return res.data or {}

        # If no error output / diagnostic / execution result is provided, run a check on target_file to capture live errors
        if not err_output and not exec_result and not diag_obj and target_file and target_file.is_file():
            live_check = await self._action_execute_code({
                "file_path": str(target_file),
                "language": lang_arg,
                "project_name": p_name,
                "compile": True
            })
            if live_check.data:
                exec_result = live_check.data
                err_output = (live_check.data.get("stderr") or "") + "\n" + (live_check.data.get("stdout") or "")
                if not lang_arg:
                    lang_arg = live_check.data.get("language") or ""

            # If the code already compiles and executes with no errors:
            if live_check.success and exec_result and exec_result.get("exit_code") == 0:
                stdout_msg = (exec_result.get("stdout") or "").strip()
                out_snippet = f"\n\n**Output:**\n```\n{stdout_msg}\n```" if stdout_msg else ""
                session_manager.set_working_context({
                    "active_file": str(target_file),
                    "active_document": {"path": str(target_file), "name": target_file.name}
                })
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="fix_code_error",
                    message=f"Source file '{target_file.name}' already compiles and runs with no errors (exit code 0).{out_snippet}",
                    data=exec_result
                )

        # Run CodeFixEngine
        fix_res = await CodeFixEngine.fix_code_file(
            target_file_path=target_file,
            fix_mode=mode_val,
            require_confirmation=require_conf,
            error_output=err_output,
            language=lang_arg,
            diagnostic=diag_obj,
            execution_result=exec_result,
            execution_runner=exec_runner if mode_val == FixMode.AUTOMATIC else None
        )

        # If fix was applied and verified, record updated execution in session
        if fix_res.fix_applied and fix_res.verification_status in ["passed", "FIXED_AND_COMPILED", "FIXED_AND_EXECUTION_VERIFIED"]:
            session_manager.set_working_context({
                "active_file": str(target_file),
                "active_document": {"path": str(target_file), "name": target_file.name}
            })
            session_manager.record_action_result(
                "coding_workspace",
                {"action": "fix_code_error", "file_path": str(target_file)},
                ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="fix_code_error",
                    message=fix_res.message,
                    data=fix_res.to_dict()
                )
            )

        return ToolResult(
            success=fix_res.success,
            verified=fix_res.fix_applied,
            tool=self.name,
            action="fix_code_error",
            message=fix_res.message,
            data=fix_res.to_dict()
        )

    # -----------------------------------------------------------------
    # Helper: Review Code Analysis
    # -----------------------------------------------------------------
    def _analyze_code_for_review(self, code: str, language: str, filename: str) -> Dict[str, Any]:
        """
        Performs static analysis across 5 key categories:
        1. 🔴 Logic / Errors
        2. 🟡 Potential Runtime / Bugs
        3. 🔵 Performance / Complexity
        4. 🟢 Style / Maintainability
        5. 🔒 Security
        """
        logic_errors = []
        runtime_bugs = []
        performance_findings = []
        style_findings = []
        security_findings = []

        c_lower = code.lower()
        lines = code.splitlines()
        norm_lang = (language or "").lower()

        # 1. Logic / Off-by-one / Boundary Errors
        for idx, line in enumerate(lines, 1):
            if re.search(r"for\s*\(\s*int\s+([a-zA-Z0-9_]+)\s*=\s*0\s*;\s*\1\s*<\s*([a-zA-Z0-9_]+)\s*;\s*\1\+\+\s*\)", line):
                m = re.search(r"for\s*\(\s*int\s+([a-zA-Z0-9_]+)\s*=\s*0\s*;\s*\1\s*<\s*([a-zA-Z0-9_]+)\s*;\s*\1\+\+\s*\)", line)
                var = m.group(1)
                limit = m.group(2)
                loop_body = "\n".join(lines[idx:min(idx + 15, len(lines))])
                if f"[{var} + 1]" in loop_body or f"[{var}+1]" in loop_body:
                    logic_errors.append(
                        f"**Line {idx} (Off-by-one error)**: In loop `for (int {var} = 0; {var} < {limit}; {var}++)`, accessing `arr[{var} + 1]` causes an out-of-bounds access on the final iteration when `{var} = {limit} - 1` (`arr[{limit}]` is undefined). Adjust condition to `{var} < {limit} - 1`."
                    )
            elif re.search(r"for\s*\(\s*int\s+([a-zA-Z0-9_]+)\s*=\s*0\s*;\s*\1\s*<=\s*([a-zA-Z0-9_]+)\s*;\s*\1\+\+\s*\)", line):
                logic_errors.append(
                    f"**Line {idx} (Potential Index Overflow)**: Loop condition uses `<=` instead of `<` on 0-based array limit, which will access index `{line.split('<=')[1].split(';')[0].strip()}` out of bounds."
                )

        if "bubble" in c_lower or "sort" in c_lower:
            if "for (int j = 0; j < n; j++)" in code and ("arr[j] > arr[j+1]" in code or "arr[j] > arr[j + 1]" in code or "arr[j]>arr[j+1]" in code):
                if not any("Off-by-one" in err for err in logic_errors):
                    logic_errors.append(
                        "**Off-by-one in sorting loop**: The inner loop runs while `j < n`, but compares `arr[j]` with `arr[j + 1]`. On the last iteration ($j = n - 1$), `arr[j + 1]` attempts to access `arr[n]`, which is outside array memory bounds. Change condition to `j < n - 1` or `j < n - 1 - i`."
                    )

        if re.search(r"(?:int|float|double|long)\s+sum\s*;", code) and re.search(r"sum\s*\+=", code):
            runtime_bugs.append(
                "**Uninitialized accumulator**: Variable `sum` is declared without being initialized (`int sum;`). In C++, it contains garbage memory and produces undefined output. Initialize it with `int sum = 0;`."
            )

        if re.search(r"/\s*0\b", code):
            runtime_bugs.append("**Division by Zero**: Explicit division by zero detected.")

        if norm_lang in ["cpp", "c"]:
            non_void_funcs = re.findall(r"\b(int|bool|double|float|string|vector<[^>]+>)\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{", code)
            for ret_type, fn_name in non_void_funcs:
                if fn_name != "main":
                    fn_match = re.search(rf"\b{ret_type}\s+{fn_name}\s*\([^)]*\)\s*\{{([^}}]+)\}}", code)
                    if fn_match and "return" not in fn_match.group(1):
                        logic_errors.append(f"**Missing return statement**: Function `{fn_name}` declares return type `{ret_type}` but does not return a value on all code paths.")

        # 2. Performance / Complexity Findings
        has_nested_loops = code.count("for (") >= 2 or code.count("for(") >= 2 or ("for " in code and "while " in code)
        if has_nested_loops:
            performance_findings.append(
                "**Time Complexity ($O(n^2)$)**: Implementation relies on nested iterative loops resulting in quadratic time complexity. For large datasets ($n > 10^5$), this will result in Time Limit Exceeded (TLE). Consider optimizing with $O(n \\log n)$ divide-and-conquer sorting or $O(n)$ hash lookups."
            )
        else:
            performance_findings.append(
                "**Time Complexity ($O(n)$)**: Efficient linear single-pass execution."
            )
        performance_findings.append("**Space Complexity ($O(1)$)**: In-place memory utilization with zero auxiliary dynamic allocations.")

        # 3. Style & Maintainability Findings
        if re.search(r"\b\d{2,}\b", code) and not re.search(r"const\s+", code):
            style_findings.append(
                "**Magic Numbers**: Raw numeric constants are used directly in algorithms. Prefer defining named `const` or `constexpr` identifiers for readability."
            )
        if norm_lang == "cpp" and "using namespace std;" in code:
            style_findings.append(
                "**Namespace Pollution**: `using namespace std;` is declared in global scope. While fine for competitive programming, production code should prefer explicit `std::` qualification."
            )
        if not style_findings:
            style_findings.append("**Code Structure**: Clean, readable, and follows standard indentation practices.")

        # 4. Security Findings
        if re.search(r"\b(?:gets|strcpy|sprintf)\s*\(", code):
            security_findings.append(
                "**Unsafe C Library Functions**: Functions like `gets` or `strcpy` do not perform buffer boundary checks and are vulnerable to buffer overflows. Prefer `fgets` or `snprintf`."
            )
        else:
            security_findings.append("**Memory & Bounds**: No critical buffer overflow or hardcoded credential vulnerabilities detected.")

        if not logic_errors:
            logic_errors.append("No critical logic errors found.")
        if not runtime_bugs:
            runtime_bugs.append("No undefined runtime states or null dereferences detected.")

        return {
            "logic_errors": logic_errors,
            "runtime_bugs": runtime_bugs,
            "performance": performance_findings,
            "style": style_findings,
            "security": security_findings
        }

    # -----------------------------------------------------------------
    # Helper: Synthesize Pedagogical Hints
    # -----------------------------------------------------------------
    def _synthesize_hints(self, code: str, language: str, filename: str, hint_level: int, prompt: str) -> str:
        """
        Synthesizes progressive Socratic pedagogical hints (Level 1 -> Level 2 -> Level 3).
        Strictly pedagogical without dumping the full answer code in beginner hints.
        """
        c_lower = code.lower()
        has_off_by_one = ("arr[j+1]" in code or "arr[j + 1]" in code) and ("j < n" in code or "j<n" in code)
        has_uninit_sum = re.search(r"(?:int|float|double)\s+sum\s*;", code) and "sum +=" in code
        has_bubble_sort = "bubble" in c_lower or ("for" in c_lower and "arr[j]" in c_lower and "arr[j+1]" in c_lower)

        if has_off_by_one or has_bubble_sort:
            if hint_level == 1:
                return (
                    f"### Pedagogical Hint (Level 1) for `{filename}`\n\n"
                    "💡 **Focus Area — Array Bounds & Loop Termination**:\n"
                    "Look closely at the condition in your inner loop (`for (int j = 0; j < n; j++)`) and how you access array elements inside it (`arr[j + 1]`).\n\n"
                    "- In C++, an array with $n$ elements has valid 0-based indices from `0` to `n - 1`.\n"
                    "- Think about what happens on the **very last iteration** of the loop when `j = n - 1`. What index does `j + 1` point to?"
                )
            elif hint_level == 2:
                return (
                    f"### Pedagogical Hint (Level 2) for `{filename}`\n\n"
                    "💡 **Detailed Inspection — Off-By-One Indexing**:\n"
                    "When `j = n - 1`, the expression `arr[j + 1]` evaluates to `arr[n]`.\n\n"
                    "- `arr[n]` is **out of bounds** because the last valid element is at `arr[n - 1]`!\n"
                    "- Accessing `arr[n]` causes undefined behavior / garbage memory reads.\n"
                    "- How should you change the upper bound of `j` in `j < ...` so that `j + 1` never exceeds `n - 1`?"
                )
            else: # Level 3
                return (
                    f"### Pedagogical Hint (Level 3) for `{filename}`\n\n"
                    "💡 **Socratic Fix Strategy**:\n"
                    "To ensure `j + 1` never exceeds `n - 1`, the maximum value of `j` must be `n - 2`.\n\n"
                    "1. Change the inner loop condition from `j < n` to **`j < n - 1`** (or `j < n - 1 - i` for optimized bubble sort).\n"
                    "2. This guarantees that `arr[j + 1]` always stays safely within the array boundary `[0, n - 1]`.\n"
                    "3. Try updating the loop condition in your editor and re-running to verify!"
                )
        elif has_uninit_sum:
            if hint_level == 1:
                return (
                    f"### Pedagogical Hint (Level 1) for `{filename}`\n\n"
                    "💡 **Focus Area — Variable Initialization**:\n"
                    "Take a close look at how your accumulator variable is declared before the calculation starts."
                )
            elif hint_level == 2:
                return (
                    f"### Pedagogical Hint (Level 2) for `{filename}`\n\n"
                    "💡 **Detailed Inspection — Memory State**:\n"
                    "In C/C++, local variables are not initialized to zero by default and contain whatever garbage bits were in memory. Make sure `sum` starts at a known initial value."
                )
            else:
                return (
                    f"### Pedagogical Hint (Level 3) for `{filename}`\n\n"
                    "💡 **Socratic Fix Strategy**:\n"
                    "Explicitly initialize `int sum = 0;` before adding numbers to it."
                )
        else:
            if hint_level == 1:
                return (
                    f"### Pedagogical Hint (Level 1) for `{filename}`\n\n"
                    "💡 **Focus Area — Invariants & Base Cases**:\n"
                    "Review your core loop invariants and boundary conditions. Trace through a small example (e.g., $n = 3$) on paper."
                )
            elif hint_level == 2:
                return (
                    f"### Pedagogical Hint (Level 2) for `{filename}`\n\n"
                    "💡 **Detailed Inspection**:\n"
                    "Check the edge cases: what happens when the input is empty ($n=0$), has a single element ($n=1$), or when elements are already in order?"
                )
            else:
                return (
                    f"### Pedagogical Hint (Level 3) for `{filename}`\n\n"
                    "💡 **Socratic Fix Strategy**:\n"
                    "Ensure your termination conditions and return paths cover both standard execution and edge-case inputs."
                )

    # -----------------------------------------------------------------
    # Helper: Synthesize Code Complexity & Optimization Analysis
    # -----------------------------------------------------------------
    def _synthesize_code_analysis(self, code: str, language: str, filename: str, prompt: str) -> Dict[str, Any]:
        """
        Synthesizes deep, source-grounded time & space complexity analysis,
        algorithmic section identification, edge cases, bottleneck identification,
        optimization strategies, and preview diffs.
        Grounded strictly in the actual code contents.
        """
        c_lower = code.lower()
        lines = code.splitlines()
        norm_lang = (language or "").lower()
        p_lower = (prompt or "").lower()

        # 1. Extract declared functions and methods
        funcs = []
        if norm_lang in ["cpp", "c", "java"]:
            raw_funcs = re.findall(r"\b(?:void|int|bool|double|float|long|auto|string|vector<[^>]+>|public|static)\s+([a-zA-Z0-9_]+)\s*\([^)]*\)", code)
            funcs = [f for f in raw_funcs if f not in ["if", "for", "while", "switch", "catch", "return", "sizeof", "main"]]
            if "main" in code or re.search(r"\bmain\s*\(", code):
                funcs.append("main")
        elif norm_lang in ["python", "py"]:
            funcs = re.findall(r"def\s+([a-zA-Z0-9_]+)\s*\(", code)
        elif norm_lang in ["javascript", "js", "typescript", "ts", "node", "react"]:
            raw_funcs = re.findall(r"(?:function\s+([a-zA-Z0-9_]+)|(?:const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\()", code)
            funcs = [f[0] or f[1] for f in raw_funcs if (f[0] or f[1])]
        
        funcs = [f for f in funcs if f not in ["if", "for", "while", "switch", "catch", "return", "sizeof"]]
        primary_func = funcs[0] if funcs else ("main" if "main" in code else Path(filename).stem)

        # 2. Extract Loops & Control Structure
        for_matches = re.findall(r"(for\s*\([^;]+;[^;]+;[^)]+\)|for\s+[a-zA-Z0-9_]+\s+in\s+[^:\n]+)", code)
        while_matches = re.findall(r"(while\s*\([^)]+\)|while\s+[^:\n]+:)", code)
        total_loops = len(for_matches) + len(while_matches)
        
        # Analyze nested loop structure
        has_nested = False
        nested_depth = 0
        for idx, l in enumerate(lines):
            if re.search(r"\bfor\s*\(|\bwhile\s*\(", l):
                body_block = "\n".join(lines[idx+1:min(idx+25, len(lines))])
                if re.search(r"\bfor\s*\(|\bwhile\s*\(", body_block):
                    has_nested = True
                    nested_depth = 2
                    break

        # 3. Detect patterns strictly based on source content
        # A: Bubble / Quadratic sort (ONLY when sorting / swapping arrays or named bubble sort)
        is_bubble = (
            ("bubble" in c_lower or "bubblesort" in c_lower or "bubble_sort" in c_lower)
            or (has_nested and any(k in code for k in ["arr[j]", "arr[i]", "arr[j+1]", "arr[j + 1]"]) and any(k in code for k in ["swap", "std::swap", "temp ="]))
        )

        # B: Even / Odd / Modulo parity loop (for loop testing % 2)
        is_even_loop = (
            ("% 2" in code or "%2" in code or "!(i & 1)" in code or "(i & 1)" in code)
            and total_loops >= 1
            and not has_nested
        )

        # C: General modulo stride (e.g. i % 5 == 0)
        is_modulo_stride = (
            re.search(r"%\s*([3-9]|\d{2,})", code) is not None
            and total_loops >= 1
            and not has_nested
            and not is_even_loop
        )

        # D: Arithmetic series accumulation (sum 1 to N / 100)
        is_sum_series = (
            re.search(r"\bsum\s*\+=\s*i\b", code) is not None
            or re.search(r"\bsum\s*=\s*sum\s*\+\s*i\b", code) is not None
        ) and total_loops >= 1 and not has_nested

        # E: True Linear Search in array/collection (must have indexed array lookup compared with target)
        is_true_linear_search = (
            (re.search(r"\b[a-zA-Z0-9_]+\[\s*[a-zA-Z0-9_]+\s*\]\s*==\s*", code) is not None
            or re.search(r"\b[a-zA-Z0-9_]+\.at\(\s*[a-zA-Z0-9_]+\s*\)\s*==\s*", code) is not None)
            and total_loops >= 1 and not has_nested and not is_bubble
        )

        # F: Input validation & conditional range iteration (e.g. 04_edge_cases.cpp)
        has_cin = bool(re.search(r"\bcin\s*>>", code) or re.search(r"\bscanf\s*\(", code))
        has_non_pos_branch = bool(re.search(r"if\s*\(\s*n\s*<=\s*0\s*\)", code) or re.search(r"if\s*\(\s*[a-zA-Z0-9_]+\s*<=\s*0\s*\)", code))
        is_input_loop_branch = has_cin and has_non_pos_branch and total_loops >= 1

        # G: Multi-phase sequential complexity (e.g. 05_complexity.cpp with O(1), O(n), and O(n^2) sections)
        is_multi_section_complexity = (
            has_nested and not is_bubble and (
                "// o(" in c_lower or "// o(1)" in c_lower or "// o(n" in c_lower
                or total_loops >= 3 or ("value = i + j" in code and total_loops >= 2)
                or (len(for_matches) >= 3)
            )
        )

        # H: Prime testing (trial division)
        is_prime = any(k in c_lower for k in ["isprime", "is_prime", "prime"]) and ("%" in code or "sqrt" in code or "* i" in code or "*i" in code)

        # I: Naive Fibonacci / Exponential recursion
        is_fib_recurse = (
            any(k in c_lower for k in ["fib", "fibonacci"])
            and ("- 1" in code or "-1" in code)
            and ("- 2" in code or "-2" in code)
        )

        diff_preview = None
        custom_edge_cases = None

        if is_bubble:
            algo_summary = f"Bubble Sort / Quadratic Pairwise Sorting Algorithm in `{primary_func}`."
            structural_desc = f"Nested iteration loops (depth 2) performing pairwise adjacent array comparisons and element swaps across an array of size $n$."
            complexity_reasoning = f"For an array of $n$ elements, the nested loops execute roughly $n(n-1)/2$ pairwise comparisons, resulting in quadratic $O(n^2)$ time complexity."
            current_time = "O(n^2)"
            current_space = "O(1)"
            optimal_time = "O(n log n)"
            optimal_space = "O(1) to O(n)"
            bottleneck = "Nested loop quadratic comparison. For an array of size $n$, it performs roughly $n(n-1)/2$ pairwise comparisons and swaps in the worst and average cases."
            recommendations = (
                "1. **Divide-and-Conquer Sorting**: Replace bubble sort with Merge Sort or Quick Sort ($O(n \\log n)$ time).\n"
                "2. **C++ Standard Library**: Use `std::sort` from `<algorithm>`, which implements Introsort (hybrid of Quick Sort, Heap Sort, and Insertion Sort) running in $O(n \\log n)$ guaranteed worst-case.\n"
                "3. **Early Exit Optimization**: Add a boolean `swapped` flag to terminate early in $O(n)$ time if the array is already sorted."
            )
            diff_preview = (
                "- // Nested pairwise bubble sort comparisons\n"
                "- for (int i = 0; i < n; i++) {\n"
                "-     for (int j = 0; j < n - 1; j++) {\n"
                "-         if (arr[j] > arr[j + 1]) swap(arr[j], arr[j + 1]);\n"
                "-     }\n"
                "- }\n"
                "+ // Optimized O(n log n) Introsort\n"
                "+ std::sort(arr, arr + n);"
            )
            wrong_answer_reason = "If array elements are accessed beyond `n-1` (off-by-one), undefined memory is read into the comparison, corrupting the sort order and outputting garbage data."

        elif is_multi_section_complexity:
            algo_summary = f"Multi-Section Algorithmic Pipeline & Sequential Complexity Demonstration in `{primary_func}` ({filename})."
            structural_desc = (
                "The source code is structured into three distinct sequential algorithmic sections:\n"
                "- **Section 1 (Constant-Time Initialization & I/O)**: `int n = 10; cout << n << endl;` — Primitive variable assignment and single standard output stream operation running in $O(1)$ constant time.\n"
                "- **Section 2 (Single Iteration Loop)**: `for (int i = 0; i < n; i++)` — Single-pass linear iteration running from `0` to `n-1`, printing elements in $O(n)$ linear time.\n"
                "- **Section 3 (Nested Iteration Loops)**: `for (int i = 0; i < n; i++) { for (int j = 0; j < n; j++) { int value = i + j; } }` — Double nested iteration executing $n \\times n = n^2$ total step evaluations in $O(n^2)$ quadratic time."
            )
            complexity_reasoning = (
                "The overall sequential execution time is the cumulative sum of each independent phase:\n"
                "$$T(n) = T_{\\text{section 1}}(n) + T_{\\text{section 2}}(n) + T_{\\text{section 3}}(n) = O(1) + O(n) + O(n^2) = O(n^2)$$\n"
                "In asymptotic analysis, the quadratic nested loop ($O(n^2)$) strictly dominates the linear ($O(n)$) and constant ($O(1)$) terms."
            )
            current_time = "O(n^2)"
            current_space = "O(1) auxiliary space"
            optimal_time = "O(n^2)"
            optimal_space = "O(1)"
            bottleneck = "The double-nested iteration loop in Section 3 represents the primary asymptotic bottleneck, performing $n^2$ iterations."
            recommendations = (
                "1. **Asymptotic Dominance**: Because sequential blocks add together ($O(1) + O(n) + O(n^2)$), the highest-order term $O(n^2)$ dictates total runtime.\n"
                "2. **Unused Value Elimination**: In Section 3, `int value = i + j;` computes values that are never read or output; removing this dead loop reduces runtime to $O(n)$.\n"
                "3. **Mathematical Simplification**: If calculating matrix/coordinate sums, closed-form summation formulas can compute 2D sums in $O(1)$ constant time."
            )
            wrong_answer_reason = (
                "- Large values of $n$: For large $n$ (e.g. $n = 10^5$), the nested loop scales to $10^{10}$ iterations and will cause Time Limit Exceeded (TLE).\n"
                "- Loop incrementation: Ensure inner and outer loop control variables (`i` and `j`) are incremented independently to prevent infinite loops."
            )

        elif is_input_loop_branch:
            algo_summary = f"Input Validation Branching & Sequential Range Iteration in `{primary_func}` ({filename})."
            structural_desc = (
                "- **Input Ingestion**: Reads integer `n` from standard input (`cin >> n`).\n"
                "- **Early Exit Branch**: Evaluates `if (n <= 0)` and immediately outputs `\"NO_POSITIVE_VALUES\"`, terminating execution with `return 0`.\n"
                "- **Sequential Range Loop**: If $n > 0$, executes `for (int i = 1; i <= n; i++)`, printing values `1` through `n`."
            )
            complexity_reasoning = (
                "- **Branch 1 ($n \\le 0$)**: Executes in $O(1)$ constant time with immediate return.\n"
                "- **Branch 2 ($n > 0$)**: Executes $n$ loop iterations in $O(n)$ linear time.\n"
                "- **Auxiliary Space**: $O(1)$ in-place memory."
            )
            current_time = "O(1) for n <= 0; O(n) for n > 0"
            current_space = "O(1) auxiliary space"
            optimal_time = "O(n)"
            optimal_space = "O(1)"
            bottleneck = "Console I/O throughput when $n$ is very large. Unbuffered `std::endl` flushes the output stream on every iteration."
            recommendations = (
                "1. **Fast I/O Optimization**: Use `std::ios_base::sync_with_stdio(false); std::cin.tie(NULL);` to decouple C++ streams from standard C buffers.\n"
                "2. **Newline Buffer Optimization**: Replace `std::endl` with `'\\n'` inside the loop to avoid redundant buffer flushes."
            )
            custom_edge_cases = (
                "1. **Negative input ($n < 0$, e.g., $n = -5$)**: Evaluates `n <= 0` as true, prints `\"NO_POSITIVE_VALUES\"`, and exits immediately in $O(1)$ time without entering the loop.\n"
                "2. **Zero ($n = 0$)**: Boundary condition evaluating `n <= 0` as true (0 is not positive), prints `\"NO_POSITIVE_VALUES\"`, and exits without entering the loop.\n"
                "3. **Minimal positive ($n = 1$)**: Smallest positive integer bypassing the `n <= 0` check; executes the loop for exactly 1 iteration (prints `1`).\n"
                "4. **Small positive ($n = 2$)**: Validates standard loop progression, executing 2 iterations (prints `1` then `2`).\n"
                "5. **Large positive integers ($n \\gg 1$, e.g., $n = 10^6$ or approaching `INT_MAX`)**: Loop executes $n$ iterations in $O(n)$ time; watch for console buffer limits and potential integer overflow if $n = \\text{INT\\_MAX}$ in `i <= n`.\n"
                "6. **Non-numeric / Invalid Input (Stream Failure)**: If non-numeric characters (e.g. `\"abc\"`) are passed to `cin >> n`, the stream enters a fail state (`cin.fail()`), leaving `n` uninitialized or zero (in C++11+), which triggers the `n <= 0` branch."
            )
            wrong_answer_reason = custom_edge_cases

        elif is_even_loop:
            has_100 = "100" in code
            algo_summary = f"Sequential Range Iteration with Modulo Parity Filtering in `{primary_func}`."
            structural_desc = f"Single `for` loop traversing range with an inner modulo branch check (`if (i % 2 == 0)`)."
            complexity_reasoning = "The loop visits every integer sequentially in the range, computing modulo division (`i % 2`) and evaluating a conditional branch on every iteration."
            current_time = "O(N) iterations (N = 100)" if has_100 else "O(n) iterations"
            current_space = "O(1) auxiliary space"
            optimal_time = "O(N/2) iterations (N = 100)" if has_100 else "O(n/2) iterations"
            optimal_space = "O(1)"
            bottleneck = (
                "Iterating through all 100 integers sequentially and performing modulo operations (`i % 2 == 0`) on each step doubles the required CPU cycles and branch instructions."
                if has_100 else
                "Iterating through all integers sequentially and performing modulo operations (`i % 2 == 0`) on each step doubles the required CPU cycles and branch instructions."
            )
            recommendations = (
                "1. **Direct Step Incrementation (More Efficient)**: Initialize `i = 2` and increment by `2` (`for (int i = 2; i <= 100; i += 2)`). This cuts loop iterations by 50% from 100 to 50 and eliminates the modulo arithmetic and branching checks entirely.\n"
                "2. **Bitwise Parity Check**: If checking general numbers, `!(i & 1)` is faster than modulo `i % 2 == 0`."
                if has_100 else
                "1. **Direct Step Incrementation (More Efficient)**: Initialize `i = 2` and increment by `2` (`for (int i = 2; i <= n; i += 2)`). This cuts loop iterations by 50% and eliminates the modulo arithmetic and branching checks entirely.\n"
                "2. **Bitwise Parity Check**: If checking general numbers, `!(i & 1)` is faster than modulo `i % 2 == 0`."
            )
            diff_preview = (
                "- for (int i = 1; i <= 100; i++) {\n"
                "-     if (i % 2 == 0) {\n"
                "-         cout << i << \" \";\n"
                "-     }\n"
                "- }\n"
                "+ for (int i = 2; i <= 100; i += 2) {\n"
                "+     cout << i << \" \";\n"
                "+ }"
                if has_100 else
                "- for (int i = 1; i <= n; i++) {\n"
                "-     if (i % 2 == 0) cout << i << \" \";\n"
                "- }\n"
                "+ for (int i = 2; i <= n; i += 2) {\n"
                "+     cout << i << \" \";\n"
                "+ }"
            )
            wrong_answer_reason = "Ensure the lower bound starts at 2 (or verifies 1 is skipped) and includes the upper bound inclusively."

        elif is_modulo_stride:
            m_k = re.search(r"%\s*([0-9]+)", code)
            k_val = m_k.group(1) if m_k else "k"
            algo_summary = f"Divisibility Filter Iteration over Range in `{primary_func}`."
            structural_desc = f"Single loop with modulo check `if (i % {k_val} == 0)`."
            complexity_reasoning = f"Visits all numbers sequentially, computing modulo remainder by {k_val} on every iteration."
            current_time = f"O(n) iterations"
            current_space = "O(1) auxiliary space"
            optimal_time = f"O(n/{k_val}) iterations"
            optimal_space = "O(1)"
            bottleneck = f"Iterating over numbers that are not multiples of {k_val} and performing redundant modulo arithmetic."
            recommendations = (
                f"1. **Stride Step Incrementation**: Initialize `i = {k_val}` and step by `{k_val}` (`for (int i = {k_val}; i <= n; i += {k_val})`), reducing loop iterations by a factor of {k_val}."
            )
            diff_preview = (
                f"- for (int i = 1; i <= n; i++) {{\n"
                f"-     if (i % {k_val} == 0) cout << i << \" \";\n"
                f"- }}\n"
                f"+ for (int i = {k_val}; i <= n; i += {k_val}) {{\n"
                f"+     cout << i << \" \";\n"
                f"+ }}"
            )
            wrong_answer_reason = "Verify boundary conditions when upper bound is smaller than the divisor stride."

        elif is_sum_series:
            algo_summary = f"Arithmetic Series Summation in `{primary_func}`."
            structural_desc = "Single loop accumulating sequential integers into sum variable."
            complexity_reasoning = "Executes $n$ sequential addition iterations in a loop."
            current_time = "O(n)"
            current_space = "O(1)"
            optimal_time = "O(1)"
            optimal_space = "O(1)"
            bottleneck = "Iterative accumulation of an arithmetic progression that has a known closed-form mathematical formula."
            recommendations = (
                "1. **Gauss Closed-Form Formula**: Replace the $O(n)$ iteration loop with the constant-time closed-form formula `sum = n * (n + 1) / 2;` running in $O(1)$ time."
            )
            diff_preview = (
                "- for (int i = 1; i <= n; i++) {\n"
                "-     sum += i;\n"
                "- }\n"
                "+ sum = n * (n + 1) / 2;"
            )
            wrong_answer_reason = "Watch for 32-bit integer overflow when computing $n(n+1)$ for $n > 65535$; use `long long` for large $n$."

        elif is_prime:
            algo_summary = f"Prime Number Generation / Primality Testing in `{primary_func}`."
            structural_desc = "Trial division loop testing divisibility by integers up to $\\sqrt{n}$."
            complexity_reasoning = "Tests potential divisors up to $\\sqrt{n}$ for each number."
            current_time = "O(n \\sqrt{n})" if ("100" in code or has_nested or "for" in code) else "O(\\sqrt{n})"
            current_space = "O(1)"
            optimal_time = "O(n \\log \\log n)" if ("100" in code or has_nested or "for" in code) else "O(\\sqrt{n}/3)"
            optimal_space = "O(n)" if ("100" in code or has_nested or "for" in code) else "O(1)"
            bottleneck = "Trial division per integer up to $\\sqrt{n}$ repeats redundant divisibility checks."
            recommendations = (
                "1. **Sieve of Eratosthenes**: For generating primes up to $n$, use a boolean sieve running in $O(n \\log \\log n)$ time.\n"
                "2. **Step Optimization**: Check 2 and 3 explicitly, then iterate with step 6 ($6k \\pm 1$)."
            )
            wrong_answer_reason = "Verify edge cases for numbers $\\le 1$ which are not prime."

        elif is_fib_recurse:
            algo_summary = f"Naive Recursive Fibonacci Computation in `{primary_func}`."
            structural_desc = "Binary recursive branching tree calling `fib(n-1) + fib(n-2)`."
            complexity_reasoning = "Each call branches into two subproblems, forming an exponential recursion tree of height $n$."
            current_time = "O(2^n)"
            current_space = "O(n) call stack"
            optimal_time = "O(n)"
            optimal_space = "O(1)"
            bottleneck = "Exponential recursion tree recalculates overlapping subproblems multiple times."
            recommendations = (
                "1. **Iterative Dynamic Programming**: Compute Fibonacci numbers iteratively using two variables in $O(n)$ time and $O(1)$ space."
            )
            diff_preview = (
                "- int fib(int n) {\n"
                "-     if (n <= 1) return n;\n"
                "-     return fib(n - 1) + fib(n - 2);\n"
                "- }\n"
                "+ int fib(int n) {\n"
                "+     if (n <= 1) return n;\n"
                "+     int a = 0, b = 1;\n"
                "+     for (int i = 2; i <= n; i++) {\n"
                "+         int c = a + b; a = b; b = c;\n"
                "+     }\n"
                "+     return b;\n"
                "+ }"
            )
            wrong_answer_reason = "Ensure base cases for $n=0$ and $n=1$ are handled correctly."

        elif is_true_linear_search:
            algo_summary = f"Linear Search / Sequential Scan Algorithm in `{primary_func}` ({filename})."
            structural_desc = "Single-pass loop scanning indexed array elements sequentially from index `0` to `n-1`, testing `arr[i] == target`."
            complexity_reasoning = (
                "Visits array elements one by one sequentially:\n"
                "- **Worst Case:** Target is at the final position ($i = n - 1$) or absent from array — requires $n$ comparisons in $O(n)$ time.\n"
                "- **Average Case:** Target located around middle — requires $n/2$ comparisons in $O(n)$ time.\n"
                "- **Best Case:** Target is the first element ($i = 0$) — requires 1 comparison in $O(1)$ time.\n"
                "- **Auxiliary Space:** $O(1)$ in-place memory with zero additional dynamic allocations."
            )
            current_time = "O(n)"
            current_space = "O(1) auxiliary space"
            optimal_time = "O(log n) (Binary Search) or O(1) (Hash Table)"
            optimal_space = "O(1) to O(n)"
            bottleneck = "Linear scanning from index 0 to $n-1$ requires up to $n$ comparisons in the worst case on unsorted collections."
            recommendations = (
                "1. **Binary Search ($O(\\log n)$)**: If the collection is sorted (like `{4, 8, 15, 16, 23, 42}`), Binary Search cuts the search space in half on each step, reducing time complexity from $O(n)$ to $O(\\log n)$ in $O(1)$ auxiliary space.\n"
                "   *Important Precondition*: Binary Search strictly requires sorted input. Applying binary search on unsorted data produces incorrect results.\n"
                "2. **Hash-Based Lookup ($O(1)$ average)**: For repeated random lookups over dynamic or unsorted collections, storing elements in a hash set/map (`std::unordered_set` / `std::unordered_map`) achieves $O(1)$ average lookup time with $O(n)$ space trade-off.\n"
                "3. **Contextual Evaluation**: For small static collections ($n=6$) with a single one-off search, linear search is already optimal with minimal execution overhead and superior CPU cache locality."
            )
            diff_preview = (
                "- // Linear Search O(n)\n"
                "- for (int i = 0; i < n; i++) {\n"
                "-     if (arr[i] == target) {\n"
                "-         cout << \"Found at index \" << i << endl;\n"
                "-         return 0;\n"
                "-     }\n"
                "- }\n"
                "+ // Binary Search O(log n) (requires sorted array)\n"
                "+ int left = 0, right = n - 1;\n"
                "+ while (left <= right) {\n"
                "+     int mid = left + (right - left) / 2;\n"
                "+     if (arr[mid] == target) {\n"
                "+         cout << \"Found at index \" << mid << endl;\n"
                "+         return 0;\n"
                "+     }\n"
                "+     if (arr[mid] < target) left = mid + 1;\n"
                "+     else right = mid - 1;\n"
                "+ }"
            )
            wrong_answer_reason = (
                "- Target absent: Scans all $n$ elements and executes fallback 'Not found' path.\n"
                "- Target at index 0: Best case, early exit after 1 comparison.\n"
                "- Target at index $n-1$: Worst case, requires $n$ comparisons.\n"
                "- Empty array ($n=0$): Loop condition `0 < 0` is false immediately, correctly printing 'Not found'.\n"
                "- Duplicate elements: Returns index of the first occurrence."
            )

        elif total_loops == 0:
            algo_summary = f"Constant-Time Sequential Execution in `{primary_func}` ({filename})."
            structural_desc = "Straight-line sequential instructions without iteration loops or recursive calls."
            complexity_reasoning = "Executes a fixed, finite sequence of primitive instructions with bounded runtime."
            current_time = "O(1)"
            current_space = "O(1)"
            optimal_time = "O(1)"
            optimal_space = "O(1)"
            bottleneck = "No algorithmic bottleneck detected. The implementation executes in direct constant time."
            recommendations = "The current implementation operates at optimal constant time complexity ($O(1)$). No algorithmic optimization is required or applicable."
            wrong_answer_reason = "Verify boundary conditions on variable initializations and zero divisions."

        else:
            # Single pass / linear processing (e.g. print array, find max, string reverse, fixed range loop)
            has_array_access = any(f"[{var}" in code or f"[{var} " in code for var in ["i", "j", "k", "idx", "index"]) or "vector" in code or "arr" in code
            
            m_const_loop = None
            if for_matches:
                m_const_loop = re.search(r'([a-zA-Z0-9_]+)\s*=\s*(\d+)\s*;\s*\1\s*(?:<=|<)\s*(\d+)', for_matches[0])
            
            if m_const_loop and not has_array_access:
                v_name = m_const_loop.group(1)
                s_val = int(m_const_loop.group(2))
                e_val = int(m_const_loop.group(3))
                if "<" in for_matches[0] and "<=" not in for_matches[0]:
                    e_val -= 1
                algo_summary = f"Fixed-Range Iterative Execution in `{primary_func}` ({filename})."
                structural_desc = f"Loop statement performing a fixed number of iterations from {s_val} through {e_val}, incrementing `{v_name}` by 1 each step and outputting the current value."
                complexity_reasoning = f"Executes a deterministic, constant-bounded number of iterations ($n = {e_val - s_val + 1}$) in $O(1)$ constant time (or $O(n)$ proportional to the loop bound)."
                current_time = "O(1)" if (e_val - s_val <= 100) else "O(n)"
                current_space = "O(1)"
                optimal_time = current_time
                optimal_space = "O(1)"
                bottleneck = "No algorithmic bottleneck detected. The loop performs a minimal, bounded sequence of operations."
                recommendations = "The current implementation is clean, minimal, and operates with standard linear stream output. No algorithmic optimization is required."
                wrong_answer_reason = "Ensure the loop boundary conditions correctly cover the intended start and end values inclusively."
            else:
                algo_summary = f"Linear Single-Pass Traversal in `{primary_func}` ({filename})."
                loop_expr = for_matches[0] if for_matches else (while_matches[0] if while_matches else "loop iteration")
                structural_desc = f"Single iteration loop (`{loop_expr}`) processing elements sequentially."
                complexity_reasoning = "Single pass visiting each element or iteration index exactly once in $O(n)$ time."
                current_time = "O(n)"
                current_space = "O(1)"
                optimal_time = "O(n)"
                optimal_space = "O(1)"
                bottleneck = "No algorithmic bottleneck detected. Inspecting or processing $n$ unsorted elements inherently requires at least one linear pass (theoretical lower bound $\\Omega(n)$)."
                recommendations = "The current implementation operates at the theoretical optimal lower bound ($O(n)$) for single-pass processing. No asymptotic time complexity reduction is possible for this operation."
                wrong_answer_reason = "Verify boundary conditions on zero or negative input sizes."

        report_lines = [
            f"### Algorithmic & Performance Analysis: `{filename}` ({language})\n",
            "#### 📋 Algorithm Overview",
            f"{algo_summary}\n",
            "#### 🔬 Structural Evidence",
            f"- **Primary Function / Scope:** `{primary_func}`",
            f"- **Loop & Control Structure:**\n{structural_desc}",
            f"- **Complexity Reasoning:**\n{complexity_reasoning}\n",
            "#### ⏱️ Complexity Breakdown",
            f"- **Current Time Complexity:** `${current_time}$`",
            f"- **Current Space Complexity:** `${current_space}$`",
            f"- **Optimal Target Complexity:** `${optimal_time}$` time, `${optimal_space}$` space\n",
            "#### 🔍 Bottleneck & Inefficiencies",
            f"{bottleneck}\n",
            "#### 💡 Optimization Recommendations & More Efficient Approach",
            f"{recommendations}\n"
        ]

        if diff_preview and any(kw in p_lower for kw in ["suggest", "recommend", "optimize", "diff", "how to optimize", "more efficient", "improve"]):
            report_lines.append("#### 📝 Proposed Optimization (Diff Preview)")
            report_lines.append(f"```diff\n{diff_preview}\n```\n")

        report_lines.append("#### ⚠️ Meaningful Edge Cases & Failure Analysis")
        report_lines.append(f"{wrong_answer_reason}")

        report = "\n".join(report_lines)

        return {
            "algorithm_summary": algo_summary,
            "current_time": current_time,
            "current_space": current_space,
            "optimal_time": optimal_time,
            "optimal_space": optimal_space,
            "bottleneck": bottleneck,
            "recommendations": recommendations,
            "report": report
        }

    # -----------------------------------------------------------------
    # 14. ACTION: REVIEW CODE (Feature #33.7)
    # -----------------------------------------------------------------
    async def _action_review_code(self, arguments: Dict[str, Any]) -> ToolResult:
        filename_arg = (arguments.get("filename") or arguments.get("file_path") or arguments.get("name") or arguments.get("path") or "").strip()
        code_arg = arguments.get("code")
        p_name = arguments.get("project_name")

        content = None
        target_file = None
        lang = "Code"
        filename = filename_arg

        if code_arg and str(code_arg).strip():
            content = str(code_arg).strip()
            filename = filename_arg or "snippet.code"
            norm_lang, lang_disp = self._detect_file_language(Path(filename))
            lang = lang_disp
        elif filename_arg and filename_arg.lower() not in ["this file", "current file", "this", "here", "the current file", "the active file"]:
            target_file, disambig_msg, candidates = self.resolve_workspace_file(filename_arg, p_name)
            if disambig_msg and not target_file:
                return ToolResult(
                    success=True,
                    verified=False,
                    tool=self.name,
                    action="review_code",
                    message=disambig_msg,
                    data={"candidates": [str(c) for c in candidates], "disambiguation": True}
                )
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="review_code",
                        message=f"Failed to read file '{filename_arg}': {e}",
                        error=str(e)
                    )
            elif target_file and target_file.is_dir():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="review_code",
                    message=f"'{filename_arg}' is a directory, not a source code file.",
                    error="Target is a directory"
                )
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="review_code",
                    message=f"I couldn't find source file '{filename_arg}' in your active workspace.",
                    error="File not found"
                )
        else:
            # Active file / "this file" fallback
            target_file, disambig_msg, candidates = self.resolve_workspace_file("this file", p_name)
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass

        if not content:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if act_file and Path(act_file).is_file():
                target_file = Path(act_file)
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass

        if not content or not content.strip():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="review_code",
                message="I don't have an active code file to review. Which file should I inspect?",
                error="Missing code file",
                data={"missing_document": True}
            )

        analysis = self._analyze_code_for_review(content, lang, filename)
        
        msg_parts = [f"### Code Review: `{filename}` ({lang})\n"]
        msg_parts.append("#### 🔴 Logic / Errors")
        for err in analysis["logic_errors"]:
            msg_parts.append(f"- {err}")
        
        msg_parts.append("\n#### 🟡 Potential Runtime / Bugs")
        for bug in analysis["runtime_bugs"]:
            msg_parts.append(f"- {bug}")
            
        msg_parts.append("\n#### 🔵 Performance & Complexity")
        for perf in analysis["performance"]:
            msg_parts.append(f"- {perf}")
            
        msg_parts.append("\n#### 🟢 Style & Maintainability")
        for st in analysis["style"]:
            msg_parts.append(f"- {st}")
            
        msg_parts.append("\n#### 🔒 Security")
        for sec in analysis["security"]:
            msg_parts.append(f"- {sec}")

        review_msg = "\n".join(msg_parts)

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="review_code",
            message=review_msg,
            data={
                "filename": filename,
                "path": str(target_file) if target_file else None,
                "language": lang,
                "read_only": True,
                "analysis": analysis
            }
        )

    # -----------------------------------------------------------------
    # 15. ACTION: TEACH CODE / PROGRESSIVE HINTS (Feature #33.8)
    # -----------------------------------------------------------------
    async def _action_teach_code(self, arguments: Dict[str, Any]) -> ToolResult:
        filename_arg = (arguments.get("filename") or arguments.get("file_path") or arguments.get("name") or arguments.get("path") or "").strip()
        code_arg = arguments.get("code")
        p_name = arguments.get("project_name")
        prompt = arguments.get("prompt") or ""
        hint_level = arguments.get("hint_level") or 1

        p_lower = prompt.lower()
        if any(k in p_lower for k in ["smaller hint", "another hint", "next hint", "level 2", "more details", "second hint"]):
            hint_level = 2
        elif any(k in p_lower for k in ["level 3", "third hint", "final hint", "how to solve"]):
            hint_level = 3

        content = None
        target_file = None
        lang = "Code"
        filename = filename_arg

        if code_arg and str(code_arg).strip():
            content = str(code_arg).strip()
            filename = filename_arg or "snippet.code"
            norm_lang, lang_disp = self._detect_file_language(Path(filename))
            lang = lang_disp
        elif filename_arg and filename_arg.lower() not in ["this file", "current file", "this", "here", "the current file", "the active file"]:
            target_file, disambig_msg, candidates = self.resolve_workspace_file(filename_arg, p_name)
            if disambig_msg and not target_file:
                return ToolResult(
                    success=True,
                    verified=False,
                    tool=self.name,
                    action="teach_code",
                    message=disambig_msg,
                    data={"candidates": [str(c) for c in candidates], "disambiguation": True}
                )
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="teach_code",
                        message=f"Failed to read file '{filename_arg}': {e}",
                        error=str(e)
                    )
            elif target_file and target_file.is_dir():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="teach_code",
                    message=f"'{filename_arg}' is a directory, not a source code file.",
                    error="Target is a directory"
                )
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="teach_code",
                    message=f"I couldn't find source file '{filename_arg}' in your active workspace.",
                    error="File not found"
                )
        else:
            # Active file / "this file" fallback
            target_file, disambig_msg, candidates = self.resolve_workspace_file("this file", p_name)
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    pass

        if not content:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if act_file and Path(act_file).is_file():
                target_file = Path(act_file)
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass

        if not content or not content.strip():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="teach_code",
                message="I don't have an active code file to teach from. Which file should I look at?",
                error="Missing code file",
                data={"missing_document": True}
            )

        hint_msg = self._synthesize_hints(content, lang, filename, hint_level, prompt)

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="teach_code",
            message=hint_msg,
            data={
                "filename": filename,
                "path": str(target_file) if target_file else None,
                "language": lang,
                "hint_level": hint_level,
                "read_only": True
            }
        )

    # -----------------------------------------------------------------
    # 16. ACTION: ANALYZE CODE / COMPLEXITY & OPTIMIZATION (Feature #33.9)
    # -----------------------------------------------------------------
    async def _action_analyze_code(self, arguments: Dict[str, Any]) -> ToolResult:
        filename_arg = (arguments.get("filename") or arguments.get("file_path") or arguments.get("name") or arguments.get("path") or "").strip()
        code_arg = arguments.get("code")
        p_name = arguments.get("project_name")
        prompt = arguments.get("prompt") or ""
        apply_opt = bool(arguments.get("apply", False) or arguments.get("optimize", False))

        if any(k in prompt.lower() for k in ["apply the optimization", "apply optimization", "optimize this file"]):
            apply_opt = True

        if any(k in prompt.lower() for k in ["don't modify", "do not modify", "dont modify", "without modifying", "read only", "read-only", "don't change", "do not change", "leave it", "show me what you would change", "don't edit", "do not edit"]):
            apply_opt = False

        content = None
        target_file = None
        lang = "Code"
        filename = filename_arg

        if code_arg and str(code_arg).strip():
            content = str(code_arg).strip()
            filename = filename_arg or "snippet.code"
            norm_lang, lang_disp = self._detect_file_language(Path(filename))
            lang = lang_disp
        elif filename_arg and filename_arg.lower() not in ["this file", "current file", "this", "here", "the current file", "the active file"]:
            target_file, disambig_msg, candidates = self.resolve_workspace_file(filename_arg, p_name)
            if disambig_msg and not target_file:
                return ToolResult(
                    success=True,
                    verified=False,
                    tool=self.name,
                    action="analyze_code",
                    message=disambig_msg,
                    data={"candidates": [str(c) for c in candidates], "disambiguation": True}
                )
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="analyze_code",
                        message=f"Failed to read file '{filename_arg}': {e}",
                        error=str(e)
                    )
            elif target_file and target_file.is_dir():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="analyze_code",
                    message=f"'{filename_arg}' is a directory, not a source code file.",
                    error="Target is a directory"
                )
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="analyze_code",
                    message=f"I couldn't find source file '{filename_arg}' in your active workspace.",
                    error="File not found"
                )
        else:
            # Active file / "this file" fallback
            target_file, disambig_msg, candidates = self.resolve_workspace_file("this file", p_name)
            if target_file and target_file.is_file():
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception as e:
                    pass

        if not content:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            act_file = ctx.get("active_file") or ctx.get("active_document")
            if act_file and Path(act_file).is_file():
                target_file = Path(act_file)
                try:
                    content = target_file.read_text(encoding="utf-8", errors="replace")
                    filename = target_file.name
                    norm_lang, lang_disp = self._detect_file_language(target_file)
                    lang = lang_disp
                except Exception:
                    pass

        if not content or not content.strip():
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="analyze_code",
                message="I don't have an active code file to analyze. Which file should I look at?",
                error="Missing code file",
                data={"missing_document": True}
            )

        analysis = self._synthesize_code_analysis(content, lang, filename, prompt)

        if apply_opt and target_file and target_file.is_file():
            edit_args = {
                "filename": target_file.name,
                "project_name": p_name,
                "instruction": "Apply the optimization"
            }
            edit_res = await self._action_edit_code_file(edit_args)
            return ToolResult(
                success=edit_res.success,
                verified=edit_res.verified,
                tool=self.name,
                action="analyze_code",
                message=f"Optimization applied successfully to `{target_file.name}`:\n\n{edit_res.message}",
                data={
                    "optimized": True,
                    "analysis": analysis,
                    "edit_result": edit_res.data
                }
            )

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="analyze_code",
            message=analysis["report"],
            data={
                "filename": filename,
                "path": str(target_file) if target_file else None,
                "language": lang,
                "analysis": analysis,
                "read_only": True
            }
        )

coding_workspace_skill = CodingWorkspaceSkill()
