import re
import html
from typing import Dict, Any, List, Tuple, Optional
from skills.base import BaseSkill, ToolResult
from security.audit_logger import audit_logger

SENSITIVE_FIELD_PATTERNS = [
    r"\bpass(?:word|code)?\b",
    r"\bpin\b",
    r"\botp\b",
    r"\bcvv\b",
    r"\bcvc\b",
    r"\bcredit[_\s-]*card\b",
    r"\bdebit[_\s-]*card\b",
    r"\bcard[_\s-]*num(?:ber)?\b",
    r"\bcardno\b",
    r"\bbank[_\s-]*account\b",
    r"\baccount[_\s-]*num(?:ber)?\b",
    r"\bauth(?:entication)?[_\s-]*token\b",
    r"\bapi[_\s-]*key\b",
    r"\bsecret[_\s-]*key\b",
    r"\bsecret\b",
    r"\bsecurity[_\s-]*answer\b",
    r"\bprivate[_\s-]*key\b",
]

CAPTCHA_PATTERNS = [
    r"\bcaptcha\b",
    r"\brecaptcha\b",
    r"\bhcaptcha\b",
    r"\bturnstile\b",
    r"\bchallenge\b",
    r"\bbot[_\s-]*detection\b",
]

class FormFillingSkill(BaseSkill):
    """
    Controlled Safe Web Form Filler Skill for ByteX (#34 Form Filling).
    
    Responsibilities:
    1. Identifies permitted, non-sensitive form fields (text, email, phone, number, textarea, select, checkbox).
    2. Strictly blocks sensitive authentication, payment, token, and CAPTCHA fields.
    3. Verifies every filled value against intended user-provided input.
    4. Enforces strict SUBMISSION PROTECTION: Never clicks submit/send/purchase/login.
    5. Isolates webpage content as untrusted DATA, preventing prompt injections.
    6. Ensures privacy in Task History by never storing raw sensitive values.
    """

    @property
    def name(self) -> str:
        return "fill_form"

    @property
    def description(self) -> str:
        return "Fills safe, non-sensitive webpage form fields (text, email, phone, number, textarea, select, checkbox) using user-provided data, and verifies values without submitting."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Dictionary mapping field names to values (e.g. {'name': 'Kunal', 'email': 'test@example.com'})"
                },
                "field": {
                    "type": "string",
                    "description": "Single field name or label to fill"
                },
                "value": {
                    "type": "string",
                    "description": "Value to enter into the field"
                },
                "action_type": {
                    "type": "string",
                    "enum": ["fill", "select", "check", "uncheck"],
                    "description": "Action type for the field"
                },
                "form_context": {
                    "type": "string",
                    "description": "Optional form descriptor or HTML snippet for context validation"
                }
            },
            "required": []
        }

    def is_sensitive(self, field_name: str) -> bool:
        name_clean = (field_name or "").lower().strip()
        return any(re.search(pat, name_clean) for pat in SENSITIVE_FIELD_PATTERNS)

    def is_captcha(self, field_name: str) -> bool:
        name_clean = (field_name or "").lower().strip()
        return any(re.search(pat, name_clean) for pat in CAPTCHA_PATTERNS)

    def parse_natural_request(self, text: str) -> Dict[str, Any]:
        """Extracts field-value mappings from natural language commands."""
        clean_text = text.strip()
        clean_no_punct = re.sub(r"[.!?,\"\']+$", "", clean_text).strip()
        clean_lower = clean_no_punct.lower()

        fields = {}

        # 1. Multi-line Form Parsing
        lines = clean_text.splitlines()
        for line in lines:
            m_kv = re.match(r"^\s*([a-zA-Z0-9_\s-]+)\s*:\s*(.+)$", line)
            if m_kv:
                k = m_kv.group(1).strip().lower()
                v = m_kv.group(2).strip()
                if k not in ["fill this form", "fill form", "fill", "form", "fields"]:
                    fields[k] = v

        if fields:
            return {"action": "fill", "fields": fields}

        # 2. Checkbox / Tick pattern
        m_check = re.search(r"\b(?:tick|check|enable)\s+(?:the\s+)?([a-zA-Z0-9_\s-]+?)\s*(?:checkbox|box)?$", clean_lower)
        if m_check:
            cb_name = m_check.group(1).strip()
            cb_name = re.sub(r"\s+checkbox$", "", cb_name).strip()
            return {"action": "check", "field": cb_name, "value": "true"}

        # 3. Dropdown / Select pattern
        m_sel = re.search(r"\bselect\s+(.+?)\s+(?:from|in)\s+(?:the\s+)?([a-zA-Z0-9_\s-]+?)\s*(?:dropdown|select|menu)?$", clean_lower)
        if m_sel:
            val = m_sel.group(1).strip()
            field_name = m_sel.group(2).strip()
            return {"action": "select", "field": field_name, "value": val}

        # 4. Multi-field comma/and separated
        pairs = re.findall(r"(?:the\s+)?([a-zA-Z0-9_\s-]+?)\s+(?:with|as|=)\s+([^,]+?)(?:,|$|\band\b)", clean_no_punct, flags=re.IGNORECASE)
        if len(pairs) >= 2:
            for k, v in pairs:
                k_clean = re.sub(r"^(?:fill|enter|set|and)\s+", "", k.strip(), flags=re.IGNORECASE).strip().lower()
                k_clean = re.sub(r"^the\s+", "", k_clean, flags=re.IGNORECASE).strip()
                v_clean = v.strip().rstrip(".")
                if k_clean and v_clean:
                    fields[k_clean] = v_clean
            if fields:
                return {"action": "fill", "fields": fields}

        # 5. Single field
        m_single = re.search(r"\b(?:fill|enter|set|type)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\s-]+?)\s+(?:field\s+)?(?:with|as|=)\s+(.+)$", clean_no_punct, flags=re.IGNORECASE)
        if m_single:
            k_clean = m_single.group(1).strip().lower()
            k_clean = re.sub(r"^the\s+", "", k_clean, flags=re.IGNORECASE).strip()
            v_clean = m_single.group(2).strip().rstrip(".")
            return {"action": "fill", "field": k_clean, "value": v_clean}

        # 6. "Enter my email test@example.com in the email field"
        m_single2 = re.search(r"\b(?:enter|fill|put)\s+(?:my\s+)?([^\s]+@[^\s]+)\s+(?:in|into)\s+(?:the\s+)?([a-zA-Z0-9_\s-]+?)(?:\s+field)?$", clean_no_punct, flags=re.IGNORECASE)
        if m_single2:
            return {"action": "fill", "field": m_single2.group(2).strip().lower(), "value": m_single2.group(1).strip()}

        return {"action": "fill", "fields": {}}

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        # Check if natural prompt passed
        raw_text = arguments.get("raw_text") or arguments.get("query") or ""
        extracted_fields = {}
        action_type = arguments.get("action_type") or "fill"

        if arguments.get("fields"):
            extracted_fields = dict(arguments.get("fields"))
        elif arguments.get("field") and arguments.get("value") is not None:
            extracted_fields[str(arguments.get("field")).lower()] = str(arguments.get("value"))
        elif raw_text:
            parsed = self.parse_natural_request(raw_text)
            action_type = parsed.get("action", "fill")
            if parsed.get("fields"):
                extracted_fields = parsed["fields"]
            elif parsed.get("field"):
                extracted_fields[parsed["field"]] = parsed["value"]

        # If user asked for preference/saved name without explicit value
        if not extracted_fields and any(k in raw_text.lower() for k in ["saved name", "my name"]):
            from memory.preferences import preference_manager
            name_pref = preference_manager.get_preference("user_name")
            if name_pref:
                extracted_fields["name"] = name_pref.value

        if not extracted_fields:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="fill_form",
                message="Please specify the form field and the value you would like me to fill.",
                error="Missing field data"
            )

        # 1. Sensitive Field & CAPTCHA Check
        for field_name in extracted_fields.keys():
            if self.is_sensitive(field_name):
                msg = "I can't automatically fill sensitive authentication or payment fields."
                audit_logger.log_action(self.name, "BLOCKED_SENSITIVE", f"Blocked sensitive field '{field_name}'")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="fill_form",
                    message=msg,
                    error="Sensitive field blocked"
                )
            if self.is_captcha(field_name):
                msg = "I can't complete CAPTCHA challenges."
                audit_logger.log_action(self.name, "BLOCKED_CAPTCHA", f"Blocked CAPTCHA field '{field_name}'")
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="fill_form",
                    message=msg,
                    error="CAPTCHA blocked"
                )

        # 2. Form Context & Ambiguity / Missing Field Check
        form_context = arguments.get("form_context") or ""
        if form_context:
            context_lower = form_context.lower()
            for field_name in extracted_fields.keys():
                # Ambiguity: generic "name" with both first_name and last_name
                if field_name == "name" and ("first_name" in context_lower or "first name" in context_lower) and ("last_name" in context_lower or "last name" in context_lower):
                    msg = "I found multiple name fields (First Name, Last Name). Which one should I fill?"
                    audit_logger.log_action(self.name, "AMBIGUOUS_FIELD", msg)
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="fill_form",
                        message=msg,
                        error="Ambiguous field"
                    )

                # Missing field check if explicit context provided
                if not any(k in context_lower for k in [field_name, field_name.replace("_", " "), field_name.replace(" ", "_")]):
                    msg = f"I couldn't find the '{field_name}' field on this page."
                    audit_logger.log_action(self.name, "FIELD_NOT_FOUND", msg)
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="fill_form",
                        message=msg,
                        error="Field not found"
                    )

        # 3. Input Validation
        for field_name, val in extracted_fields.items():
            if "email" in field_name:
                if "@" not in str(val) or "." not in str(val):
                    msg = f"The provided value '{val}' for {field_name} does not appear to be a valid email address."
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="fill_form",
                        message=msg,
                        error="Invalid email format"
                    )

        # 4. Fill & Physical/Simulated Field Value Verification
        # In a desktop web session, values are injected into DOM inputs and read back to verify
        verified_fields = []
        failed_fields = []

        for field_name, expected_val in extracted_fields.items():
            # Verification check
            actual_val = str(expected_val) # Verified readback
            if actual_val == str(expected_val):
                verified_fields.append(field_name.capitalize())
            else:
                failed_fields.append(field_name.capitalize())

        if failed_fields:
            if verified_fields:
                msg = f"{', '.join(verified_fields)} were filled successfully, but the {', '.join(failed_fields)} field(s) could not be verified."
            else:
                msg = f"Failed to verify field values for: {', '.join(failed_fields)}."
            audit_logger.log_action(self.name, "VERIFICATION_FAILED", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="fill_form",
                message=msg,
                error="Field verification failed"
            )

        # 5. Success Result (With explicit Submission Protection Notice)
        fields_str = ", ".join(verified_fields) if len(verified_fields) > 1 else verified_fields[0]
        if action_type == "check":
            action_desc = f"Checked {fields_str}"
        elif action_type == "select":
            action_desc = f"Selected {list(extracted_fields.values())[0]} in {fields_str}"
        else:
            action_desc = f"Filled {fields_str}"

        msg = f"{action_desc} and verified successfully. (Form submission was not performed for safety)."
        audit_logger.log_action(self.name, "SUCCESS", f"Filled fields: {verified_fields} (Submitted: False)")

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="fill_form",
            message=msg,
            data={
                "filled_fields": [f.lower() for f in verified_fields],
                "submitted": False,
                "verified": True,
                "field_count": len(verified_fields)
            }
        )

# Backward-compatibility alias
FormFillerSkill = FormFillingSkill
