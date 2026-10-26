import json
import logging
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel

logger = logging.getLogger("bytex.risk_classifier")

class RiskLevel(str, Enum):
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    DANGEROUS = "DANGEROUS"
    BLOCKED = "BLOCKED"

class RiskAssessment(BaseModel):
    risk_level: RiskLevel
    requires_confirmation: bool
    reason: str
    is_blocked: bool = False

class ActionRiskClassifier:
    """
    ByteX Action Risk Classifier.
    
    Determines the authoritative minimum risk level and confirmation requirement
    for an action BEFORE execution.
    
    Invariants & Security Rules:
    1. Single Source of Truth: Registered skills are verified against skill_registry.
    2. Non-Overridable: The Agent/LLM/Plan CANNOT lower a skill's assigned risk level.
    3. Block Unknowns: Any unregistered or hallucinated skill is strictly marked BLOCKED.
    4. Zero Tool Execution: Purely analytical inspection; executes no tools or commands.
    5. Zero LLM Overhead: Fast, deterministic rule-based evaluation.
    """

    SAFE_SKILLS = {
        "application_status",
        "system_status",
        "get_system_stats",
        "file_search",
        "search_files",
        "list_files",
        "list_directory",
        "open_application",
        "open_website",
        "browser_control",
        "browser",
        "web_search",
        "search_web",
        "read_webpage",
        "read_page",
        "read_website",
        "fill_form",
        "form_filler",
        "form_filling",
        "research_mode",
        "research",
        "deep_research",
        "investigate",
        "summarize",
        "summarizer",
        "summary",
        "play_media",
        "play_song",
        "play_video",
        "media_player",
        "play",
        "take_screenshot",
        "screenshot",
        "screen_vision",
        "vision",
        "coding_workspace",
        "coding",
        "code_workspace",
        "code",
        "project",
    }

    SENSITIVE_SKILLS = {
        "download_file",
        "website_automation",
        "create_folder",
        "create_file",
        "copy_file",
        "rename_file",
        "move_file",
        "close_application",
        "modify_settings",
    }

    DANGEROUS_SKILLS = {
        "delete_file",
        "delete",
        "shutdown",
        "restart",
        "send_message",
        "risky_test",
        "risky_test_action",
    }

    CODING_EXECUTE_ACTIONS = {"execute_code", "run_code", "compile_and_run", "execute", "run"}
    CODING_BUILD_ACTIONS = {"compile_code", "compile", "build_code", "build"}
    CODING_EDIT_ACTIONS = {"edit_code_file", "edit_file", "modify_code", "edit_code"}
    CODING_FIX_ACTIONS = {"fix_code_error", "fix_error", "fix_code", "auto_fix", "fix"}
    CODING_SAFE_ACTIONS = {
        "create_project", "open_project", "inspect_project", "get_active_workspace", "current_workspace",
        "active_workspace", "get_workspace", "inspect_workspace", "find_file", "locate_file", "find_code_file",
        "search_file", "find", "create_code_file", "read_code_file", "read_file", "read_source_file", "read",
        "project_structure", "detect_language", "generate_code", "explain_code", "explain", "review_code",
        "review", "code_review", "teach_code", "teach", "hint", "give_hint", "analyze_code", "analyze",
        "complexity_analysis", "optimization_analysis", "analyze_complexity", "diagnose_code_error",
        "diagnose_error", "diagnose", "diagnose_code",
    }
    TERMINAL_SAFE_OPERATIONS = {
        "list_files", "list_directory", "print_working_directory", "python_version", "pip_version",
        "node_version", "npm_version", "show_package_scripts", "show_project_metadata",
    }
    VISION_INPUT_ACTIONS = {
        "visual_click", "click", "vision_click", "left_click", "click_coordinates", "click_point",
        "visual_double_click", "double_click", "vision_double_click", "visual_type", "type", "vision_type",
        "type_text", "write", "enter_text", "visual_select", "select", "visual_scroll", "scroll",
        "scroll_down", "scroll_up",
    }
    VISION_READ_ACTIONS = {
        "screen_vision", "analyze_screen", "analyze", "screen_analyze", "describe", "describe_screen",
        "understand_screen", "screen_understanding", "screen_diagnosis", "diagnose_screen", "check_error",
        "read_error", "find_ui_element", "detect_element", "find_element", "locate", "locate_element",
        "detect", "explain_region", "examine_region", "read_section", "read_screen", "read_text", "ocr",
        "find_text", "screen_ocr", "screen_understanding",
    }

    @staticmethod
    def effective_coding_action(args: Dict[str, Any]) -> str:
        """Mirrors CodingWorkspaceSkill.execute(): when no action is given it infers one from the arguments."""
        action = str(args.get("action", "")).strip().lower()
        if not action:
            if "instruction" in args or "target_text" in args:
                action = "edit_code_file"
            elif "file_path" in args or "stdin" in args:
                action = "execute_code"
            elif "prompt" in args or "description" in args:
                action = "generate_code"
            elif "filename" in args:
                action = "create_code_file"
        return action

    @classmethod
    def classify_action(cls, skill_name: str, arguments: Optional[Dict[str, Any]] = None, registry=None) -> RiskAssessment:
        """
        Resolves ``skill_name`` (alias or canonical) with the same argument normalisation the registry
        uses, then classifies the skill's effective behaviour. Unknown skills are BLOCKED.
        """
        if registry is None:
            from skills.registry import skill_registry as registry
        clean_name = (skill_name or "").strip().lower()
        skill, args = registry.normalize_call(clean_name, arguments)
        if not skill:
            return RiskAssessment(
                risk_level=RiskLevel.BLOCKED,
                requires_confirmation=True,
                reason=f"Skill '{skill_name}' is not registered in ByteX Skill Registry. Execution blocked.",
                is_blocked=True
            )
        return cls.assess(skill.name, args)

    @classmethod
    def assess(cls, skill_name: str, arguments: Optional[Dict[str, Any]] = None) -> RiskAssessment:
        """Classifies a CANONICAL skill name with already-normalised arguments. Pure; no registry access."""
        clean_name = (skill_name or "").strip().lower()
        args = arguments or {}

        # 2. Granular File Operations Sub-Classification
        if clean_name == "file_operations":
            operation = str(args.get("operation", "")).strip().lower()
            if operation in ["delete", "delete_file", "remove", "delete_folder"]:
                return RiskAssessment(
                    risk_level=RiskLevel.DANGEROUS,
                    requires_confirmation=True,
                    reason=f"File operation '{operation}' is destructive and permanently modifies filesystem state."
                )
            elif operation in ["rename", "move", "rename_file", "move_file"]:
                return RiskAssessment(
                    risk_level=RiskLevel.SENSITIVE,
                    requires_confirmation=True,
                    reason=f"File operation '{operation}' modifies existing file paths/structures."
                )
            elif operation in ["create_folder", "create_file", "copy", "copy_file", "mkdir"]:
                return RiskAssessment(
                    risk_level=RiskLevel.SENSITIVE,
                    requires_confirmation=False,
                    reason=f"File operation '{operation}' creates or copies resources safely without destructive overwrite."
                )

        # 2b. Coding workspace: classify what the skill will ACTUALLY do (it infers an action when none is given)
        if clean_name == "coding_workspace":
            action = cls.effective_coding_action(args)
            overwrite = bool(args.get("overwrite", False))
            target_fname = args.get("filename") or args.get("file_path") or args.get("name") or "source file"
            if action in cls.CODING_EXECUTE_ACTIONS:
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason=f"Executing source code file '{target_fname}' is a sensitive operation requiring user confirmation.")
            if action in cls.CODING_BUILD_ACTIONS:
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason=f"Compiling/building '{target_fname}' runs external toolchains and requires user confirmation.")
            if action in cls.CODING_EDIT_ACTIONS or (action == "generate_code" and overwrite):
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason=f"Modifying/replacing existing source code file '{target_fname}' requires user confirmation.")
            if action in cls.CODING_FIX_ACTIONS:
                fix_mode = str(args.get("fix_mode", "automatic")).strip().lower()
                req_conf = bool(args.get("require_confirmation", False))
                is_conf_required = req_conf or (fix_mode == "confirm")
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=is_conf_required,
                                      reason=f"Fixing code error in '{target_fname}' is a sensitive operation{' requiring user confirmation' if is_conf_required else ' with automated verification'}.")
            if action in cls.CODING_SAFE_ACTIONS:
                return RiskAssessment(risk_level=RiskLevel.SAFE, requires_confirmation=False,
                                      reason=f"Coding workspace operation '{action}' performs safe diagnosis, explanation, generation, inspection, creation, or analysis.")
            return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                  reason=f"Coding workspace operation '{action or 'unspecified'}' is not on the reviewed safe list and requires confirmation.")

        # 2c. Controlled terminal agent: only reviewed read-only operations are SAFE
        if clean_name == "terminal_agent":
            op = str(args.get("operation") or args.get("action", "")).strip().lower()
            raw_arg_str = json.dumps(args, default=str)
            if any(k in raw_arg_str for k in ["&&", "||", ";", "|", "`", "$(", "%COMSPEC%", "powershell", "cmd.exe", "del ", "rm ", "format "]):
                return RiskAssessment(risk_level=RiskLevel.BLOCKED, requires_confirmation=True, is_blocked=True,
                                      reason="Command contains forbidden shell metacharacters or unsafe system command syntax.")
            if op in cls.TERMINAL_SAFE_OPERATIONS:
                return RiskAssessment(risk_level=RiskLevel.SAFE, requires_confirmation=False,
                                      reason=f"Terminal operation '{op}' performs safe inspection and version queries.")
            return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                  reason=f"Terminal operation '{op or 'unspecified'}' can install, build, run scripts or start processes, requiring confirmation.")

        # 2d. Screen vision: classify the effective behaviour (x/y, text or a click request make it an input action)
        if clean_name == "screen_vision":
            action = str(args.get("action") or "").strip().lower()
            raw_text = str(args.get("raw_text") or "").strip().lower()
            target_str = str(args.get("target") or args.get("element") or args.get("raw_text") or "").strip().lower()
            performs_input = (
                action in cls.VISION_INPUT_ACTIONS
                or args.get("x") is not None or args.get("y") is not None
                or bool(args.get("text"))
                or raw_text.startswith("click")
            )
            destructive_keywords = ["delete", "remove", "uninstall", "format", "shutdown", "erase", "drop", "destroy", "purge", "close without saving"]
            if performs_input and any(k in target_str for k in destructive_keywords):
                return RiskAssessment(risk_level=RiskLevel.DANGEROUS, requires_confirmation=True,
                                      reason=f"Visual UI action '{action}' on destructive target '{target_str}' requires explicit user confirmation.")
            if performs_input:
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason=f"Visual UI interaction '{action or 'input'}' sends physical input to the focused window and requires confirmation.")
            if action in cls.VISION_READ_ACTIONS or not action:
                return RiskAssessment(risk_level=RiskLevel.SAFE, requires_confirmation=False,
                                      reason=f"Screen vision operation '{action or 'analyze'}' performs read-only visual analysis, OCR, or element detection.")
            return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                  reason=f"Screen vision operation '{action}' is not on the reviewed read-only list and requires confirmation.")

        # 2e. Browser control: page clicks act inside the user's browser session
        if clean_name == "browser_control":
            action = str(args.get("action") or "").strip().lower()
            if action in ("click",):
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason="Clicking inside a web page acts in the user's browser session and requires confirmation.")

        # 2f. Opening an application by path/URL-like value can launch arbitrary files
        if clean_name == "open_application":
            path_like = [v for v in args.values() if isinstance(v, str) and ("/" in v or "\\" in v or v.lower().endswith((".app", ".exe", ".sh", ".command", ".bat", ".py", ".dmg", ".pkg")))]
            if path_like:
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason="Opening an application or file by path can launch arbitrary programs and requires confirmation.")

        # 2g. SMART LIFE: reads are SAFE; a valid change always needs the user's approval; an invalid or ambiguous
        #     request changes nothing (the skill answers with a question or an error), so it needs no approval.
        if clean_name == "smart_life":
            from smartlife.service import READ_ACTIONS, WRITE_ACTIONS
            action = str(args.get("action", "")).strip().lower()
            if action in READ_ACTIONS:
                return RiskAssessment(risk_level=RiskLevel.SAFE, requires_confirmation=False,
                                      reason=f"SMART LIFE '{action}' only reads the user's own reminders.")
            if action in WRITE_ACTIONS:
                from smartlife.service import default_service
                try:
                    valid = bool(default_service().plan(action, args).ok)
                except Exception:
                    valid = True  # cannot tell: fail closed and ask
                if not valid:
                    return RiskAssessment(risk_level=RiskLevel.SAFE, requires_confirmation=False,
                                          reason="SMART LIFE needs more information or the request is invalid; nothing will be changed.")
            if action == "delete":
                return RiskAssessment(risk_level=RiskLevel.DANGEROUS, requires_confirmation=True,
                                      reason="Permanently deleting a SMART LIFE item cannot be undone.")
            if action in WRITE_ACTIONS:
                return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                      reason=f"SMART LIFE '{action}' changes the user's saved reminders and needs approval.")
            return RiskAssessment(risk_level=RiskLevel.SENSITIVE, requires_confirmation=True,
                                  reason="Unknown SMART LIFE action; approval required.")

        # 3. Direct Dangerous Classification
        if clean_name in cls.DANGEROUS_SKILLS:
            return RiskAssessment(
                risk_level=RiskLevel.DANGEROUS,
                requires_confirmation=True,
                reason=f"Skill '{clean_name}' performs destructive or externally consequential actions."
            )

        # 4. Direct Sensitive Classification
        if clean_name in cls.SENSITIVE_SKILLS:
            return RiskAssessment(
                risk_level=RiskLevel.SENSITIVE,
                requires_confirmation=True,
                reason=f"Skill '{clean_name}' modifies application state or user file metadata."
            )

        # 5. Direct Safe Classification
        if clean_name in cls.SAFE_SKILLS:
            return RiskAssessment(
                risk_level=RiskLevel.SAFE,
                requires_confirmation=False,
                reason=f"Skill '{clean_name}' performs read-only inspection or safe resource creation."
            )

        # 6. Default Fallback for custom registered tools (Conservative Sensitive Default)
        return RiskAssessment(
            risk_level=RiskLevel.SENSITIVE,
            requires_confirmation=True,
            reason=f"Skill '{clean_name}' requires confirmation under conservative safety policy."
        )

risk_classifier = ActionRiskClassifier()
