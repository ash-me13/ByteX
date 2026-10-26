"""
ByteX — Feature #33.4: Intelligent Code Error Detection & Diagnosis Engine

Provides deterministic and structural diagnosis of compiler errors, runtime exceptions,
tracebacks, time-outs, and toolchain issues across multiple languages:
C++, C, Python, JavaScript, TypeScript, Java, Go, Rust.

Strict Security & Architectural Invariants:
1. Zero File Modification: Analysis is strictly read-only and never modifies code files.
2. Zero Shell/Command Execution: Never invokes terminal, compilers, or subprocesses.
3. Secret Sanitization: Automatically redacts credentials, keys, and tokens from snippets & diagnostics.
4. Cascading Error Ordering: Prioritizes the primary root-cause error and classifies cascading errors.
5. Deterministic Confidence Scoring: Returns calibrated HIGH, MEDIUM, or LOW confidence.
"""

import re
import enum
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict


class ErrorCategory(str, enum.Enum):
    COMPILER_ERROR = "COMPILER_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    NAME_ERROR = "NAME_ERROR"
    LINKER_ERROR = "LINKER_ERROR"
    IMPORT_ERROR = "IMPORT_ERROR"
    MODULE_ERROR = "MODULE_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SEGMENTATION_FAULT = "SEGMENTATION_FAULT"
    EXCEPTION = "EXCEPTION"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    INDEX_ERROR = "INDEX_ERROR"
    NULL_REFERENCE = "NULL_REFERENCE"
    TIMEOUT = "TIMEOUT"
    MEMORY_ERROR = "MEMORY_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    MISSING_TOOLCHAIN = "MISSING_TOOLCHAIN"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class ParsedError:
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    severity: str = "error"
    error_code: Optional[str] = None
    message: str = ""
    raw_line: str = ""
    is_cascading: bool = False


