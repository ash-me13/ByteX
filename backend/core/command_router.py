import re
import time
from typing import Tuple, List, Dict, Optional, Any
from memory.manager import MemoryManager
from skills.registry import skill_registry
from security.permissions import permissions

class CommandRouter:
    """Deterministic intent router matching user prompts to registered ByteX skills."""

    CODE_EXT_RE = r"(?:py|pyw|pyi|cpp|cxx|cc|hpp|hxx|c|h|js|mjs|cjs|jsx|ts|tsx|html|htm|css|scss|sass|less|json|go|rs|java|kt|cs|rb|php|swift|sql|md|txt|yaml|yml|toml|xml|env)"

    @classmethod
    def _extract_target_file(cls, text: str) -> Optional[str]:
        """
        Extracts a code file path, URI, or filename from a natural language request.
        Ignores HTTP/HTTPS URLs so they are never treated as local filesystem paths.
        """
        if not text:
            return None

        # 0. Mask out HTTP/HTTPS URLs so they are never interpreted as local filesystem paths.
        # This preserves separate local paths if the text contains both a URL and a local path.
        search_text = re.sub(r'https?://[^\s"\'<>]+', ' ', text)

        # 1. Quoted file:// URI (supports spaces inside quotes)
        m_q_file = re.search(r'["\'<](file://[^\s"\'<>]+(?:\s+[^\s"\'<>]+)*)["\'>]', search_text, flags=re.IGNORECASE)
        if m_q_file:
            cand = m_q_file.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 2. Unquoted file:// URI (may be percent-encoded)
        m_file = re.search(r'(file://[^\s"\'<>]+)', search_text, flags=re.IGNORECASE)
        if m_file:
            cand = m_file.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 3. Quoted local paths (e.g. "C:\My Dir\main.cpp", "/Users/name/my code/test.cpp", "src/app.ts")
        m_q = re.search(r'["\']([^"\']+?\.' + cls.CODE_EXT_RE + r')["\']', search_text, flags=re.IGNORECASE)
        if m_q:
            cand = m_q.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 4. Windows absolute path (e.g. C:\project\main.cpp or C:/project/main.cpp)
        m_win = re.search(r'([a-zA-Z]:[\\/](?:[^\\/:*?"<>|\r\n\s]+[\\/])*[^\\/:*?"<>|\r\n\s]+\.' + cls.CODE_EXT_RE + r')\b', search_text, flags=re.IGNORECASE)
        if m_win:
            cand = m_win.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 5. Unix / macOS absolute path (e.g. /Users/name/project/main.cpp, /var/folders/.../test.py)
        # Must start with / at beginning of string or preceded by whitespace / punctuation
        m_unix = re.search(r'(?:\A|[\s"\'<(\[])(/(?:[^/\s:*?"<>|\r\n]+[\\/])*[^/\s:*?"<>|\r\n]+\.' + cls.CODE_EXT_RE + r')\b', search_text, flags=re.IGNORECASE)
        if m_unix:
            cand = m_unix.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 6. Explicit relative paths with directory components (e.g. src/utils.js, tests/test.py)
        m_rel = re.search(r'\b([a-zA-Z0-9_\-./\\]+[\\/][a-zA-Z0-9_\-./\\]+\.' + cls.CODE_EXT_RE + r')\b', search_text, flags=re.IGNORECASE)
        if m_rel:
            cand = m_rel.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 7. Plain filename with code extension (e.g. 01_basic.cpp, main.py, testing.cpp, App.tsx)
        m_fn = re.search(r'\b([a-zA-Z0-9_\-\.]+\.' + cls.CODE_EXT_RE + r')\b', search_text, flags=re.IGNORECASE)
        if m_fn:
            cand = m_fn.group(1).strip()
            return re.sub(r"[.!?,\"\':)\]>]+$", "", cand).strip()

        # 8. Active file references (e.g. "this file", "current file", "here")
        if re.search(r'\b(?:this\s+file|current\s+file|active\s+file|the\s+current\s+file|the\s+active\s+file|this\s+code|my\s+code|the\s+code|this\s+source|here)\b', search_text, flags=re.IGNORECASE):
            return "this file"

        return None

    @classmethod
    async def parse_skill_intent(cls, message: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        # 0. Multilingual Pre-processing (Feature #37.3)
        from core.multilingual_router import MultilingualRouter
        norm_msg, _ = MultilingualRouter.process_input(message)

        # Pre-process: strip conversational fillers and trailing punctuation
        msg_clean = norm_msg.strip()
        msg_clean = re.sub(r"^(?:hey\s+bytex|bytex|please|can\s+you|could\s+you|would\s+you|actually|no\s+wait|wait)[,:\s]+", "", msg_clean, flags=re.IGNORECASE)
        msg_clean = re.sub(r"[.!?,\"\']+$", "", msg_clean).strip()
        msg_clean = re.sub(r"\s+instead$", "", msg_clean, flags=re.IGNORECASE).strip()
        msg_lower = msg_clean.lower()

        # 1. Application Status Check
        app_status_match = re.match(r"^(?:is\s+([a-zA-Z0-9_\s-]+)\s+running\??|status\s+of\s+([a-zA-Z0-9_\s-]+))$", msg_lower)
        if app_status_match:
            app_target = (app_status_match.group(1) or app_status_match.group(2)).strip()
            exe = permissions.get_allowed_app_executable(app_target)
            if exe:
                return "application_status", {"application": app_target}

        # 1.4. Coding Workspace Intent (Feature #33.1 Coding Workspace)
        # 1.4.0 Active Coding Workspace Query
        # E.g. "What coding workspace am I currently working in?", "What workspace am I in?", "Where is my current workspace?"
        m_ws_query = re.match(
            r"^(?:what|which|where)\s+(?:is\s+)?(?:my\s+|the\s+)?(?:current\s+|active\s+)?(?:coding\s+)?(?:workspace|project)(?:\s+am\s+i\s+(?:currently\s+)?(?:working\s+in|in|working\s+on))?(?:\s+currently)?(?:\s+open|\s+active|\s+located)?\??$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_ws_query or msg_lower in [
            "what coding workspace am i currently working in",
            "what coding workspace am i currently working in?",
            "what coding workspace am i in",
            "what coding workspace am i in?",
            "what workspace am i currently working in",
            "what workspace am i currently working in?",
            "what workspace am i working in",
            "what workspace am i working in?",
            "what workspace am i in",
            "what workspace am i in?",
            "what is my current coding workspace",
            "what is my current coding workspace?",
            "what is my current workspace",
            "what is my current workspace?",
            "what is my active workspace",
            "what is my active workspace?",
            "what is the active workspace",
            "which coding workspace am i working in",
            "which workspace am i currently working in",
            "which workspace am i in",
            "which project am i currently working on",
            "which project is currently open",
            "which project is open",
            "what project is open",
            "what project am i working on",
            "where is my current workspace",
            "where is my active workspace",
            "where is the coding workspace",
            "show my current workspace",
            "show active workspace",
            "get active workspace",
            "get current workspace",
            "current workspace",
            "active workspace",
            "current project",
            "active project"
        ]:
            return "coding_workspace", {"action": "get_active_workspace"}

        # A. Project Creation
        # E.g. "Create a Python project called TestApp", "Create a C++ project called DSA", "Create a JavaScript project called WebApp"
        m_create_proj = re.match(
            r"^(?:create|make|init|initialize)\s+(?:a\s+)?(?:([a-zA-Z0-9_\+\#]+)\s+)?project\s+(?:called|named|with\s+name|for)?\s*([a-zA-Z0-9_\-\.]+)\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_create_proj:
            lang_cand = (m_create_proj.group(1) or "").strip().lower()
            p_name = m_create_proj.group(2).strip()
            return "coding_workspace", {
                "action": "create_project",
                "project_name": p_name,
                "language": lang_cand if lang_cand else "python"
            }

        # B. Project Structure & Inspection
        # E.g. "Show the project structure", "Show project structure", "Show TestApp files", "What is inside this project?", "Inspect this project"
        if msg_lower in [
            "show the project structure", "show project structure", "project structure", "show project tree", "project tree", "what is inside this project", "what is inside this project?", "show this project structure"
        ]:
            return "coding_workspace", {"action": "project_structure"}

        m_show_proj_files = re.match(r"^(?:show|list|display)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\s+(?:project\s+)?(?:files|structure|tree)\.?$", msg_clean, flags=re.IGNORECASE)
        if m_show_proj_files:
            p_cand = m_show_proj_files.group(1).strip()
            if p_cand.lower() not in ["my", "the", "all", "open"]:
                return "coding_workspace", {"action": "project_structure", "project_name": p_cand}

        m_what_files = re.match(r"^what\s+files\s+are\s+in\s+([a-zA-Z0-9_\-]+)\??$", msg_clean, flags=re.IGNORECASE)
        if m_what_files:
            p_cand = m_what_files.group(1).strip()
            return "coding_workspace", {"action": "inspect_project", "project_name": p_cand}

        m_inspect = re.match(r"^(?:inspect|show|display)\s+(?:my\s+|the\s+)?project(?:\s+called|\s+named|\s+([a-zA-Z0-9_\-]+))?\.?$", msg_clean, flags=re.IGNORECASE)
        if m_inspect or msg_lower in ["inspect this project", "inspect project", "show my project", "show the project"]:
            p_cand = m_inspect.group(1).strip() if (m_inspect and m_inspect.group(1)) else None
            return "coding_workspace", {"action": "inspect_project", "project_name": p_cand}

        # C. Open Project
        # E.g. "Open my TestApp project", "Open project TestApp", "Open project called TestApp"
        m_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?(?:project\s+called|project\s+named|project)\s+([a-zA-Z0-9_\-]+)\.?$", msg_clean, flags=re.IGNORECASE)
        if not m_open_proj:
            m_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-]+)\s+project\.?$", msg_clean, flags=re.IGNORECASE)
        if m_open_proj:
            p_name = m_open_proj.group(1).strip()
            if p_name.lower() in ["folder", "dir", "directory", "files"]:
                from memory.manager import memory_manager
                act = memory_manager.get_active_project()
                if act and act.workspace_path:
                    return "file_search", {"query": act.workspace_path}
                elif act and act.project_name:
                    return "coding_workspace", {"action": "open_project", "project_name": act.project_name}
            elif p_name.lower() not in ["my", "the", "a", "this"]:
                return "coding_workspace", {"action": "open_project", "project_name": p_name}

        # D. Detect Language
        # E.g. "Detect the project language", "Detect language of this project", "What language is TestApp?"
        if (
            re.match(r"^(?:detect|identify|what\s+is)\s+(?:the\s+)?(?:project\s+)?language(?:\s+of\s+this\s+project|\s+of\s+([a-zA-Z0-9_\-]+))?\??$", msg_clean, flags=re.IGNORECASE)
            or msg_lower in ["detect the project language", "detect project language", "detect the language of this project", "detect language", "project language"]
        ):
            m_det = re.match(r"^(?:detect|identify|what\s+is)\s+(?:the\s+)?(?:project\s+)?language\s+of\s+([a-zA-Z0-9_\-]+)\??$", msg_clean, flags=re.IGNORECASE)
            p_cand = m_det.group(1).strip() if m_det else None
            return "coding_workspace", {"action": "detect_language", "project_name": p_cand}

        m_what_lang = re.match(r"^what\s+language\s+is\s+([a-zA-Z0-9_\-]+)\??$", msg_clean, flags=re.IGNORECASE)
        if m_what_lang:
            p_cand = m_what_lang.group(1).strip()
            return "coding_workspace", {"action": "detect_language", "project_name": p_cand}

        # E. Code File Creation
        # E.g. "Create main.py", "Create main.cpp", "Create app.js", "Create App.tsx"
        m_create_code = re.match(r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?(?:code\s+|source\s+)?file\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)(?:\s+in\s+([a-zA-Z0-9_\-]+))?\.?$", msg_clean, flags=re.IGNORECASE)
        if not m_create_code:
            m_create_code = re.match(r"^(?:create|make)\s+([a-zA-Z0-9_\-\.]+\.(?:html|htm|json|java|jsx|tsx|hpp|cpp|css|sql|py|ts|js|go|rs|md|c|h))(?:\s+in\s+([a-zA-Z0-9_\-]+))?\.?$", msg_clean, flags=re.IGNORECASE)
        if m_create_code:
            fname = m_create_code.group(1).strip()
            p_cand = m_create_code.group(2).strip() if m_create_code.group(2) else None
            return "coding_workspace", {"action": "create_code_file", "filename": fname, "project_name": p_cand}

        # F. Code File Read
        # E.g. "Read main.py", "Show main.cpp", "What is inside App.tsx?", "Open and read testing.cpp"
        if (
            re.match(r"^(?:read|show|view|display|cat|open\s+and\s+read)\b", msg_clean, flags=re.IGNORECASE)
            or re.match(r"^what\s+(?:is|code\s+is)\s+inside\b", msg_clean, flags=re.IGNORECASE)
        ):
            target_fn = cls._extract_target_file(msg_clean)
            if target_fn and not any(kw in msg_lower for kw in ["screen", "display", "button", "window", "website", "web", "browser", "youtube", "google"]):
                if any(kw in msg_lower for kw in ["tell me what", "what it does", "what does it do", "explain", "describe", "how it works", "walk me through"]):
                    return "coding_workspace", {"action": "explain_code", "filename": target_fn, "prompt": msg_clean}
                return "coding_workspace", {"action": "read_code_file", "filename": target_fn}

        # F2. Coding File Location / Find File in Workspace
        # E.g. "Find testing.cpp in my current project", "Find main.cpp", "Locate dsa.cpp in my workspace", "Search for hello.html in my project", "Find settings.py in my project", "Find this file"
        if msg_lower in [
            "find this file", "find this file.", "locate this file", "where is this file", "where is this file?",
            "where is the current file", "find the current file", "locate current file", "find current file"
        ]:
            return "coding_workspace", {"action": "find_file", "filename": "this file"}

        m_find_code_file = re.match(
            r"^(?:find|locate|search\s+for|where\s+is|show\s+me\s+where\s+is)\s+(?:the\s+|my\s+)?(?:source\s+|code\s+)?(?:file\s+)?([a-zA-Z0-9_\-\.]+\.(?:html|htm|json|java|jsx|tsx|hpp|cpp|cc|cxx|css|sql|py|pyw|ts|js|mjs|cjs|go|rs|md|txt|c|h|xml|yaml|yml|toml|kt|cs|rb|php|swift))(?:[,\s]+(?:in|inside)\s+(?:my\s+|the\s+)?(?:current\s+|active\s+)?(?:coding\s+)?(?:project|workspace|folder|dir))?\.?\??$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_find_code_file:
            fname = m_find_code_file.group(1).strip()
            return "coding_workspace", {"action": "find_file", "filename": fname}

        m_find_in_proj = re.match(
            r"^(?:find|locate|search\s+for|where\s+is)\s+(?:the\s+|my\s+)?(.+?)\s+(?:in|inside)\s+(?:my\s+|the\s+)?(?:current\s+|active\s+)?(?:coding\s+)?(?:project|workspace|folder)\??$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_find_in_proj:
            cand_target = m_find_in_proj.group(1).strip()
            if not any(kw in cand_target.lower() for kw in ["screen", "button", "web", "internet", "browser", "youtube", "google"]):
                return "coding_workspace", {"action": "find_file", "filename": cand_target}

        # G. Code File Edit & Modification (Coding Workspace 2.0)
        # G. Code File Edit & Modification (Coding Workspace 2.0)
        _target_pattern = r"([a-zA-Z0-9_\-\./\\]+\." + cls.CODE_EXT_RE + r"|this\s+file|current\s+file|active\s+file|the\s+current\s+file|the\s+active\s+file|this\s+code|the\s+code|here)\b"

        # 0. "Change the sum calculation in main.cpp to calculate the sum from 1 to 100 instead of a + b", "Rewrite the function in main.cpp to calculate factorial"
        m_modify_part_in_file = re.match(
            r"^(?:modify|update|edit|alter|rewrite|change|optimize|optimise|fix|repair|correct|patch|make)\s+(?:the\s+)?(.+?)\s+(?:in|inside|of)\s+" + _target_pattern + r"\s*(?:to|and\s+make\s+it|and\s+add\s+a|and\s+add|and|so\s+that|so\s+it|so|that\s+it|that|for|with|:|,\s*)?\s*(.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_modify_part_in_file:
            part_name = m_modify_part_in_file.group(1).strip()
            fname = m_modify_part_in_file.group(2).strip()
            instr = m_modify_part_in_file.group(3).strip()
            if any(k in msg_lower for k in [
                "don't modify", "do not modify", "dont modify", "without modifying",
                "show me what you would change", "don't change", "do not change",
                "reduce its time complexity", "reduce time complexity", "reduce complexity", "analyze complexity"
            ]):
                return "coding_workspace", {
                    "action": "analyze_code",
                    "filename": fname,
                    "prompt": msg_clean
                }
            should_run = bool(re.search(r"\b(?:run|execute|and\s+run)\b", msg_clean, re.IGNORECASE))
            should_verify = bool(re.search(r"\b(?:verify|verification)\b", msg_clean, re.IGNORECASE))
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": f"{part_name} {instr}".strip(),
                "prompt": msg_clean,
                "run": should_run,
                "verify": should_verify
            }

        # 1. "Modify my main.cpp to print numbers from 1 to 100 instead of Hello ByteX", "Optimize main.cpp", "Fix main.cpp", "Change main.cpp to print Hello World", "Change 01_basic.cpp so it prints numbers from 1 to 10", "Make main.cpp print hello"
        m_modify_file = re.match(
            r"^(?:modify|update|edit|alter|rewrite|change|optimize|optimise|fix|repair|correct|patch|make)\s+(?:my\s+|the\s+|this\s+)?" + _target_pattern + r"\s*(?:and\s+make\s+it|and\s+add\s+a|and\s+add|and|to|for|with|so\s+that|so\s+it|so|that\s+it|that|:|,\s*)?\s*(.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_modify_file:
            fname = m_modify_file.group(1).strip()
            instr = m_modify_file.group(2).strip()
            if not instr and any(k in msg_lower for k in ["optimize", "optimise"]):
                instr = "optimize"
            elif not instr and any(k in msg_lower for k in ["fix", "repair", "correct", "patch"]):
                instr = "fix bug"
            elif not instr:
                instr = "modify"

            if any(k in msg_lower for k in [
                "don't modify", "do not modify", "dont modify", "without modifying",
                "show me what you would change", "don't change", "do not change",
                "reduce its time complexity", "reduce time complexity", "reduce complexity", "analyze complexity"
            ]):
                return "coding_workspace", {
                    "action": "analyze_code",
                    "filename": fname,
                    "prompt": msg_clean
                }
            should_run = bool(re.search(r"\b(?:run|execute|and\s+run)\b", msg_clean, re.IGNORECASE))
            should_verify = bool(re.search(r"\b(?:verify|verification)\b", msg_clean, re.IGNORECASE))
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": instr,
                "prompt": msg_clean,
                "run": should_run,
                "verify": should_verify
            }

        # 1b. "Add a function to find the largest element in this file", "Add a function to this file to find the largest element"
        m_this_file_add = re.match(
            r"^(?:add|insert|create|write|put|append)\s+(?:a\s+|an\s+)?(?:function|method|logic|code|snippet)?\s*(?:to|for)?\s*(.+?)\s+(?:in|to|into)\s+(this\s+file|current\s+file|the\s+current\s+file|the\s+active\s+file|here)\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_this_file_add:
            instr = m_this_file_add.group(1).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": "this file",
                "instruction": f"add {instr}",
                "prompt": msg_clean
            }

        # 1c. "Add a loop to main.cpp", "Add a message after the existing output in 01_basic.cpp that says HELLO_BYTE_X", "Add a function to main.cpp that calculates factorial", "Add factorial function to main.cpp"
        m_add_to_file = re.match(
            r"^(?:add|insert|create|write|put|append)\s+(?:a\s+|an\s+)?(.+?)\s+(?:to|in|into)\s+" + _target_pattern + r"\s*(?:to|for|that|which|so\s+that|so\s+it|so|and)?\s*(.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_add_to_file:
            what = m_add_to_file.group(1).strip()
            fname = m_add_to_file.group(2).strip()
            extra = m_add_to_file.group(3).strip()
            full_instr = f"add {what}" + (f" that {extra}" if extra else "")
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": full_instr,
                "prompt": msg_clean
            }

        m_add_to_file_prefix = re.match(
            r"^(?:add|insert|create|write|put|append)\s+(?:to|in|into)\s+" + _target_pattern + r"\s*(?:a\s+|an\s+)?(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_add_to_file_prefix:
            fname = m_add_to_file_prefix.group(1).strip()
            what = m_add_to_file_prefix.group(2).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": f"add {what}",
                "prompt": msg_clean
            }

        # 1d. "Remove the old loop from main.cpp.", "Remove the loop from main.cpp", "Delete the loop in main.cpp", "Remove factorial function from main.cpp"
        m_remove_from_file = re.match(
            r"^(?:remove|delete|drop|strip|clean\s+up|cut)\s+(?:the\s+|this\s+)?(.+?)\s+(?:from|in|inside|of)\s+" + _target_pattern + r"\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_remove_from_file:
            what = m_remove_from_file.group(1).strip()
            fname = m_remove_from_file.group(2).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": f"remove {what}",
                "prompt": msg_clean
            }

        # 1e. Implicit Output / Message / Loop Modification (Active File)
        # E.g. "Change the output to Hello ByteX.", "Change output to Hello World", "Change message to Hello ByteX"
        m_implicit_output_change = re.match(
            r"^(?:change|update|set|modify|replace)\s+(?:the\s+)?(?:output|print|message|greeting|text|result)\s+(?:to|with|as|=)\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_implicit_output_change:
            new_val = m_implicit_output_change.group(1).strip()
            target_fn = cls._extract_target_file(msg_clean) or "this file"
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": target_fn,
                "instruction": f"change output to {new_val}",
                "prompt": msg_clean
            }

        m_implicit_add = re.match(
            r"^(?:add|insert|create|write|put)\s+(?:a\s+|an\s+)?(loop|for\s+loop|while\s+loop|function\s+.+|method\s+.+|factorial\s+function|print\s+statement.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_implicit_add:
            what = m_implicit_add.group(1).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": "this file",
                "instruction": f"add {what}",
                "prompt": msg_clean
            }

        m_implicit_remove = re.match(
            r"^(?:remove|delete|drop|strip|clean\s+up)\s+(?:the\s+|this\s+)?(old\s+loop|loop|for\s+loop|while\s+loop|function\s+.+|factorial\s+function|print\s+statement.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_implicit_remove:
            what = m_implicit_remove.group(1).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": "this file",
                "instruction": f"remove {what}",
                "prompt": msg_clean
            }

        # 2. "In main.cpp, print numbers from 1 to 100 instead of Hello ByteX", "Inside main.py modify the print statement"
        m_in_file_modify = re.match(
            r"^(?:in|inside)\s+(?:my\s+|the\s+)?" + _target_pattern + r"[,:\s]+(?:modify|update|edit|alter|rewrite|change|replace|print|add|write|set)?\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_in_file_modify:
            fname = m_in_file_modify.group(1).strip()
            instr = m_in_file_modify.group(2).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": instr,
                "prompt": msg_clean
            }

        # 3. "Open main.cpp and modify it to print numbers from 1 to 100 instead of Hello ByteX", "Open main.cpp and change ..."
        m_open_and_modify = re.match(
            r"^(?:open|load)\s+(?:my\s+|the\s+)?" + _target_pattern + r"\s+and\s+(?:modify|update|edit|alter|rewrite|change|replace)\s*(?:it\s+to|it\s+with|it\s+so\s+that|it)?\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_open_and_modify:
            fname = m_open_and_modify.group(1).strip()
            instr = m_open_and_modify.group(2).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "instruction": instr,
                "prompt": msg_clean
            }

        # 4. "Change Hello World to Hello ByteX in main.py", "Replace A with B in main.cpp"
        m_edit_replace = re.match(r"^(?:change|replace)\s+(.+?)\s+(?:to|with)\s+(.+?)\s+in\s+" + _target_pattern + r"\.?$", msg_clean, flags=re.IGNORECASE)
        if m_edit_replace:
            tgt = m_edit_replace.group(1).strip().strip('"\'')
            repl = m_edit_replace.group(2).strip().strip('"\'')
            fname = m_edit_replace.group(3).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "target_text": tgt,
                "replacement_text": repl,
                "prompt": msg_clean
            }

        # 5. "Add Hello World to main.cpp", "Write ... in main.py"
        m_edit_add = re.match(r"^(?:add|append|write|insert)\s+([\"\'].+?[\"\'])\s+(?:to|in|into)\s+" + _target_pattern + r"\.?$", msg_clean, flags=re.IGNORECASE)
        if m_edit_add:
            content_val = m_edit_add.group(1).strip().strip('"\'')
            fname = m_edit_add.group(2).strip()
            return "coding_workspace", {
                "action": "edit_code_file",
                "filename": fname,
                "content": content_val,
                "prompt": msg_clean
            }

        # 6. Universal Fallback: Local Code File + Code Modification Intent -> Coding Workspace
        cand_code_file = cls._extract_target_file(msg_clean)
        is_exec_start = bool(re.match(r"^(?:run|compile|execute|build)\b", msg_clean, flags=re.IGNORECASE))
        if cand_code_file and not is_exec_start:
            mod_keywords = [
                "change", "modify", "update", "edit", "alter", "rewrite", "make",
                "fix", "repair", "patch", "optimize", "optimise", "add", "insert",
                "remove", "delete", "replace", "write", "set", "print", "append",
                "cut", "strip", "clean up"
            ]
            non_mod_keywords = [
                "don't modify", "do not modify", "dont modify", "without modifying",
                "don't fix", "do not fix", "dont fix", "without fixing", "hint", "teach",
                "explain", "what does", "what is", "tell me what", "walk me through",
                "suggest", "review", "compile but don't run", "compile only", "build only",
                "find", "where is", "locate"
            ]
            has_mod = any(re.search(r"\b" + kw + r"\b", msg_lower) for kw in mod_keywords)
            has_non_mod = any(kw in msg_lower for kw in non_mod_keywords)
            if has_mod and not has_non_mod:
                should_run = bool(re.search(r"\b(?:run|execute|and\s+run)\b", msg_clean, re.IGNORECASE))
                should_verify = bool(re.search(r"\b(?:verify|verification)\b", msg_clean, re.IGNORECASE))
                return "coding_workspace", {
                    "action": "edit_code_file",
                    "filename": cand_code_file,
                    "instruction": msg_clean,
                    "prompt": msg_clean,
                    "run": should_run,
                    "verify": should_verify
                }

        # H. Code Execution (Feature #33.3)
        # 0. "Run dsa.cpp and fix the error", "Compile and run dsa.cpp and fix the error", "Run arrays.cpp and fix the bug"
        m_run_and_fix = re.match(
            r"^(?:run|compile\s+and\s+run|execute)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css))\s+and\s+(?:fix|repair|heal|correct)(?:\s+the)?\s+(?:error|bug|issue|problem)?\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_run_and_fix:
            fname = m_run_and_fix.group(1).strip()
            return "coding_workspace", {
                "action": "execute_code",
                "filename": fname,
                "auto_fix": True
            }

        # H0. Explicit Compile-Only Intent (Feature #33.1 / Coding Intelligence 2.0)
        # E.g. "Compile 01_basic.cpp but don't run it.", "Compile 01_basic.cpp", "Compile this C++ file but don't execute it.", "Build 01_basic.cpp without running it.", "Compile my current C++ file only."
        is_compile_query = (
            re.match(r"^(?:compile|build)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\b(?:compile\s+(?:the\s+|my\s+|this\s+)?(?:code|file|program|source)|build\s+(?:the\s+|my\s+|this\s+)?(?:code|file|program|source))\b", msg_lower)
        )
        if is_compile_query:
            # Check if execution/running is explicitly requested
            has_run_request = any(kw in msg_lower for kw in [
                "and run", "and execute", "then run", "then execute", "& run", "+ run",
                "to verify the output", "and verify the output", "to verify output", "and verify output"
            ]) and not any(kw in msg_lower for kw in [
                "don't run", "dont run", "do not run", "without running",
                "don't execute", "dont execute", "do not execute", "without executing",
                "compile only", "build only", "only compile", "only build", "compile-only", "build-only"
            ])

            if not has_run_request:
                target_fn = cls._extract_target_file(msg_clean)
                if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code", "this c++ file", "this c file", "this"]):
                    target_fn = "this file"
                return "coding_workspace", {
                    "action": "compile_code",
                    "filename": target_fn or "this file",
                    "compile_only": True,
                    "prompt": msg_clean
                }
            else:
                target_fn = cls._extract_target_file(msg_clean)
                if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code", "this c++ file", "this c file", "this", "it"]):
                    target_fn = "this file"
                return "coding_workspace", {
                    "action": "execute_code",
                    "filename": target_fn or "this file",
                    "compile": True,
                    "prompt": msg_clean
                }

        # E.g. "Run main.cpp", "Compile and run main.cpp", "Run the C++ program", "Execute main.py with input 10", "Run my program", "Execute this Python program"
        m_exec_with_input = re.match(
            r"^(?:run|execute|compile\s+and\s+run|compile\s+and\s+execute)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s+with\s+input[:\s]+(.+)$",
            msg_clean,
            flags=re.IGNORECASE | re.DOTALL
        )
        if m_exec_with_input:
            fname = m_exec_with_input.group(1).strip()
            stdin_val = m_exec_with_input.group(2).strip()
            return "coding_workspace", {
                "action": "execute_code",
                "filename": fname,
                "stdin": stdin_val
            }

        m_exec_general_input = re.match(
            r"^(?:run|execute)\s+(?:this\s+|the\s+|my\s+)?(?:program|code|script)\s+with\s+input[:\s]+(.+)$",
            msg_clean,
            flags=re.IGNORECASE | re.DOTALL
        )
        if m_exec_general_input:
            stdin_val = m_exec_general_input.group(1).strip()
            return "coding_workspace", {
                "action": "execute_code",
                "stdin": stdin_val
            }

        m_run_file = re.match(
            r"^(?:run|execute|compile\s+and\s+run|compile\s+and\s+execute)\s+(?:the\s+|my\s+|this\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))\b",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_run_file:
            fname = m_run_file.group(1).strip()
            return "coding_workspace", {
                "action": "execute_code",
                "filename": fname,
                "prompt": msg_clean
            }

        m_run_it = re.match(
            r"^(?:run|execute|compile\s+and\s+run|compile\s+and\s+execute)\s+(?:it|this\s+file|current\s+file|the\s+file|the\s+code|this)\b",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_run_it:
            return "coding_workspace", {
                "action": "execute_code",
                "prompt": msg_clean
            }

        m_run_lang = re.match(
            r"^(?:run|execute|compile\s+and\s+run)\s+(?:the\s+|this\s+|my\s+)?([a-zA-Z0-9_\+\#]+)\s+(?:program|code|script|solution)(?:\s+(?:to|and)\s+verify(?:\s+the\s+output)?)?\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_run_lang:
            l_cand = m_run_lang.group(1).strip().lower()
            if l_cand in ["cpp", "c++", "c plus plus", "c", "python", "py", "javascript", "js", "typescript", "ts", "java", "go", "golang", "rust"]:
                return "coding_workspace", {
                    "action": "execute_code",
                    "language": l_cand
                }

        if msg_lower in [
            "run my program", "run the program", "run this program", "run program", "execute this program",
            "execute my program", "execute the program", "execute program", "compile and run", "run the c++ program",
            "run the python program", "execute this python program", "run code", "execute code",
            "run to verify", "run to verify the output", "run it to verify", "run it to verify the output",
            "run and verify", "run it and verify the output", "compile and run it to verify the output",
            "compile and run to verify the output", "verify the output", "verify output"
        ]:
            return "coding_workspace", {
                "action": "execute_code"
            }

        # I. Natural-Language Code Generation (Feature #33.2 / Coding Workspace 2.0)
        # 0. "Create and run a Python program that prints Hello World", "Write and run a C++ program to print numbers from 1 to 100"
        m_gen_and_run = re.match(
            r"^(?:create|write|make|generate|build)\s+and\s+(?:run|execute)\s+(?:a\s+|an\s+)?(?:([a-zA-Z0-9_\+\#\.\-]+)\s+)?(?:program|script|solution|function|code|app|file)\s*(?:for|to|that|which|of|with)?\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_and_run:
            lang_cand = (m_gen_and_run.group(1) or "").strip().lower()
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": msg_clean,
                "language": lang_cand if lang_cand else None,
                "run": True
            }

        # 1. "Print prime numbers from 1 to 100 in C++", "Print numbers from 1 to 100 in C++", "Print prime numbers in C++"
        m_print_algo = re.match(r"^print\s+(?:all\s+)?(prime\s+numbers|primes|numbers\s+from\s+1\s+to\s+100|numbers\s+1\s+to\s+100|1\s+to\s+100|fibonacci|even\s+numbers|odd\s+numbers)(.+)$", msg_clean, flags=re.IGNORECASE)
        if m_print_algo:
            algo_topic = m_print_algo.group(1).strip()
            rest = m_print_algo.group(2).strip()
            full_prompt = f"Print {algo_topic} {rest}".strip()
            should_run = bool(re.search(r"\b(?:and\s+(?:run|execute)(?:\s+it)?|with\s+execution)\b", msg_clean, re.IGNORECASE))
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": full_prompt,
                "run": should_run
            }

        # 2. "Write merge sort in C++ and save it as merge.cpp" / "Write binary search in C++" / "Code merge sort in C++"
        m_gen_save = re.match(
            r"^(?:write|create|implement|code|generate|build|make)\s+(?:a\s+|an\s+)?(.+?)\s+in\s+([a-zA-Z0-9_\+\#\.\-]+)(?:\s+and\s+save\s+(?:it\s+)?as\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))?\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_save:
            topic = m_gen_save.group(1).strip()
            lang_cand = m_gen_save.group(2).strip()
            fname = m_gen_save.group(3).strip() if m_gen_save.group(3) else None
            # Filter out non-programming phrases
            if lang_cand.lower() in ["cpp", "c++", "c plus plus", "c", "python", "py", "javascript", "js", "typescript", "ts", "java", "go", "golang", "rust", "html", "css", "web", "react", "node", "nodejs", "sql"]:
                should_run = bool(re.search(r"\b(?:and\s+(?:run|execute)(?:\s+it)?|with\s+execution)\b", msg_clean, re.IGNORECASE))
                return "coding_workspace", {
                    "action": "generate_code",
                    "prompt": f"Write {topic} in {lang_cand}",
                    "language": lang_cand,
                    "filename": fname,
                    "run": should_run
                }

        # 3. "Write a C++ program for binary search", "Create a React navbar component", "Write Java code for binary search", "Write CSS for a responsive navbar"
        m_gen_prog = re.match(
            r"^(?:write|create|implement|code|generate|build|make)\s+(?:a\s+|an\s+)?(?:([a-zA-Z0-9_\+\#\.\-]+)\s+)?(?:program|script|solution|function|code|calculator|app|component|query|interface|page|api|endpoint|navbar|stylesheet|file)\s+(?:for|to|that|which|of|with)?\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_prog:
            lang_cand = (m_gen_prog.group(1) or "").strip().lower()
            should_run = bool(re.search(r"\b(?:and\s+(?:run|execute)(?:\s+it)?|with\s+execution)\b", msg_clean, re.IGNORECASE))
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": msg_clean,
                "language": lang_cand if lang_cand else None,
                "run": should_run
            }

        # 3b. "Write CSS for a responsive navbar", "Write HTML for a login page", "Write SQL for second highest salary"
        m_gen_lang_for = re.match(
            r"^(?:write|create|implement|code|generate|build|make)\s+([a-zA-Z0-9_\+\#\.\-]+)\s+(?:for|to|that|which|of|with)\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_lang_for:
            lang_cand = m_gen_lang_for.group(1).strip().lower()
            if lang_cand in ["cpp", "c++", "c plus plus", "c", "python", "py", "javascript", "js", "typescript", "ts", "java", "go", "golang", "rust", "html", "css", "web", "react", "node", "nodejs", "sql"]:
                return "coding_workspace", {
                    "action": "generate_code",
                    "prompt": msg_clean,
                    "language": lang_cand
                }

        # 3b. "Write code in C++ to reverse an array", "Write code in Java for binary search"
        m_gen_code_in = re.match(
            r"^(?:write|create|implement|code|generate)\s+code\s+in\s+([a-zA-Z0-9_\+\#\.\-]+)\s+(?:for|to|that|which|of)?\s*(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_code_in:
            lang_cand = m_gen_code_in.group(1).strip().lower()
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": msg_clean,
                "language": lang_cand
            }

        # 3c. Direct start: "C++ program to print numbers from 1 to 100", "Python script for calculator"
        m_direct_prog = re.match(
            r"^(?:a\s+|an\s+)?([a-zA-Z0-9_\+\#\.\-]+)\s+(?:program|script|solution|function|code|component|query)\s+(?:for|to|that|which|of)\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_direct_prog:
            lang_cand = m_direct_prog.group(1).strip().lower()
            if lang_cand in ["cpp", "c++", "c plus plus", "c", "python", "py", "javascript", "js", "typescript", "ts", "java", "go", "golang", "rust", "html", "css", "web", "react", "node", "nodejs", "sql"]:
                return "coding_workspace", {
                    "action": "generate_code",
                    "prompt": msg_clean,
                    "language": lang_cand
                }

        # 4. "Write a JavaScript calculator", "Write a Python calculator"
        m_gen_calc = re.match(
            r"^(?:write|create|implement|code|generate|build|make)\s+(?:a\s+|an\s+)?(?:([a-zA-Z0-9_\+\#]+)\s+)?calculator\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_calc:
            lang_cand = (m_gen_calc.group(1) or "").strip().lower()
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": msg_clean,
                "language": lang_cand if lang_cand else None
            }

        # 5. "Write prime.cpp to print prime numbers"
        m_gen_file = re.match(
            r"^(?:write|create|code|generate)\s+([a-zA-Z0-9_\-]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|sql))\s+(?:to|that|which|for)\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_gen_file:
            fname = m_gen_file.group(1).strip()
            topic = m_gen_file.group(2).strip()
            return "coding_workspace", {
                "action": "generate_code",
                "prompt": f"Write {fname} to {topic}",
                "filename": fname
            }

        # J. Code Explanation (Feature #33.3)
        # 1. Line-by-line mode
        # E.g. "Explain 01_basic.cpp line by line. Don't modify it.", "Explain testing.cpp line by line", "Break it down line by line"
        if (
            re.search(r"\b(?:line\s+by\s+line|step\s+by\s+step|line-by-line|step-by-step)\b", msg_lower)
            and any(k in msg_lower for k in ["explain", "walk through", "break down", "describe", "analyze", "inspect", "read", "show"])
        ):
            target_fn = cls._extract_target_file(msg_clean)
            if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code"]):
                target_fn = "this file"
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "line_by_line",
                "filename": target_fn or "this file",
                "prompt": msg_clean
            }

        # 2. Beginner mode
        if any(kw in msg_lower for kw in ["like a beginner", "like i'm a beginner", "for a beginner", "explain simply", "simple explanation"]) and any(k in msg_lower for k in ["explain", "code", "program", "this"]):
            m_exp_beg = re.match(r"^explain\s+(?:the\s+|this\s+|my\s+)?(?:code\s+in\s+|file\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)?.*(?:beginner|simply)", msg_clean, flags=re.IGNORECASE)
            f_cand = m_exp_beg.group(1).strip() if (m_exp_beg and m_exp_beg.group(1)) else None
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "beginner",
                "filename": f_cand
            }

        # 3. Complexity mode & Optimization Analysis
        if any(kw in msg_lower for kw in [
            "time and space complexity", "time complexity", "space complexity", "give complexity",
            "give me the time and space complexity", "give time and space complexity", "what is the time and space complexity",
            "what is the time complexity", "what is the space complexity", "analyze complexity", "analyze the complexity"
        ]):
            m_f = re.search(r"([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json))", msg_clean)
            f_cand = m_f.group(1).strip() if m_f else None
            if not f_cand and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code"]):
                f_cand = "this file"
            return "coding_workspace", {
                "action": "analyze_code",
                "filename": f_cand,
                "prompt": msg_clean
            }

        # 4. Algorithm mode
        if msg_lower in ["explain the algorithm", "explain algorithm", "what is the algorithm", "explain the logic", "explain logic"] or re.match(r"^explain\s+(?:the\s+)?algorithm(?:\s+of\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))?\.?$", msg_clean, flags=re.IGNORECASE):
            m_exp_algo = re.match(r"^explain\s+(?:the\s+)?algorithm(?:\s+of\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))?\.?$", msg_clean, flags=re.IGNORECASE)
            f_cand = m_exp_algo.group(1).strip() if (m_exp_algo and m_exp_algo.group(1)) else None
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "algorithm",
                "filename": f_cand
            }

        # 5. Interview mode
        if "interview" in msg_lower and any(k in msg_lower for k in ["explain", "explanation", "walkthrough"]):
            m_exp_int = re.match(r"^.*(?:interview\s+explanation|explain.*for\s+an\s+interview|interview\s+walkthrough)(?:\s+(?:for|of)\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))?", msg_clean, flags=re.IGNORECASE)
            f_cand = m_exp_int.group(1).strip() if (m_exp_int and m_exp_int.group(1)) else None
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "interview",
                "filename": f_cand
            }

        # 6. Specific file explanation: "Explain main.cpp", "Explain main.py", "Explain App.tsx"
        m_exp_file = re.match(
            r"^(?:explain|break\s+down)\s+(?:the\s+code\s+in\s+|the\s+file\s+|file\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json))\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_exp_file:
            fname = m_exp_file.group(1).strip()
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "normal",
                "filename": fname
            }

        # 7. General code explanation: "Explain this code", "Explain the prime number program", "What is this function doing?"
        if (
            msg_lower in ["explain this code", "explain the code", "explain my code", "explain this program", "explain the program", "explain my program", "what is this code doing", "what is this program doing", "what is this function doing", "what is this function doing?"]
            or re.match(r"^explain\s+(?:the\s+|this\s+|my\s+)?([a-zA-Z0-9_\-\s]+(?:program|code|script|solution|function))\.?$", msg_clean, flags=re.IGNORECASE)
        ):
            return "coding_workspace", {
                "action": "explain_code",
                "mode": "normal"
            }

        # K. Code Error Detection & Diagnosis (Feature #33.4)
        # 1. "Why didn't main.cpp compile?", "Why did main.cpp fail?", "Diagnose the error in main.cpp"
        m_diag_file = re.match(
            r"^(?:why\s+did\s+(?:not\s+|n't\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s+(?:compile|fail|crash|exit)|why\s+didn't\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s+compile|diagnose\s+(?:the\s+)?(?:compiler\s+|runtime\s+)?error\s+(?:in\s+|for\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)|what(?:'s|\s+is)\s+wrong\s+with\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))[\.\?]*$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_diag_file:
            fname = m_diag_file.group(1) or m_diag_file.group(2) or m_diag_file.group(3) or m_diag_file.group(4)
            return "coding_workspace", {
                "action": "diagnose_code_error",
                "filename": fname.strip() if fname else None
            }

        # 2. Specific Error Inquiries: "Why am I getting NameError?", "Why am I getting segmentation fault?", "Why am I getting syntax error?"
        m_diag_err_name = re.match(
            r"^(?:why\s+am\s+i\s+getting|why\s+is\s+there|what\s+does\s+(?:this\s+)?(?:error\s+mean|mean)?)\s+([a-zA-Z0-9_\-\s]+(?:error|fault|panic|exception|traceback|undefined|violation))[\.\?]*$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_diag_err_name:
            err_name = m_diag_err_name.group(1).strip()
            return "coding_workspace", {
                "action": "diagnose_code_error",
                "error_output": err_name
            }

        # 3. General Diagnosis Queries:
        # "Why did my program fail?", "What's wrong with my code?", "Diagnose the error.", "Explain this compiler error.",
        # "What caused the runtime error?", "Tell me how to fix this error.", "What is wrong with my Python program?",
        # "Diagnose the compiler error.", "Explain this runtime error.", "Why did it fail?", "What went wrong?"
        if (
            msg_lower in [
                "why did my program fail", "why did my program fail?", "why did it fail", "why did it fail?",
                "what's wrong with my code", "what's wrong with my code?", "what is wrong with my code", "what is wrong with my code?",
                "what's wrong with my program", "what's wrong with my program?", "what is wrong with my program", "what is wrong with my program?",
                "diagnose the error", "diagnose the error.", "diagnose error", "diagnose the compiler error", "diagnose the runtime error",
                "explain this compiler error", "explain the compiler error", "explain this runtime error", "explain the runtime error",
                "what caused the runtime error", "what caused the runtime error?", "what caused the error", "what caused this error",
                "tell me how to fix this error", "how to fix this error", "how do i fix this error", "how do i fix this error?",
                "what went wrong", "what went wrong?", "diagnose", "diagnose it", "why did compilation fail", "why did execution fail"
            ]
            or re.match(r"^what(?:'s|\s+is)\s+wrong\s+with\s+(?:my\s+|this\s+)?([a-zA-Z0-9_\+\#]+)\s+(?:program|code|script)[\.\?]*$", msg_clean, flags=re.IGNORECASE)
            or re.match(r"^diagnose\s+(?:the\s+)?(?:compiler\s+|runtime\s+)?error[\.\?]*$", msg_clean, flags=re.IGNORECASE)
            or re.match(r"^explain\s+(?:this\s+|the\s+)?(?:compiler\s+|runtime\s+)?error[\.\?]*$", msg_clean, flags=re.IGNORECASE)
            or re.match(r"^why\s+did\s+(?:my\s+|the\s+|this\s+)?(?:program|code|script|compilation|execution)\s+fail[\.\?]*$", msg_clean, flags=re.IGNORECASE)
        ):
            return "coding_workspace", {
                "action": "diagnose_code_error"
            }

        # L. Automatic Code Error Fixing (Feature #33.5)
        # 1. Explicit Automatic Fixing: "Fix the error automatically.", "Automatically fix the error", "Fix main.cpp automatically"
        m_auto_fix = re.match(
            r"^(?:automatically\s+fix|auto\s+fix|fix\s+(?:the\s+)?(?:compiler\s+|runtime\s+)?error\s+automatically|fix\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s+automatically|fix\s+automatically)[\.\?]*$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_auto_fix:
            fname = m_auto_fix.group(1).strip() if (m_auto_fix.group(1)) else None
            return "coding_workspace", {
                "action": "fix_code_error",
                "filename": fname,
                "fix_mode": "automatic"
            }

        # 2. File-specific Fixing: "Fix main.cpp", "Fix the error in main.cpp", "Fix bug in main.py", "Fix the mistakes in dsa.cpp"
        m_fix_file = re.match(
            r"^(?:fix|repair|correct|patch)\s+(?:the\s+)?(?:compilation\s+|compiler\s+|runtime\s+|syntax\s+)?(?:error|bug|issue|typo|mistake|mistakes)?\s*(?:in\s+|for\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)[\.\?]*$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_fix_file:
            fname = m_fix_file.group(1).strip()
            return "coding_workspace", {
                "action": "fix_code_error",
                "filename": fname,
                "fix_mode": "automatic"
            }

        # 3. General Fix Queries: "Fix this error.", "Fix the compiler error.", "Fix my code.", "Try to fix it.", "Fix it."
        if (
            msg_lower in [
                "fix this error", "fix this error.", "fix the error", "fix the error.", "fix error",
                "fix the compilation error", "fix compilation error",
                "fix the compiler error", "fix compiler error", "fix the runtime error", "fix runtime error",
                "fix my code", "fix my code.", "fix the code", "fix this code", "fix the bug", "fix the syntax error",
                "try to fix it", "try to fix it.", "try to fix the error", "fix it", "fix it.", "fix please", "fix this",
                "automatically fix the error", "auto fix", "autofix", "repair it", "correct the error"
            ]
            or re.match(r"^(?:try\s+to\s+)?(?:fix|repair|correct)\s+(?:this|the|my)?\s*(?:code|error|program|bug|issue|mistakes)[\.\?]*$", msg_clean, flags=re.IGNORECASE)
        ):
            return "coding_workspace", {
                "action": "fix_code_error",
                "fix_mode": "automatic"
            }

        # N. Code Review (Feature #33.7 / Coding Intelligence 2.0)
        # E.g. "Review testing.cpp and tell me what mistakes I'm making. Don't modify it.", "Review testing.cpp", "Review main.cpp in my current project", "Review this file", "What mistakes am I making in dsa.cpp?", "Check testing.cpp for bugs", "What is wrong with my logic in testing.cpp?"
        if (
            re.search(r"\b(?:what\s+mistakes\s+am\s+i\s+making|what\s+is\s+wrong\s+with\s+(?:my\s+logic|my\s+code|my\s+solution)?)\b", msg_lower)
            or re.search(r"^(?:open\s+and\s+)?(?:review|code\s+review)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\b(?:check\s+(?:the\s+|my\s+)?code|check\s+.+?\s+for\s+(?:bugs|mistakes|errors|issues))\b", msg_lower)
            or msg_lower in [
                "what mistakes am i making in this code", "what mistakes am i making in this code?",
                "what mistakes am i making", "what mistakes am i making?",
                "review my code", "review this code", "code review", "perform code review",
                "check my code for mistakes", "check this code for bugs", "check this code for mistakes"
            ]
            or re.match(r"^(?:review|code\s+review|check)\s+(?:my\s+|this\s+|the\s+)?code[\.\?]*$", msg_clean, flags=re.IGNORECASE)
        ):
            target_fn = cls._extract_target_file(msg_clean)
            if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "the current file", "this code", "my code"]):
                target_fn = "this file"
            return "coding_workspace", {
                "action": "review_code",
                "filename": target_fn or "this file",
                "prompt": msg_clean
            }

        # O. Pedagogical Teaching & Progressive Hints (Feature #33.8 / Coding Intelligence 2.0)
        # E.g. "Don't fix testing.cpp. Give me a hint about the biggest problem.", "Don't fix my code. Give me a hint about the bug", "Give me a hint about dsa.cpp", "Give me a hint", "Teach me how to fix testing.cpp"
        if (
            re.search(r"\b(?:give\s+(?:me\s+)?(?:a\s+)?hint|give\s+hint|teach\s+me|hint\s+please)\b", msg_lower)
            or msg_lower.startswith("hint")
            or "give me a hint" in msg_lower
            or "give me another hint" in msg_lower
            or "smaller hint" in msg_lower
            or "next hint" in msg_lower
        ):
            hint_lvl = 1
            if any(k in msg_lower for k in ["smaller hint", "another hint", "next hint", "level 2", "more details", "second hint"]):
                hint_lvl = 2
            elif any(k in msg_lower for k in ["level 3", "third hint", "final hint", "how to solve"]):
                hint_lvl = 3

            target_fn = cls._extract_target_file(msg_clean)
            if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code"]):
                target_fn = "this file"

            return "coding_workspace", {
                "action": "teach_code",
                "filename": target_fn or "this file",
                "hint_level": hint_lvl,
                "prompt": msg_clean
            }

        # P. Complexity & Optimization Analysis (Feature #33.9 / Coding Intelligence 2.0)
        # E.g. "Open and analyze this file: C:\...\testing.cpp. Don't modify it.", "Analyze testing.cpp.", "Analyze this file.", "Analyze the time complexity of testing.cpp.", "Analyze the time and space complexity of testing.cpp.", "Analyze testing.cpp and tell me how to optimize it", "How can I optimize testing.cpp?", "Analyze performance of testing.cpp", "Why is testing.cpp giving the wrong answer?", "Suggest a more efficient approach for 02_search.cpp, but don't modify it.", "Analyze 04_edge_cases.cpp and identify all meaningful edge cases. Don't modify it.", "Analyze 05_complexity.cpp. Identify every major algorithmic section and give its time complexity. Don't modify it."
        if (
            re.search(r"^(?:open\s+and\s+)?(?:analyze|analyse)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"^(?:suggest|recommend|propose)\s+(?:a\s+|an\s+)?(?:more\s+efficient|better|alternative|optimal|different)?\s*(?:approach|solution|way|algorithm|method|optimization|improvement|strategy)\b", msg_clean, flags=re.IGNORECASE)
            or (
                re.search(r"\b(?:complexity|optimize|optimization|performance|bottleneck|edge\s+cases?|algorithmic\s+sections?|efficient\s+approach|more\s+efficient)\b", msg_lower)
                and (re.search(r"\b(?:analyze|analyse|how\s+can\s+i|what\s+is\s+the|improve|tell\s+me|suggest|recommend|propose|identify|find|list|show|check|extract|give)\b", msg_lower) or "time complexity" in msg_lower or "space complexity" in msg_lower or "edge cases" in msg_lower or "more efficient" in msg_lower)
            )
            or re.search(r"\b(?:identify|find|list|show|check|extract)\s+(?:all\s+)?(?:the\s+)?(?:meaningful\s+)?edge\s+cases\b", msg_lower)
            or re.search(r"\b(?:identify|find|list|show|check|extract)\s+(?:every|all|the)?\s*(?:major\s+)?algorithmic\s+sections?\b", msg_lower)
            or re.search(r"^why\s+is\s+.+?\s+giving\s+(?:the\s+)?wrong\s+answer", msg_lower)
            or msg_lower in ["analyze code", "analyze this code", "analyze complexity", "analyze time complexity", "analyze space complexity", "suggest a more efficient approach", "suggest more efficient approach"]
        ):
            target_fn = cls._extract_target_file(msg_clean)
            if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code"]):
                target_fn = "this file"
            return "coding_workspace", {
                "action": "analyze_code",
                "filename": target_fn or "this file",
                "prompt": msg_clean
            }

        # P2. Code Explanation & Understanding (Coding Workspace / Coding Intelligence)
        # E.g. "Explain 01_basic.cpp.", "Read 01_basic.cpp and tell me what it does. Don't modify it.", "Tell me what 01_basic.cpp does.", "What does 01_basic.cpp do?", "Read 01_basic.cpp and explain it.", "Explain this file", "Walk me through 01_basic.cpp"
        if (
            re.search(r"^(?:open\s+and\s+|read\s+.+?\s+and\s+)?(?:explain|describe)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\b(?:explain|describe|walk\s+me\s+through|how\s+does\s+.+?\s+work)\b", msg_lower)
            or re.search(r"\b(?:what\s+does\s+.+?\s+do|tell\s+me\s+what\s+.+?\s+does|what\s+it\s+does)\b", msg_lower)
            or msg_lower in ["explain code", "explain this file", "explain my code", "explain the code", "what does this code do", "what does this file do", "what does this do", "tell me what this does", "tell me what this file does", "tell me what this code does"]
        ):
            target_fn = cls._extract_target_file(msg_clean)
            if not target_fn and any(kw in msg_lower for kw in ["this file", "current file", "active file", "this code", "my code", "the code"]):
                target_fn = "this file"
            exp_mode = "normal"
            if any(k in msg_lower for k in ["line by line", "line-by-line", "step by step", "step-by-step"]):
                exp_mode = "line_by_line"
            elif any(k in msg_lower for k in ["beginner", "simply", "simple explanation", "like a beginner"]):
                exp_mode = "beginner"
            elif any(k in msg_lower for k in ["algorithm", "logic", "how it works"]):
                exp_mode = "algorithm"
            elif any(k in msg_lower for k in ["complexity"]):
                exp_mode = "complexity"
            elif any(k in msg_lower for k in ["interview"]):
                exp_mode = "interview"

            if target_fn or msg_lower in ["explain code", "explain this file", "explain my code", "explain the code", "what does this code do", "what does this file do", "what does this do", "tell me what this does", "tell me what this file does", "tell me what this code does"]:
                return "coding_workspace", {
                    "action": "explain_code",
                    "mode": exp_mode,
                    "filename": target_fn or "this file",
                    "prompt": msg_clean
                }

        # Q. Apply Optimization (Coding Intelligence 2.0)
        # "Apply the optimization", "Apply optimization", "Apply the optimized version", "Optimize dsa.cpp"
        if (
            msg_lower in [
                "apply the optimization", "apply optimization", "apply the optimized version", "apply optimized version",
                "apply the optimize", "apply optimize"
            ]
            or re.match(r"^apply\s+(?:the\s+)?optimization[\.\?]*$", msg_clean, flags=re.IGNORECASE)
        ):
            return "coding_workspace", {
                "action": "analyze_code",
                "apply": True,
                "prompt": msg_clean
            }

        # R. Conversational Code File Follow-up (Feature #33.1 / #33.3)
        # E.g. "testing.cpp", "use testing.cpp", "for testing.cpp", "in testing.cpp", "look at testing.cpp"
        target_fn = cls._extract_target_file(msg_clean)
        if target_fn and target_fn != "this file":
            clean_sans_file = msg_clean.replace(target_fn, "").strip()
            clean_sans_file = re.sub(r"^(?:use|for|in|look\s+at|check|inspect|open|see)\s*", "", clean_sans_file, flags=re.IGNORECASE).strip()
            clean_sans_file = re.sub(r"[.!?,\"\':]+$", "", clean_sans_file).strip()
            if not clean_sans_file or clean_sans_file.lower() in ["please"]:
                from core.session import session_manager
                ctx = session_manager.get_working_context()
                last_act = ctx.get("last_action")
                act_name = "explain_code"
                if isinstance(last_act, dict) and last_act.get("action"):
                    act_name = last_act.get("action")
                elif isinstance(last_act, str) and last_act:
                    act_name = last_act

                if act_name in ["analyze_code", "explain_code", "review_code", "teach_code", "execute_code", "diagnose_code_error", "fix_code_error", "read_code_file"]:
                    return "coding_workspace", {
                        "action": act_name,
                        "filename": target_fn,
                        "prompt": msg_clean
                    }
                return "coding_workspace", {
                    "action": "explain_code",
                    "filename": target_fn,
                    "prompt": msg_clean
                }

        # M. Controlled Terminal Agent (Feature #33.6)
        # Exclude purely conversational / informational queries:
        if (
            re.match(r"^(?:how\s+does|how\s+do\s+i\s+use|what\s+is|explain\s+how|tell\s+me\s+about)\s+(?:npm|pytest|pip|python|node|virtual\s+environment)", msg_clean, re.IGNORECASE)
            or msg_lower in ["explain pytest", "explain npm", "explain pip", "what is npm?", "what is pytest?"]
        ):
            return None, {}

        # 1. File & Directory Inspection:
        # "Show me the files in this project", "Show files in this project", "Show files", "List files", "List directory", "Show project files"
        if (
            msg_lower in [
                "show me the files in this project", "show files in this project", "show files", "show me the files",
                "show the files", "list files", "list directory", "list project files", "show project files",
                "show files in project", "files in this project"
            ]
            or re.match(r"^(?:show|list)\s+(?:me\s+)?(?:the\s+)?(?:project\s+)?files(?:\s+in\s+(?:this\s+)?project)?[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "list_files"}

        # 2. Print Working Directory:
        # "What is the current project directory?", "Print working directory", "Where is the project located?", "Show project directory"
        if (
            msg_lower in [
                "what is the current project directory", "what is the current project directory?", "print working directory",
                "print working directory.", "show working directory", "show project directory", "pwd",
                "where is the project located", "where is the project located?", "what is my working directory"
            ]
            or re.match(r"^(?:what\s+is\s+(?:the\s+)?(?:current\s+)?(?:project\s+|working\s+)?directory|print\s+working\s+directory)[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "print_working_directory"}

        # 3. Test Execution:
        # "Run my tests", "Run the tests", "Run project tests", "Run tests", "Execute tests", "Test project"
        if (
            msg_lower in [
                "run my tests", "run the tests", "run project tests", "run tests", "run all tests",
                "execute tests", "test the project", "test project", "run automated tests"
            ]
            or re.match(r"^(?:run|execute)\s+(?:all\s+|the\s+|my\s+)?(?:project\s+|automated\s+)?tests[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "run_project_tests"}

        # 4. Pytest Execution:
        # "Run pytest", "Execute pytest", "Run python tests"
        if (
            msg_lower in ["run pytest", "execute pytest", "pytest", "run python tests"]
            or re.match(r"^(?:run|execute)\s+pytest[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "run_pytest"}

        # 5. npm Test Execution:
        # "Run npm test", "npm test", "Execute npm test"
        if (
            msg_lower in ["run npm test", "npm test", "execute npm test"]
            or re.match(r"^(?:run|execute)\s+npm\s+test[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "npm_test"}

        # 6. Dependency Installation:
        # "Install the project dependencies", "Install dependencies", "Run npm install", "Install npm dependencies", "Install packages"
        if (
            msg_lower in [
                "install the project dependencies", "install dependencies", "install project dependencies",
                "run npm install", "npm install", "install npm dependencies", "install packages", "install npm packages"
            ]
            or re.match(r"^(?:run\s+)?npm\s+install[\.\?]*$", msg_clean, re.IGNORECASE)
            or re.match(r"^install\s+(?:the\s+)?(?:project\s+)?(?:npm\s+)?dependencies[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "npm_install"}

        # 7. Python Pip Requirements:
        # "Run pip install", "Install requirements", "Install python dependencies", "pip install -r requirements.txt"
        if (
            msg_lower in [
                "run pip install", "install requirements", "install requirements.txt",
                "install python dependencies", "pip install requirements", "pip install -r requirements.txt"
            ]
            or re.match(r"^(?:run\s+)?pip\s+install\s+(?:-r\s+)?requirements(?:\.txt)?[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "pip_install_requirements"}

        # 8. Virtual Environment Creation:
        # "Create a virtual environment", "Create a Python virtual environment", "Create venv", "Create virtualenv"
        if (
            msg_lower in [
                "create a virtual environment", "create a python virtual environment",
                "create virtual environment", "create venv", "create virtualenv", "set up virtual environment"
            ]
            or re.match(r"^create\s+(?:a\s+)?(?:python\s+)?virtual\s+environment[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "create_virtual_environment"}

        # 9. Development Server:
        # "Start the development server", "Start dev server", "Launch dev server", "Start development server"
        if (
            msg_lower in [
                "start the development server", "start dev server", "launch dev server",
                "start development server", "run dev server", "start server"
            ]
            or re.match(r"^(?:start|launch|run)\s+(?:the\s+)?(?:development|dev)\s+server[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "start_dev_server"}

        # 10. Package Scripts & Metadata:
        # "Show npm scripts", "Show package scripts", "What scripts are in package.json?"
        if (
            msg_lower in [
                "show npm scripts", "show package scripts", "what scripts are in package.json",
                "what scripts are in package.json?", "show scripts", "list npm scripts"
            ]
            or re.match(r"^(?:show|list)\s+(?:npm\s+|package\s+)?scripts[\.\?]*$", msg_clean, re.IGNORECASE)
        ):
            return "terminal_agent", {"action": "terminal_command", "operation": "show_package_scripts"}

        # 11. Version Queries:
        # "Check Python version", "Python version", "Check Node version", "Node version", "Check npm version", "npm version"
        if msg_lower in ["check python version", "python version", "what python version"]:
            return "terminal_agent", {"action": "terminal_command", "operation": "python_version"}
        if msg_lower in ["check node version", "node version", "what node version"]:
            return "terminal_agent", {"action": "terminal_command", "operation": "node_version"}
        if msg_lower in ["check npm version", "npm version", "what npm version"]:
            return "terminal_agent", {"action": "terminal_command", "operation": "npm_version"}

        # 12. Build Project:
        # "Build the project", "Build project", "Run build"
        if msg_lower in ["build the project", "build project", "run build", "build"]:
            return "terminal_agent", {"action": "terminal_command", "operation": "build_project"}

        # 1.5. Browser Search Intent (Search through Browser)
        # E.g. "search google for c++ dsa", "search the web in chrome for c++ dsa", "search in edge for c++ dsa"
        m_bsearch = re.match(r"^(?:search\s+(?:the\s+web\s+)?in\s+(chrome|edge|firefox|brave)\s+(?:for\s+)?|search\s+google\s+(?:for\s+)?)(.+)$", msg_lower)
        if m_bsearch:
            b_name = m_bsearch.group(1) if m_bsearch.group(1) else None
            s_query = m_bsearch.group(2).strip()
            return "browser_control", {"action": "search", "engine": "google", "query": s_query, "browser": b_name}

        # 1.6. Browser Control Actions (Feature #32 Browser Control)
        # A. Open / Navigate to Website in a New Tab
        # E.g. "Open GitHub in a new tab", "Open YouTube in a new browser tab", "Navigate to GitHub in a new tab", "Go to https://github.com in a new tab", "Open Google in a new tab"
        m_new_tab_url = re.match(
            r"^(?:open|navigate\s+to|go\s+to|visit|launch)\s+(.+?)\s+in\s+(?:a\s+)?new\s+(?:browser\s+)?tab\.?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_new_tab_url:
            dest = m_new_tab_url.group(1).strip()
            if dest:
                return "browser_control", {"action": "new_tab", "url": dest}

        # B. Standalone New Tab Creation
        # E.g. "Open a new tab", "Open a new browser tab", "Create new browser tab", "Create a new browser tab", "Create new tab", "Create tab", "Open tab", "New tab", "New browser tab"
        if (
            re.match(r"^(?:open|create|make|launch|start)?\s*(?:a\s+)?new\s+(?:browser\s+)?tab\.?$", msg_lower)
            or re.match(r"^(?:open|create)\s+(?:a\s+)?(?:new\s+)?(?:browser\s+)?tab\.?$", msg_lower)
            or msg_lower in [
                "new tab", "new tab.", "new browser tab", "new browser tab.",
                "create tab", "create tab.", "open tab", "open tab.",
                "create new tab", "create new tab.", "create new browser tab", "create new browser tab.",
                "open a new tab", "open a new tab.", "open a new browser tab", "open a new browser tab."
            ]
        ):
            return "browser_control", {"action": "new_tab"}

        # C. Close Tab
        if re.match(r"^(?:close\s+(?:this|the\s+current|the|active)\s+tab|close\s+tab|close\s+browser\s+tab)\.?$", msg_lower):
            return "browser_control", {"action": "close_tab"}

        # D. List Tabs
        if re.match(r"^(?:show|list|get|display)\s+(?:all\s+|my\s+|open\s+)?(?:browser\s+)?tabs\.?$", msg_lower) or msg_lower in ["tabs", "my tabs", "open tabs", "show my tabs", "list open tabs", "list open tabs."]:
            return "browser_control", {"action": "list_tabs"}

        # Tab Switching (Feature #32)
        # A. Numerical Tab Switching ("switch tab 2", "switch to tab 2", "switch to tab #2", "switch to tab number 2", "go to tab 2", "select tab 2", "switch tab 1")
        m_sw_idx = re.match(r"^(?:switch|go|select)(?:\s+to)?\s+tab\s+(?:number\s+|#)?(\d+)\.?$", msg_lower)
        if m_sw_idx:
            return "browser_control", {"action": "switch_tab", "index": int(m_sw_idx.group(1))}

        # B. Ordinal Tab Switching ("switch to the first tab", "switch to the second tab", "switch to first tab", "switch first tab", "switch to 1st tab", "switch tab first")
        m_sw_ord = re.match(r"^(?:switch|go|select)(?:\s+to)?\s+(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\s+tab\.?$", msg_lower)
        if not m_sw_ord:
            m_sw_ord = re.match(r"^(?:switch|go|select)(?:\s+to)?\s+tab\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\.?$", msg_lower)
        if m_sw_ord:
            ord_word = m_sw_ord.group(1).lower()
            ord_map = {
                "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
                "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
                "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "ninth": 9, "9th": 9,
                "tenth": 10, "10th": 10
            }
            if ord_word in ord_map:
                return "browser_control", {"action": "switch_tab", "index": ord_map[ord_word]}

        # C. Directional Tab Switching ("switch to next tab", "switch next tab", "next tab", "previous tab", "prev tab")
        if re.match(r"^(?:switch|go|select)?(?:\s+to)?\s+(?:the\s+)?next\s+tab\.?$", msg_lower) or msg_lower in ["next tab", "next tab."]:
            return "browser_control", {"action": "switch_tab", "direction": "next"}
        if re.match(r"^(?:switch|go|select)?(?:\s+to)?\s+(?:the\s+)?(?:previous|prev)\s+tab\.?$", msg_lower) or msg_lower in ["previous tab", "prev tab", "previous tab.", "prev tab."]:
            return "browser_control", {"action": "switch_tab", "direction": "previous"}

        # D. Title/Domain Tab Switching ("switch to the tab with Google", "switch to the tab called GitHub", "switch to Google tab", "switch tab GitHub", "switch to tab GitHub")
        m_sw_named = re.match(r"^(?:switch|go|select)(?:\s+to)?\s+(?:the\s+)?(?:tab\s+(?:with|called|named|for)\s+|tab\s+)?(.+?)(?:\s+tab)?\.?$", msg_clean, flags=re.IGNORECASE)
        if m_sw_named and ("switch" in msg_lower or "go to tab" in msg_lower or "select tab" in msg_lower) and not any(kw in msg_lower for kw in ["next", "previous", "prev", "new tab"]):
            tgt_name = m_sw_named.group(1).strip()
            tgt_name = re.sub(r"^(?:the\s+)?(?:tab\s+(?:with|called|named|for)\s+)", "", tgt_name, flags=re.IGNORECASE).strip()
            if tgt_name and not tgt_name.isdigit():
                return "browser_control", {"action": "switch_tab", "target": tgt_name}

        # Back / Forward / Refresh / Stop
        if msg_lower in ["go back", "go back.", "go back one page", "back one page", "previous page"]:
            return "browser_control", {"action": "back"}
        if msg_lower in ["go forward", "go forward.", "go forward one page", "forward one page", "next page"]:
            return "browser_control", {"action": "forward"}
        if msg_lower in ["refresh the page", "refresh this page", "refresh page", "reload the page", "reload this page", "reload page", "reload", "refresh", "refresh."]:
            return "browser_control", {"action": "refresh"}
        if msg_lower in ["stop loading", "stop loading.", "stop page loading", "stop loading page"]:
            return "browser_control", {"action": "stop_loading"}

        # Current Page Status / In-page Search
        if msg_lower in ["what's the current page", "what is the current page", "what's the current page?", "what is the current page?", "what page is open", "current webpage", "current page", "what's the active page"]:
            return "browser_control", {"action": "get_current_page"}
        m_find_in_page = re.match(r"^(?:search\s+(?:this|current)\s+page\s+for|find\s+(?:on|in)\s+(?:this|current)\s+page)\s+(.+)$", msg_clean, flags=re.IGNORECASE)
        if m_find_in_page:
            return "browser_control", {"action": "search_page", "query": m_find_in_page.group(1).strip()}

        # Focus / Open Browser
        if msg_lower in ["open edge", "open edge.", "focus edge", "focus edge.", "open microsoft edge", "focus microsoft edge"]:
            return "browser_control", {"action": "open_browser", "browser": "edge"}

        # Explicit In-Place Current Tab Navigation Intent
        # E.g. "navigate this tab to github.com", "navigate current tab to google.com", "open github in this tab", "replace this tab with github.com"
        m_nav_current = re.match(
            r"^(?:navigate|open|go\s+to|visit)\s+(?:in\s+|on\s+)?(?:this\s+tab|the\s+current\s+tab|current\s+tab|active\s+tab)(?:\s+to)?\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if not m_nav_current:
            m_nav_current = re.match(
                r"^(?:navigate|open|go\s+to|visit)\s+(.+?)\s+in\s+(?:this\s+tab|the\s+current\s+tab|current\s+tab|active\s+tab)$",
                msg_clean,
                flags=re.IGNORECASE
            )
        if not m_nav_current:
            m_nav_current = re.match(
                r"^(?:replace|reuse)\s+(?:this\s+tab|the\s+current\s+tab|current\s+tab|active\s+tab)\s+with\s+(.+)$",
                msg_clean,
                flags=re.IGNORECASE
            )
        if m_nav_current:
            dest = m_nav_current.group(1).strip()
            return "browser_control", {"action": "navigate_current", "url": dest, "current_tab": True}

        # Website Direct Navigation Intent (Default: Creates / Opens in New Tab)
        # E.g. "go to github.com", "take me to google", "navigate to openai.com", "open this website: https://example.com"
        nav_match = re.match(r"^(?:go\s+to|navigate\s+to|take\s+me\s+to|visit|open\s+this\s+website\s*:\s*)\s*(.+)$", msg_clean, flags=re.IGNORECASE)
        if nav_match:
            dest = nav_match.group(1).strip()
            return "browser_control", {"action": "navigate", "url": dest}

        read_page_match = re.match(
            r"^(?:read\s+(?:this\s+|the\s+)?(?:web)?page(?:\s*:\s*|\s+)?|read\s+website(?:\s*:\s*|\s+)|what\s+does\s+(?:this|the)\s+(?:web)?page\s+say(?:\s*:\s*|\s+)?|tell\s+me\s+what\s+(?:this|the)\s+(?:web)?page\s+contains(?:\s*:\s*|\s+)?)(.*)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if read_page_match and not any(kw in msg_lower for kw in ["screen", "display", "monitor", "error", "files", "file", "directory", "folder", "my pc", "system stats", "battery", "clipboard", "my clipboard", "the clipboard"]):
            target_url = read_page_match.group(1).strip()
            # Must NOT match local source code files or coding workspace queries
            if not cls._extract_target_file(msg_clean) and not cls._extract_target_file(target_url):
                # If target provided or explicitly refers to a webpage
                if (target_url and not any(kw in target_url.lower() for kw in ["screen", "display", "monitor", "error"])) or "page" in msg_lower or "website" in msg_lower:
                    return "read_webpage", {"url": target_url}

        # 1.8. Form Filling Intent (#34)
        # E.g. "fill my name as Kunal", "fill the email field with...", "tick the newsletter checkbox", "select India from country"
        if (
            re.search(r"\b(?:fill|enter|set|type)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\s-]+?)\s+(?:field\s+)?(?:with|as|=)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\b(?:tick|check|enable)\s+(?:the\s+)?([a-zA-Z0-9_\s-]+?)\s*(?:checkbox|box)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\bselect\s+(.+?)\s+(?:from|in)\s+(?:the\s+)?([a-zA-Z0-9_\s-]+?)\s*(?:dropdown|select|menu)\b", msg_clean, flags=re.IGNORECASE)
            or re.search(r"\b(?:fill\s+(?:this\s+|the\s+)?(?:contact\s+)?form|fill\s+the\s+form|fill\s+this\s+form)\b", msg_clean, flags=re.IGNORECASE)
            or (":" in msg_clean and any(k in msg_lower for k in ["name:", "email:", "message:"]))
        ):
            # If phrase contains 'open' / 'launch' alongside form fill -> multi-step
            if re.search(r"\b(?:open|launch|navigate\s+to|go\s+to)\b", msg_lower) and any(kw in msg_lower for kw in [" and ", " then ", ","]):
                pass # let multi_step classifier handle it
            else:
                return "fill_form", {"raw_text": msg_clean}

        # 1.9. Download Management Intent (#35)
        # E.g. "download https://example.com/file.pdf", "download this PDF to Downloads", "save it in my Documents folder"
        if re.search(r"\b(?:download|save\s+file)\b", msg_lower) and not any(kw in msg_lower for kw in ["open chrome and", "open browser and", "open this page and", "open page and"]):
            # If composite multi-step command
            if any(kw in msg_lower for kw in [" and ", " then ", ","]) and any(kw in msg_lower for kw in ["open", "find", "read", "navigate"]):
                pass # let multi_step classifier handle it
            else:
                m_dl = re.search(r"\b(?:download\s+file|download|save\s+file\s+from|save\s+it\s+in|save\s+to)\s+(.*)$", msg_clean, flags=re.IGNORECASE)
                target_str = m_dl.group(1).strip() if m_dl else ""
                url_param = target_str if (target_str.startswith("http") or target_str.startswith("file")) else None
                return "download_file", {"raw_text": msg_clean, "url": url_param}

        # 1.10. Website Automation Intent (#36)
        if re.match(r"^(?:buy\s+this|purchase\s+this|place\s+order\s+for|pay\s+for\s+this)\b", msg_lower):
            return "website_automation", {"raw_text": msg_clean}

        if re.search(r"^(?:open|navigate\s+to|go\s+to)\s+(github|google|youtube|wikipedia)\s+and\s+search\s+(?:for\s+)?(.+)$", msg_clean, flags=re.IGNORECASE):
            return "website_automation", {"raw_text": msg_clean}

        # 1.11. Advanced Web Research 2.0 Intent (Feature #43)
        # E.g. "research the latest React features", "compare React and Vue", "do a deep research on X", "find reliable sources about X", "verify this claim", "what's the latest information about X?"
        if (
            re.match(r"^(?:research|investigate|do\s+a\s+deep\s+(?:dive|research)\s+(?:into|on|comparing)?|find\s+reliable\s+sources\s+about|find\s+sources\s+that\s+support|verify\s+(?:this\s+claim\s+that|this\s+claim|claim)?|what(?:'s|\s+is)\s+the\s+latest\s+information\s+about)\b", msg_lower)
            or (re.match(r"^compare\s+", msg_lower) and not any(kw in msg_lower for kw in ["files", "folders"]))
            or re.match(r"^(?:research\s+this\s+from\s+multiple\s+websites|compare\s+these\s+websites|summarize\s+the\s+research)\b", msg_lower)
        ):
            m_urls = re.findall(r"https?://[^\s]+", msg_clean)
            depth_val = "deep" if any(kw in msg_lower for kw in ["deep", "thorough", "detailed", "deeply", "comprehensive"]) else ("quick" if any(kw in msg_lower for kw in ["quick", "brief", "short", "fast"]) else "standard")
            return "research_mode", {"raw_text": msg_clean, "sources": m_urls if m_urls else None, "depth": depth_val}

        # 1.12. Summarization Intent (#38)
        # E.g. "summarize this webpage", "summarize https://example.com", "summarize in 5 bullet points", "explain this like I'm a beginner", "search for react and summarize"
        if re.search(r"\b(?:summarize|give\s+me\s+a\s+(?:short\s+|brief\s+|detailed\s+)?summary|explain\s+this\s+(?:like\s+i'm\s+a\s+beginner|simply|in\s+simple\s+words)|give\s+me\s+(?:the\s+)?key\s+takeaways)\b", msg_lower):
            return "summarize", {"raw_text": msg_clean}

        # 1.13. Media Control Intent (Stop / Pause / Resume YouTube Playback)
        # E.g. "stop the music", "stop playing", "stop the song", "stop playback", "pause the music", "pause the song", "resume the music", "continue playing", "resume the song", "pause media", "resume media"
        if (
            re.match(r"^(?:pause)\s+(?:the\s+)?(?:music|song|audio|track|playback|playing|youtube|media|video)\b", msg_lower)
            or re.match(r"^(?:resume|continue|unpause)\s+(?:the\s+)?(?:music|song|audio|track|playback|playing|youtube|media|video)\b", msg_lower)
            or msg_lower in ["pause", "pause it", "pause media", "pause music", "pause the music", "pause song", "pause the song", "resume", "resume it", "resume media", "resume music", "resume the music", "resume song", "resume the song", "continue playing", "unpause", "unpause it", "unpause music", "unpause media"]
        ):
            act = "pause" if "pause" in msg_lower else "resume"
            return "play_media", {"action": act}

        if (
            re.match(r"^(?:stop)\s+(?:the\s+)?(?:music|song|audio|track|playback|playing|youtube|media|video)\b", msg_lower)
            or re.match(r"^stop\s+playing\b", msg_lower)
            or msg_lower in ["stop", "stop it", "stop music", "stop the music", "stop song", "stop the song", "stop playing", "stop media", "stop the media"]
        ):
            return "play_media", {"action": "stop"}

        # 1.14. Media Playback Intent (YouTube Browser-Only Playback)
        # E.g. "play kalyani", "play believer", "play shape of you", "play kalyani on youtube", "play kalyani in the browser"
        if re.match(r"^(?:play|start\s+playing|listen\s+to|stream)\s+", msg_lower):
            if any(kw in msg_lower for kw in [" and ", " then ", ","]):
                return None
            return "play_media", {"raw_text": msg_clean}

        # 1.15. Global Desktop Clipboard Control Intent (#20)
        # E.g. "what is in my clipboard", "read my clipboard", "what's in my clipboard", "clear my clipboard", "copy this to my clipboard: hello world", "put hello world in my clipboard", "copy ByteX is awesome to my clipboard", "paste from clipboard", "paste my clipboard", "paste the clipboard", "paste it", "paste"
        if re.search(r"\b(?:clipboard|clip\s+board)\b", msg_lower) or msg_lower in ["paste", "paste it", "paste this", "paste here", "paste text"]:
            # Paste clipboard
            if (
                any(kw in msg_lower for kw in ["paste from clipboard", "paste my clipboard", "paste the clipboard", "paste clipboard", "paste from my clipboard"])
                or msg_lower in ["paste", "paste it", "paste this", "paste here", "paste text"]
                or re.match(r"^paste\s+(?:it|this|here|text|from\s+clipboard|my\s+clipboard|the\s+clipboard)$", msg_lower)
            ):
                return "clipboard_control", {"action": "paste", "raw_text": msg_clean}

            # Clear clipboard
            if any(kw in msg_lower for kw in ["clear", "empty", "erase", "wipe", "flush", "reset"]):
                return "clipboard_control", {"action": "clear", "raw_text": msg_clean}
            
            # Set / Copy to clipboard
            m_set1 = re.search(r"(?:to\s+(?:my\s+)?clipboard\s*[:\s]*|in\s+(?:my\s+)?clipboard\s*[:\s]*)(.*)$", msg_clean, flags=re.IGNORECASE)
            m_set2 = re.search(r"(?:copy|put|set|write|save)\s+(?:this\s+)?(.+?)\s+(?:to|in)\s+(?:my\s+)?clipboard", msg_clean, flags=re.IGNORECASE)
            
            if m_set2 and m_set2.group(1).strip():
                return "clipboard_control", {"action": "set", "content": m_set2.group(1).strip(), "raw_text": msg_clean}
            elif m_set1 and m_set1.group(1).strip() and not any(kw in msg_lower for kw in ["what", "read", "show", "check", "view"]):
                return "clipboard_control", {"action": "set", "content": m_set1.group(1).strip(), "raw_text": msg_clean}

            # Read / Get clipboard
            return "clipboard_control", {"action": "get", "raw_text": msg_clean}

        # 2. Open Application / Browser Navigation Intent
        open_app_match = re.match(r"^(?:open|launch|run|start)\s+(.+)$", msg_lower)
        if open_app_match:
            app_target = open_app_match.group(1).strip()
            
            # Ignore code files, code execution pronouns, or code verification phrases
            if (
                any(ext in app_target.lower() for ext in [".cpp", ".py", ".c", ".h", ".hpp", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".html", ".css", ".json", ".sql", ".md"])
                or any(k in app_target.lower() for k in ["to verify", "and verify", "verify the output", "this file", "current file", "it to verify", "it and verify", "the code", "the program"])
                or app_target.lower() in ["it", "this file", "current file", "the program", "the code", "code", "program"]
            ):
                return None

            # Check for "open youtube/google and search for ..."
            m_yt_search = re.match(r"^(?:youtube|google)\s+and\s+search\s+(?:for\s+)?(.+)$", app_target, flags=re.IGNORECASE)
            if m_yt_search:
                eng = "youtube" if "youtube" in app_target.lower() else "google"
                return "browser_control", {"action": "search", "engine": eng, "query": m_yt_search.group(1).strip()}

            # If phrase contains ' and ', ' then ', or comma, it is a multi-step composite command
            if " and " in app_target or " then " in app_target or ", " in app_target:
                return None

            # Check for preferred browser resolution if abstract target (Feature #39)
            if app_target.lower() in ["my browser", "browser", "the browser", "default browser"]:
                from memory.manager import memory_manager
                all_mems = memory_manager.get_all_memories()
                pref_browser = next((m.value for m in all_mems if m.key == "preferred_browser" and m.value), None)
                if not pref_browser:
                    from memory.preferences import preference_manager
                    pref = preference_manager.get_preference("preferred_browser")
                    pref_browser = pref.value if pref else None
                app_target = pref_browser or "edge"

            # Check for preferred editor resolution if abstract target (Feature #39)
            if app_target.lower() in ["my editor", "editor", "the editor", "code editor", "my code editor"]:
                from memory.manager import memory_manager
                all_mems = memory_manager.get_all_memories()
                pref_editor = next((m.value for m in all_mems if m.key == "preferred_editor" and m.value), None)
                if not pref_editor:
                    from memory.preferences import preference_manager
                    pref = preference_manager.get_preference("preferred_editor")
                    pref_editor = pref.value if pref else None
                app_target = pref_editor or "vscode"

            # Check for active project / project folder resolution (Feature #39)
            if app_target.lower() in ["my project", "project", "the project", "my active project", "active project", "my project folder", "project folder"]:
                from memory.manager import memory_manager
                act = memory_manager.get_active_project()
                if act and act.workspace_path:
                    return "file_search", {"query": act.workspace_path}
                elif act and act.project_name:
                    return "open_application", {"application": act.project_name}
                else:
                    all_mems = memory_manager.get_all_memories()
                    proj_mem = next((m.value for m in all_mems if m.key == "main_project" and m.value), None)
                    if proj_mem:
                        return "open_application", {"application": proj_mem}

            # Check if target is a known website, web domain, or URL
            target_lower = app_target.lower()
            if (
                target_lower in ["youtube", "google", "github", "chatgpt", "openai", "reddit", "twitter", "x", "wikipedia", "microsoft"]
                or target_lower.startswith("http://")
                or target_lower.startswith("https://")
                or any(ext in target_lower for ext in [".com", ".org", ".net", ".io", ".dev", ".edu", ".gov"])
                or "website" in target_lower
            ):
                return "browser_control", {"action": "navigate", "url": app_target}
            
            return "open_application", {"application": app_target}

        # 3. Close Application Intent
        close_app_match = re.match(r"^(?:close|quit|exit|kill|stop)\s+(.+)$", msg_lower)
        if close_app_match:
            app_target = close_app_match.group(1).strip()
            if app_target not in ["it", "this", "that", "the app"]:
                if not any(k in app_target for k in ["file", "folder", "directory"]):
                    return "close_application", {"application": app_target}

        # 4. Screenshot Intent
        if re.match(r"^(?:take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|screenshot)$", msg_lower):
            return "take_screenshot", {}

        # 4.5. Screen Vision & Visual Grounding Intents (Feature #34)
        # Exclude purely conversational / informational queries
        if msg_lower.rstrip("?.") in [
            "what is screen vision", "what is vision", "what is visual grounding",
            "how does screen vision work", "how does visual grounding work", "explain screen vision"
        ]:
            return None

        # 4.5.1. Screen Error Diagnosis
        if (
            re.search(r"\b(?:what(?:'s|\s+is)\s+wrong\s+with\s+(?:my\s+|this\s+)?screen|why\s+is\s+(?:this|my)\s+(?:page|screen)\s+showing\s+(?:an\s+)?error|read\s+(?:the\s+|this\s+)?error(?:\s+on\s+(?:my\s+)?screen)?|diagnose\s+(?:the\s+|this\s+)?(?:screen\s+)?error|check\s+(?:for\s+)?(?:screen\s+)?error|what\s+(?:error\s+is\s+showing|is\s+(?:the\s+)?error\s+showing|is\s+the\s+error|does\s+this\s+error\s+mean)|error\s+kya\s+hai)\b", msg_lower)
        ):
            return "screen_vision", {"action": "screen_diagnosis", "question": msg_clean, "raw_text": msg_clean}

        # 4.5.2. Screen Region Explanation
        m_region_explain = re.match(r"^(?:explain|examine|read|describe)\s+(?:this|the)?\s*(?:part|section|area|region)\s*(?:of\s+(?:the|my)\s+screen)?(?:\s+(?:in\s+|at\s+)?(top-left|top-right|bottom-left|bottom-right|center|top|bottom|left|right))?[.?]*$", msg_lower)
        if m_region_explain:
            reg_found = m_region_explain.group(1) or "center"
            return "screen_vision", {"action": "explain_region", "region": reg_found, "question": msg_clean, "raw_text": msg_clean}

        # 4.5.3. Screen Reading / OCR
        if (
            re.match(r"^(?:read\s+(?:my|this|the)\s+screen|read\s+(?:the\s+)?text\s+on\s+(?:my|this|the)\s+screen|what\s+does\s+(?:this|my|the)\s+screen\s+say|what\s+does\s+(?:this|the)\s+button\s+say|screen\s+padho|screen\s+read\s+karo)\b", msg_lower)
        ):
            return "screen_vision", {"action": "read_screen", "question": msg_clean, "raw_text": msg_clean}

        # 4.5.4. General Screen Understanding & Analysis (Screen Understanding 2.0)
        if (
            re.search(r"\b(?:on\s+(?:my\s+)?screen|in\s+(?:my\s+)?screen|my\s+screen|the\s+screen|current\s+screen|screen\s+pe\s+kya\s+hai|screen\s+explain\s+karo)\b", msg_lower)
            or re.match(r"^(?:describe\s+(?:my\s+)?(?:screen|display)|what\s+do\s+you\s+see(?:\s+on\s+(?:my\s+)?screen)?|what\s+is\s+open|what\s+app(?:lication)?\s+is\s+open|analyze\s+(?:my\s+)?screen|inspect\s+(?:my\s+)?screen|what(?:'s|\s+is)\s+on\s+(?:my|the)\s+screen|explain\s+(?:my|the)\s+screen)\b", msg_lower)
        ):
            if not any(kw in msg_lower for kw in ["take a screenshot", "capture the screen", "take screenshot", "save screenshot"]):
                return "screen_vision", {"action": "analyze_screen", "question": msg_clean, "raw_text": msg_clean}

        # 4.5.5. Direct Coordinate Click Intent: "click at (500, 300)" / "click at 500 300" / "click coordinates 500, 300"
        m_coord = re.search(r"\b(?:click\s+(?:at\s+|coordinates?\s+)?\(?\s*(\d{1,5})\s*[, ]\s*(\d{1,5})\s*\)?)\b", msg_lower)
        if m_coord:
            cx_val = int(m_coord.group(1))
            cy_val = int(m_coord.group(2))
            return "screen_vision", {"action": "click_coordinates", "x": cx_val, "y": cy_val, "raw_text": msg_clean}

        # 4.5.6. Visual Scroll Intent
        if re.match(r"^(?:scroll\s+(?:down|up)|scroll\s+down\s+the\s+page|scroll\s+up\s+the\s+page|scroll\s+page)\b", msg_lower):
            clicks = 3 if "up" in msg_lower else -3
            return "screen_vision", {"action": "visual_scroll", "scroll_clicks": clicks, "raw_text": msg_clean}

        # 4.5.7. Visual Double Click Intent
        m_dbl_click = re.match(r"^(?:double\s+click|double-click)\s+(?:on\s+)?(?:the\s+)?(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_dbl_click:
            target_elem = m_dbl_click.group(1).strip()
            return "screen_vision", {"action": "visual_double_click", "target": target_elem, "raw_text": msg_clean}

        # 4.5.8. UI Element Detection / Visual Grounding Intent
        m_find = re.match(r"^(?:find|locate|where\s+is|show\s+me\s+where)\s+(?:the\s+)?(.+?)(?:\s+is|\s+on\s+(?:my\s+)?screen|\s+located|\?|\.)*$", msg_lower)
        if m_find:
            target_elem = m_find.group(1).strip()
            is_file_or_proj = (
                any(target_elem.lower().endswith(ext) for ext in [".cpp", ".c", ".h", ".hpp", ".py", ".pyw", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".rs", ".go", ".html", ".htm", ".css", ".sql", ".json", ".xml", ".md", ".txt", ".cs", ".rb", ".php", ".swift", ".yaml", ".yml", ".toml", ".pdf"])
                or bool(re.search(r"\.[a-zA-Z0-9]{1,5}\b", target_elem))
                or any(kw in target_elem for kw in ["file", "folder", "directory", "project", "workspace", "document", "pdf", "image of", "picture of"])
                or any(kw in msg_lower for kw in ["in my project", "in current project", "in workspace", "in my workspace", "in this project", "in the project", "search the web for", "google for", "look up"])
                or target_elem in ["this file", "current file", "the file", "the current file", "active file"]
            )
            if not is_file_or_proj:
                return "screen_vision", {"action": "find_ui_element", "target": target_elem, "raw_text": msg_clean}

        # 4.5.9. Compound Visual Typing Intent: "Find/Click ... and type ..."
        m_find_type = re.match(r"^(?:find|click)\s+(?:the\s+)?(.+?)\s+and\s+type\s+(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_find_type:
            target_val = m_find_type.group(1).strip().strip('"\'')
            text_val = m_find_type.group(2).strip().strip('"\'')
            return "screen_vision", {"action": "visual_type", "target": target_val, "text": text_val, "raw_text": msg_clean}

        # 4.5.10. Vision-Guided Typing Intent
        m_type_target = re.match(r"^(?:write|type|enter|input)\s+(.+?)\s+(?:in|into|on)\s+(?:the\s+)?(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_type_target:
            text_val = m_type_target.group(1).strip().strip('"\'')
            target_val = m_type_target.group(2).strip().strip('"\'')
            if not any(kw in target_val.lower() for kw in ["python", "javascript", "c++", "file", "folder", "directory", "script"]):
                return "screen_vision", {"action": "visual_type", "text": text_val, "target": target_val, "raw_text": msg_clean}

        m_type_direct = re.match(r"^(?:write|type|enter)\s+(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_type_direct:
            text_val = m_type_direct.group(1).strip().strip('"\'')
            if not any(text_val.lower().startswith(kw) for kw in ["a ", "an ", "about ", "code ", "file ", "of "]):
                return "screen_vision", {"action": "visual_type", "text": text_val, "target": None, "raw_text": msg_clean}

        # 4.5.11. Visual Selection Intent
        m_select = re.match(r"^(?:select)\s+(?:the\s+)?(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_select:
            target_elem = m_select.group(1).strip()
            if not any(kw in target_elem.lower() for kw in ["file", "folder", "directory", "text", "all"]):
                return "screen_vision", {"action": "visual_select", "target": target_elem, "raw_text": msg_clean}

        # 4.5.12. Vision-Guided Clicking Intent (including "Click the button that says ...", Hinglish "... pe click karo")
        m_click_named = re.match(r"^(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(?:button\s+(?:that\s+says\s+|named\s+)?|icon\s+|link\s+)?(.+?)[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_click_named:
            target_elem = m_click_named.group(1).strip()
            return "screen_vision", {"action": "visual_click", "target": target_elem, "raw_text": msg_clean}

        m_click_hinglish = re.match(r"^(.+?)\s+(?:button\s+)?(?:pe\s+)?click\s+karo[.!?]*$", msg_clean, flags=re.IGNORECASE)
        if m_click_hinglish:
            target_elem = m_click_hinglish.group(1).strip()
            return "screen_vision", {"action": "visual_click", "target": target_elem, "raw_text": msg_clean}

        # 5. System Telemetry Intent
        if (
            any(kw in msg_lower for kw in ["cpu usage", "ram usage", "system stats", "system status", "battery status", "battery percentage", "battery", "power status", "memory usage", "disk space", "cpu and ram", "ram and cpu", "check my computer", "check computer", "check my pc", "computer status", "pc status"])
            or (re.search(r"\b(?:check|get|show|view|display|what is|tell me)\s+(?:my\s+)?(?:cpu|ram|system|battery|computer|pc)\b", msg_lower) and not any(kw in msg_lower for kw in ["prepare", "organize", "setup", "optimize"]))
        ):
            if " and " in msg_lower or " then " in msg_lower or ", " in msg_lower:
                if any(action_kw in msg_lower for action_kw in ["open", "launch", "start", "run", "close", "delete", "create", "make", "search for"]):
                    return None
            return "system_status", {}

        # 6. List Files Intent
        if any(kw in msg_lower for kw in ["list files", "show files", "dir"]):
            path_match = re.search(r"in\s+(.+)$", msg_lower)
            target = path_match.group(1).strip() if path_match else "."
            return "list_files", {"target_path": target}

        # 7. Web Search Intent (Feature #31)
        if (
            msg_lower.startswith("search the web for ")
            or msg_lower.startswith("search web for ")
            or msg_lower.startswith("search online for ")
            or msg_lower.startswith("search the internet for ")
            or msg_lower.startswith("search for ")
            or msg_lower.startswith("search youtube for ")
            or msg_lower.startswith("search on youtube for ")
            or msg_lower.startswith("search github for ")
            or msg_lower.startswith("search on github for ")
            or msg_lower.startswith("search google for ")
            or msg_lower.startswith("search on google for ")
            or msg_lower.startswith("google for ")
            or msg_lower.startswith("google ")
            or msg_lower.startswith("find the official website for ")
            or msg_lower.startswith("find official website for ")
            or msg_lower.startswith("what's the latest news about ")
            or msg_lower.startswith("what is the latest news about ")
            or msg_lower.startswith("latest news about ")
            or msg_lower.startswith("latest news on ")
            or msg_lower.startswith("find recent news about ")
            or msg_lower.startswith("look up ")
            or re.match(r"^find\s+.+?\s+(?:online|on\s+the\s+web|on\s+the\s+internet)$", msg_lower)
        ):
            # Exclude local file searches
            if not any(k in msg_lower for k in ["files named", "python files", "pdf files", "files in", "downloads folder", "desktop folder", "my files", "my project", "files modified", "recent files"]):
                engine = "google"
                if "youtube" in msg_lower:
                    engine = "youtube"
                elif "github" in msg_lower:
                    engine = "github"
                elif "reddit" in msg_lower:
                    engine = "reddit"
                elif "wikipedia" in msg_lower:
                    engine = "wikipedia"

                m_q = re.search(r"^(?:search\s+(?:on\s+)?(?:youtube|reddit|github|wikipedia|google)\s+(?:for\s+)?|search\s+(?:the\s+)?(?:web|internet|online)\s+(?:for\s+)?|search\s+for\s+|google\s+(?:for\s+)?|find\s+(?:the\s+)?official\s+website\s+(?:for\s+)?|what(?:'s|\s+is)\s+the\s+latest\s+news\s+(?:about|on)\s+|latest\s+news\s+(?:about|on)\s+|find\s+recent\s+news\s+about\s+|look\s+up\s+)(.+)$", msg_clean, flags=re.IGNORECASE)
                if m_q:
                    raw_q = m_q.group(1).strip()
                    raw_q = re.sub(r"\s+(?:online|on\s+the\s+web|on\s+the\s+internet)$", "", raw_q, flags=re.IGNORECASE).strip()
                    return "web_search", {"query": raw_q, "engine": engine}
                
                m_find_online = re.match(r"^find\s+(.+?)\s+(?:online|on\s+the\s+web|on\s+the\s+internet)$", msg_clean, flags=re.IGNORECASE)
                if m_find_online:
                    raw_q = m_find_online.group(1).strip()
                    return "web_search", {"query": raw_q, "engine": "google"}

        # 8. Feature #35: SMART FILE MANAGER INTENTS

        # 8.1. Create Folder Intent
        m_create_folder = re.match(
            r"^(?:create|make|mkdir)\s+(?:a\s+)?(?:new\s+)?folder(?:\s+called|\s+named)?\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_create_folder:
            raw_folder_target = m_create_folder.group(1).strip()
            m_nested = re.search(r"^(.+?)\s+(?:inside|in|under|on)\s+(.+)$", raw_folder_target, flags=re.IGNORECASE)
            if m_nested:
                fn = m_nested.group(1).strip().strip('"').strip("'")
                loc = m_nested.group(2).strip().strip('"').strip("'")
                return "create_folder", {"folder_name": fn, "location": loc, "target_path": f"{loc}/{fn}"}
            else:
                return "create_folder", {"folder_name": raw_folder_target, "target_path": raw_folder_target}

        # 8.2. Create File Intent
        m_create_file = re.match(
            r"^(?:create|make|touch)\s+(?:a\s+)?(?:new\s+)?(?:empty\s+)?file(?:\s+called|\s+named)?\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_create_file:
            raw_file_target = m_create_file.group(1).strip()
            m_nested_file = re.search(r"^(.+?)\s+(?:inside|in|under|on)\s+(.+)$", raw_file_target, flags=re.IGNORECASE)
            if m_nested_file:
                fn = m_nested_file.group(1).strip().strip('"').strip("'")
                loc = m_nested_file.group(2).strip().strip('"').strip("'")
                return "create_file", {"filename": fn, "folder": loc, "target_path": f"{loc}/{fn}"}
            else:
                return "create_file", {"filename": raw_file_target, "target_path": raw_file_target}

        # 8.3. Rename File / Folder Intent
        m_rename = re.match(
            r"^rename\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)\s+(?:to|as)\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_rename:
            src = m_rename.group(1).strip().strip('"').strip("'")
            dst = m_rename.group(2).strip().strip('"').strip("'")
            return "rename_file", {"source_path": src, "new_name": dst, "target_path": src}

        # 8.4. Move File / Folder Intent
        m_move = re.match(
            r"^move\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)\s+(?:to|into|inside|in)\s+(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_move:
            src = m_move.group(1).strip().strip('"').strip("'")
            dst = m_move.group(2).strip().strip('"').strip("'")
            return "move_file", {"source_path": src, "destination_path": dst, "target_path": src}

        # 8.5. Copy File / Folder Intent
        m_copy = re.match(
            r"^(?:copy|make\s+a\s+copy\s+of)\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)(?:\s+(?:to|into|inside|in)\s+(.+))?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_copy:
            src = m_copy.group(1).strip().strip('"').strip("'")
            dst = (m_copy.group(2) or "documents").strip().strip('"').strip("'")
            return "copy_file", {"source_path": src, "destination_path": dst, "target_path": src}

        # 8.6. Delete File / Folder Intent
        m_delete = re.match(
            r"^(?:delete|remove|erase|trash)\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+|directory\s+)?(.+)$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_delete:
            target_del = m_delete.group(1).strip().strip('"').strip("'")
            if not any(kw in target_del.lower() for kw in ["character", "text", "line", "word", "paragraph", "selection"]):
                return "delete_file", {"target_path": target_del}

        # 8.7. List Directory Intent
        m_list = re.match(
            r"^(?:list|show|view|display|what(?:'s|\s+is)\s+inside)\s+(?:the\s+)?(?:files\s+in|contents\s+of|inside|folder\s+contents\s+for|files\s+inside)?\s*(downloads|desktop|documents|pictures|videos|music|this\s+folder|[a-zA-Z0-9_\-\s]+?\s+folder|[a-zA-Z0-9_\-\s]+?\s+directory|[a-zA-Z]:[\\/][a-zA-Z0-9_\-\s\\/]+)?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if (
            m_list
            or msg_lower in ["show files", "list files", "show my files", "list my files", "what's inside this folder?", "what is inside this folder", "show folder contents", "show project structure"]
            or (re.match(r"^(?:show|list)\s+files\s+(?:in|inside|on)\s+(.+)$", msg_clean, re.IGNORECASE))
        ):
            target_f = "downloads"
            if m_list and m_list.group(1):
                target_f = m_list.group(1).strip()
            else:
                m_direct = re.match(r"^(?:show|list)\s+files\s+(?:in|inside|on)\s+(.+)$", msg_clean, re.IGNORECASE)
                if m_direct:
                    target_f = m_direct.group(1).strip()
            return "list_files", {"target_path": target_f, "folder": target_f}

        # 8.8. Smart File Search Intent
        if not re.match(r"^(?:what\s+is\s+(?:a|an|the)|how\s+does|why\s+is|who\s+is|explain\s+what)\b", msg_lower):
            search_match = re.match(
                r"^(?:search|find|locate|where\s+is|show\s+me)\s+(?:files?\s+(?:for\s+|matching\s+|named\s+|containing\s+)?|for\s+(?:files?\s+)?|(?:my\s+)?(?:files?\s+|file\s+|project\s+)?|my\s+|all\s+)?(.+)$",
                msg_lower
            )
            if search_match or any(kw in msg_lower for kw in ["largest files", "recently modified", "modified today", "modified yesterday", "files larger than", "files smaller than", "pdf files", "python files"]):
                raw_q = search_match.group(1).strip() if search_match else msg_clean
                if raw_q and not any(kw in raw_q for kw in ["running", "app status", "take screenshot", "the web", "online", "internet"]):
                    return "file_search", {"query": msg_clean}

        # 9. Save Document / Create File Intent (legacy fallback)
        m_save_doc = re.match(
            r"^(?:save\s+(?:the\s+)?(?:document|file)|save\s+it|write\s+to\s+file)(?:\s+as\s+([a-zA-Z0-9_\-\.]+))?(?:\s+(?:on|in)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+))?$",
            msg_clean,
            flags=re.IGNORECASE
        )
        if m_save_doc:
            fn = (m_save_doc.group(1) or "document.txt").strip()
            loc = (m_save_doc.group(2) or "desktop").strip()
            return "create_file", {"filename": fn, "folder": loc, "target_path": f"{loc}/{fn}"}

        # 15. Automation & Routine Management Intent (Feature #36)
        if (
            msg_lower in ["show my automations", "show automations", "list my automations", "list automations", "view automations", "list my routines", "show my routines", "show routines", "list routines", "what's scheduled today?", "what is scheduled today?", "what's scheduled today", "what is scheduled today", "show today's schedule", "scheduled today", "turn off all automations", "disable all automations", "pause all automations"]
            or re.match(r"^(?:enable|disable|delete)\s+(?:my\s+)?(?:automation\s+|workflow\s+|routine\s+)?.+$", msg_lower)
            or re.match(r"^run\s+(?:my\s+)?.+?\s+now$", msg_lower)
            or re.match(r"^change\s+(?:my\s+)?.+?\s+to\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?$", msg_lower)
            or re.match(r"^(?:every\s+(?:day|morning|evening|weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|whenever\s+i\s+say|when\s+i\s+start\s+bytex|at\s+startup)\b", msg_lower)
        ):
            return "automation", {"raw_text": msg_clean}

        return None

    @classmethod
    def is_compound_command(cls, text: str) -> bool:
        """
        Determines if a natural language command consists of multiple sequential actions
        separated by commas, 'and', 'then', or 'and then'.
        """
        clean = text.strip()
        clean = re.sub(r"^(?:hey\s+bytex|bytex|please|can\s+you|could\s+you|would\s+you)\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"[.!?,\"\']+$", "", clean).strip()
        low = clean.lower()

        if any(sep in low for sep in [",", " and then ", " then ", " and "]):
            # Ignore single code generation commands with save filename specification (e.g. "Write merge sort in C++ and save it as merge.cpp")
            if re.search(r"^(?:write|create|implement|code|generate|build|make)\s+.+?\s+and\s+save\s+(?:it\s+)?as\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+$", clean, re.IGNORECASE):
                return False
            # Ignore "open and analyze / review / explain / inspect / check / read <file>" and read-and-explain / tell me what <file> does variants
            if re.search(r"^(?:open\s+and\s+|read\s+)?(?:analyze|analyse|review|explain|inspect|check|examine|read|tell\s+me)\b", clean, re.IGNORECASE):
                return False
            if re.search(r"\b(?:what\s+it\s+does|what\s+does\s+it\s+do|tell\s+me\s+what\s+.+?\s+does|don't\s+modify|do\s+not\s+modify)\b", low):
                return False
            # Ignore "create and run a ... program" or "create a ... program and run it"
            if re.search(r"^(?:create|write|make|generate|build)\s+and\s+(?:run|execute)\b", clean, re.IGNORECASE):
                return False
            if re.search(r"^(?:write|create|implement|code|generate|build|make)\s+(?:a\s+|an\s+)?(?:[a-zA-Z0-9_\+\#\.\-]+\s+)?(?:program|script|solution|function|code|app|file)\s+.*?and\s+(?:run|execute)(?:\s+it)?\.?$", clean, re.IGNORECASE):
                return False
            # Ignore "open <file> and modify..." / "edit/optimize <file> to/and..."
            if re.search(r"^(?:open|load|edit|modify|update|alter|rewrite|change|optimize|optimise)\b", clean, re.IGNORECASE):
                return False
            # Ignore "run <file> and fix the error"
            if re.search(r"^(?:run|compile\s+and\s+run|execute)\s+(?:the\s+)?[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+\s+and\s+(?:fix|repair|heal|correct)\b", clean, re.IGNORECASE):
                return False
            # Ignore "add a function ... in this file" / "add a function ... in <file>"
            if re.search(r"^(?:add|insert|create|write)\s+(?:a\s+)?(?:function|method|logic|code|snippet)?\s+.*?(?:in|to|into)\s+(?:this\s+file|current\s+file|[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)", clean, re.IGNORECASE):
                return False
            # Ignore "analyze ... and tell me how I can improve it / optimize it"
            if re.search(r"^analyze\s+.*?\s+and\s+(?:tell\s+me\s+)?how\b", clean, re.IGNORECASE):
                return False
            # Ignore "don't fix ... give me a hint"
            if re.search(r"\bgive\s+me\s+(?:a\s+)?hint\b", clean, re.IGNORECASE):
                return False
            # Ignore "modify / change ... to calculate ... instead of ..."
            if "instead of" in low and any(w in low for w in ["modify", "change", "edit", "replace", "print", "sum", "numbers"]):
                return False
            # Ignore "run <file>" and "compile and run <file>"
            if re.search(r"^(?:run|execute|compile\s+and\s+run|compile\s+and\s+execute)\b", clean, re.IGNORECASE) and not any(w in low for w in ["and fix", "and repair", "and heal", "and correct"]):
                return False
            # Ignore "compile / build <file> [but don't run / without running]"
            if re.search(r"^(?:compile|build)\b", clean, re.IGNORECASE):
                return False

            actions = ["open", "launch", "start", "run", "type", "write", "enter", "click", "press", "tap", "save", "close", "quit", "exit", "search", "create", "make", "delete", "copy", "move", "check", "diagnose", "explain", "fix", "repair"]
            found_actions = 0
            parts = re.split(r',\s*(?:and\s+|then\s+)?|\s+and\s+then\s+|\s+then\s+|\s+and\s+', clean, flags=re.IGNORECASE)
            for p in parts:
                p_strip = p.strip().lower()
                if any(p_strip.startswith(a + " ") or p_strip == a or p_strip.startswith(a + "ing ") for a in actions) or p_strip in ["save it", "save file", "save document", "save"]:
                    found_actions += 1
            if found_actions >= 2:
                return True
        return False

    @classmethod
    async def classify_request(cls, message: str) -> Dict[str, Any]:
        """
        Lightweight deterministic request router classifying requests into:
        - NORMAL (conversational / Q&A / general knowledge)
        - SINGLE_ACTION (matches a registered ByteX skill)
        - MULTI_STEP (multi-step tasks, composite goals, workflow optimization)
        Zero LLM / API calls.
        """
        clean_msg = message.strip()
        clean_msg = re.sub(r"^(?:hey\s+bytex|bytex|please|can\s+you|could\s+you|would\s+you)\s+", "", clean_msg, flags=re.IGNORECASE)
        clean_msg = re.sub(r"[.!?,\"\']+$", "", clean_msg).strip()
        msg_lower = clean_msg.lower()

        # 1. Check for Multi-Step / Composite Workflow Goals FIRST
        if cls.is_compound_command(clean_msg):
            return {
                "route": "MULTI_STEP",
                "intent": clean_msg
            }

        # 2. Check for Single Action Intent (e.g. browser search, single app, file search)
        parsed_intent = await cls.parse_skill_intent(message)
        if parsed_intent:
            tool_name, args = parsed_intent
            return {
                "route": "SINGLE_ACTION",
                "skill": tool_name,
                "arguments": args
            }

        # 3. Detect Multi-Step / Composite Workflow Goals (pattern-based)
        multi_step_patterns = [
            r"\b(?:prepare|setup|set\s+up|optimize|tune)\s+(?:my\s+)?(?:pc|computer|system|laptop)\b",
            r"\b(?:prepare|setup|set\s+up)\s+(?:my\s+)?(?:workspace|work\s+environment)\b",
            r"\b(?:organize|sort|clean\s+up|tidy\s+up)\s+(?:my\s+)?(?:downloads?|desktop|documents?|folder|files?)\b",
            r"\b(?:backup|archive)\s+(?:all\s+)?(?:my\s+)?(?:files?|documents?|folders?)\b",
            r"\b(?:find\s+.+?\s+and\s+(?:delete|move|rename|copy)\s+.+)",
            r"\b(?:open\s+.+?\s+and\s+(?:take\s+a\s+screenshot|check\s+.+))",
            r"\b(?:first\s+.+?\s+then\s+.+)",
            r"\b(?:check\s+(?:my\s+)?(?:computer|pc|system|laptop)\s+and\s+report\s+(?:the\s+)?(?:system\s+)?status)\b",
            r"\b(?:check\s+.+?\s+and\s+(?:report|show|tell)\s+.+)",
            r"\b(?:check\s+.+?\s+and\s+(?:then\s+)?(?:open|launch|start|run|create|make)\s+.+)",
            r"\b(?:and\s+then\s+.+)",
            r"\b(?:create|make|build)\s+.+?\s+and\s+(?:verify|check)\s+.+",
            r"\b(?:open|launch|start)\s+.+?\s+and\s+(?:verify|check)\s+.+",
            r"\b(?:open|launch|start|run)\s+.+?\s*(?:,|and|\+)\s*.+",
            r"\b(?:close|quit|exit|stop|kill)\s+.+?\s*(?:,|and|\+)\s*.+",
            r"\b(?:play|stream|listen\s+to)\s+.+?\s*(?:,|and|\+)\s*.+"
        ]
        for pattern in multi_step_patterns:
            if re.search(pattern, msg_lower):
                return {
                    "route": "MULTI_STEP",
                    "intent": clean_msg
                }

        # 3. Default to NORMAL (conversational / Q&A / general knowledge)
        return {
            "route": "NORMAL"
        }

    @classmethod
    async def route_command(cls, message: str, history: List[Dict[str, str]] = None) -> Tuple[bool, str, str, Optional[Dict[str, Any]]]:
        """
        Routes user prompt. Handles active confirmations, multi-step requests, skills, and memory commands.
        Returns: (is_handled, response_text, state, data)
        """
        print(f"[ByteX CommandRouter] Processing: '{message}'")
        
        # 0. Multilingual Normalization (Feature #37.3)
        from core.multilingual_router import MultilingualRouter, detect_language
        detected_lang = detect_language(message)
        norm_message, _ = MultilingualRouter.process_input(message)
        if norm_message.startswith("AMBIGUOUS_OPEN:"):
            clarification = norm_message.replace("AMBIGUOUS_OPEN:", "").strip()
            return True, clarification, "speaking", None

        if norm_message and norm_message != message:
            print(f"[ByteX Multilingual] Normalized '{message}' ({detected_lang}) -> '{norm_message}'")
            message = norm_message

        # 0.5. Direct Voice/Text Interruption and Stop Command
        clean_prompt = message.strip().lower()
        clean_prompt = re.sub(r"[.!?,\"\']+$", "", clean_prompt).strip()
        if clean_prompt in ["stop", "cancel", "stop speaking", "stop talking", "be quiet", "quiet", "hush", "shut up", "pause"]:
            print(f"[ByteX CommandRouter] Interruption Stop command received: '{message}'")
            return True, "Stopped.", "idle", {"interrupted": True}
        
        # 1. Check for Pending Confirmation Response
        from core.confirmation import confirmation_manager
        from core.session import session_manager
        
        # Resolve Conversational Follow-Up if active session exists
        if session_manager.is_session_active():
            resolved = session_manager.resolve_follow_up(message)
            if resolved.startswith("AMBIGUOUS_FOLLOWUP:"):
                clarification = resolved.replace("AMBIGUOUS_FOLLOWUP:", "").strip()
                return True, clarification, "speaking", None
            if resolved.startswith("STALE_CONTEXT:"):
                stale_msg = resolved.replace("STALE_CONTEXT:", "").strip()
                return True, stale_msg, "speaking", None
            message = resolved
            print(f"[ByteX CommandRouter] Session follow-up resolved: '{message}'")
        else:
            # Session inactive: check if user tried to use pronoun follow-up without active session
            if re.match(r"^(?:close|quit|exit|kill|stop)\s+(?:it|this|that|the\s+app)$", clean_prompt):
                return True, "Which application would you like me to close?", "speaking", None
            if re.match(r"^(?:read\s+(?:this|the)\s+(?:web)?page|read\s+it|what\s+does\s+(?:this|the)\s+(?:web)?page\s+say|tell\s+me\s+what\s+(?:this|the)\s+(?:web)?page\s+contains)$", clean_prompt):
                return True, "Please provide the URL of the webpage you would like me to read.", "speaking", None
            if (
                re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?|top)\s+(?:result|one|link)$", clean_prompt)
                or re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?result\s+(?:number\s+|#)?\d+$", clean_prompt)
                or re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?result\s+from\s+.+$", clean_prompt)
                or re.match(r"^(?:open|click|view|go\s+to|select)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]+)\s+result$", clean_prompt)
            ):
                return True, "I don't have a recent search result to open.", "speaking", None
            if re.match(r"^(?:click|press|tap|select)\s+(?:on\s+)?(?:it|this|that|the\s+button|the\s+element|the\s+first\s+one)$", clean_prompt):
                return True, "Which element would you like me to click?", "speaking", None
            if re.match(r"^(?:pause|pause\s+it|resume|resume\s+it|unpause|unpause\s+it)$", clean_prompt):
                return True, "There is no active media playback to pause or resume.", "speaking", None
            if re.match(r"^(?:type|write|enter|input)\s+.+?\s+(?:in|into|on|to)\s+(?:it|this|that|the\s+app|the\s+window)$", clean_prompt):
                return True, "Which application or window would you like me to type into?", "speaking", None
            if re.match(r"^(?:open|show|explore)\s+(?:it|this|that|the\s+folder|the\s+file)$", clean_prompt):
                return True, "Which item or folder would you like me to open?", "speaking", None
            if re.match(r"^(?:analyze|describe|inspect)\s+(?:it|this|that|the\s+screenshot)$", clean_prompt):
                return True, "What is on my screen?", "speaking", None

        if confirmation_manager.has_pending():
            eval_res = confirmation_manager.evaluate_response(message)
            if eval_res is True:
                # Approval comes only from this trusted branch (a real user "yes" for THIS conversation's pending request).
                pending, approval = confirmation_manager.approve_pending()
                if pending is None:
                    return True, "That confirmation has expired. Please ask again.", "speaking", None
                print(f"[ByteX CommandRouter] User CONFIRMED pending action: {pending.action}")
                if pending.tool == "create_automation" or pending.action == "create_automation":
                    from agent.automation import automation_manager, Automation
                    auto_data = pending.arguments.get("automation")
                    if not auto_data:
                        return True, "No automation data provided.", "speaking", None
                    auto_obj = Automation(**auto_data)
                    automation_manager.save_automation(auto_obj)
                    return True, f"Automation '{auto_obj.name}' has been created and enabled.", "speaking", {"automation": auto_obj.model_dump()}
                elif pending.tool == "delete_automation" or pending.action == "delete_automation":
                    from agent.automation import automation_manager
                    auto_id = pending.arguments.get("automation_id", "")
                    name = pending.arguments.get("name", "Automation")
                    automation_manager.delete_automation(auto_id)
                    return True, f"Automation '{name}' has been deleted.", "speaking", {"deleted_id": auto_id}
                elif pending.tool == "delete_all_automations" or pending.action == "delete_all_automations":
                    from agent.automation import automation_manager
                    cnt = automation_manager.clear_all_automations()
                    return True, f"All {cnt} automation(s) have been deleted.", "speaking", {"count": cnt}
                elif pending.tool == "clear_task_history" or pending.action == "clear_task_history":
                    from agent.history import task_history_manager
                    count = task_history_manager.clear_history()
                    return True, f"Your ByteX task history has been permanently cleared ({count} task(s) deleted).", "speaking", {"count": count}
                elif pending.tool == "clear_all_memories" or pending.action == "clear_all_memories":
                    from memory.manager import memory_manager
                    count = memory_manager.clear_all_memories()
                    return True, f"All saved ByteX memories have been permanently cleared ({count} deleted).", "speaking", {"count": count}
                elif pending.tool == "save_learned_preference" or pending.action == "save_learned_preference":
                    from memory.manager import memory_manager
                    from memory.preferences import preference_manager
                    from memory.learning import preference_learner
                    
                    key = pending.arguments.get("key", "")
                    val = pending.arguments.get("value", "")
                    cat = pending.arguments.get("category", "USER_PREFERENCE")
                    cnt = pending.arguments.get("content", f"User prefers {val}.")
                    
                    memory_manager.add_memory(
                        content=cnt,
                        category=cat,
                        key=key,
                        value=val,
                        source="learned_confirmation"
                    )
                    preference_manager.set_explicit_preference(key=key, value=val, category=cat)
                    preference_learner.record_confirmation(key, val)
                    return True, "Understood! I've saved this preference to your long-term memory.", "speaking", {"learned_preference": {"key": key, "value": val}}
                elif pending.tool == "execute_suggestion" or pending.action == "execute_suggestion":
                    from agent.suggestions import suggestion_engine, SuggestionCandidate
                    cand = pending.arguments.get("candidate")
                    if not cand:
                        return True, "No suggestion details found.", "speaking", None
                    candidate_obj = SuggestionCandidate(**cand)
                    is_valid, invalid_reason = suggestion_engine.validate_suggestion_context(candidate_obj)
                    if not is_valid:
                        suggestion_engine.record_dismissal(candidate_obj.id)
                        return True, f"The context has changed ({invalid_reason}). I need to re-verify before proceeding.", "speaking", {"context_invalid": True}
                    suggestion_engine.record_acceptance(candidate_obj.id)
                    print(f"[ByteX CommandRouter] Executing accepted proactive suggestion: '{candidate_obj.command}'")
                    h_sug, r_sug, s_sug, d_sug = await cls.route_command(candidate_obj.command)
                    return True, f"Executed suggestion: {r_sug}", s_sug, d_sug
                result = await skill_registry.execute_tool(pending.tool, dict(pending.arguments), approval=approval)
                state = "speaking" if result.success else "error"
                session_manager.start_or_renew_session(target=pending.arguments.get("target_path"), action=pending.action)
                return True, result.message, state, result.data
            elif eval_res is False:
                pending = confirmation_manager.get_pending()
                confirmation_manager.clear()
                print(f"[ByteX CommandRouter] User REJECTED pending action: {pending.action}")
                if pending.tool == "save_learned_preference" or pending.action == "save_learned_preference":
                    from memory.learning import preference_learner
                    key = pending.arguments.get("key", "")
                    val = pending.arguments.get("value", "")
                    preference_learner.record_rejection(key, val)
                    return True, "Understood. I won't save this preference.", "speaking", None
                elif pending.tool == "execute_suggestion" or pending.action == "execute_suggestion":
                    from agent.suggestions import suggestion_engine
                    cand_id = pending.arguments.get("candidate", {}).get("id", "")
                    if cand_id:
                        suggestion_engine.record_dismissal(cand_id)
                    return True, "Suggestion dismissed.", "speaking", None
                return True, f"Action cancelled: {pending.description}.", "speaking", None
            else:
                # User typed an unrelated new command; invalidate pending confirmation
                print(f"[ByteX CommandRouter] Pending confirmation superseded by new request.")
                confirmation_manager.clear()


        # 1.3. SMART LIFE phrasings (reminders, dated life events) are left to the AI model, which uses the validated,
        #      user-approved smart_life tool. Without this, the older generic handlers below (file move/delete skills,
        #      automation editing, "remember that ..." memory notes) would grab them first. Executes nothing itself.
        from smartlife.intent import is_smart_life_request
        if is_smart_life_request(message):
            print("[ByteX CommandRouter] SMART LIFE phrasing: passing to the AI model.")
            return False, "", "speaking", None

        # 1.35. Direct Code Workspace Intent Priority (Feature #33 / Coding Intelligence 2.0)
        # Prevents local code file commands from being hijacked by ambiguous automation heuristics
        cand_target_file = cls._extract_target_file(message)
        if cand_target_file and not any(kw in message.lower() for kw in ["every day", "every weekday", "every monday", "every hour", "at startup", "when bytex starts", "routine called", "automation called"]):
            classification = await cls.classify_request(message)
            if classification.get("route") == "SINGLE_ACTION" and classification.get("skill") == "coding_workspace":
                tool_name = classification["skill"]
                args = classification.get("arguments", {})
                print(f"[ByteX CommandRouter] Direct Code File Match -> Skill: '{tool_name}', Arguments: {args}")
                result = await skill_registry.execute_tool(tool_name, args, origin=skill_registry.ORIGIN_USER)
                if result.confirmation_required:
                    prompt_msg = confirmation_manager.set_pending(
                        tool=result.tool,
                        action=result.action or result.tool,
                        description=result.message,
                        arguments=result.pending_action or args
                    )
                    return True, prompt_msg, "speaking", {"confirmation_required": True, "action": result.action}
                session_manager.record_action_result(tool_name, args, result)
                state = "speaking" if result.success else "error"
                return True, result.message, state, result.data

        # 1.4. Handle Natural Language Automation (Feature #36)
        from agent.automation import NaturalLanguageAutomationParser, automation_manager

        # A. Automation Management Commands (List, Enable, Disable, Delete, Modify, Schedule Query)
        is_auto_cmd, auto_msg, auto_st, auto_dt = automation_manager.handle_natural_automation_command(message)
        if is_auto_cmd and auto_msg:
            return True, auto_msg, auto_st or "speaking", auto_dt

        # B. Run Automation Now (e.g. "Run my morning routine now", "Run morning routine now", "Run my morning routine")
        m_run_now = re.match(r"^run\s+(?:my\s+)?(.+?)(?:\s+now)?\.?$", message.strip(), re.IGNORECASE)
        if m_run_now:
            tgt_auto_name = m_run_now.group(1).strip()
            target_auto = automation_manager.get_automation_by_name(tgt_auto_name)
            if target_auto:
                print(f"[ByteX CommandRouter] Running Automation On-Demand: '{target_auto.name}'")
                h_now, r_now, s_now, d_now = await automation_manager.execute_automation(target_auto, is_manual=True)
                return h_now, r_now, s_now, d_now

        # C. Automation Creation Parsing
        is_auto_create, auto_candidate, auto_feedback = NaturalLanguageAutomationParser.parse_creation_request(message)
        if is_auto_create:
            if auto_candidate:
                # Duplicate Check
                dup = automation_manager.check_duplicate(auto_candidate)
                if dup:
                    dup_steps = "\n".join([f"{i}. {s.description or s.action}" for i, s in enumerate(dup.steps, 1)])
                    return True, f"An equivalent automation '**{dup.name}**' ({dup.trigger}) already exists:\n\n{dup_steps}\n\nWould you like to modify or delete the existing routine?", "speaking", {"duplicate_id": dup.automation_id}

                auto_saved = automation_manager.save_automation(auto_candidate)
                steps_desc = "\n".join([f"{i}. {s.description or s.action}" for i, s in enumerate(auto_saved.steps, 1)])
                resp_msg = f"✓ **Automation created**\n\n**{auto_saved.name}**\n{auto_saved.trigger}\n\n{steps_desc}"
                if auto_saved.requires_confirmation:
                    resp_msg += "\n\n*(⚠️ Note: Steps requiring confirmation will prompt before executing)*"
                return True, resp_msg, "speaking", {"automation": auto_saved.model_dump()}
            else:
                return True, auto_feedback or "I couldn't create this automation.", "speaking", None

        # D. Command Trigger / Manual Execution Matching
        matched_autos = automation_manager.find_matching_command_automations(message)
        if len(matched_autos) == 1:
            print(f"[ByteX CommandRouter] Matched Command Automation: '{matched_autos[0].name}'")
            h_auto, r_auto, s_auto, d_auto = await automation_manager.execute_automation(matched_autos[0])
            return h_auto, r_auto, s_auto, d_auto
        elif len(matched_autos) > 1:
            lines = ["I found multiple automations matching that command. Which one would you like to run?"]
            for i, a in enumerate(matched_autos, 1):
                lines.append(f"{i}. **{a.name}** (Trigger: '{a.trigger}')")
            return True, "\n".join(lines), "speaking", {"matched_automations": [a.model_dump() for a in matched_autos]}

        # 1.5. Handle Natural Routine & Automation Commands
        from agent.routines import routine_manager
        is_routine_cmd, routine_resp, routine_action, routine_payload = routine_manager.handle_natural_routine_command(message)
        if is_routine_cmd:
            if routine_action == "RUN_ROUTINE" and routine_payload and "routine" in routine_payload:
                routine = routine_payload["routine"]
                print(f"[ByteX CommandRouter] Executing Routine '{routine.display_name}' via Agent Pipeline...")
                from agent.pipeline import agent_pipeline
                from agent.models import AgentPlan, PlanStep, StepState
                
                steps = []
                for idx, s in enumerate(routine.steps, 1):
                    steps.append(
                        PlanStep(
                            step_id=idx,
                            description=s.description,
                            suggested_skill=s.skill,
                            arguments=s.arguments,
                            requires_confirmation=False,
                            status=StepState.PENDING,
                            max_replans=1
                        )
                    )
                routine_plan = AgentPlan(
                    plan_id=f"plan_routine_{routine.name}_{int(time.time())}",
                    goal=f"Run {routine.display_name} routine",
                    steps=steps
                )
                success, resp, state, data = await agent_pipeline.run_pipeline(goal=f"Run {routine.display_name} routine", plan=routine_plan)
                session_manager.start_or_renew_session(action="agent_pipeline")
                return True, resp, state, data
            else:
                print(f"[ByteX CommandRouter] Matched Natural Routine Command: {routine_action}")
                return True, routine_resp, routine_action or "speaking", routine_payload

        # 1.6. Handle Natural Work Resume & "What was I doing?" Queries (Feature #42)
        from agent.work_resume import work_resume_engine
        is_resume_cmd, resume_resp, resume_state, resume_data = await work_resume_engine.handle_natural_resume_command(message)
        if is_resume_cmd:
            print(f"[ByteX CommandRouter] Matched Natural Work Resume Command.")
            return True, resume_resp, resume_state or "speaking", resume_data

        # 2. Lightweight Request Classification (Zero-LLM)
        classification = await cls.classify_request(message)
        route_type = classification.get("route", "NORMAL")
        print(f"[ByteX CommandRouter] Request Classification: {classification}")

        # 3. Handle MULTI_STEP via Controlled Agent Pipeline
        if route_type == "MULTI_STEP":
            from agent.pipeline import agent_pipeline
            success, resp, state, data = await agent_pipeline.run_pipeline(message)
            session_manager.start_or_renew_session(action="agent_pipeline")
            return True, resp, state, data

        # 4. Handle SINGLE_ACTION
        elif route_type == "SINGLE_ACTION":
            tool_name = classification["skill"]
            args = classification.get("arguments", {})
            print(f"[ByteX CommandRouter] Matched Intent -> Skill: '{tool_name}', Arguments: {args}")
            result = await skill_registry.execute_tool(tool_name, args, origin=skill_registry.ORIGIN_USER)

            # Handle tool requesting user confirmation
            if result.confirmation_required:
                prompt_msg = confirmation_manager.set_pending(
                    tool=result.tool,
                    action=result.action or result.tool,
                    description=result.message,
                    arguments=result.pending_action or args
                )
                return True, prompt_msg, "speaking", {"confirmation_required": True, "action": result.action}

            target = args.get("application") or args.get("folder_name") or args.get("target_path") or args.get("url") or (result.data.get("url") if isinstance(result.data, dict) else None)
            session_manager.record_action_result(tool_name, args, result)

            # Record Single Action in Task History
            from agent.history import task_history_manager, TaskStepRecord, StepStatus, TaskStatus
            from agent.recovery import error_recovery_engine, ErrorCategory

            if result.success and result.verified:
                step_st = StepStatus.VERIFIED_SUCCESS
            else:
                err_cat = error_recovery_engine.classify_error(tool_name, args, result)
                if err_cat == ErrorCategory.NOT_FOUND:
                    step_st = StepStatus.NOT_FOUND
                elif err_cat == ErrorCategory.UNSUPPORTED:
                    step_st = StepStatus.UNSUPPORTED
                elif err_cat == ErrorCategory.PERMISSION_DENIED:
                    step_st = StepStatus.PERMISSION_DENIED
                elif err_cat == ErrorCategory.VERIFICATION_FAILED:
                    step_st = StepStatus.VERIFICATION_FAILED
                else:
                    step_st = StepStatus.FAILED

            step_rec = TaskStepRecord(
                step_id=1,
                action=tool_name,
                target=str(target) if target else None,
                status=step_st,
                human_readable_result=result.message
            )
            task_history_manager.record_task(
                request=message,
                steps=[step_rec]
            )

            state = "speaking" if result.success else "error"
            out_data = dict(result.data) if result.data else {}
            if result.success:
                from agent.suggestions import suggestion_engine
                sug = suggestion_engine.evaluate_triggers(last_action=tool_name, target=str(target) if target else None, data=out_data)
                if sug:
                    out_data["active_suggestion"] = sug.model_dump()
            return True, result.message, state, out_data

        # 5. Handle Task History Queries & Clearing
        from agent.history import task_history_manager
        clean_msg = message.strip().lower()
        if re.match(r"^(?:clear|delete|wipe|erase|purge)\s+(?:all\s+)?(?:task\s+history|task\s+records|my\s+tasks|tasks)\.?$", clean_msg):
            from core.confirmation import confirmation_manager
            confirmation_manager.set_pending(
                tool="clear_task_history",
                action="clear_task_history",
                description="This will permanently delete your ByteX task history. Continue?",
                arguments={}
            )
            return True, "This will permanently delete your ByteX task history. Continue?", "waiting_confirmation", {"pending_action": "clear_task_history"}

        is_hist_cmd, hist_response = task_history_manager.handle_natural_history_query(message)
        if is_hist_cmd and hist_response:
            print(f"[ByteX CommandRouter] Matched Natural Task History Query.")
            return True, hist_response, "speaking", None

        # 6. Handle Natural Memory and Preference Commands
        from memory.manager import MemoryManager
        is_mem_cmd, mem_response, mem_state, mem_data = MemoryManager.handle_natural_command(message)
        if is_mem_cmd and mem_response:
            print(f"[ByteX CommandRouter] Matched Natural Memory Command.")
            return True, mem_response, mem_state or "speaking", mem_data

        from memory.preferences import preference_manager
        is_pref_cmd, pref_response = preference_manager.handle_natural_preference_command(message)
        if is_pref_cmd and pref_response:
            print(f"[ByteX CommandRouter] Matched Natural Preference Command.")
            return True, pref_response, "speaking", None

        # 6.4. Handle Natural Suggestion Actions
        from agent.suggestions import suggestion_engine
        msg_norm = message.strip().lower()
        if msg_norm in ["accept suggestion", "yes to suggestion", "run suggestion", "execute suggestion", "accept suggested action"]:
            act_sug = suggestion_engine.get_active_suggestion()
            if not act_sug:
                return True, "There is no active proactive suggestion right now.", "speaking", None
            is_valid, invalid_reason = suggestion_engine.validate_suggestion_context(act_sug)
            if not is_valid:
                suggestion_engine.record_dismissal(act_sug.id)
                return True, f"The context has changed ({invalid_reason}). I need to re-verify before proceeding.", "speaking", {"context_invalid": True}
            suggestion_engine.record_acceptance(act_sug.id)
            print(f"[ByteX CommandRouter] Executing accepted proactive suggestion: '{act_sug.command}'")
            h_sug, r_sug, s_sug, d_sug = await cls.route_command(act_sug.command)
            return True, f"Executed suggestion: {r_sug}", s_sug, d_sug
        elif msg_norm in ["dismiss suggestion", "reject suggestion", "no to suggestion", "ignore suggestion"]:
            act_sug = suggestion_engine.get_active_suggestion()
            if act_sug:
                suggestion_engine.record_dismissal(act_sug.id)
            return True, "Suggestion dismissed.", "speaking", None
        # 6.5. Observe Interaction via Preference Learner
        from memory.learning import preference_learner
        learned_prompt = preference_learner.observe_interaction(message)
        if learned_prompt:
            prompt_text, confirm_args = learned_prompt
            prompt_msg = confirmation_manager.set_pending(
                tool="save_learned_preference",
                action="save_learned_preference",
                description=prompt_text,
                arguments=confirm_args
            )
            return True, prompt_msg, "speaking", {"confirmation_required": True, "action": "save_learned_preference", "candidate": confirm_args}

        # 7. NORMAL -> Passes through to fast AI streaming response
        return False, "", "speaking", None

    @classmethod
    def _extract_folder_creation_args(cls, msg_text: str) -> Optional[Tuple[str, str]]:
        """
        Extracts (folder_name, folder_location) preserving original user casing and
        stripping all command noise ('on desktop', 'and name it', 'called', 'named').
        """
        clean_text = msg_text.strip()
        clean_text = re.sub(r"^(?:hey\s+bytex|bytex|please|can\s+you|could\s+you|would\s+you)\s+", "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"[.!?,\"\']+$", "", clean_text).strip()

        if not re.search(r"\b(?:folder|directory)\b", clean_text, flags=re.IGNORECASE):
            return None
        if not re.match(r"^(?:create|make|add|new)\b", clean_text, flags=re.IGNORECASE):
            return None

        # Determine location (desktop, downloads, documents, pictures)
        location = "desktop"
        loc_match = re.search(r"\b(?:in|on|inside|under)\s+(?:my\s+|the\s+)?(desktop|downloads?|documents?|pictures?)\b", clean_text, flags=re.IGNORECASE)
        if loc_match:
            loc_raw = loc_match.group(1).lower()
            if loc_raw in ["download", "downloads"]:
                location = "downloads"
            elif loc_raw in ["document", "documents"]:
                location = "documents"
            elif loc_raw in ["picture", "pictures"]:
                location = "pictures"
            else:
                location = "desktop"

        # Pattern A: "... and name it <Name>" or "... and call it <Name>"
        m_name_it = re.search(r"\b(?:and\s+)?(?:name|call)\s+(?:it\s+)?([a-zA-Z0-9_\-\s]+)$", clean_text, flags=re.IGNORECASE)
        if m_name_it:
            folder_name = m_name_it.group(1).strip()
            folder_name = re.sub(r"^(?:called|named)\s+", "", folder_name, flags=re.IGNORECASE).strip()
            return folder_name, location

        # Pattern B: "... (called|named) <Name> ..."
        m_called = re.search(r"\b(?:called|named)\s+([a-zA-Z0-9_\-]+)", clean_text, flags=re.IGNORECASE)
        if m_called:
            folder_name = m_called.group(1).strip()
            return folder_name, location

        # Pattern C: "create <Name> folder ..."
        m_name_folder = re.search(r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?([a-zA-Z0-9_\-]+)\s+folder\b", clean_text, flags=re.IGNORECASE)
        if m_name_folder:
            folder_name = m_name_folder.group(1).strip()
            if folder_name.lower() not in ["new", "a", "the", "my"]:
                return folder_name, location

        # Pattern D: Fallback strip known command prefix and location clause
        text_no_prefix = re.sub(r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?folder\s*", "", clean_text, flags=re.IGNORECASE).strip()
        text_no_loc = re.sub(r"\b(?:in|on|inside|under)\s+(?:my\s+|the\s+)?(?:desktop|downloads?|documents?|pictures?)\b", "", text_no_prefix, flags=re.IGNORECASE).strip()
        text_clean_name = re.sub(r"^(?:and\s+)?(?:name\s+it|call\s+it|called|named)\s*", "", text_no_loc, flags=re.IGNORECASE).strip()

        if text_clean_name:
            return text_clean_name, location

        return "NewFolder", location

    @classmethod
    def _extract_file_creation_args(cls, msg_text: str) -> Optional[Tuple[str, str]]:
        """
        Extracts (filename, folder_target) from natural file creation requests.
        """
        clean_text = msg_text.strip()
        clean_text = re.sub(r"^(?:hey\s+bytex|bytex|please|can\s+you|could\s+you|would\s+you)\s+", "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"[.!?,\"\']+$", "", clean_text).strip()

        if not re.search(r"\b(?:file|document|text\s+file)\b", clean_text, flags=re.IGNORECASE):
            return None
        if not re.search(r"\b(?:create|make|add|new|generate)\b", clean_text, flags=re.IGNORECASE):
            return None

        # Pattern 1: "(under|in|inside) <folder> [folder/directory] (make|create|add) [another/a/new/a new] file [named/called] [<filename>]"
        m1 = re.match(
            r"^(?:in|on|inside|under)\s+(?:the\s+|my\s+)?(.+?)\s+(?:make|create|add|generate)\s+(?:(?:a|another)\s+(?:new\s+)?|new\s+)?file(?:\s+(?:named|called|\s+)?(.+))?$",
            clean_text,
            flags=re.IGNORECASE
        )
        if m1:
            folder_target = m1.group(1).strip()
            folder_target = re.sub(r"\s+(?:folder|directory)$", "", folder_target, flags=re.IGNORECASE).strip()
            raw_fname = (m1.group(2) or "").strip()
            clean_fname = re.sub(r"^(?:named|called)\s+", "", raw_fname, flags=re.IGNORECASE).strip()
            return clean_fname or "NewFile.txt", folder_target

        # Pattern 2: "(make|create|add) [a/new/another/a new] file [named/called] <filename> (in|on|inside|under) <folder> [folder/directory]"
        m2 = re.match(
            r"^(?:create|make|add)\s+(?:(?:a|another)\s+(?:new\s+)?|new\s+)?file(?:\s+(?:named|called)\s+|\s+)?(.+?)\s+(?:in|on|inside|under)\s+(?:the\s+|my\s+)?(.+?)(?:\s+folder|\s+directory)?$",
            clean_text,
            flags=re.IGNORECASE
        )
        if m2:
            filename_target = m2.group(1).strip()
            folder_target = m2.group(2).strip()
            filename_clean = re.sub(r"^(?:named|called)\s+", "", filename_target, flags=re.IGNORECASE).strip()
            return filename_clean, folder_target

        # Pattern 3: Fallback general file creation
        m3 = re.match(
            r"^(?:create|make|add)\s+(?:(?:a|another)\s+(?:new\s+)?|new\s+)?file(?:\s+(.+?))?(?:\s+(?:in|on|inside|under)\s+(?:the\s+)?(.+))?$",
            clean_text,
            flags=re.IGNORECASE
        )
        if m3:
            raw_fn = (m3.group(1) or "").strip()
            raw_loc = (m3.group(2) or "").strip()
            clean_fn = re.sub(r"^(?:called|named)\s+", "", raw_fn, flags=re.IGNORECASE).strip()

            if not clean_fn and raw_loc:
                clean_fn = "NewFile.txt"
            elif clean_fn and not raw_loc:
                if any(f in clean_fn.lower() for f in ["download", "desktop", "document", "picture"]):
                    raw_loc = clean_fn
                    clean_fn = "NewFile.txt"
                else:
                    raw_loc = "downloads"
            return clean_fn or "NewFile.txt", raw_loc or "downloads"

        return None


command_router = CommandRouter()
