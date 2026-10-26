import re
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class MemoryCategory(str, Enum):
    USER_PREFERENCE = "USER_PREFERENCE"
    PROJECT = "PROJECT"
    WORKFLOW = "WORKFLOW"
    APPLICATION_PREFERENCE = "APPLICATION_PREFERENCE"
    ROUTINE = "ROUTINE"
    FACT = "FACT"
    CONTEXT = "CONTEXT"
    ALIAS = "ALIAS"
    TASK_CONTEXT = "TASK_CONTEXT"
    
    # Backwards compatibility aliases
    USER_PROFILE = "USER_PROFILE"
    GENERAL_FACT = "GENERAL_FACT"
    PREFERENCE = "preference"
    PERSONAL_INFO = "personal_info"
    INSTRUCTION = "instruction"

class ConfidenceLevel(str, Enum):
    EXPLICIT = "EXPLICIT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

CATEGORY_NORMALIZATION_MAP = {
    "preference": MemoryCategory.USER_PREFERENCE.value,
    "user_preference": MemoryCategory.USER_PREFERENCE.value,
    "user preference": MemoryCategory.USER_PREFERENCE.value,
    "preferences": MemoryCategory.USER_PREFERENCE.value,
    "project": MemoryCategory.PROJECT.value,
    "projects": MemoryCategory.PROJECT.value,
    "workflow": MemoryCategory.WORKFLOW.value,
    "workflows": MemoryCategory.WORKFLOW.value,
    "application": MemoryCategory.APPLICATION_PREFERENCE.value,
    "app": MemoryCategory.APPLICATION_PREFERENCE.value,
    "app_preference": MemoryCategory.APPLICATION_PREFERENCE.value,
    "application_preference": MemoryCategory.APPLICATION_PREFERENCE.value,
    "routine": MemoryCategory.ROUTINE.value,
    "routines": MemoryCategory.ROUTINE.value,
    "fact": MemoryCategory.FACT.value,
    "facts": MemoryCategory.FACT.value,
    "general_fact": MemoryCategory.FACT.value,
    "context": MemoryCategory.CONTEXT.value,
    "project_context": MemoryCategory.CONTEXT.value,
    "alias": MemoryCategory.ALIAS.value,
    "aliases": MemoryCategory.ALIAS.value,
    "task_context": MemoryCategory.TASK_CONTEXT.value,
    "personal_info": MemoryCategory.USER_PROFILE.value,
    "user_profile": MemoryCategory.USER_PROFILE.value,
    "profile": MemoryCategory.USER_PROFILE.value,
}

def normalize_category(cat: str) -> str:
    """Normalizes any category alias to standard MemoryCategory."""
    if not cat:
        return MemoryCategory.FACT.value
    clean = cat.strip().lower()
    return CATEGORY_NORMALIZATION_MAP.get(clean, cat.upper())

class MemoryCreate(BaseModel):
    category: str = Field(default=MemoryCategory.FACT.value, description="Memory classification category")
    content: str = Field(..., min_length=1, max_length=2000, description="Memory content text")
    key: Optional[str] = Field(default=None, description="Optional canonical key for structured preferences")
    value: Optional[str] = Field(default=None, max_length=2000, description="Optional structured value")
    source: str = Field(default="explicit_user_request", description="Memory origin source")
    importance: float = Field(default=0.8, ge=0.0, le=1.0, description="Importance weight rating (0.0 to 1.0)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Numeric confidence rating (0.0 to 1.0)")
    confidence_level: str = Field(default="EXPLICIT", description="Categorical confidence: EXPLICIT, HIGH, MEDIUM, LOW")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata dictionary")
    expires_at: Optional[str] = Field(default=None, description="Optional ISO timestamp expiration date")

class MemoryUpdate(BaseModel):
    category: Optional[str] = None
    content: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    key: Optional[str] = None
    value: Optional[str] = Field(default=None, max_length=2000)
    importance: Optional[float] = None
    confidence: Optional[float] = None
    confidence_level: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None

class MemoryItem(BaseModel):
    id: str
    category: str
    content: str
    key: Optional[str] = None
    value: Optional[str] = None
    source: str = "explicit_user_request"
    confidence: float = 1.0
    confidence_level: str = "EXPLICIT"
    importance: float = 0.8
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None

class MemoryListResponse(BaseModel):
    count: int
    memories: List[MemoryItem]

class ActiveProjectContext(BaseModel):
    project_name: str
    workspace_path: Optional[str] = None
    framework: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    updated_at: str

SENSITIVE_PATTERNS = [
    r"gsk_[a-zA-Z0-9_-]+",                            # Groq API Keys
    r"AIzaSy[a-zA-Z0-9_-]+",                          # Google API Keys
    r"sk-[a-zA-Z0-9]{32,}",                           # OpenAI API Keys
    r"ghp_[a-zA-Z0-9]{36,}",                          # GitHub Personal Access Token
    r"github_pat_[a-zA-Z0-9_]{50,}",                  # GitHub Fine-grained PAT
    r"(?:password|passwd|pwd)\s*(?:is|=|:)\s*\S+",    # Passwords (e.g. password is 12345, pwd=xyz)
    r"(?:my\s+password\s+is\s+)\S+",                  # "my password is ..."
    r"(?:remember\s+(?:my\s+)?password\s+is\s+)\S+",  # "remember my password is ..."
    r"(?:pairing\s+secret|secret\s+key)\s*(?:is|=|:)\s*\S+", # Pairing secrets
    r"(?:device_token|auth_token|access_token|api_key)\s*(?:is|=|:)\s*\S+", # Auth tokens
    r"bearer\s+[a-zA-Z0-9_\-\.]{20,}",                # Bearer tokens
    r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP)?\s*PRIVATE KEY-----", # Private keys
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",       # Credit card numbers
    r"\b\d{3}-\d{2}-\d{4}\b",                         # SSN
]

def is_sensitive_content(text: str) -> bool:
    """
    Strictly checks if text contains private credentials, API keys, passwords,
    pairing secrets, device tokens, or private keys.
    """
    if not text:
        return False
    t_lower = text.strip().lower()
    
    # Check for direct phrase mentions of password setting
    if re.search(r"\b(?:password|passwd|pwd)\s*(?:is|=|:|\b)", t_lower) and any(w in t_lower for w in ["remember", "is", "set", "save"]):
        if re.search(r"password\s*(?:is\s*|:\s*|=\s*)\S+", t_lower) or "my password is" in t_lower:
            return True

    # Check for API key / secret phrases
    if any(k in t_lower for k in ["api_key is", "api key is", "secret is", "token is", "device token is", "private key is"]):
        return True

    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
            
    return False
