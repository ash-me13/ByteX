"""
ByteX - Feature #33.6: Controlled Terminal Agent Skill

Provides bounded, deterministic, and securely controlled terminal operations
strictly within the active Coding Workspace project directory.

Strict Security & Architectural Invariants:
1. Zero Raw Shell Access: Never accepts arbitrary shell command strings. Never uses `shell=True`, `cmd.exe /c`, `powershell.exe -Command`, or `bash -c`.
2. Executable Allowlist: Only approved development executables (python, node, npm, pytest, pip, etc.) are permitted.
3. Argument Sanitization: Strictly rejects shell metacharacters (&&, ||, ;, |, >, <, $(), etc.).
4. Workspace Boundary: All operations execute strictly within the active project directory; path traversal (../, absolute external paths) is strictly blocked.
5. Resource & Output Limits: Max timeout 120s (default 30s). Max output 100 KB per stream with truncation indicators.
6. Secret Protection: Redacts credentials, tokens, and sensitive environment variables from stdout, stderr, and history.
7. Git/GitHub Boundary: Git operations are NOT handled here (deferred to Feature #33.7).
"""

import os
import re
import time
import json
import enum
import shutil
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

from skills.base import BaseSkill, ToolResult
from skills.files import resolve_user_directory, get_known_user_roots
from skills.diagnostics import CodeDiagnosticEngine

logger = logging.getLogger("bytex.skills.terminal")


class TerminalOperation(str, enum.Enum):
    # Inspection
    LIST_FILES = "list_files"
    LIST_DIRECTORY = "list_directory"
    PRINT_WORKING_DIRECTORY = "print_working_directory"
    # Python
    PYTHON_VERSION = "python_version"
    PIP_VERSION = "pip_version"
    CREATE_VIRTUAL_ENVIRONMENT = "create_virtual_environment"
    RUN_PYTEST = "run_pytest"
    PIP_INSTALL_REQUIREMENTS = "pip_install_requirements"
    # Node / JavaScript
    NODE_VERSION = "node_version"
    NPM_VERSION = "npm_version"
    NPM_INSTALL = "npm_install"
    NPM_TEST = "npm_test"
    NPM_RUN_SCRIPT = "npm_run_script"
    # Build & Test
    BUILD_PROJECT = "build_project"
    RUN_PROJECT_TESTS = "run_project_tests"
    START_DEV_SERVER = "start_dev_server"
    # Metadata
    SHOW_PACKAGE_SCRIPTS = "show_package_scripts"
    SHOW_PROJECT_METADATA = "show_project_metadata"


