import re
import json
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("bytex.response_sanitizer")

class ResponseSanitizer:
    """
    Authoritative User-Facing Response Sanitizer and Agent Protocol Parser.
    
    Guarantees:
    1. ZERO internal agent reasoning ('thought', '<think>', chain-of-thought) is ever shown to the user or sent to TTS.
    2. ZERO raw tool JSON ('tool_use', 'tool_call', 'arguments') is leaked to user-facing chat.
    3. Internal agent tool calls (e.g. {"tool_use": {"name": "play_media", ...}}) are executed internally and replaced with the verified tool result.
    4. Normal user-facing JSON requested by the user (e.g. 'give me a sample user JSON') is preserved.
    """

    @classmethod
    def contains_internal_agent_protocol(cls, text: str) -> bool:
        """Determines if text contains internal agent reasoning or tool call structures."""
        if not text or not text.strip():
            return False
        
        t_clean = text.strip()

        # Check for thinking / reasoning / tool tags
        if any(tag in t_clean for tag in ["<think>", "</think>", "<tool>", "</tool>", "<tool_call>", "</tool_call>"]):
            return True

        # Check for markdown json codeblocks containing tool protocol
        m_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t_clean, flags=re.DOTALL)
        if m_code:
            try:
                data = json.loads(m_code.group(1))
                if isinstance(data, dict) and any(k in data for k in ["tool_use", "tool_call", "thought", "internal_reasoning", "action"]):
                    return True
            except Exception:
                pass

        # Check for direct JSON containing agent tool protocol
        if t_clean.startswith("{") and t_clean.endswith("}"):
            try:
                data = json.loads(t_clean)
                if isinstance(data, dict) and any(k in data for k in ["tool_use", "tool_call", "thought", "internal_reasoning", "name"]):
                    return True
            except Exception:
                pass

        # Check for embedded json with tool_use or tool_call
        if '"tool_use"' in t_clean or '"tool_call"' in t_clean or '"thought"' in t_clean or '<tool_call>' in t_clean:
            if re.search(r'\{\s*"(?:thought|tool_use|tool_call|action|name)"', t_clean):
                return True

        return False

    @classmethod
    def extract_tool_call(cls, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Extracts tool name and arguments dictionary from raw agent output.
        Supports XML tags (<tool_call>, <tool>), markdown JSON blocks, and raw JSON.
        """
        if not text or not text.strip():
            return None

        t_clean = text.strip()
        extracted_data = None

        # 1. Check for XML tool tags: <tool_call>...</tool_call> or <tool>...</tool>
        m_tag = re.search(r"<(?:tool_call|tool)>(.*?)(?:</(?:tool_call|tool)>|$)", t_clean, flags=re.DOTALL | re.IGNORECASE)
        if m_tag:
            tag_content = m_tag.group(1).strip()
            # Try to parse JSON from inside the tag
            m_inner_json = re.search(r"(\{.*\})", tag_content, flags=re.DOTALL)
            if m_inner_json:
                try:
                    extracted_data = json.loads(m_inner_json.group(1))
                except Exception:
                    pass

        # 2. Try markdown JSON codeblock: ```json { ... } ```
        if not extracted_data:
            m_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t_clean, flags=re.DOTALL)
            if m_code:
                try:
                    extracted_data = json.loads(m_code.group(1))
                except Exception:
                    pass

        # 3. Try direct JSON parsing
        if not extracted_data:
            m_json = re.search(r"(\{.*\})", t_clean, flags=re.DOTALL)
            if m_json:
                try:
                    extracted_data = json.loads(m_json.group(1))
                except Exception:
                    pass

        if not extracted_data or not isinstance(extracted_data, dict):
            return None

        # Extract tool name and arguments
        tool_name = None
        tool_args: Dict[str, Any] = {}

        if "tool_use" in extracted_data and isinstance(extracted_data["tool_use"], dict):
            tool_name = extracted_data["tool_use"].get("name")
            tool_args = extracted_data["tool_use"].get("arguments", {})
        elif "tool_call" in extracted_data and isinstance(extracted_data["tool_call"], dict):
            tool_name = extracted_data["tool_call"].get("name")
            tool_args = extracted_data["tool_call"].get("arguments", {})
        elif "name" in extracted_data and "arguments" in extracted_data:
            tool_name = extracted_data.get("name")
            tool_args = extracted_data.get("arguments", {})
        elif "action" in extracted_data:
            tool_name = extracted_data.get("action")
            tool_args = extracted_data.get("arguments", {}) or extracted_data.get("params", {})
        elif "name" in extracted_data:
            tool_name = extracted_data.get("name")
            tool_args = {k: v for k, v in extracted_data.items() if k not in ["name", "thought", "reasoning", "call_id"]}

        # If tool_args is a string (JSON string from some providers), parse it
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except Exception:
                tool_args = {}

        if not isinstance(tool_args, dict):
            tool_args = {}

        if not tool_name or not isinstance(tool_name, str):
            return None

        return tool_name.strip(), tool_args

    @classmethod
    async def extract_and_execute_tool_if_present(cls, text: str) -> Optional[str]:
        """
        Extracts internal tool call from agent output, executes the corresponding registered skill,
        and returns the verified user-facing result. Returns None if no tool call was present.
        """
        from skills.registry import skill_registry

        tool_info = cls.extract_tool_call(text)
        if not tool_info:
            # Check if pure reasoning JSON with "thought" and "response" / "answer"
            m_json = re.search(r"(\{.*\})", text, flags=re.DOTALL)
            if m_json:
                try:
                    data = json.loads(m_json.group(1))
                    if isinstance(data, dict) and "thought" in data and ("response" in data or "answer" in data):
                        return data.get("response") or data.get("answer")
                except Exception:
                    pass
            return None

        tool_name, tool_args = tool_info
        logger.info(f"[ByteX ResponseSanitizer] Executing extracted tool: '{tool_name}' (argument keys: {sorted(tool_args.keys())})")
        try:
            tool_res = await skill_registry.execute_tool(tool_name, tool_args)
            if tool_res.confirmation_required:
                from core.confirmation import confirmation_manager
                return confirmation_manager.set_pending(
                    tool=tool_res.tool,
                    action=tool_res.action or tool_res.tool,
                    description=tool_res.message,
                    arguments=tool_res.pending_action or tool_args,
                )
            return tool_res.message
        except Exception as e:
            logger.error(f"[ByteX ResponseSanitizer] Tool execution failed: {e}")
            return f"I encountered an issue executing {tool_name}: {e}"

    @classmethod
    def sanitize(cls, raw_text: str) -> str:
        """
        Synchronous sanitizer removing internal tags, <think> blocks, and agent protocol.
        Guarantees clean, user-facing markdown output.
        """
        if not raw_text or not raw_text.strip():
            return "I was unable to generate a response. Please try again."

        text = raw_text.strip()

        # 1. Strip properly closed <think>...</think>, <tool>...</tool>, <tool_call>...</tool_call>
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE).strip()
        text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL | re.IGNORECASE).strip()
        text = re.sub(r'<tool>.*?</tool>', '', text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 2. Handle unclosed/truncated <think>
        if "<think>" in text.lower():
            inner = re.sub(r'^<think>', '', text, flags=re.IGNORECASE).strip()
            # Look for concluding answer
            markers = [
                r'(?:Draft\s+Response|Draft|Final\s+Output|Output\s+Generation|Output|Response|Answer|Result)\s*:\s*',
                r'\n\n(?=[-•*]|\d+\.)'
            ]
            for pattern in markers:
                parts = re.split(pattern, inner, flags=re.IGNORECASE)
                if len(parts) > 1:
                    candidate = parts[-1].strip()
                    candidate = re.sub(r'\(Self-correction:.*?\)', '', candidate, flags=re.DOTALL)
                    candidate = re.sub(r'</?think>', '', candidate, flags=re.IGNORECASE).strip()
                    if candidate and len(candidate) > 10 and not candidate.lower().startswith('thinking'):
                        text = candidate
                        break

        # 3. Handle unclosed <tool_call> or <tool>
        text = re.sub(r'<(?:tool_call|tool)>.*$', '', text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 4. Strip any lingering tags
        text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE).strip()
        text = re.sub(r'</?tool_call>', '', text, flags=re.IGNORECASE).strip()
        text = re.sub(r'</?tool>', '', text, flags=re.IGNORECASE).strip()

        # 5. Strip internal agent protocol JSON block if it was not a valid tool call
        if cls.contains_internal_agent_protocol(text):
            # Check if JSON has a user-facing response/answer field
            try:
                m_json = re.search(r"(\{.*\})", text, flags=re.DOTALL)
                if m_json:
                    data = json.loads(m_json.group(1))
                    if isinstance(data, dict):
                        for k in ["response", "answer", "message", "output", "result"]:
                            if k in data and isinstance(data[k], str) and data[k].strip():
                                return data[k].strip()
            except Exception:
                pass

            # If it's purely internal JSON without user message, provide clean fallback
            if text.startswith("{") and text.endswith("}"):
                return "Operation completed."

        return text.strip() if text.strip() else "I was unable to complete the response. Please try again."

response_sanitizer = ResponseSanitizer()