@dataclass
class DiagnosticResult:
    success: bool
    error_type: str
    stage: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    message: str = ""
    cause: str = ""
    diagnosis: str = ""
    suggested_fix: str = ""
    confidence: float = 0.95
    confidence_level: str = "HIGH"
    source_context: str = ""
    errors: List[Dict[str, Any]] = field(default_factory=list)
    primary_error: Optional[Dict[str, Any]] = None
    related_errors: List[Dict[str, Any]] = field(default_factory=list)
    human_readable: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CodeDiagnosticEngine:
    """
    Deterministic diagnosis engine for compiler outputs, runtime tracebacks,
    and process execution failures.
    """

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Sanitizes sensitive API keys, tokens, and passwords from diagnostics."""
        if not text:
            return ""
        text = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}", "[REDACTED_API_KEY]", text)
        text = re.sub(r"['\"][A-Za-z0-9+/=_-]{24,}['\" ]", "'[REDACTED_SECRET]'", text)
        text = re.sub(r"(?i)(?:password|secret|api[_-]?key|bearer|auth[_-]?token)\s*[:=]\s*['\"][^'\"]+['\" ]", "secret = '[REDACTED]'", text)
        return text

    @classmethod
    def extract_source_context(
        cls,
        source_code: Optional[str],
        file_path: Optional[str],
        line_num: Optional[int],
        col_num: Optional[int] = None,
        context_radius: int = 2,
        token_len: Optional[int] = None
    ) -> str:
        """
        Extracts a small window around the error line and formats it with line numbers
        and column pointer (e.g. ^^^^).
        """
        if not line_num or line_num <= 0:
            return ""

        lines = []
        if source_code:
            lines = source_code.splitlines()
        elif file_path:
            try:
                p = Path(file_path)
                if p.is_file():
                    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                pass

        if not lines or line_num > len(lines):
            return ""

        start_idx = max(0, line_num - 1 - context_radius)
        end_idx = min(len(lines), line_num + context_radius)

        out_lines = []
        max_num_width = len(str(end_idx))

        for idx in range(start_idx, end_idx):
            cur_line_num = idx + 1
            line_str = cls.sanitize_text(lines[idx])
            prefix = f"{cur_line_num:>{max_num_width}} | "
            out_lines.append(f"{prefix}{line_str}")

            if cur_line_num == line_num:
                # Add caret pointer line
                indent_spaces = max_num_width + 3
                if col_num and col_num > 0:
                    col_offset = max(0, col_num - 1)
                    t_len = max(1, token_len or 1)
                    caret_str = " " * (indent_spaces + col_offset) + "^" * t_len
                else:
                    # Highlight first non-whitespace token or beginning of code
                    stripped = line_str.lstrip()
                    offset = len(line_str) - len(stripped)
                    caret_str = " " * (indent_spaces + offset) + "^" * max(1, len(stripped.split()[0]) if stripped.split() else 3)
                out_lines.append(caret_str)

        return "\n".join(out_lines)

    @classmethod
    def diagnose(
        cls,
        error_output: str,
        stage: str = "auto",
        language: Optional[str] = None,
        file_path: Optional[str] = None,
        exit_code: Optional[int] = None,
        source_code: Optional[str] = None,
        timed_out: bool = False,
        execution_result: Optional[Dict[str, Any]] = None
    ) -> DiagnosticResult:
        """
        Diagnoses a compiler error, runtime exception, or execution failure.
        """
        # 1. Inspect execution_result dictionary if passed
        if execution_result and isinstance(execution_result, dict):
            error_output = error_output or execution_result.get("stderr", "") or execution_result.get("stdout", "") or ""
            stage = stage if stage != "auto" else (execution_result.get("stage") or "auto")
            language = language or execution_result.get("language")
            file_path = file_path or execution_result.get("file") or execution_result.get("path")
            if exit_code is None:
                exit_code = execution_result.get("exit_code")
            if not timed_out:
                timed_out = bool(execution_result.get("timed_out", False))

        error_output = cls.sanitize_text((error_output or "").strip())
        norm_lang = (language or "").strip().lower()

        # 2. Check for TIMEOUT
        if timed_out or (exit_code == -1 and "timed out" in error_output.lower()):
            context_str = cls.extract_source_context(source_code, file_path, 1)
            return DiagnosticResult(
                success=True,
                error_type=ErrorCategory.TIMEOUT.value,
                stage="runtime",
                file=file_path or "program",
                line=None,
                column=None,
                message="Execution exceeded the allotted timeout limit.",
                cause="Possible infinite loop, excessively large computation, or unresolved blocking I/O operation.",
                diagnosis="The process failed to complete within the maximum permitted execution limit and was terminated to protect system resources.",
                suggested_fix="Inspect loops (e.g. while/for loops) and recursive calls to ensure proper termination conditions and bounded inputs.",
                confidence=0.95,
                confidence_level="HIGH",
                source_context=context_str,
                human_readable=(
                    f"⏱️ **Execution Timeout Detected**\n\n"
                    f"**File:** `{file_path or 'Source Code'}`\n\n"
                    f"**Problem:** Execution exceeded the time limit.\n\n"
                    f"**Likely Cause:** Infinite loop, blocking operation, or unbounded recursion.\n\n"
                    f"**Suggested Fix:** Verify loop exit conditions and base cases in recursive functions."
                )
            )

        # 3. Check for Missing Toolchain
        if "runner not available" in error_output.lower() or "compiler not found" in error_output.lower() or "is not available" in error_output.lower():
            return DiagnosticResult(
                success=True,
                error_type=ErrorCategory.MISSING_TOOLCHAIN.value,
                stage="setup",
                file=file_path,
                message=error_output or "Required language runner or compiler is not installed.",
                cause="The local environment is missing the toolchain binary (e.g. g++, python, node, javac, rustc, go).",
                diagnosis="Execution could not be initiated because the language executable is not present on the host PATH.",
                suggested_fix="Install the required compiler or interpreter SDK and ensure it is registered on the system PATH.",
                confidence=0.98,
                confidence_level="HIGH",
                human_readable=f"⚠️ **Missing Toolchain**\n\n{error_output}"
            )

        # 4. Check for Permission Errors
        if "permission denied" in error_output.lower() or "access is denied" in error_output.lower():
            return DiagnosticResult(
                success=True,
                error_type=ErrorCategory.PERMISSION_ERROR.value,
                stage=stage if stage != "auto" else "runtime",
                file=file_path,
                message="Access or permission denied while executing the program.",
                cause="Insufficient file system or executable permissions on the target directory or binary.",
                diagnosis="The operating system prevented the operation due to permission restrictions.",
                suggested_fix="Verify read/write/execute permissions for the file and directory.",
                confidence=0.90,
                confidence_level="HIGH",
                human_readable=f"🔒 **Permission Error**\n\n{error_output}"
            )

        # 5. Check for Segmentation Fault
        if (
            "segmentation fault" in error_output.lower()
            or "sigsegv" in error_output.lower()
            or "status_access_violation" in error_output.lower()
            or exit_code in [-1073741819, 139, 3221225477]
        ):
            line_val, col_val = cls._find_any_source_location(error_output, file_path)
            ctx_str = cls.extract_source_context(source_code, file_path, line_val, col_val)
            return DiagnosticResult(
                success=True,
                error_type=ErrorCategory.SEGMENTATION_FAULT.value,
                stage="runtime",
                file=file_path,
                line=line_val,
                column=col_val,
                message="Segmentation fault (access violation).",
                cause="Invalid memory access — attempted to dereference a null, unallocated, or already freed pointer, or buffer overflow.",
                diagnosis="The process crashed because it attempted to access restricted memory addresses without permission.",
                suggested_fix="Check pointer initializations, array bounds, dynamic allocations, and null pointer checks before dereferencing.",
                confidence=0.92,
                confidence_level="HIGH",
                source_context=ctx_str,
                human_readable=(
                    f"💥 **Segmentation Fault (Memory Access Violation)**\n\n"
                    f"**File:** `{file_path or 'Unknown'}`\n\n"
                    f"**Likely Cause:** Invalid memory access, null pointer dereference, or out-of-bounds memory indexing.\n\n"
                    f"**Suggested Fix:** Check pointer validity and ensure arrays stay within allocated boundaries."
                )
            )

        # 6. Parse Compiler Outputs (if stage is compile or output looks like compiler)
        comp_res = cls._parse_compiler_output(error_output, norm_lang, file_path, source_code)
        if comp_res:
            return comp_res

        # 7. Parse Runtime Outputs (Tracebacks, Panics, Exceptions)
        run_res = cls._parse_runtime_output(error_output, norm_lang, file_path, source_code, exit_code)
        if run_res:
            return run_res

        # 8. Fallback / Generic Non-Zero Exit Code
        line_val, col_val = cls._find_any_source_location(error_output, file_path)
        ctx_str = cls.extract_source_context(source_code, file_path, line_val, col_val)
        return DiagnosticResult(
            success=True,
            error_type=ErrorCategory.UNKNOWN_ERROR.value if not error_output else ErrorCategory.RUNTIME_ERROR.value,
            stage=stage if stage != "auto" else "runtime",
            file=file_path,
            line=line_val,
            column=col_val,
            message=error_output or f"Process exited with non-zero exit code {exit_code}",
            cause="Program encountered an unclassified error or non-zero exit code.",
            diagnosis="The program terminated with an error code without standard compiler or traceback markers.",
            suggested_fix="Inspect the standard error output and verify logic around program termination.",
            confidence=0.50,
            confidence_level="LOW",
            source_context=ctx_str,
            human_readable=(
                f"❌ **Execution Failed**\n\n"
                f"**Details:**\n```\n{error_output or f'Exit code {exit_code}'}\n```\n\n"
                f"**Note:** I found the error, but I can't determine its exact cause reliably."
            )
        )

    # -------------------------------------------------------------------------
    # Compiler Parsing Subsystem
    # -------------------------------------------------------------------------
    @classmethod
    def _parse_compiler_output(
        cls,
        output: str,
        language: str,
        file_path: Optional[str],
        source_code: Optional[str]
    ) -> Optional[DiagnosticResult]:
        parsed_errors: List[ParsedError] = []

        # A. GCC / G++ / Clang format
        # main.cpp:12:5: error: 'coutt' was not declared in this scope
        # C:\path\main.cpp:10:5: fatal error: ...
        gcc_pattern = re.compile(
            r"^\s*((?:[a-zA-Z]:[\\/])?[^:\n\r]+):(\d+):(?:(\d+):)?\s*(fatal error|error|warning|note):\s*(.+)$",
            re.MULTILINE | re.IGNORECASE
        )
        for m in gcc_pattern.finditer(output):
            f_name, l_num, c_num, sev, msg = m.groups()
            if sev.lower() in ["error", "fatal error"]:
                parsed_errors.append(ParsedError(
                    file=f_name.strip(),
                    line=int(l_num),
                    column=int(c_num) if c_num else None,
                    severity="error",
                    message=msg.strip(),
                    raw_line=m.group(0).strip()
                ))

        # B. MSVC / Visual Studio C++ / Clang-cl format
        # main.cpp(12): error C2143: syntax error : missing ';' before 'cout'
        # C:\path\main.cpp(12,5): error C2143: ...
        msvc_pattern = re.compile(
            r"^\s*((?:[a-zA-Z]:[\\/])?[^(\n\r]+)\((\d+)(?:,(\d+))?\):\s*(?:fatal error|error)\s*([A-Z0-9]+)?:\s*(.+)$",
            re.MULTILINE | re.IGNORECASE
        )
        for m in msvc_pattern.finditer(output):
            f_name, l_num, c_num, err_code, msg = m.groups()
            parsed_errors.append(ParsedError(
                file=f_name.strip(),
                line=int(l_num),
                column=int(c_num) if c_num else None,
                severity="error",
                error_code=err_code,
                message=msg.strip(),
                raw_line=m.group(0).strip()
            ))

        # C. Java Compiler (javac)
        # Main.java:8: error: cannot find symbol
        javac_pattern = re.compile(
            r"^\s*((?:[a-zA-Z]:[\\/])?[^:\n\r]+):(\d+):\s*(?:error:)\s*(.+)$",
            re.MULTILINE | re.IGNORECASE
        )
        for m in javac_pattern.finditer(output):
            f_name, l_num, msg = m.groups()
            parsed_errors.append(ParsedError(
                file=f_name.strip(),
                line=int(l_num),
                column=None,
                severity="error",
                message=msg.strip(),
                raw_line=m.group(0).strip()
            ))

        # D. TypeScript Compiler (tsc)
        # main.ts(12,5): error TS2304: Cannot find name 'coutt'.
        tsc_pattern = re.compile(
            r"^\s*((?:[a-zA-Z]:[\\/])?[^(\n\r]+)\((\d+),(\d+)\):\s*error\s*(TS\d+)?:?\s*(.+)$",
            re.MULTILINE | re.IGNORECASE
        )
        for m in tsc_pattern.finditer(output):
            f_name, l_num, c_num, err_code, msg = m.groups()
            parsed_errors.append(ParsedError(
                file=f_name.strip(),
                line=int(l_num),
                column=int(c_num),
                severity="error",
                error_code=err_code,
                message=msg.strip(),
                raw_line=m.group(0).strip()
            ))

        # E. Go Compiler
        # ./main.go:8:5: undefined: coutt
        # main.go:8: syntax error: unexpected semicolon
        go_pattern = re.compile(
            r"^\s*((?:[a-zA-Z]:[\\/])?[^:\n\r]+):(\d+):(?:(\d+):)?\s*(.+)$",
            re.MULTILINE
        )
        if language == "go" or ".go:" in output:
            for m in go_pattern.finditer(output):
                f_name, l_num, c_num, msg = m.groups()
                if not any(k in f_name for k in ["/usr", "/lib", "goroot"]) and not msg.startswith("note:"):
                    parsed_errors.append(ParsedError(
                        file=f_name.strip().lstrip("./"),
                        line=int(l_num),
                        column=int(c_num) if c_num else None,
                        severity="error",
                        message=msg.strip(),
                        raw_line=m.group(0).strip()
                    ))

        # F. Rust Compiler (rustc)
        # error[E0425]: cannot find value `x` in this scope --> main.rs:8:5
        rust_pattern = re.compile(
            r"error(?:\[(E\d+)\])?:\s*(.+?)\n\s*-->\s*((?:[a-zA-Z]:[\\/])?[^:\n\r]+):(\d+):(\d+)",
            re.MULTILINE | re.DOTALL
        )
        for m in rust_pattern.finditer(output):
            err_code, msg, f_name, l_num, c_num = m.groups()
            parsed_errors.append(ParsedError(
                file=f_name.strip(),
                line=int(l_num),
                column=int(c_num),
                severity="error",
                error_code=err_code,
                message=msg.strip().splitlines()[0],
                raw_line=m.group(0).strip()
            ))

        # Filter out system header notes/errors if user file errors are present
        if file_path and parsed_errors:
            p_name = Path(file_path).name.lower()
            user_errors = [e for e in parsed_errors if e.file and Path(e.file).name.lower() == p_name]
            if user_errors:
                parsed_errors = user_errors
        elif parsed_errors:
            non_sys_errors = [e for e in parsed_errors if not any(s in (e.file or "").lower() for s in ["include\\c++", "include/c++", "usr/include", "lib/gcc", "bits/"])]
            if non_sys_errors:
                parsed_errors = non_sys_errors

        # G. Linker Errors (e.g. undefined reference to `main`, unresolved external symbol)
        if not parsed_errors:
            linker_match = re.search(r"(?:undefined reference to|unresolved external symbol|ld returned 1 exit status|LNK\d+:)\s*[`']?([^'\n\r]+)[`']?", output, re.IGNORECASE)
            if linker_match:
                sym_name = linker_match.group(1).strip()
                return DiagnosticResult(
                    success=True,
                    error_type=ErrorCategory.LINKER_ERROR.value,
                    stage="compile",
                    file=file_path or "build",
                    message=f"Linker error: undefined reference to `{sym_name}`.",
                    cause=f"The symbol `{sym_name}` was declared or required but its definition or linked library is missing.",
                    diagnosis="Compilation succeeded, but the linker could not find the executable entry point or compiled function body.",
                    suggested_fix=f"Ensure `{sym_name}` is defined in your source code or link the required object file / library.",
                    confidence=0.95,
                    confidence_level="HIGH",
                    human_readable=(
                        f"🔗 **Linker Error Detected**\n\n"
                        f"**Problem:** Undefined reference to `{sym_name}`.\n\n"
                        f"**Likely Cause:** Missing function implementation, missing `main()` entry point, or missing linked library.\n\n"
                        f"**Suggested Fix:** Provide the definition for `{sym_name}` or include the required source/library in compilation."
                    )
                )

        if not parsed_errors:
            return None

        # Sort errors by (file, line, column)
        parsed_errors.sort(key=lambda e: (e.file or "", e.line or 0, e.column or 0))

        # Mark cascading errors
        for i, err in enumerate(parsed_errors):
            if i > 0:
                err.is_cascading = True

        primary = parsed_errors[0]
        cat, cause, fix, token = cls._classify_compiler_error(primary.message, primary.file or file_path)
        token_len = len(token) if token else None

        ctx_str = cls.extract_source_context(source_code, primary.file or file_path, primary.line, primary.column, token_len=token_len)

        # Build errors dict list
        err_dicts = [
            {
                "file": e.file,
                "line": e.line,
                "column": e.column,
                "severity": e.severity,
                "message": e.message,
                "is_cascading": e.is_cascading
            }
            for e in parsed_errors
        ]

        cascading_str = ""
        if len(parsed_errors) > 1:
            cascading_str = f"\n\n*{len(parsed_errors)} errors detected. The first error at line {primary.line} is likely causing the following {len(parsed_errors)-1} cascading error(s).*"

        human_msg = (
            f"❌ **Compilation Failed**\n\n"
            f"**File:** `{primary.file or file_path or 'Source'}`\n"
            f"**Line:** {primary.line or '?'}" + (f"\n**Column:** {primary.column}" if primary.column else "") + "\n\n"
            f"**Problem:**\n`{primary.message}`\n\n"
            f"**Likely Cause:**\n{cause}\n\n"
            f"**Suggested Fix:**\n{fix}"
        )
        if ctx_str:
            human_msg += f"\n\n```\n{ctx_str}\n```"
        # Calibrate confidence based on error category specificity
        if cat in [ErrorCategory.COMPILER_ERROR, ErrorCategory.UNKNOWN_ERROR]:
            conf_score = 0.60
            conf_level = "MEDIUM"
        else:
            conf_score = 0.95
            conf_level = "HIGH"

        return DiagnosticResult(
            success=True,
            error_type=cat.value,
            stage="compile",
            file=primary.file or file_path,
            line=primary.line,
            column=primary.column,
            message=primary.message,
            cause=cause,
            diagnosis=f"Compiler error in {primary.file or 'source'} at line {primary.line}: {primary.message}",
            suggested_fix=fix,
            confidence=conf_score,
            confidence_level=conf_level,
            source_context=ctx_str,
            errors=err_dicts,
            primary_error=err_dicts[0] if err_dicts else None,
            related_errors=err_dicts[1:] if len(err_dicts) > 1 else [],
            human_readable=human_msg
        )

    @classmethod
    def _classify_compiler_error(cls, msg: str, filename: Optional[str] = None) -> Tuple[ErrorCategory, str, str, Optional[str]]:
        """
        Returns (ErrorCategory, LikelyCause, SuggestedFix, ProblematicToken).
        """
        msg_clean = msg.strip()

        # 1. Undeclared identifier / name error / typo / cannot find symbol / Cannot find name
        m_undecl = re.search(r"[`']?([a-zA-Z0-9_\.]+)[`']?\s*(?:was not declared in this scope|is not declared|undefined:)", msg_clean, re.IGNORECASE)
        if not m_undecl:
            m_undecl = re.search(r"(?:cannot find (?:symbol|value|name)|undefined:)\s*[`']?([a-zA-Z0-9_\.]+)[`']?", msg_clean, re.IGNORECASE)
        if m_undecl:
            token = m_undecl.group(1).strip()
            # Common typos mapping
            typo_corrections = {
                "coutt": "cout",
                "coint": "cout",
                "prin": "print",
                "prnt": "print",
                "prntln": "println",
                "sout": "System.out.println",
                "cnosole": "console",
                "consle": "console",
                "inclue": "include",
                "vectr": "vector",
                "sttring": "string",
                "strng": "string"
            }
            intended = typo_corrections.get(token.lower())
            if intended:
                return (
                    ErrorCategory.NAME_ERROR,
                    f"Typographical error - `{token}` is likely a typo for `{intended}`.",
                    f"Change `{token}` -> `{intended}`.",
                    token
                )
            return (
                ErrorCategory.NAME_ERROR,
                f"Identifier `{token}` is not declared, missing `#include` header, namespace `std::`, or out of scope.",
                f"Declare `{token}`, verify spelling, or include the appropriate library/header.",
                token
            )

        if any(k in msg_clean.lower() for k in ["cannot find symbol", "cannot find name", "not declared in this scope"]):
            m_sym = re.search(r"(?:symbol|name|variable|method|function)\s*[:\s]+(?:variable\s+|method\s+)?[`']?([a-zA-Z0-9_\.]+)[`']?", msg_clean, re.IGNORECASE)
            token = m_sym.group(1).strip() if m_sym else None
            return (
                ErrorCategory.NAME_ERROR,
                f"Identifier or symbol `{token or 'name'}` cannot be found or is not declared in this scope.",
                f"Verify declaration and spelling of `{token or 'symbol'}` or check required imports/includes.",
                token
            )

        # 2. Missing Semicolon / Syntax Error
        if (
            (";" in msg_clean and "expected" in msg_clean.lower())
            or "expected ';'" in msg_clean.lower()
            or "missing ';'" in msg_clean.lower()
            or "';' expected" in msg_clean.lower()
            or "expected semicolon" in msg_clean.lower()
            or "missing semicolon" in msg_clean.lower()
            or re.search(r"(?:expected\s+(?:.*?[,;\s]+)?['`]?;\s*['`]?|missing\s+['`;]|';'\s+expected)", msg_clean, re.IGNORECASE)
        ):
            return (
                ErrorCategory.SYNTAX_ERROR,
                "Missing statement terminator `;`.",
                "Add a semicolon `;` at the end of the preceding statement.",
                ";"
            )

        # 3. Missing Bracket / Parenthesis
        if re.search(r"(?:expected\s*['})\]]|unmatched|missing\s*['})\]])", msg_clean, re.IGNORECASE):
            return (
                ErrorCategory.SYNTAX_ERROR,
                "Mismatched or missing closing bracket, brace, or parenthesis.",
                "Check bracket pairs and ensure all `{`, `(`, `[` are properly closed.",
                None
            )

        # 4. Type Error / Incompatible Types / Cannot Convert
        if re.search(r"(?:cannot convert|incompatible types|type mismatch|mismatched types|cannot use .* as type|not assignable to type)", msg_clean, re.IGNORECASE):
            return (
                ErrorCategory.TYPE_ERROR,
                "Type mismatch - attempted to assign or pass a value of incompatible type.",
                "Cast or convert the value to the expected type, or adjust variable type declaration.",
                None
            )

        # 5. Missing Include / File Not Found
        if re.search(r"(?:No such file or directory|cannot open include file|module not found)", msg_clean, re.IGNORECASE):
            return (
                ErrorCategory.IMPORT_ERROR,
                "Header or module file not found.",
                "Verify the file path and ensure required library header is correctly installed and referenced.",
                None
            )

        # Default Compiler Error
        return (
            ErrorCategory.COMPILER_ERROR,
            "Compiler rejected source syntax or semantic structure.",
            "Inspect the syntax around the indicated line and column.",
            None
        )

    # -------------------------------------------------------------------------
    # Runtime Parsing Subsystem (Tracebacks, Panics, Exceptions)
    # -------------------------------------------------------------------------
    @classmethod
    def _parse_runtime_output(
        cls,
        output: str,
        language: str,
        file_path: Optional[str],
        source_code: Optional[str],
        exit_code: Optional[int]
    ) -> Optional[DiagnosticResult]:
        out_clean = output.strip()

        # A. JavaScript / Node.js Runtime Exception
        # ReferenceError: x is not defined at main.js:8:5
        # TypeError: Cannot read properties of undefined (reading 'x')
        if (
            ("ReferenceError:" in out_clean or "TypeError:" in out_clean or "SyntaxError:" in out_clean or "RangeError:" in out_clean)
            and (" at " in out_clean or "node:internal" in out_clean or language in ["javascript", "js", "typescript", "ts"] or (file_path and file_path.endswith((".js", ".ts", ".jsx", ".tsx"))))
        ):
            m_js_frame = re.search(r"at\s+(?:.*\((.+?):(\d+):(\d+)\)|(.+?):(\d+):(\d+))", out_clean)
            js_file = file_path
            js_line = None
            js_col = None
            if m_js_frame:
                js_file = m_js_frame.group(1) or m_js_frame.group(4) or file_path
                js_line = int(m_js_frame.group(2) or m_js_frame.group(5))
                js_col = int(m_js_frame.group(3) or m_js_frame.group(6))

            first_line = out_clean.splitlines()[0]
            cat = ErrorCategory.RUNTIME_ERROR
            cause = first_line
            fix = "Review the JavaScript stack trace and fix the expression."

            if "ReferenceError:" in first_line:
                cat = ErrorCategory.NAME_ERROR
                m_var = re.search(r"ReferenceError:\s*([a-zA-Z0-9_$]+)\s*is not defined", first_line)
                var_name = m_var.group(1) if m_var else None
                cause = f"Variable `{var_name or 'variable'}` was accessed without prior declaration or contains a typo."
                fix = f"Declare `{var_name or 'variable'}` with `const`, `let`, or verify its scope."

            elif "TypeError:" in first_line:
                if "null" in first_line.lower() or "undefined" in first_line.lower():
                    cat = ErrorCategory.NULL_REFERENCE
                    cause = "Attempted to access properties or methods on `null` or `undefined`."
                    fix = "Use optional chaining `?.` or check that the object is not null/undefined prior to access."
                else:
                    cat = ErrorCategory.TYPE_ERROR
                    cause = "Incompatible type or function invocation on non-callable value."
                    fix = "Ensure the target value is of the expected type before invocation."

            elif "RangeError:" in first_line and "stack" in first_line.lower():
                cat = ErrorCategory.EXCEPTION
                cause = "Maximum call stack size exceeded - infinite recursion detected."
                fix = "Verify base cases in recursive functions to prevent unbounded execution."

            ctx_str = cls.extract_source_context(source_code, js_file, js_line, js_col)
            return DiagnosticResult(
                success=True,
                error_type=cat.value,
                stage="runtime",
                file=js_file,
                line=js_line,
                column=js_col,
                message=first_line,
                cause=cause,
                diagnosis=f"JavaScript runtime error in {js_file} at line {js_line}: {first_line}",
                suggested_fix=fix,
                confidence=0.92,
                confidence_level="HIGH",
                source_context=ctx_str,
                human_readable=(
                    f"❌ **JavaScript Runtime Error**\n\n"
                    f"**File:** `{js_file or 'script.js'}`\n"
                    f"**Line:** {js_line or '?'}\n\n"
                    f"**Problem:**\n`{first_line}`\n\n"
                    f"**Likely Cause:**\n{cause}\n\n"
                    f"**Suggested Fix:**\n{fix}"
                )
            )

        # B. Python Traceback or Single-line exception
        if (
            "Traceback (most recent call last):" in out_clean
            or re.search(r"File\s*['\"].+?['\"],\s*line\s*\d+", out_clean)
            or re.search(r"^(?:[a-zA-Z0-9_\.]*(?:Error|Exception|Warning)):\s*", out_clean, re.MULTILINE)
            or language == "python"
        ):
            # Extract frames
            frame_pattern = re.compile(r"File\s*['\"]([^'\"]+)['\"],\s*line\s*(\d+)(?:,\s*in\s*(.+))?", re.IGNORECASE)
            frames = frame_pattern.findall(out_clean)
            last_file = frames[-1][0] if frames else file_path
            last_line = int(frames[-1][1]) if frames else None

            # Extract exception line (usually last non-empty line)
            exc_lines = [l.strip() for l in out_clean.splitlines() if l.strip()]
            exc_line = exc_lines[-1] if exc_lines else "Exception"

            m_exc = re.match(r"^([a-zA-Z0-9_\.]+):\s*(.*)$", exc_line)
            exc_type = m_exc.group(1) if m_exc else "Exception"
            exc_msg = m_exc.group(2) if m_exc else exc_line

            # Map Python exception to Category
            cat = ErrorCategory.EXCEPTION
            cause = f"Python raised `{exc_type}`: {exc_msg}"
            fix = "Inspect the traceback and handle the exception."
            token = None

            if exc_type == "NameError":
                cat = ErrorCategory.NAME_ERROR
                m_var = re.search(r"name\s*['\"]([^'\"]+)['\"]\s*is not defined", exc_msg)
                var_name = m_var.group(1) if m_var else None
                token = var_name
                cause = f"Variable or identifier `{var_name or 'name'}` is referenced before definition or contains a typo."
                fix = f"Define `{var_name or 'variable'}` before using it, or verify its spelling and scope."

            elif exc_type == "ZeroDivisionError":
                cat = ErrorCategory.DIVISION_BY_ZERO
                cause = "Division or modulo by zero operation encountered at runtime."
                fix = "Add a guard condition to verify the denominator is non-zero before dividing (e.g. `if b != 0:`)."

            elif exc_type == "IndexError":
                cat = ErrorCategory.INDEX_ERROR
                cause = "Attempted to access list, tuple, or sequence element at an index outside its valid range."
                fix = "Verify sequence length before indexing (e.g. `if 0 <= index < len(seq):`)."

            elif exc_type in ["ModuleNotFoundError", "ImportError"]:
                cat = ErrorCategory.MODULE_ERROR
                m_mod = re.search(r"No module named\s*['\"]([^'\"]+)['\"]", exc_msg)
                mod_name = m_mod.group(1) if m_mod else None
                token = mod_name
                cause = f"Python module `{mod_name or 'module'}` is not installed in the current environment."
                fix = f"Install `{mod_name or 'package'}` via package manager or check the import name spelling."

            elif exc_type == "SyntaxError":
                cat = ErrorCategory.SYNTAX_ERROR
                cause = "Invalid Python syntax structure."
                fix = "Check colons, indentation, brackets, or invalid keywords around the line."

            elif exc_type == "TypeError":
                cat = ErrorCategory.TYPE_ERROR
                cause = f"Unsupported operation or function call with incompatible argument types: {exc_msg}"
                fix = "Verify parameter types and ensure compatible values are passed."

            elif exc_type == "KeyError":
                cat = ErrorCategory.EXCEPTION
                cause = f"Dictionary key not found: {exc_msg}"
                fix = "Check key presence or use `.get(key)` with default fallback."

            elif exc_type == "RecursionError":
                cat = ErrorCategory.EXCEPTION
                cause = "Maximum recursion depth exceeded - likely infinite recursive function calls."
                fix = "Check recursive base case and ensure recursion progresses toward termination."

            ctx_str = cls.extract_source_context(source_code, last_file, last_line)

            human_msg = (
                f"❌ **Python Runtime Exception: `{exc_type}`**\n\n"
                f"**File:** `{last_file or 'script.py'}`\n"
                f"**Line:** {last_line or '?'}\n\n"
                f"**Problem:**\n`{exc_msg}`\n\n"
                f"**Likely Cause:**\n{cause}\n\n"
                f"**Suggested Fix:**\n{fix}"
            )
            if ctx_str:
                human_msg += f"\n\n```\n{ctx_str}\n```"

            return DiagnosticResult(
                success=True,
                error_type=cat.value,
                stage="runtime",
                file=last_file,
                line=last_line,
                column=None,
                message=f"{exc_type}: {exc_msg}",
                cause=cause,
                diagnosis=f"Python runtime exception '{exc_type}' in {last_file} at line {last_line}: {exc_msg}",
                suggested_fix=fix,
                confidence=0.95,
                confidence_level="HIGH",
                source_context=ctx_str,
                human_readable=human_msg
            )

        # C. Java Runtime Exceptions
        # Exception in thread "main" java.lang.NullPointerException
        # Exception in thread "main" java.lang.ArrayIndexOutOfBoundsException: Index 5 out of bounds for length 3
        # Exception in thread "main" java.lang.ArithmeticException: / by zero
        if "Exception in thread" in out_clean or "java.lang." in out_clean:
            m_java_frame = re.search(r"at\s+[a-zA-Z0-9_\.]+\(([^:]+):(\d+)\)", out_clean)
            j_file = m_java_frame.group(1) if m_java_frame else file_path
            j_line = int(m_java_frame.group(2)) if m_java_frame else None

            first_line = out_clean.splitlines()[0]
            cat = ErrorCategory.RUNTIME_ERROR
            cause = first_line
            fix = "Inspect Java runtime exception details."

            if "NullPointerException" in out_clean:
                cat = ErrorCategory.NULL_REFERENCE
                cause = "Attempted to invoke a method or access a field on a `null` object reference."
                fix = "Initialize the object reference or add a null check (`if (obj != null)`)."
            elif "ArrayIndexOutOfBoundsException" in out_clean:
                cat = ErrorCategory.INDEX_ERROR
                cause = "Array index was out of bounds (negative or >= array.length)."
                fix = "Verify array indices remain within `0 <= index < array.length`."
            elif "ArithmeticException" in out_clean and "/ by zero" in out_clean:
                cat = ErrorCategory.DIVISION_BY_ZERO
                cause = "Integer division by zero."
                fix = "Check divisor before division to prevent dividing by zero."

            ctx_str = cls.extract_source_context(source_code, j_file, j_line)
            return DiagnosticResult(
                success=True,
                error_type=cat.value,
                stage="runtime",
                file=j_file,
                line=j_line,
                column=None,
                message=first_line,
                cause=cause,
                diagnosis=f"Java exception in {j_file} at line {j_line}: {first_line}",
                suggested_fix=fix,
                confidence=0.92,
                confidence_level="HIGH",
                source_context=ctx_str,
                human_readable=(
                    f"❌ **Java Runtime Exception**\n\n"
                    f"**File:** `{j_file or 'Main.java'}`\n"
                    f"**Line:** {j_line or '?'}\n\n"
                    f"**Problem:**\n`{first_line}`\n\n"
                    f"**Likely Cause:**\n{cause}\n\n"
                    f"**Suggested Fix:**\n{fix}"
                )
            )

        # D. Go Runtime Panic
        # panic: runtime error: index out of range [5] with length 3
        # panic: runtime error: integer divide by zero
        if "panic:" in out_clean:
            m_go_frame = re.search(r"([^:\n\r]+\.go):(\d+)", out_clean)
            g_file = m_go_frame.group(1) if m_go_frame else file_path
            g_line = int(m_go_frame.group(2)) if m_go_frame else None

            panic_line = [l.strip() for l in out_clean.splitlines() if l.strip().startswith("panic:")][0]
            cat = ErrorCategory.RUNTIME_ERROR
            cause = panic_line
            fix = "Handle the panic condition or guard inputs."

            if "index out of range" in panic_line:
                cat = ErrorCategory.INDEX_ERROR
                cause = "Slice or array index is out of bounds."
                fix = "Check slice length with `len(slice)` before accessing index."
            elif "divide by zero" in panic_line:
                cat = ErrorCategory.DIVISION_BY_ZERO
                cause = "Integer division by zero."
                fix = "Ensure denominator is non-zero before dividing."
            elif "nil pointer dereference" in panic_line:
                cat = ErrorCategory.NULL_REFERENCE
                cause = "Attempted to access field or call method on a nil pointer."
                fix = "Verify pointer is not nil (`if ptr != nil`) before dereferencing."

            ctx_str = cls.extract_source_context(source_code, g_file, g_line)
            return DiagnosticResult(
                success=True,
                error_type=cat.value,
                stage="runtime",
                file=g_file,
                line=g_line,
                column=None,
                message=panic_line,
                cause=cause,
                diagnosis=f"Go panic in {g_file} at line {g_line}: {panic_line}",
                suggested_fix=fix,
                confidence=0.92,
                confidence_level="HIGH",
                source_context=ctx_str,
                human_readable=(
                    f"❌ **Go Panic**\n\n"
                    f"**File:** `{g_file or 'main.go'}`\n"
                    f"**Line:** {g_line or '?'}\n\n"
                    f"**Problem:**\n`{panic_line}`\n\n"
                    f"**Likely Cause:**\n{cause}\n\n"
                    f"**Suggested Fix:**\n{fix}"
                )
            )

        # E. Rust Runtime Panic
        # thread 'main' panicked at 'index out of bounds: the len is 3 but the index is 5', src/main.rs:8:5
        if "panicked at" in out_clean:
            m_rust_frame = re.search(r"panicked at '([^']+)',\s*([^:\n\r]+):(\d+):(\d+)", out_clean)
            if m_rust_frame:
                p_msg, r_file, r_line, r_col = m_rust_frame.groups()
                cat = ErrorCategory.RUNTIME_ERROR
                if "index out of bounds" in p_msg:
                    cat = ErrorCategory.INDEX_ERROR
                elif "divide by zero" in p_msg:
                    cat = ErrorCategory.DIVISION_BY_ZERO

                ctx_str = cls.extract_source_context(source_code, r_file, int(r_line), int(r_col))
                return DiagnosticResult(
                    success=True,
                    error_type=cat.value,
                    stage="runtime",
                    file=r_file,
                    line=int(r_line),
                    column=int(r_col),
                    message=p_msg,
                    cause=f"Rust panic: {p_msg}",
                    diagnosis=f"Rust panic in {r_file} at line {r_line}:{r_col}: {p_msg}",
                    suggested_fix="Guard against out-of-bounds access or invalid operation.",
                    confidence=0.95,
                    confidence_level="HIGH",
                    source_context=ctx_str,
                    human_readable=(
                        f"❌ **Rust Panic**\n\n"
                        f"**File:** `{r_file}`\n"
                        f"**Line:** {r_line}\n**Column:** {r_col}\n\n"
                        f"**Problem:**\n`{p_msg}`\n\n"
                        f"**Suggested Fix:** Verify boundaries and handle `Option`/`Result` values."
                    )
                )

        return None

    @classmethod
    def _find_any_source_location(cls, text: str, default_file: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
        """Finds line and column numbers from unstructured error text if present."""
        m = re.search(r"(?:line|:)\s*(\d+)(?::(\d+))?", text, re.IGNORECASE)
        if m:
            l = int(m.group(1))
            c = int(m.group(2)) if m.group(2) else None
            return l, c
        return None, None
