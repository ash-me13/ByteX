import os
from pathlib import Path
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Settings(BaseModel):
    PROJECT_NAME: str = "ByteX AI Core"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"
    
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    
    AI_PRIMARY_PROVIDER: str = os.getenv("AI_PRIMARY_PROVIDER") or os.getenv("PRIMARY_AI_PROVIDER") or "groq"
    AI_FALLBACK_PROVIDER: str = os.getenv("AI_FALLBACK_PROVIDER") or os.getenv("FALLBACK_AI_PROVIDER") or "gemini"
    
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

settings = Settings()
