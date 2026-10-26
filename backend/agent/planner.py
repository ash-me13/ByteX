import re
import logging
from typing import Dict, Any, List, Optional
from agent.models import AgentPlan, PlanStep, StepState
from agent.selector import ByteXSkillSelector
from skills.registry import skill_registry

logger = logging.getLogger("bytex.agent.planner")

MAX_PLAN_STEPS = 5

class ByteXPlanner:
    """
    Dynamic Plan Generation Engine for ByteX Agent.
    
    Receives a MULTI_STEP user goal, queries Dynamic Skill Selection,
    and deterministically constructs a structured AgentPlan using ONLY
    validated registered ByteX skills.
    
    Security & Structural Invariants:
    1. Zero Tool Execution: The planner ONLY produces data structures and never runs tools.
    2. Zero Skill Invention: Strictly bounded to skills provided by ByteXSkillSelector.
    3. Structured Arguments Only: No raw shell commands, CMD, PowerShell, or arbitrary code.
    4. Bounded Length: Plans are capped at MAX_PLAN_STEPS (5) to prevent infinite plans.
    5. Confirmation Enforcement: Automatically flags destructive/risky skills for confirmation.
    """

    MAX_STEPS = MAX_PLAN_STEPS

    @classmethod
    async def create_plan(cls, goal: str, relevant_memory: Optional[List[str]] = None) -> Optional[AgentPlan]:
        """Async alias for generate_plan."""
        return cls.generate_plan(goal, relevant_memory)

    @classmethod
    def generate_plan(cls, goal: str, relevant_memory: Optional[List[str]] = None) -> Optional[AgentPlan]:
        """
        Dynamically constructs an AgentPlan for a user goal using registered ByteX skills and
        optional read-only persistent memory context.
        Returns None if no registered skills apply or goal is unfulfillable.
        """
        clean_goal = goal.strip()
        # Clean schedule / routine creation prefixes if present
        clean_goal = re.sub(r"^(?:create|make|build|add|define|set\s+up)\s+(?:an?\s+)?(?:new\s+)?(?:automation|workflow|routine)\s+(?:called|named|that|to)?\s*", "", clean_goal, flags=re.IGNORECASE).strip()
        clean_goal = re.sub(r"^(?:every\s+(?:day|morning|evening|weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|whenever\s+i\s+say|when\s+i\s+start\s+bytex|at\s+startup)[,\s]*", "", clean_goal, flags=re.IGNORECASE).strip()
        goal_lower = clean_goal.lower()

        # Atomic Code Execution / Compilation Goal
        from core.command_router import CommandRouter
        cand_target = CommandRouter._extract_target_file(clean_goal)
        if cand_target and any(kw in goal_lower for kw in ["compile", "run", "execute", "build"]):
            m_atomic_code = re.match(
                r"^(?:compile\s+and\s+run|compile\s+and\s+execute|compile\s+and\s+verify|build\s+and\s+run|run|execute|compile|build)\b",
                clean_goal,
                flags=re.IGNORECASE
            )
            if m_atomic_code and not any(kw in goal_lower for kw in ["diagnose", "fix", "repair", "correct", "explain", "review", "open"]):
                is_compile_only = any(kw in goal_lower for kw in [
                    "don't run", "dont run", "do not run", "without running",
                    "don't execute", "dont execute", "do not execute", "without executing",
                    "compile only", "build only", "only compile", "only build", "compile-only", "build-only"
                ]) or (clean_goal.lower().startswith(("compile", "build")) and not any(kw in goal_lower for kw in ["and run", "and execute", "then run", "then execute", "& run", "+ run", "to verify", "and verify"]))
                act = "compile_code" if is_compile_only else "execute_code"
                desc = f"Compile source file '{cand_target}'" if is_compile_only else f"Compile and execute source file '{cand_target}'"
                step = PlanStep(
                    step_id=1,
                    description=desc,
                    suggested_skill="coding_workspace",
                    arguments={"action": act, "filename": cand_target, "prompt": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
                return AgentPlan(goal=clean_goal, steps=[step])

        # Compound Code Fix + Execution Workflow
        # E.g. "Fix the compilation error in 03_buggy.cpp. Preserve the existing code and make only the necessary change. Then compile and run it, and show me the output."
        if cand_target and any(kw in goal_lower for kw in ["fix", "repair", "correct"]) and any(kw in goal_lower for kw in ["compile", "run", "execute"]):
            m_fix_kw = re.search(r"\b(?:fix|repair|correct)\b", goal_lower)
            m_exec_kw = re.search(r"\b(?:compile|run|execute|build)\b", goal_lower)
            if m_fix_kw and m_exec_kw and m_fix_kw.start() < m_exec_kw.start():
                step1 = PlanStep(
                    step_id=1,
                    description=f"Fix code error in '{cand_target}'",
                    suggested_skill="coding_workspace",
                    arguments={"action": "fix_code_error", "filename": cand_target, "file_path": cand_target, "fix_mode": "automatic", "prompt": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
                step2 = PlanStep(
                    step_id=2,
                    description=f"Compile and execute source file '{cand_target}'",
                    suggested_skill="coding_workspace",
                    arguments={"action": "execute_code", "filename": cand_target, "file_path": cand_target, "compile": True, "prompt": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
                return AgentPlan(goal=clean_goal, steps=[step1, step2])

        # 0. Sequential Compound Command Decomposition
        # E.g. "Open Notepad, type hello, and save it.", "Open Notepad and type Hello ByteX."
        if any(sep in goal_lower for sep in [",", " and then ", " then ", " and "]):
            parts = re.split(r',\s*(?:and\s+|then\s+)?|\s+and\s+then\s+|\s+then\s+|\s+and\s+(?!(?:run|execute)\b)', clean_goal, flags=re.IGNORECASE)
            parts = [p.strip().rstrip('.!?') for p in parts if p.strip().rstrip('.!?')]
            if len(parts) >= 2:
                seq_steps = []
                for idx, clause in enumerate(parts, 1):
                    if idx > cls.MAX_STEPS:
                        break
                    
                    # 0a. Open Project (Feature #33.1)
                    m_p_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?(?:project\s+called|project\s+named|project)\s+([a-zA-Z0-9_\-]+)$", clause, flags=re.IGNORECASE)
                    if not m_p_open_proj:
                        m_p_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-]+)\s+project$", clause, flags=re.IGNORECASE)
                    if m_p_open_proj:
                        p_name = m_p_open_proj.group(1).strip()
                        if p_name.lower() not in ["my", "the", "a", "this"]:
                            seq_steps.append(
                                PlanStep(
                                    step_id=idx,
                                    description=f"Open project '{p_name}'",
                                    suggested_skill="coding_workspace",
                                    arguments={"action": "open_project", "project_name": p_name},
                                    requires_confirmation=False,
                                    status=StepState.PENDING,
                                    max_replans=1
                                )
                            )
                            continue

                    # 0b. Create Code File (Feature #33.1)
                    m_p_code_file = re.match(r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?(?:code\s+|source\s+)?file\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)$", clause, flags=re.IGNORECASE)
                    if not m_p_code_file:
                        m_p_code_file = re.match(r"^(?:create|make)\s+([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))$", clause, flags=re.IGNORECASE)
                    if m_p_code_file:
                        fname = m_p_code_file.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Create source file '{fname}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "create_code_file", "filename": fname},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0b2. Code File Modification / Edit (Coding Workspace 2.0)
                    m_p_modify = re.match(
                        r"^(?:modify|update|edit|alter|rewrite|change|optimize|optimise)\s+(?:my\s+|the\s+|this\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))\s*(?:to|for|with|so\s+that|:|,\s*)?\s*(.+)$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if not m_p_modify:
                        m_p_modify = re.match(
                            r"^(?:modify|update|edit|alter|rewrite|change|optimize|optimise)\s+(?:it\s+to|it\s+with|it\s+so\s+that|it)?\s*(.+)$",
                            clause,
                            flags=re.IGNORECASE
                        )
                    if m_p_modify:
                        if len(m_p_modify.groups()) == 2 and m_p_modify.group(2):
                            fname = m_p_modify.group(1).strip()
                            instr = m_p_modify.group(2).strip()
                        else:
                            fname = None
                            instr = m_p_modify.group(1).strip()
                        args_dict = {"action": "edit_code_file", "instruction": instr, "prompt": clause}
                        if fname:
                            args_dict["filename"] = fname
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Modify code file{' ' + fname if fname else ''}",
                                suggested_skill="coding_workspace",
                                arguments=args_dict,
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0c. Code Generation (Feature #33.2)
                    m_p_gen_code = re.match(
                        r"^(?:write|create|implement|code|generate|build)\s+(?:a\s+|an\s+)?(?:([a-zA-Z0-9_\+\#]+)\s+)?(?:program|script|solution|function|code|app)?\s*(?:to|for|that|which)?\s*(.+)$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if not m_p_gen_code:
                        m_p_gen_code = re.match(r"^print\s+(?:all\s+)?(?:prime\s+numbers|primes|fibonacci|even\s+numbers|odd\s+numbers)(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_gen_code and not any(k in clause.lower() for k in ["automation", "routine", "workflow", "browser tab", "tab", "project called", "project named"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Generate code for '{clause}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "generate_code", "prompt": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0d. Code Execution (Feature #33.3)
                    m_p_code_exec = re.match(
                        r"^(?:compile\s+and\s+run\s+it|compile\s+and\s+run|compile\s+it|run\s+it|execute\s+it|show\s+me\s+the\s+output|run\s+the\s+program|execute\s+the\s+program|compile\s+and\s+execute|run\s+it\s+(?:and|to)\s+verify(?:\s+the\s+output)?|run\s+(?:and|to)\s+verify(?:\s+the\s+output)?|verify\s+the\s+output|run\s+it\s+with\s+(?:input\s+)?(.+)|run\s+with\s+(?:input\s+)?(.+)|run\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)(?:\s+(?:and|to)\s+verify(?:\s+the\s+output)?)?(?:\s+with\s+input\s+(.+))?)$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if m_p_code_exec:
                        if clause.lower().strip() in ["show me the output", "show the output", "show me output", "show output", "verify the output"]:
                            if seq_steps and seq_steps[-1].suggested_skill == "coding_workspace" and seq_steps[-1].arguments.get("action") in ["execute_code", "compile_code", "fix_code_error"]:
                                continue
                        fname = m_p_code_exec.group(3) if (len(m_p_code_exec.groups()) >= 3 and m_p_code_exec.group(3)) else (cand_target or None)
                        stdin_val = m_p_code_exec.group(1) or m_p_code_exec.group(2) or (m_p_code_exec.group(4) if len(m_p_code_exec.groups()) >= 4 else None)
                        if stdin_val:
                            stdin_val = stdin_val.strip().strip("'\"")
                        exec_args = {"action": "execute_code"}
                        if fname:
                            exec_args["filename"] = fname
                            exec_args["file_path"] = fname
                        if stdin_val:
                            exec_args["stdin"] = stdin_val
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Execute program{' ' + fname if fname else ''}{' with input ' + str(stdin_val) if stdin_val else ''}",
                                suggested_skill="coding_workspace",
                                arguments=exec_args,
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0e. Code Explanation (Feature #33.3)
                    m_p_code_exp = re.match(
                        r"^(?:explain\s+it|explain\s+the\s+code|explain\s+the\s+program|explain\s+it\s+line\s+by\s+line|explain\s+line\s+by\s+line|explain\s+the\s+algorithm|give\s+(?:the\s+)?time\s+and\s+space\s+complexity|give\s+(?:the\s+)?complexity|explain\s+(?:this\s+|it\s+)?like\s+a\s+beginner|explain\s+it\s+for\s+an\s+interview|explain\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if m_p_code_exp:
                        cl_lower = clause.lower()
                        mode = "normal"
                        if "line by line" in cl_lower:
                            mode = "line_by_line"
                        elif "beginner" in cl_lower:
                            mode = "beginner"
                        elif "complexity" in cl_lower:
                            mode = "complexity"
                        elif "algorithm" in cl_lower:
                            mode = "algorithm"
                        elif "interview" in cl_lower:
                            mode = "interview"
                        
                        fname = m_p_code_exp.group(1) if (m_p_code_exp.group(1) and "." in m_p_code_exp.group(1)) else None
                        exp_args = {"action": "explain_code", "mode": mode}
                        if fname:
                            exp_args["filename"] = fname
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Explain code ({mode} mode){' for ' + fname if fname else ''}",
                                suggested_skill="coding_workspace",
                                arguments=exp_args,
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0f. Code Error Diagnosis (Feature #33.4)
                    m_p_code_diag = re.match(
                        r"^(?:diagnose\s+(?:the\s+)?(?:compiler\s+|runtime\s+)?(?:error|errors)?|diagnose\s+any\s+errors|diagnose\s+it|diagnose|explain\s+(?:the\s+|this\s+)?(?:compiler\s+|runtime\s+)?error|tell\s+me\s+how\s+to\s+fix\s+it|how\s+to\s+fix\s+it|why\s+did\s+it\s+fail|what\s+went\s+wrong|what(?:'s|\s+is)\s+wrong(?:\s+with\s+it)?|diagnose\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))[\.\?]*$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if m_p_code_diag:
                        fname = m_p_code_diag.group(1) if (len(m_p_code_diag.groups()) >= 1 and m_p_code_diag.group(1) and "." in m_p_code_diag.group(1)) else None
                        diag_args = {"action": "diagnose_code_error"}
                        if fname:
                            diag_args["filename"] = fname
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Diagnose code error{' for ' + fname if fname else ''}",
                                suggested_skill="coding_workspace",
                                arguments=diag_args,
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0g. Code Error Fixing (Feature #33.5)
                    m_p_code_fix = re.match(
                        r"^(?:fix|repair|correct)\s+(?:the\s+)?(?:compilation\s+|compiler\s+|runtime\s+|syntax\s+)?(?:error|errors|bug|bugs|mistake|mistakes)?(?:\s+(?:in|for|of)\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))?.*$|^(?:fix\s+it|fix\s+my\s+code|automatically\s+fix\s+it|fix\s+any\s+errors|repair\s+it|correct\s+the\s+error|fix\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+))[\.\?]*$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if m_p_code_fix:
                        fname = (m_p_code_fix.group(1) or (m_p_code_fix.group(2) if len(m_p_code_fix.groups()) >= 2 else None) or cand_target)
                        if fname and "." not in fname:
                            fname = cand_target
                        fix_args = {"action": "fix_code_error", "fix_mode": "automatic", "prompt": clause}
                        if fname:
                            fix_args["filename"] = fname
                            fix_args["file_path"] = fname
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Fix code error{' for ' + fname if fname else ''}",
                                suggested_skill="coding_workspace",
                                arguments=fix_args,
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0h. Controlled Terminal Agent Operations (Feature #33.6)
                    clause_lower = clause.lower().strip()
                    if any(clause_lower.startswith(k) or clause_lower == k for k in ["show files", "show me its files", "show me the files", "list files", "list directory"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="List project files",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "list_files"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if any(k in clause_lower for k in ["install dependencies", "install project dependencies", "run npm install", "npm install", "install npm dependencies"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Install project dependencies",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "npm_install"},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if any(k in clause_lower for k in ["create a python virtual environment", "create a python environment", "create virtual environment", "create a virtual environment", "create venv"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Create Python virtual environment",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "create_virtual_environment"},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if any(k in clause_lower for k in ["run pytest", "pytest", "run python tests"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Run pytest",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "run_pytest"},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if any(k in clause_lower for k in ["run the tests", "run my tests", "run project tests", "run tests"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Run project tests",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "run_project_tests"},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if any(k in clause_lower for k in ["build the project", "build project"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Build project",
                                suggested_skill="terminal_agent",
                                arguments={"action": "terminal_command", "operation": "build_project"},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0i. Visual UI Grounding & Detection (Feature #34)
                    m_p_find_elem = re.match(r"^(?:find|locate|where\s+is)\s+(?:the\s+)?(.+?)[.!?]*$", clause, flags=re.IGNORECASE)
                    if m_p_find_elem and not any(kw in clause.lower() for kw in ["file", "folder", "directory", "script", "news about", "recent news"]):
                        target_elem = m_p_find_elem.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Locate UI element '{target_elem}' on screen",
                                suggested_skill="screen_vision",
                                arguments={"action": "find_ui_element", "target": target_elem, "raw_text": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 0j. Visual Screen Understanding / Summary
                    if clause.lower() in ["tell me what happened", "describe the screen", "analyze the screen", "what is on screen", "inspect screen"]:
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Analyze resulting screen state",
                                suggested_skill="screen_vision",
                                arguments={"action": "analyze_screen", "question": clause, "raw_text": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 1. Open Application
                    m_open = re.match(r"^(?:open|launch|start|run)\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_open and not any(kw in clause.lower() for kw in [
                        "first result", "second result", "third result", "top result", "result 1", "result 2", "result 3",
                        "the result", "open result", "project", "verify", "output", "it to", "it and", "program", "code",
                        ".cpp", ".py", ".c", ".js", ".ts", ".html", "save the file", "save it"
                    ]):
                        app_name = m_open.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Launch {app_name.capitalize()} on interactive desktop",
                                suggested_skill="open_application",
                                arguments={"application": app_name},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 2. Vision Typing
                    m_type = re.match(r"^(?:type|write|enter|input)\s+(.+?)(?:\s+(?:in|into|on)\s+(?:the\s+)?(.+))?$", clause, flags=re.IGNORECASE)
                    if m_type:
                        text_val = m_type.group(1).strip().strip('"\'')
                        target_val = m_type.group(2).strip().strip('"\'') if m_type.group(2) else None
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Type '{text_val}' into {'the ' + target_val if target_val else 'active input area'}",
                                suggested_skill="screen_vision",
                                arguments={"action": "visual_type", "text": text_val, "target": target_val, "raw_text": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 3. Vision Clicking / Save
                    m_save_file = re.match(r"^save\s+(?:it\s+)?(?:as\s+)?([a-zA-Z0-9_\-\.]+)(?:\s+(?:in|on|inside|to)\s+(?:the\s+)?(.+))?$", clause, flags=re.IGNORECASE)
                    if m_save_file:
                        fname = m_save_file.group(1).strip()
                        floc = (m_save_file.group(2) or "desktop").strip()
                        prev_text = ""
                        for s in seq_steps:
                            if s.suggested_skill == "screen_vision" and s.arguments.get("action") == "type":
                                prev_text = s.arguments.get("text", "")
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Save document as '{fname}' on {floc}",
                                suggested_skill="file_operations",
                                arguments={
                                    "operation": "create_file",
                                    "filename": fname,
                                    "folder": floc,
                                    "content": prev_text
                                },
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if clause.lower() in ["save it", "save", "save file", "save document", "click save", "press save", "save the file"]:
                        if any(s.suggested_skill == "coding_workspace" for s in seq_steps):
                            continue
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Initiate Save on the active document",
                                suggested_skill="screen_vision",
                                arguments={"action": "click", "target": "Save", "raw_text": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    m_click = re.match(r"^(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(.+)$", clause, flags=re.IGNORECASE)
                    if m_click:
                        target_val = m_click.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Click '{target_val}' on screen",
                                suggested_skill="screen_vision",
                                arguments={"action": "click", "target": target_val, "raw_text": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 4. Close Application
                    m_close = re.match(r"^(?:close|quit|exit|stop|kill)\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_close:
                        app_name = m_close.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Close {app_name.capitalize()}",
                                suggested_skill="close_application",
                                arguments={"application": app_name},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 5. Web Search
                    m_search = re.match(r"^(?:search\s+(?:the\s+)?(?:web|internet|online)?\s*(?:for\s+)?|google\s+(?:for\s+)?|find\s+(?:news\s+about|recent\s+news\s+about)?)(.+)$", clause, flags=re.IGNORECASE)
                    if m_search and not any(kw in clause.lower() for kw in ["first result", "open result", "summarize"]):
                        q = m_search.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Search web for '{q}'",
                                suggested_skill="web_search",
                                arguments={"query": q},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 6. Direct Navigation (e.g. "go to Google", "go to YouTube")
                    m_nav = re.match(r"^(?:go\s+to|navigate\s+to|visit)\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_nav:
                        dest = m_nav.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Navigate to {dest.capitalize()}",
                                suggested_skill="browser_control",
                                arguments={"action": "navigate", "url": dest},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 7. Open Search Result / Browser Navigation
                    m_open_res = re.match(r"^(?:open|click|view|select)\s+(?:the\s+)?(first|second|third|fourth|fifth|top|\d+(?:st|nd|rd|th)?)\s+(?:result|one|link)$", clause, flags=re.IGNORECASE)
                    if m_open_res:
                        ord_word = m_open_res.group(1).lower()
                        ord_idx = {"first": 1, "top": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}.get(ord_word, 1)
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Open search result #{ord_idx}",
                                suggested_skill="browser_control",
                                arguments={"action": "navigate", "target": f"result_{ord_idx}"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 8. Browser Back / Forward / New Tab / Close Tab
                    if clause.lower() in ["go back", "go back one page", "back"]:
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Navigate back to previous page",
                                suggested_skill="browser_control",
                                arguments={"action": "back"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue
                    m_plan_new_tab_url = re.match(r"^(?:open|navigate\s+to|go\s+to|visit|launch)\s+(.+?)\s+in\s+(?:a\s+)?new\s+(?:browser\s+)?tab$", clause, flags=re.IGNORECASE)
                    if m_plan_new_tab_url:
                        dest = m_plan_new_tab_url.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Open {dest} in a new tab",
                                suggested_skill="browser_control",
                                arguments={"action": "new_tab", "url": dest},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    if (
                        re.match(r"^(?:open|create|make|launch|start)?\s*(?:a\s+)?new\s+(?:browser\s+)?tab$", clause, flags=re.IGNORECASE)
                        or re.match(r"^(?:open|create)\s+(?:a\s+)?(?:browser\s+)?tab$", clause, flags=re.IGNORECASE)
                        or clause.lower() in ["new tab", "new browser tab", "create tab", "open tab", "create new tab", "create new browser tab"]
                    ):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Open a new browser tab",
                                suggested_skill="browser_control",
                                arguments={"action": "new_tab"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 9. Summarize / Read Webpage
                    if re.match(r"^(?:summarize|summarise|read|analyze|extract)\s+(?:it|this|the\s+page|the\s+webpage|the\s+article|the\s+content)$", clause, flags=re.IGNORECASE):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description="Summarize the active webpage content",
                                suggested_skill="read_webpage",
                                arguments={"action": "summarize"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 10. Coding Project Creation
                    m_p_proj = re.match(r"^(?:create|make|init|initialize)\s+(?:a\s+)?(?:([a-zA-Z0-9_\+\#]+)\s+)?project\s+(?:called|named|with\s+name|for)?\s*([a-zA-Z0-9_\-\.]+)$", clause, flags=re.IGNORECASE)
                    if m_p_proj:
                        lang_cand = (m_p_proj.group(1) or "").strip().lower()
                        p_name = m_p_proj.group(2).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Create {lang_cand.capitalize() if lang_cand else 'Python'} project '{p_name}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "create_project", "project_name": p_name, "language": lang_cand if lang_cand else "python"},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 11. Open Project
                    m_p_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?(?:project\s+called|project\s+named|project)\s+([a-zA-Z0-9_\-]+)$", clause, flags=re.IGNORECASE)
                    if not m_p_open_proj:
                        m_p_open_proj = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-]+)\s+project$", clause, flags=re.IGNORECASE)
                    if m_p_open_proj:
                        p_name = m_p_open_proj.group(1).strip()
                        if p_name.lower() not in ["my", "the", "a", "this"]:
                            seq_steps.append(
                                PlanStep(
                                    step_id=idx,
                                    description=f"Open project '{p_name}'",
                                    suggested_skill="coding_workspace",
                                    arguments={"action": "open_project", "project_name": p_name},
                                    requires_confirmation=False,
                                    status=StepState.PENDING,
                                    max_replans=1
                                )
                            )
                            continue

                    # 12. Create Code File
                    m_p_code_file = re.match(r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?(?:code\s+|source\s+)?file\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)$", clause, flags=re.IGNORECASE)
                    if not m_p_code_file:
                        m_p_code_file = re.match(r"^(?:create|make)\s+([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))$", clause, flags=re.IGNORECASE)
                    if m_p_code_file:
                        fname = m_p_code_file.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Create source file '{fname}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "create_code_file", "filename": fname},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 13. Read Code File
                    m_p_read_code = re.match(r"^(?:read|show|view|display|cat)\s+(?:the\s+)?(?:code\s+(?:in|of)\s+|source\s+(?:in|of)\s+|file\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))$", clause, flags=re.IGNORECASE)
                    if m_p_read_code:
                        fname = m_p_read_code.group(1).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Read source file '{fname}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "read_code_file", "filename": fname},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 14. Edit Code File
                    # 14a. Modify / Update / Edit file
                    m_p_modify = re.match(r"^(?:modify|update|edit|alter|rewrite|change|optimize|optimise)\s+(?:my\s+|the\s+|this\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))\s*(?:to|for|with|so\s+that|:|,\s*)?\s*(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_modify:
                        fname = m_p_modify.group(1).strip()
                        instr = m_p_modify.group(2).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Modify '{fname}': {instr}",
                                suggested_skill="coding_workspace",
                                arguments={"action": "edit_code_file", "filename": fname, "instruction": instr, "prompt": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 14b. In <file> modify / replace
                    m_p_in_file = re.match(r"^(?:in|inside)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))[,:\s]+(?:modify|update|edit|alter|rewrite|change|replace|print|add|write|set)?\s*(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_in_file:
                        fname = m_p_in_file.group(1).strip()
                        instr = m_p_in_file.group(2).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Modify '{fname}': {instr}",
                                suggested_skill="coding_workspace",
                                arguments={"action": "edit_code_file", "filename": fname, "instruction": instr, "prompt": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 14c. Open <file> and modify / replace
                    m_p_open_modify = re.match(r"^(?:open|load)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))\s+and\s+(?:modify|update|edit|alter|rewrite|change|replace)\s*(?:it\s+to|it\s+with|it\s+so\s+that|it)?\s*(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_open_modify:
                        fname = m_p_open_modify.group(1).strip()
                        instr = m_p_open_modify.group(2).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Modify '{fname}': {instr}",
                                suggested_skill="coding_workspace",
                                arguments={"action": "edit_code_file", "filename": fname, "instruction": instr, "prompt": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    m_p_edit_repl = re.match(r"^(?:change|replace)\s+(.+?)\s+(?:to|with)\s+(.+?)\s+in\s+([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)$", clause, flags=re.IGNORECASE)
                    if m_p_edit_repl:
                        tgt = m_p_edit_repl.group(1).strip().strip('"\'')
                        repl = m_p_edit_repl.group(2).strip().strip('"\'')
                        fname = m_p_edit_repl.group(3).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Replace '{tgt}' with '{repl}' in '{fname}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "edit_code_file", "filename": fname, "target_text": tgt, "replacement_text": repl},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    m_p_edit_add = re.match(r"^(?:add|append|write|insert)\s+(.+?)\s+(?:to|in|into)\s+([a-zA-Z0-9_\-\.]+\.(?:py|cpp|c|h|hpp|js|jsx|ts|tsx|java|go|rs|html|css|json|md|sql))$", clause, flags=re.IGNORECASE)
                    if m_p_edit_add:
                        content_val = m_p_edit_add.group(1).strip().strip('"\'')
                        fname = m_p_edit_add.group(2).strip()
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Add code to '{fname}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "edit_code_file", "filename": fname, "content": content_val},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 15. Generate Code
                    m_p_gen_code = re.match(
                        r"^(?:write|create|implement|code|generate|build)\s+(?:a\s+|an\s+)?(?:([a-zA-Z0-9_\+\#]+)\s+)?(?:program|script|solution|function|code|app)?\s*(?:to|for|that|which)?\s*(.+)$",
                        clause,
                        flags=re.IGNORECASE
                    )
                    if not m_p_gen_code:
                        m_p_gen_code = re.match(r"^print\s+(?:all\s+)?(?:prime\s+numbers|primes|fibonacci|even\s+numbers|odd\s+numbers)(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_gen_code:
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Generate code for '{clause}'",
                                suggested_skill="coding_workspace",
                                arguments={"action": "generate_code", "prompt": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 16. File Management Steps (Feature #35)
                    # 16a. Create Folder
                    m_p_mkdir = re.match(r"^(?:create|make|mkdir)\s+(?:a\s+)?(?:new\s+)?folder(?:\s+called|\s+named)?\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_mkdir:
                        raw_fn = m_p_mkdir.group(1).strip()
                        m_nest = re.search(r"^(.+?)\s+(?:inside|in|under|on)\s+(.+)$", raw_fn, flags=re.IGNORECASE)
                        if m_nest:
                            fn_val = m_nest.group(1).strip().strip('"\'')
                            loc_val = m_nest.group(2).strip().strip('"\'')
                            seq_steps.append(
                                PlanStep(
                                    step_id=idx,
                                    description=f"Create folder '{fn_val}' in {loc_val}",
                                    suggested_skill="create_folder",
                                    arguments={"folder_name": fn_val, "location": loc_val, "target_path": f"{loc_val}/{fn_val}"},
                                    requires_confirmation=False,
                                    status=StepState.PENDING,
                                    max_replans=1
                                )
                            )
                        else:
                            seq_steps.append(
                                PlanStep(
                                    step_id=idx,
                                    description=f"Create folder '{raw_fn}'",
                                    suggested_skill="create_folder",
                                    arguments={"folder_name": raw_fn, "target_path": raw_fn},
                                    requires_confirmation=False,
                                    status=StepState.PENDING,
                                    max_replans=1
                                )
                            )
                        continue

                    # 16b. Move File
                    m_p_move = re.match(r"^move\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)\s+(?:to|into|inside|in)\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_move:
                        src_v = m_p_move.group(1).strip().strip('"\'')
                        dst_v = m_p_move.group(2).strip().strip('"\'')
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Move '{src_v}' to '{dst_v}'",
                                suggested_skill="move_file",
                                arguments={"source_path": src_v, "destination_path": dst_v, "target_path": src_v},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 16c. Copy File
                    m_p_copy = re.match(r"^(?:copy|make\s+a\s+copy\s+of)\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)(?:\s+(?:to|into|inside|in)\s+(.+))?$", clause, flags=re.IGNORECASE)
                    if m_p_copy:
                        src_v = m_p_copy.group(1).strip().strip('"\'')
                        dst_v = (m_p_copy.group(2) or "documents").strip().strip('"\'')
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Copy '{src_v}' to '{dst_v}'",
                                suggested_skill="copy_file",
                                arguments={"source_path": src_v, "destination_path": dst_v, "target_path": src_v},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 16d. Rename File
                    m_p_rename = re.match(r"^rename\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+)?(.+?)\s+(?:to|as)\s+(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_rename:
                        src_v = m_p_rename.group(1).strip().strip('"\'')
                        dst_v = m_p_rename.group(2).strip().strip('"\'')
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Rename '{src_v}' to '{dst_v}'",
                                suggested_skill="rename_file",
                                arguments={"source_path": src_v, "new_name": dst_v, "target_path": src_v},
                                requires_confirmation=True,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 16e. Delete File
                    m_p_delete = re.match(r"^(?:delete|remove|erase|trash)\s+(?:the\s+|this\s+)?(?:file\s+|folder\s+|directory\s+)?(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_delete:
                        del_tgt = m_p_delete.group(1).strip().strip('"\'')
                        if not any(kw in del_tgt.lower() for kw in ["character", "text", "line", "word", "paragraph"]):
                            seq_steps.append(
                                PlanStep(
                                    step_id=idx,
                                    description=f"Delete '{del_tgt}'",
                                    suggested_skill="delete_file",
                                    arguments={"target_path": del_tgt},
                                    requires_confirmation=True,
                                    status=StepState.PENDING,
                                    max_replans=1
                                )
                            )
                            continue

                    # 16f. File Search Step
                    m_p_fsearch = re.match(r"^(?:find|search|locate|where\s+is)\s+(?:all\s+)?(?:files?\s+(?:in|matching|named|for)?|my\s+)?(.+)$", clause, flags=re.IGNORECASE)
                    if m_p_fsearch and not any(kw in clause.lower() for kw in ["element", "button", "screen", "online", "web", "internet"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"Search for files matching '{clause}'",
                                suggested_skill="file_search",
                                arguments={"query": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                    # 16g. List Files Step
                    if any(k in clause.lower() for k in ["show files", "list files", "show folder contents", "what's inside"]):
                        seq_steps.append(
                            PlanStep(
                                step_id=idx,
                                description=f"List directory contents for '{clause}'",
                                suggested_skill="list_files",
                                arguments={"target_path": clause},
                                requires_confirmation=False,
                                status=StepState.PENDING,
                                max_replans=1
                            )
                        )
                        continue

                if len(seq_steps) >= 2:
                    if cand_target:
                        for s in seq_steps:
                            if s.suggested_skill == "coding_workspace":
                                if not s.arguments.get("filename") and not s.arguments.get("file_path"):
                                    s.arguments["filename"] = cand_target
                                    s.arguments["file_path"] = cand_target
                                    if "program" in s.description.lower() and cand_target not in s.description:
                                        s.description = s.description.replace("program", f"'{cand_target}'")
                    print(f"[ByteX Planner] Decomposed compound goal into {len(seq_steps)} sequential steps: {[s.description for s in seq_steps]}")
                    return AgentPlan(goal=clean_goal, steps=seq_steps)

        # 1. Query Dynamic Skill Selection
        selection = ByteXSkillSelector.select_skills_for_goal(clean_goal)
        selected_skills = selection.get("selected_skills", [])

        if not selected_skills:
            print(f"[ByteX Planner] No registered skills selected for goal: '{clean_goal}'")
            return None

        steps: List[PlanStep] = []
        step_id = 1

        # 2. Extract Goal Directives & Construct Steps
        # A. System Status Step
        if "system_status" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description="Inspect real-time CPU, RAM, and battery performance metrics",
                    suggested_skill="system_status",
                    arguments={},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # B. File Operations (Folder/File creation, rename, move, copy)
        if "file_operations" in selected_skills and step_id <= cls.MAX_STEPS:
            # Extract folder name
            m_name = re.search(r"\b(?:called|named)\s+([a-zA-Z0-9_\-]+)", clean_goal, flags=re.IGNORECASE)
            if not m_name:
                m_name = re.search(r"\b(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?([a-zA-Z0-9_\-]+)\s*(?:folder|directory)?\b", clean_goal, flags=re.IGNORECASE)
            folder_name = m_name.group(1).strip() if m_name else "ByteXWorkspace"
            if folder_name.lower() in ["a", "new", "the", "my"]:
                folder_name = "ByteXWorkspace"

            # Extract location: Explicit user prompt ALWAYS takes priority over memory
            loc_match = re.search(r"\b(?:in|on|inside|under)\s+(?:my\s+|the\s+)?(desktop|downloads?|documents?|pictures?)\b", clean_goal, flags=re.IGNORECASE)
            if loc_match:
                folder_loc = loc_match.group(1).lower()
            else:
                # Contextual fallback from relevant memory if available
                memory_loc = None
                if relevant_memory:
                    for mem in relevant_memory:
                        mem_lower = mem.lower()
                        if folder_name.lower() in mem_lower or "folder" in mem_lower or "preferred" in mem_lower:
                            m_loc = re.search(r"\b(desktop|downloads?|documents?|pictures?)\b", mem_lower)
                            if m_loc:
                                memory_loc = m_loc.group(1).lower()
                                print(f"[ByteX Planner] Used read-only memory context for '{folder_name}' location: '{memory_loc}'")
                                break
                folder_loc = memory_loc if memory_loc else "desktop"

            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Create directory '{folder_name}' at {folder_loc}",
                    suggested_skill="file_operations",
                    arguments={
                        "operation": "create_folder",
                        "folder_name": folder_name,
                        "location": folder_loc
                    },
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # C. File Search
        if "file_search" in selected_skills and step_id <= cls.MAX_STEPS:
            m_query = re.search(r"\b(?:find|search(?:\s+for)?|locate)\s+(?:my\s+)?([a-zA-Z0-9_\-\s.]+)", clean_goal, flags=re.IGNORECASE)
            query = m_query.group(1).strip() if m_query else "resume"
            query = re.sub(r"\b(?:and|then|also|where|tell)\b.*$", "", query, flags=re.IGNORECASE).strip()
            if not query:
                query = "resume"

            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Search for files matching '{query}' across safe user directories",
                    suggested_skill="file_search",
                    arguments={"query": query},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D1. Application Launch
        if "open_application" in selected_skills and step_id <= cls.MAX_STEPS:
            from skills.resolver import universal_app_resolver, ResolutionStatus
            apps_found = []
            
            # Extract all comma- or 'and'-separated targets following open/launch/start/run or Hinglish verbs
            m_phrase = re.search(r"\b(?:open|launch|start|run)\s+(.+)$", clean_goal, flags=re.IGNORECASE)
            if not m_phrase:
                m_phrase = re.search(r"^(.+?)\s+(?:kholo|khol\s+do|kholna|khol|chalao|chala)$", clean_goal, flags=re.IGNORECASE)
            if m_phrase:
                raw_phrase = m_phrase.group(1)
                parts = re.split(r",|\band\b", raw_phrase, flags=re.IGNORECASE)
                for p in parts:
                    clean_p = p.strip().strip(".")
                    if (
                        clean_p
                        and clean_p.lower() not in ["and", "the", "my", "a", "an", "files", "folder", "website", "it", "code", "program", "the program", "the code"]
                        and not clean_p.lower().startswith("read ")
                        and not any(k in clean_p.lower() for k in ["verify", "output", "it to", "it and"])
                        and not any(ext in clean_p.lower() for ext in [".cpp", ".py", ".c", ".h", ".hpp", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".html", ".css", ".json", ".sql", ".md"])
                        and not (clean_p.lower() in ["github", "youtube", "wikipedia", "google", "openai", "example", "homepage"] and ("browser_control" in selected_skills or "read_webpage" in selected_skills))
                    ):
                        status, rec, _ = universal_app_resolver.resolve(clean_p)
                        app_name = rec.display_name if (status == ResolutionStatus.FOUND and rec) else clean_p
                        if app_name not in apps_found:
                            apps_found.append(app_name)

            # Fallback catalog search
            if not apps_found and not ("browser_control" in selected_skills or "read_webpage" in selected_skills):
                for alias, rec in universal_app_resolver._alias_map.items():
                    if len(alias) >= 3 and re.search(r'\b' + re.escape(alias) + r'\b', goal_lower):
                        if rec.display_name not in apps_found:
                            apps_found.append(rec.display_name)

            if not apps_found and not ("browser_control" in selected_skills or "read_webpage" in selected_skills):
                if any(w in goal_lower for w in ["browser", "web"]):
                    from memory.preferences import preference_manager
                    pref = preference_manager.get_preference("preferred_browser")
                    apps_found = [pref.value if pref else "Chrome"]
                else:
                    apps_found = ["Chrome"]

            for app_target in apps_found:
                if step_id > cls.MAX_STEPS:
                    break
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        description=f"Launch {app_target.capitalize()} application on interactive desktop and verify process state",
                        suggested_skill="open_application",
                        arguments={"application": app_target},
                        requires_confirmation=False,
                        status=StepState.PENDING,
                        max_replans=1
                    )
                )
                step_id += 1

        # D3. Browser Navigation Step
        if ("browser_control" in selected_skills or "open_website" in selected_skills) and step_id <= cls.MAX_STEPS:
            m_nav = re.search(r"\b(?:go\s+to|navigate\s+to|take\s+me\s+to|visit)\s+(https?://[^\s]+|[a-zA-Z0-9_\-.]+\.(?:com|org|net|io|dev|edu|gov)|youtube|github|google|chatgpt|openai|reddit|wikipedia)\b", clean_goal, flags=re.IGNORECASE)
            if not m_nav and any(site in goal_lower for site in ["youtube", "github", "google", "chatgpt", "openai", "reddit", "wikipedia"]):
                m_site = re.search(r"\b(youtube|github|google|chatgpt|openai|reddit|wikipedia)\b", goal_lower)
                dest = m_site.group(1) if m_site else "github"
            else:
                dest = m_nav.group(1).strip() if m_nav else "github"

            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Navigate browser to {dest}",
                    suggested_skill="browser_control",
                    arguments={"action": "navigate", "url": dest},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D4. Read Webpage Step (#33)
        if "read_webpage" in selected_skills and step_id <= cls.MAX_STEPS:
            m_target = re.search(r"(https?://[^\s]+|[a-zA-Z0-9_\-.]+\.(?:com|org|net|io|dev|edu|gov)|github|example|wikipedia|openai|google)", clean_goal, flags=re.IGNORECASE)
            dest_url = m_target.group(1).strip() if m_target else "https://example.com"
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Read textual content and structure from {dest_url}",
                    suggested_skill="read_webpage",
                    arguments={"url": dest_url},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D5. Form Filling Step (#34)
        if "fill_form" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Identify and fill requested safe form fields with user-provided data",
                    suggested_skill="fill_form",
                    arguments={"raw_text": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D6. Download File Step (#35)
        if "download_file" in selected_skills and step_id <= cls.MAX_STEPS:
            m_target = re.search(r"(https?://[^\s]+|[a-zA-Z0-9_\-.]+\.(?:com|org|net|io|dev|edu|gov)/[^\s]+)", clean_goal, flags=re.IGNORECASE)
            dest_url = m_target.group(1).strip() if m_target else None
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Safely download file from source and verify destination integrity",
                    suggested_skill="download_file",
                    arguments={"url": dest_url, "raw_text": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D7. Website Automation Step (#36)
        if "website_automation" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Execute structured safe multi-action website automation workflow",
                    suggested_skill="website_automation",
                    arguments={"raw_text": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D8. Research Mode Step (#37)
        if "research_mode" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Conduct multi-source web research, cross-check evidence, and synthesize cited findings",
                    suggested_skill="research_mode",
                    arguments={"raw_text": clean_goal, "query": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D9. Summarize Step (#38)
        if "summarize" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Synthesize grounded, structured summary from verified sources and evidence",
                    suggested_skill="summarize",
                    arguments={"raw_text": clean_goal},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D10. Play Media Step (YouTube / Song Playback)
        if "play_media" in selected_skills and step_id <= cls.MAX_STEPS:
            m_play = re.search(r"\b(?:play|stream|listen\s+to)\s+(.+?)(?:\s+(?:and\s+then|and\s+open|and\s+close)\s+|$)", clean_goal, flags=re.IGNORECASE)
            q_target = m_play.group(1).strip() if m_play else clean_goal
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Search and play '{q_target}' on YouTube with ad-filtering and playback verification",
                    suggested_skill="play_media",
                    arguments={"raw_text": q_target, "query": q_target},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # D2. Application Close
        if "close_application" in selected_skills and step_id <= cls.MAX_STEPS:
            from skills.resolver import universal_app_resolver, ResolutionStatus
            apps_found = []
            
            # Extract all comma- or 'and'-separated targets following close/quit/exit/stop/kill
            m_phrase = re.search(r"\b(?:close|quit|exit|stop|kill)\s+(.+)$", clean_goal, flags=re.IGNORECASE)
            if m_phrase:
                raw_phrase = m_phrase.group(1)
                parts = re.split(r",|\band\b", raw_phrase, flags=re.IGNORECASE)
                for p in parts:
                    clean_p = p.strip().strip(".")
                    if clean_p and clean_p.lower() not in ["and", "the", "my", "a", "an", "files", "folder", "website"]:
                        status, rec, _ = universal_app_resolver.resolve(clean_p)
                        app_name = rec.display_name if (status == ResolutionStatus.FOUND and rec) else clean_p
                        if app_name not in apps_found:
                            apps_found.append(app_name)

            # Fallback catalog search
            if not apps_found:
                for alias, rec in universal_app_resolver._alias_map.items():
                    if len(alias) >= 3 and re.search(r'\b' + re.escape(alias) + r'\b', goal_lower):
                        if rec.display_name not in apps_found:
                            apps_found.append(rec.display_name)

            if not apps_found:
                apps_found = ["Chrome"]

            for app_target in apps_found:
                if step_id > cls.MAX_STEPS:
                    break
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        description=f"Safely close {app_target.capitalize()} application and verify process termination",
                        suggested_skill="close_application",
                        arguments={"application": app_target},
                        requires_confirmation=False,
                        status=StepState.PENDING,
                        max_replans=1
                    )
                )
                step_id += 1

        # E. Take Screenshot
        if "take_screenshot" in selected_skills and step_id <= cls.MAX_STEPS:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description="Capture primary display screenshot to file",
                    suggested_skill="take_screenshot",
                    arguments={},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # F. Web Search
        if "web_search" in selected_skills and step_id <= cls.MAX_STEPS:
            m_s = re.search(r"\b(?:search\s+(?:the\s+)?(?:web|online|internet)?\s*(?:for)?|google|lookup|look\s+up)\s+(.+)$", clean_goal, flags=re.IGNORECASE)
            search_query = m_s.group(1).strip() if m_s else clean_goal
            search_query = re.sub(r"\b(?:and\s+tell\s+me.*|and\s+show\s+me.*|and\s+report.*)$", "", search_query, flags=re.IGNORECASE).strip()
            if not search_query:
                search_query = clean_goal
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Search the web for '{search_query}'",
                    suggested_skill="web_search",
                    arguments={"query": search_query},
                    requires_confirmation=False,
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # G. Delete File (Risky - requires confirmation)
        if "delete_file" in selected_skills and step_id <= cls.MAX_STEPS:
            m_del = re.search(r"\b(?:delete|remove)\s+(?:file\s+)?([a-zA-Z0-9_\-.]+)$", clean_goal, flags=re.IGNORECASE)
            del_target = m_del.group(1).strip() if m_del else ""
            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=f"Permanently delete file '{del_target}'",
                    suggested_skill="delete_file",
                    arguments={"target_path": del_target},
                    requires_confirmation=True,  # Critical confirmation enforcement
                    status=StepState.PENDING,
                    max_replans=1
                )
            )
            step_id += 1

        # H. Coding Workspace Operations (Compile, Execute, Generate, Edit, Explain)
        if "coding_workspace" in selected_skills and step_id <= cls.MAX_STEPS:
            from core.command_router import CommandRouter
            cand_fn = CommandRouter._extract_target_file(clean_goal) or "this file"
            if any(kw in goal_lower for kw in ["compile and run", "compile and execute", "build and run", "run", "execute"]):
                is_compile_only = any(kw in goal_lower for kw in [
                    "don't run", "dont run", "do not run", "without running",
                    "don't execute", "dont execute", "do not execute", "without executing",
                    "compile only", "build only", "only compile", "only build", "compile-only", "build-only"
                ])
                act = "compile_code" if is_compile_only else "execute_code"
                desc = f"Compile source file '{cand_fn}'" if is_compile_only else f"Compile and execute source file '{cand_fn}'"
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        description=desc,
                        suggested_skill="coding_workspace",
                        arguments={"action": act, "filename": cand_fn, "prompt": clean_goal},
                        requires_confirmation=False,
                        status=StepState.PENDING,
                        max_replans=1
                    )
                )
                step_id += 1
            elif any(kw in goal_lower for kw in ["compile", "build"]):
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        description=f"Compile source file '{cand_fn}'",
                        suggested_skill="coding_workspace",
                        arguments={"action": "compile_code", "filename": cand_fn, "prompt": clean_goal},
                        requires_confirmation=False,
                        status=StepState.PENDING,
                        max_replans=1
                    )
                )
                step_id += 1
            elif any(kw in goal_lower for kw in ["explain", "walk through", "complexity"]):
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        description=f"Explain code in '{cand_fn}'",
                        suggested_skill="coding_workspace",
                        arguments={"action": "explain_code", "filename": cand_fn, "prompt": clean_goal},
                        requires_confirmation=False,
                        status=StepState.PENDING,
                        max_replans=1
                    )
                )
                step_id += 1

        # 3. Validate Step Construction Integrity
        if not steps:
            return None

        # Verify all skills in generated steps are valid in skill_registry
        for step in steps:
            if skill_registry.get_skill(step.suggested_skill) is None:
                logger.error(f"[ByteX Planner] Invalid skill generated: {step.suggested_skill}")
                return None

        plan = AgentPlan(
            goal=clean_goal,
            steps=steps[:cls.MAX_STEPS]
        )
        print(f"[ByteX Planner] Generated {len(plan.steps)}-step plan for goal: '{clean_goal}'")
        return plan

planner = ByteXPlanner()
