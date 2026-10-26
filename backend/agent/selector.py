import re
import time
import logging
from typing import Dict, Any, List, Optional
from skills.registry import skill_registry

logger = logging.getLogger("bytex.agent.selector")

class ByteXSkillSelector:
    """
    Dynamic Skill Selection Engine for ByteX Agent.
    
    Identifies and selects appropriate skills from the existing registered ByteX
    Skill Registry based on the user's goal.
    
    Invariants & Security Constraints:
    1. Single Source of Truth: Validates all selected skills directly against skill_registry.
    2. Never Invents Skills: Rejects all unregistered or hallucinated capabilities.
    3. Zero Tool Execution: Performs purely static/analytical skill selection.
    4. Zero LLM Overhead: Fast, deterministic goal-to-capability matching.
    """

    @classmethod
    def select_skills_for_goal(cls, goal: str) -> Dict[str, Any]:
        """
        Analyzes the goal and selects matching registered skills.
        Returns a structured selection payload.
        """
        clean_goal = goal.strip()
        goal_lower = clean_goal.lower()
        selected: List[str] = []
        unsupported: List[str] = []

        # Get all registered skill names from single source of truth
        registered_skills = set(skill_registry.list_skills().keys())

        # 1. System Status / Telemetry
        if any(kw in goal_lower for kw in [
            "check my computer", "system status", "computer status",
            "cpu and ram", "cpu", "ram", "battery", "pc status", "check system",
            "check my system", "prepare my computer"
        ]):
            if "system_status" in registered_skills and "system_status" not in selected:
                selected.append("system_status")

        # 2. File Operations (Create folder/file, rename, move, copy, delete)
        if any(kw in goal_lower for kw in [
            "create folder", "create a folder", "make folder", "make a folder",
            "create directory", "make directory", "create file", "make file",
            "rename", "move", "copy"
        ]) or re.search(r"\b(?:folder|directory)\s+called\b", goal_lower) or re.search(r"\b(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?([a-zA-Z0-9_\-]+)\s*(?:folder|directory)?\b", goal_lower):
            if "file_operations" in registered_skills and "file_operations" not in selected:
                selected.append("file_operations")

        # 3. File Search
        if any(kw in goal_lower for kw in [
            "find my", "search for", "search files", "locate file",
            "find file", "find the file", "where is my"
        ]) or re.search(r"\b(?:find|search(?:\s+for)?|locate)\s+(?:my\s+)?([a-zA-Z0-9_\-]+)\b", goal_lower):
            if "file_search" in registered_skills and "file_search" not in selected:
                selected.append("file_search")

        # Detect if request is related to code, coding files, or coding workspace
        is_code_request = (
            bool(re.search(r"\.(?:cpp|cc|cxx|py|pyw|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|sql)\b", goal_lower))
            or any(kw in goal_lower for kw in [
                "coding workspace", "create project", "python project", "c++ project", "javascript project",
                "open project", "project structure", "detect language", "read code", "edit code", "generate code",
                "write a c++", "write a python", "write a javascript", "write merge sort", "write binary search",
                "print prime numbers", "execute code", "compile and run", "run the program", "run code", "run it",
                "compile", "build", "compile only", "build only", "compile the", "build the", "compile this", "build this",
                "explain code", "explain the code", "line by line", "time and space complexity", "explain the algorithm",
                "explain like a beginner", "optimize", "optimise", "optimization", "code review", "diagnose", "diagnose error",
                "verify the output", "verify output", "to verify the output", "and verify the output",
                "this file", "current file", "active file", "read this file", "explain this file", "tell me what this file does"
            ])
            or bool(re.search(r"\b(?:create|write|run|execute|compile|build|explain|optimize|optimise|modify|edit|update|refactor|fix|check|review|teach|read|inspect)\s+(?:this\s+file|current\s+file|active\s+file|[a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json))\b", goal_lower))
        )

        # 4. Application Launch (Chrome, Notepad, Calc, Spotify, etc.)
        if not is_code_request and any(kw in goal_lower for kw in ["open", "launch", "start", "run"]):
            if "open_application" in registered_skills and "open_application" not in selected:
                selected.append("open_application")

        # 4b. Application Close (Chrome, Notepad, Calc, Spotify, etc.)
        if any(kw in goal_lower for kw in ["close", "quit", "exit", "stop", "kill"]):
            if "close_application" in registered_skills and "close_application" not in selected:
                selected.append("close_application")

        # 5. Screenshot
        if any(kw in goal_lower for kw in ["take a screenshot", "screenshot", "capture screen"]):
            if "take_screenshot" in registered_skills and "take_screenshot" not in selected:
                selected.append("take_screenshot")

        # 6. Browser Control / Web Browsing
        if not is_code_request and (any(kw in goal_lower for kw in ["open website", "browse to", "go to http", "open url", "go to", "navigate to", "take me to"]) or any(site in goal_lower for site in ["youtube", "github", "google.com", "openai"])):
            if any(k in goal_lower for k in ["go to", "navigate to", "open website", "youtube", "github", "openai", "http", ".com"]):
                if "browser_control" in registered_skills and "browser_control" not in selected:
                    selected.append("browser_control")

        # 6b. Web Search
        if not is_code_request and (any(kw in goal_lower for kw in [
            "search the web", "search web", "search online", "search internet",
            "google", "look up online", "search for the latest", "search for latest",
            "find the official website", "find official website"
        ]) or (re.search(r"\bsearch\s+(?:the\s+web\s+)?for\b", goal_lower) and not any(k in goal_lower for k in ["files", "folder", "directory"]))):
            if "web_search" in registered_skills and "web_search" not in selected:
                selected.append("web_search")

        # 6c. Read Webpages (#33)
        if not is_code_request and (
            any(kw in goal_lower for kw in ["read the page", "read page", "read webpage", "read this page", "read the homepage", "read website", "extract page", "what does this page say", "tell me what this page contains"])
            or bool(re.search(r"\bread\s+(?:https?://|[a-zA-Z0-9_\-.]+\.(?:com|org|net|io|dev|edu|gov))", goal_lower))
        ):
            if "read_webpage" in registered_skills and "read_webpage" not in selected:
                selected.append("read_webpage")

        # 6d. Form Filling (#34)
        if any(kw in goal_lower for kw in ["fill form", "fill the form", "fill my name", "fill email", "enter my email", "enter name", "tick the checkbox", "fill contact form", "fill this form", "fill name"]) or (re.search(r"\bfill\s+(?:the\s+|my\s+)?[a-zA-Z0-9_\-]+\b", goal_lower)):
            if "fill_form" in registered_skills and "fill_form" not in selected:
                selected.append("fill_form")

        # 6e. Download Management (#35)
        if any(kw in goal_lower for kw in ["download the pdf", "download file", "download pdf", "download it", "download from this page", "save the pdf", "save it in my documents", "download it to desktop", "download"]) and not any(k in goal_lower for k in ["overclock", "hack", "gpu"]):
            if "download_file" in registered_skills and "download_file" not in selected:
                selected.append("download_file")

        # 6f. Website Automation (#36)
        if any(kw in goal_lower for kw in ["automate website", "website automation", "search for react", "search for c++", "open github and search", "open google and search"]) or re.match(r"^(?:buy\s+this|purchase\s+this)\b", goal_lower):
            if "website_automation" in registered_skills and "website_automation" not in selected:
                selected.append("website_automation")

        # 6g. Research Mode (#37)
        if any(kw in goal_lower for kw in ["research the", "research", "deep research", "investigate the", "investigate", "compare react and vue", "compare"]) and not any(k in goal_lower for k in ["overclock", "hack", "gpu"]):
            if "research_mode" in registered_skills and "research_mode" not in selected:
                selected.append("research_mode")

        # 6h. Summarization (#38)
        if any(kw in goal_lower for kw in ["summarize", "summary", "key takeaways", "explain this simply", "explain like i'm a beginner"]):
            if "summarize" in registered_skills and "summarize" not in selected:
                selected.append("summarize")

        # 6i. Media Playback (YouTube / Songs)
        if re.search(r"\b(?:play|stream|listen\s+to)\b", goal_lower) and not any(kw in goal_lower for kw in ["game", "football", "cricket"]):
            if "play_media" in registered_skills and "play_media" not in selected:
                selected.append("play_media")

        # 6j. Coding Workspace (#33.1, #33.2, #33.3)
        if is_code_request or re.search(r"\b(?:project\s+called|project\s+named)\b", goal_lower):
            if "coding_workspace" in registered_skills and "coding_workspace" not in selected:
                selected.append("coding_workspace")

        # 7. Check for unfulfillable / unsupported requests
        if any(kw in goal_lower for kw in ["overclock", "boost fps", "hack", "mine crypto", "clean dust", "install gpu"]):
            unsupported.append("hardware_manipulation_unsupported")

        # Final Verification: Ensure EVERY selected skill is valid in registry
        verified_selected = [s for s in selected if skill_registry.get_skill(s) is not None]

        print(f"[ByteX SkillSelector] Goal: '{clean_goal}' -> Selected Skills: {verified_selected}")
        return {
            "goal": clean_goal,
            "selected_skills": verified_selected,
            "unsupported_intents": unsupported,
            "timestamp": time.time()
        }

skill_selector = ByteXSkillSelector()