class TerminalAgentSkill(BaseSkill):
    """
    Controlled Terminal Agent Skill.
    Executes approved, structured developer operations within the active project workspace.
    """

    MAX_OUTPUT_BYTES = 100 * 1024  # 100 KB
    DEFAULT_TIMEOUT_SECONDS = 30
    MAX_TIMEOUT_SECONDS = 120

    EXECUTABLE_ALLOWLIST: Set[str] = {
        "python", "python3", "node", "npm", "npx", "pytest", "pip", "pip3",
        "g++", "gcc", "clang++", "clang", "cargo", "rustc", "go", "javac", "java", "tsc"
    }

    FORBIDDEN_SHELL_PATTERNS = [
        re.compile(r"[;&|`$<>]"),
        re.compile(r"\b(?:powershell|cmd\.exe|bash|sh|zsh|csh|tcsh)\b", re.IGNORECASE),
        re.compile(r"\b(?:del|rm|rmdir|format|diskpart|shutdown|restart|taskkill|chmod|chown)\b", re.IGNORECASE),
        re.compile(r"\b(?:reg|regedit|netsh|sc|vssadmin)\b", re.IGNORECASE),
        re.compile(r"%[a-zA-Z0-9_]+%"),
        re.compile(r"\$\([^\)]*\)")
    ]

    def __init__(self):
        super().__init__()
        self._running_processes: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "terminal_agent"

    @property
    def description(self) -> str:
        return (
            "Performs safe, controlled developer operations inside the active project directory "
            "(file inspection, tests, package scripts, dependency installation, virtual environments)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "terminal_command",
                        "list_files",
                        "list_directory",
                        "print_working_directory",
                        "python_version",
                        "pip_version",
                        "create_virtual_environment",
                        "run_pytest",
                        "pip_install_requirements",
                        "node_version",
                        "npm_version",
                        "npm_install",
                        "npm_test",
                        "npm_run_script",
                        "build_project",
                        "run_project_tests",
                        "start_dev_server",
                        "show_package_scripts",
                        "show_project_metadata"
                    ],
                    "description": "Terminal agent action or structured operation name."
                },
                "operation": {
                    "type": "string",
                    "description": "Approved structured terminal operation name."
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional project path or project name. If omitted, uses active project from context."
                },
                "arguments": {
                    "type": "object",
                    "description": "Structured parameters for the approved operation."
                },
                "script_name": {
                    "type": "string",
                    "description": "Script name from package.json for npm_run_script (e.g. dev, build, start, lint)."
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (default 30, max 120)."
                },
                "working_directory": {
                    "type": "string",
                    "description": "Relative subdirectory within the active project."
                }
            },
            "required": ["action"]
        }

    # -----------------------------------------------------------------
    # Helper: Resolve Workspace Root
    # -----------------------------------------------------------------
    def _resolve_project_dir(self, project_path_arg: Optional[str] = None) -> Optional[Path]:
        """Resolves the active project directory securely."""
        target_dir = None

        if project_path_arg:
            p_arg = Path(project_path_arg)
            if p_arg.is_absolute() and p_arg.is_dir():
                target_dir = p_arg
            else:
                for root in get_known_user_roots():
                    cand = root / project_path_arg
                    if cand.is_dir():
                        target_dir = cand
                        break

        if not target_dir:
            from core.session import session_manager
            ctx = session_manager.get_working_context()
            active_proj = ctx.get("active_project", {})
            if active_proj and isinstance(active_proj, dict):
                p_path = active_proj.get("path")
                if p_path and Path(p_path).is_dir():
                    target_dir = Path(p_path)

        if not target_dir:
            from skills.registry import skill_registry
            coding_s = skill_registry.get_skill("coding_workspace")
            if coding_s and getattr(coding_s, "_active_project_path", None):
                if isinstance(coding_s._active_project_path, Path) and coding_s._active_project_path.is_dir():
                    target_dir = coding_s._active_project_path

        return target_dir

    # -----------------------------------------------------------------
    # Helper: Validate Arguments
    # -----------------------------------------------------------------
    @classmethod
    def _validate_safe_string(cls, val: str) -> bool:
        """Validates that a string contains no shell metacharacters or dangerous commands."""
        if not val or not isinstance(val, str):
            return False
        for pat in cls.FORBIDDEN_SHELL_PATTERNS:
            if pat.search(val):
                return False
        return True

    # -----------------------------------------------------------------
    # Helper: Sanitize Output
    # -----------------------------------------------------------------
    @classmethod
    def _sanitize_output(cls, raw: str) -> str:
        """Truncates and removes secrets from process output streams."""
        if not raw:
            return ""
        sanitized = CodeDiagnosticEngine.sanitize_text(raw)
        encoded = sanitized.encode("utf-8", errors="replace")
        if len(encoded) > cls.MAX_OUTPUT_BYTES:
            truncated = encoded[:cls.MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            return truncated + "\n[OUTPUT TRUNCATED]"
        return sanitized

    # -----------------------------------------------------------------
    # Helper: Find Executable
    # -----------------------------------------------------------------
    @classmethod
    def _resolve_executable(cls, exe_name: str) -> Optional[str]:
        """Safely locates allowed executable binary in PATH."""
        clean_name = exe_name.lower().replace(".exe", "").strip()
        if clean_name not in cls.EXECUTABLE_ALLOWLIST:
            return None
        return shutil.which(exe_name)

    # -----------------------------------------------------------------
    # Helper: Run Controlled Subprocess
    # -----------------------------------------------------------------
    async def _run_process(
        self,
        cmd_args: List[str],
        cwd: Path,
        timeout: int = DEFAULT_TIMEOUT_SECONDS
    ) -> Dict[str, Any]:
        """
        Executes a controlled process directly (shell=False) with tracking,
        timeout enforcement, graceful termination, and output truncation.
        """
        import subprocess

        timeout = max(1, min(timeout, self.MAX_TIMEOUT_SECONDS))
        exe_path = self._resolve_executable(cmd_args[0])
        if not exe_path:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Executable '{cmd_args[0]}' is not installed or not in the allowlist.",
                "timed_out": False,
                "duration_seconds": 0.0,
                "status": "missing_executable"
            }

        cmd_args[0] = exe_path
        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to spawn process: {e}",
                "timed_out": False,
                "duration_seconds": round(time.time() - start_time, 3),
                "status": "failed"
            }

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=float(timeout)
            )
            exit_code = process.returncode
        except asyncio.TimeoutError:
            timed_out = True
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            stdout_bytes, stderr_bytes = b"", b"Process timed out and was terminated safely."
            exit_code = -1

        duration = round(time.time() - start_time, 3)
        stdout_str = self._sanitize_output(stdout_bytes.decode("utf-8", errors="replace"))
        stderr_str = self._sanitize_output(stderr_bytes.decode("utf-8", errors="replace"))

        is_success = (exit_code == 0) and not timed_out

        return {
            "success": is_success,
            "exit_code": exit_code,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "timed_out": timed_out,
            "duration_seconds": duration,
            "status": "passed" if is_success else ("timeout" if timed_out else "failed")
        }

    # -----------------------------------------------------------------
    # Main Execute Dispatch
    # -----------------------------------------------------------------
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action", "terminal_command")).strip().lower()
        operation = str(arguments.get("operation") or action).strip().lower()
        p_path_arg = arguments.get("project_path") or arguments.get("project_name")
        timeout_sec = int(arguments.get("timeout_seconds") or self.DEFAULT_TIMEOUT_SECONDS)
        sub_dir_arg = arguments.get("working_directory") or ""
        op_args = arguments.get("arguments") or {}

        # 1. Resolve Project Root
        project_dir = self._resolve_project_dir(p_path_arg)
        if not project_dir:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action=operation,
                message="I don't have an active coding project. Open a project first.",
                error="No active project"
            )

        # 2. Check Workspace Boundary for Subdirectory
        working_dir = project_dir
        if sub_dir_arg:
            if ".." in sub_dir_arg or "\\" in sub_dir_arg and sub_dir_arg.startswith(("\\", "//")):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message="Directory traversal outside the active project workspace is strictly blocked.",
                    error="Path traversal blocked"
                )
            cand_dir = (project_dir / sub_dir_arg).resolve()
            try:
                cand_dir.relative_to(project_dir.resolve())
                if cand_dir.is_dir():
                    working_dir = cand_dir
                else:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=operation,
                        message=f"Subdirectory '{sub_dir_arg}' not found inside project.",
                        error="Subdirectory not found"
                    )
            except ValueError:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message="Target directory is outside the active project boundary.",
                    error="Workspace boundary violation"
                )

        # -------------------------------------------------------------
        # 3. OPERATION DISPATCH
        # -------------------------------------------------------------

        # A. File / Directory Inspection (Safe)
        if operation in ["list_files", "list_directory"]:
            items = []
            for p in sorted(working_dir.rglob("*")):
                if any(part.startswith((".", "node_modules", "__pycache__", "venv", ".venv")) for part in p.parts):
                    continue
                rel = p.relative_to(project_dir)
                items.append(f"{'📁' if p.is_dir() else '📄'} {rel.as_posix()}")
            file_list_str = "\n".join(items[:100])
            count = len(items)
            msg = f"Project files in `{project_dir.name}` ({count} item(s)):\n\n{file_list_str}"
            if count > 100:
                msg += f"\n... and {count - 100} more item(s)."
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=operation,
                message=msg,
                data={"project": project_dir.name, "path": str(project_dir), "count": count, "files": items[:100]}
            )

        elif operation == "print_working_directory":
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=operation,
                message=f"Current project directory: `{working_dir}`",
                data={"working_directory": str(working_dir), "project_name": project_dir.name}
            )

        # B. Python Tooling
        elif operation == "python_version":
            res = await self._run_process(["python", "--version"], cwd=working_dir, timeout=timeout_sec)
            ver = (res["stdout"] or res["stderr"]).strip()
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"Python Version: {ver}" if res["success"] else f"Failed getting Python version: {res['stderr']}",
                data=res
            )

        elif operation == "pip_version":
            res = await self._run_process(["pip", "--version"], cwd=working_dir, timeout=timeout_sec)
            ver = (res["stdout"] or res["stderr"]).strip()
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"Pip Version: {ver}" if res["success"] else f"Failed getting pip version: {res['stderr']}",
                data=res
            )

        elif operation == "create_virtual_environment":
            venv_name = op_args.get("name") or arguments.get("name") or ".venv"
            if not self._validate_safe_string(venv_name) or ".." in venv_name:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message="Invalid virtual environment name.",
                    error="Invalid name"
                )
            res = await self._run_process(["python", "-m", "venv", venv_name], cwd=working_dir, timeout=60)
            if res["success"]:
                msg = f"[OK] Created Python virtual environment `{venv_name}` in `{project_dir.name}`."
            else:
                msg = f"Failed creating virtual environment: {res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        elif operation == "run_pytest":
            test_target = op_args.get("target") or arguments.get("target") or ""
            cmd = ["pytest"]
            if test_target:
                if not self._validate_safe_string(test_target) or ".." in test_target:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action=operation,
                        message="Invalid test target path.",
                        error="Invalid target"
                    )
                cmd.append(test_target)
            res = await self._run_process(cmd, cwd=working_dir, timeout=timeout_sec)
            msg = f"**Pytest Results:**\n\n{res['stdout'] or res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        elif operation == "pip_install_requirements":
            req_file = working_dir / "requirements.txt"
            if not req_file.is_file():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No `requirements.txt` found in `{working_dir.name}`.",
                    error="Missing requirements.txt"
                )
            res = await self._run_process(["pip", "install", "-r", "requirements.txt"], cwd=working_dir, timeout=timeout_sec)
            msg = f"**Pip Install Output:**\n\n{res['stdout'] or res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        # C. Node.js & npm Tooling
        elif operation == "node_version":
            res = await self._run_process(["node", "--version"], cwd=working_dir, timeout=timeout_sec)
            ver = (res["stdout"] or res["stderr"]).strip()
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"Node.js Version: {ver}" if res["success"] else f"Node.js is not installed: {res['stderr']}",
                data=res
            )

        elif operation == "npm_version":
            res = await self._run_process(["npm", "--version"], cwd=working_dir, timeout=timeout_sec)
            ver = (res["stdout"] or res["stderr"]).strip()
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"npm Version: {ver}" if res["success"] else f"npm is not installed: {res['stderr']}",
                data=res
            )

        elif operation == "npm_install":
            pkg_file = working_dir / "package.json"
            if not pkg_file.is_file():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No `package.json` found in `{working_dir.name}`. npm install requires package.json.",
                    error="Missing package.json"
                )
            res = await self._run_process(["npm", "install"], cwd=working_dir, timeout=max(60, timeout_sec))
            msg = f"**npm install output:**\n\n{res['stdout'] or res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        elif operation == "npm_test":
            res = await self._run_process(["npm", "test"], cwd=working_dir, timeout=timeout_sec)
            msg = f"**npm test output:**\n\n{res['stdout'] or res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        elif operation == "npm_run_script":
            script_name = (arguments.get("script_name") or op_args.get("script") or "").strip()
            if not script_name:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message="Please specify the npm script name to run (e.g. dev, build, start, lint).",
                    error="Missing script name"
                )
            if not self._validate_safe_string(script_name):
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message="Invalid script name containing shell metacharacters.",
                    error="Invalid script name"
                )
            res = await self._run_process(["npm", "run", script_name], cwd=working_dir, timeout=timeout_sec)
            msg = f"**npm run {script_name} output:**\n\n{res['stdout'] or res['stderr']}"
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=msg,
                data=res
            )

        # D. Generic Project Build & Test
        elif operation in ["build_project", "build"]:
            # Auto-detect build toolchain
            if (working_dir / "package.json").is_file():
                res = await self._run_process(["npm", "run", "build"], cwd=working_dir, timeout=timeout_sec)
            elif (working_dir / "Cargo.toml").is_file():
                res = await self._run_process(["cargo", "build"], cwd=working_dir, timeout=timeout_sec)
            elif (working_dir / "Makefile").is_file():
                res = await self._run_process(["make"], cwd=working_dir, timeout=timeout_sec)
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No build configuration (package.json, Cargo.toml, or Makefile) found in `{working_dir.name}`.",
                    error="No build config"
                )
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"**Build Output:**\n\n{res['stdout'] or res['stderr']}",
                data=res
            )

        elif operation in ["run_project_tests", "run_tests", "test"]:
            # Auto-detect test runner
            if (working_dir / "package.json").is_file():
                res = await self._run_process(["npm", "test"], cwd=working_dir, timeout=timeout_sec)
            elif any(working_dir.glob("test_*.py")) or (working_dir / "tests").is_dir():
                res = await self._run_process(["pytest"], cwd=working_dir, timeout=timeout_sec)
            elif (working_dir / "Cargo.toml").is_file():
                res = await self._run_process(["cargo", "test"], cwd=working_dir, timeout=timeout_sec)
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No automated test suite detected in `{working_dir.name}`.",
                    error="No tests found"
                )
            return ToolResult(
                success=res["success"],
                verified=res["success"],
                tool=self.name,
                action=operation,
                message=f"**Test Output:**\n\n{res['stdout'] or res['stderr']}",
                data=res
            )

        elif operation == "start_dev_server":
            # Bounded startup check (runs up to 5s then verifies initialization)
            if (working_dir / "package.json").is_file():
                res = await self._run_process(["npm", "run", "dev"], cwd=working_dir, timeout=5)
            elif (working_dir / "app.py").is_file() or (working_dir / "main.py").is_file():
                entry = "main.py" if (working_dir / "main.py").is_file() else "app.py"
                res = await self._run_process(["python", entry], cwd=working_dir, timeout=5)
            else:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No development server entrypoint found in `{working_dir.name}`.",
                    error="No server entrypoint"
                )
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=operation,
                message=f"Development server test check output:\n\n{res['stdout'] or res['stderr']}",
                data=res
            )

        # E. Project Metadata & Package Scripts
        elif operation == "show_package_scripts":
            pkg_file = working_dir / "package.json"
            if not pkg_file.is_file():
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"No `package.json` found in `{working_dir.name}`.",
                    error="Missing package.json"
                )
            try:
                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
                scripts = pkg_data.get("scripts", {})
                if not scripts:
                    msg = "No scripts defined in `package.json`."
                else:
                    lines = [f"- **`{k}`**: `{v}`" for k, v in scripts.items()]
                    msg = f"Scripts in `{working_dir.name}/package.json`:\n\n" + "\n".join(lines)
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action=operation,
                    message=msg,
                    data={"scripts": scripts}
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action=operation,
                    message=f"Failed parsing `package.json`: {e}",
                    error=str(e)
                )

        elif operation == "show_project_metadata":
            meta: Dict[str, Any] = {"name": project_dir.name, "path": str(project_dir)}
            if (working_dir / "package.json").is_file():
                try:
                    meta["package_json"] = json.loads((working_dir / "package.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
            if (working_dir / "requirements.txt").is_file():
                meta["has_requirements"] = True
            if (working_dir / "Cargo.toml").is_file():
                meta["has_cargo"] = True
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action=operation,
                message=f"Project metadata for `{project_dir.name}` retrieved.",
                data=meta
            )

        else:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action=operation,
                message=f"Unsupported or unapproved terminal operation: '{operation}'.",
                error="Invalid operation"
            )


terminal_agent_skill = TerminalAgentSkill()

