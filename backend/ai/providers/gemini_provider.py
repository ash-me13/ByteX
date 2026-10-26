import json
import logging
import httpx
from typing import AsyncGenerator, List, Dict, Any
from ai.providers.base import AIProvider
from config.settings import settings

logger = logging.getLogger("bytex.gemini_provider")


def extract_sse_texts(line: str) -> List[str]:
    """Text parts carried by one Server-Sent-Events line of a streamGenerateContent response ([] for anything else)."""
    line = (line or "").strip()
    if not line.startswith("data:"):
        return []
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return []
    try:
        obj = json.loads(data)
    except ValueError:
        return []
    texts: List[str] = []
    for cand in (obj.get("candidates") or []) if isinstance(obj, dict) else []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            t = part.get("text") if isinstance(part, dict) else None
            if isinstance(t, str) and t:
                texts.append(t)
    return texts


class GeminiProvider(AIProvider):
    """Native Async Gemini Fallback Provider implementation."""
    
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL

    async def health_check(self) -> bool:
        return bool(self.api_key)

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        chunks = []
        async for chunk in self.stream(messages, **kwargs):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        # Build message history prompt
        formatted_prompt = []
        for msg in messages:
            role = "Assistant" if msg["role"] == "assistant" else "User"
            if msg["role"] == "system":
                formatted_prompt.append(f"System: {msg['content']}")
            else:
                formatted_prompt.append(f"{role}: {msg['content']}")
        
        prompt_text = "\n".join(formatted_prompt)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}]
        }

        # Preferred path: real streaming (SSE). If it cannot start (HTTP error, network error, empty stream) we fall
        # back to the single-shot request below. After text has been forwarded we never fall back (no duplicates).
        started = False
        try:
            sse_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}"
            async with httpx.AsyncClient() as sse_client:
                async with sse_client.stream("POST", sse_url, json=payload, timeout=httpx.Timeout(10.0, read=30.0)) as sse_res:
                    if sse_res.status_code == 200:
                        async for line in sse_res.aiter_lines():
                            for text in extract_sse_texts(line):
                                started = True
                                yield text
                        if started:
                            return
                    else:
                        logger.warning(f"[GeminiProvider] Streaming endpoint returned HTTP {sse_res.status_code}; using non-streaming request.")
        except Exception as sse_err:
            if started:
                logger.warning(f"[GeminiProvider] Stream failed mid-response ({type(sse_err).__name__})")
                raise
            logger.warning(f"[GeminiProvider] Streaming unavailable ({type(sse_err).__name__}); using non-streaming request.")

        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                # Stream words cleanly
                words = text.split(" ")
                for i, word in enumerate(words):
                    yield word + (" " if i < len(words) - 1 else "")
            elif res.status_code == 401:
                logger.error("[GeminiProvider] Authentication failed (HTTP 401): Invalid or expired GEMINI_API_KEY.")
                raise RuntimeError("Gemini REST error HTTP 401: Invalid or expired GEMINI_API_KEY.")
            elif res.status_code == 404:
                logger.error(f"[GeminiProvider] Model '{self.model}' not found (HTTP 404).")
                raise RuntimeError(f"Gemini model '{self.model}' not found (HTTP 404).")
            else:
                logger.error(f"[GeminiProvider] HTTP {res.status_code}: {res.text[:200]}")
                raise RuntimeError(f"Gemini REST error HTTP {res.status_code}")
