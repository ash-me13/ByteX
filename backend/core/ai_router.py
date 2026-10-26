import os
import asyncio
import logging
from typing import List, Dict
from config.settings import settings

logger = logging.getLogger("bytex.ai_router")

SYSTEM_PROMPT = (
    "You are ByteX AI, a fast, modern personal desktop AI assistant built for high performance. "
    "Be direct, helpful, concise, and technical when appropriate. Avoid unnecessary conversational fluff."
)

class AIRouter:
    """Intelligent AI Provider Router with Automatic Failover (Groq -> Gemini)."""
    
    def __init__(self):
        self.groq_client = None
        self.gemini_available = bool(settings.GEMINI_API_KEY)
        
        if settings.GROQ_API_KEY:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                logger.warning(f"Groq SDK initialization warning: {e}")

    async def generate_response(self, user_message: str, history: List[Dict[str, str]] = None) -> str:
        """Generates AI response with automatic failover."""
        # 1. Try Groq (Primary)
        if self.groq_client and settings.PRIMARY_AI_PROVIDER == "groq":
            try:
                res = await self._call_groq(user_message, history)
                if res and res.strip():
                    return res.strip()
            except Exception as e:
                logger.warning(f"Groq API call failed, attempting fallback: {e}")

        # 2. Fallback to Gemini
        if self.gemini_available:
            try:
                res = await self._call_gemini(user_message, history)
                if res and res.strip():
                    return res.strip()
            except Exception as e:
                logger.error(f"Gemini API call failed: {e}")

        # 3. Fallback mock response if AI APIs fail
        return f"ByteX AI Core received: '{user_message}'."

    async def _call_groq(self, user_message: str, history: List[Dict[str, str]] = None) -> str:
        """Calls Groq LLM API in an async thread execution."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if history:
            for item in history[-6:]:
                messages.append({"role": item["role"], "content": item["content"]})
                
        messages.append({"role": "user", "content": user_message})

        loop = asyncio.get_running_loop()
        
        def _exec_groq():
            # Try verified Groq models
            models_to_try = [settings.GROQ_MODEL, "qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
            last_err = None
            
            for m in models_to_try:
                try:
                    completion = self.groq_client.chat.completions.create(
                        model=m,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=600,
                    )
                    content = completion.choices[0].message.content
                    if content:
                        return content
                except Exception as ex:
                    last_err = ex
                    continue
                    
            if last_err:
                raise last_err
            return ""

        response_text = await loop.run_in_executor(None, _exec_groq)
        return response_text

    async def _call_gemini(self, user_message: str, history: List[Dict[str, str]] = None) -> str:
        """Calls Gemini API via httpx REST call or SDK."""
        loop = asyncio.get_running_loop()
        
        def _exec_gemini():
            import httpx
            # Try REST call with key
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nUser: {user_message}"}]}]
            }
            res = httpx.post(url, json=payload, timeout=8.0)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            raise Exception(f"Gemini REST error HTTP {res.status_code}")

        response_text = await loop.run_in_executor(None, _exec_gemini)
        return response_text

ai_router = AIRouter()
