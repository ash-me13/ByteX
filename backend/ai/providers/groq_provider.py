import logging
from typing import AsyncGenerator, List, Dict, Any
from ai.providers.base import AIProvider
from config.settings import settings

logger = logging.getLogger("bytex.groq_provider")

class GroqProvider(AIProvider):
    """Native Async Groq LLM Provider implementation using high-performance active Groq models."""
    
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self.client = None
        
        if self.api_key:
            try:
                from groq import AsyncGroq
                self.client = AsyncGroq(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"[GroqProvider] Failed to initialize AsyncGroq client: {e}")

    async def health_check(self) -> bool:
        if not self.client:
            return False
        try:
            await self.client.models.list()
            return True
        except Exception as e:
            logger.warning(f"[GroqProvider] Health check failed: {e}")
            return False

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        chunks = []
        async for chunk in self.stream(messages, **kwargs):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncGenerator[str, None]:
        if not self.client:
            raise RuntimeError("GROQ_API_KEY is not configured.")

        # Prioritize verified, active models on Groq that return immediate direct responses
        models_to_try = [
            self.model,
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant"
        ]
        
        # Deduplicate models while keeping priority order
        seen = set()
        unique_models = []
        for m in models_to_try:
            if m and m not in seen:
                seen.add(m)
                unique_models.append(m)

        last_exception = None

        for m in unique_models:
            started = False
            try:
                stream_res = await self.client.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.5),
                    max_tokens=kwargs.get("max_tokens", 1024),
                    stream=True,
                )
                async for chunk in stream_res:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        started = True
                        yield delta
                return
            except Exception as ex:
                if started:
                    # Text was already streamed out: retrying another model would duplicate / contradict it.
                    logger.warning(f"[GroqProvider] Model '{m}' failed mid-stream ({type(ex).__name__})")
                    raise
                last_exception = ex
                logger.warning(f"[GroqProvider] Model '{m}' failed: {ex}")
                print(f"[GroqProvider] Model '{m}' failed: {ex}")
                continue

        if last_exception:
            raise last_exception
        raise RuntimeError("Groq Provider failed on all model options.")
