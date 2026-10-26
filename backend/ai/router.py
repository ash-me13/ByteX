import logging
import re
from typing import AsyncGenerator, List, Dict, Any
from ai.providers.groq_provider import GroqProvider
from ai.providers.gemini_provider import GeminiProvider
from ai.prompts.system import get_system_prompt
from ai.stream_safety import ThinkStripper
from config.settings import settings

logger = logging.getLogger("bytex.ai_router")

class StreamInterrupted(Exception):
    """A provider failed AFTER some text had already been forwarded. The caller must not run tools on the partial
    text and must not restart the answer with another provider (the user may already have heard the first part)."""


class AIRouter:
    """Intelligent Router with automatic failover (Groq -> Gemini -> Friendly Error)."""
    
    def __init__(self):
        self.groq_provider = GroqProvider()
        self.gemini_provider = GeminiProvider()

    def _prepare_messages(self, user_history: List[Dict[str, str]], memory_context: str = "") -> List[Dict[str, str]]:
        system_content = get_system_prompt()
        if memory_context:
            system_content += f"\n{memory_context}"
            
        messages = [{"role": "system", "content": system_content}]
        messages.extend(user_history[-10:])
        return messages

    async def stream_response(self, history: List[Dict[str, str]], memory_context: str = "") -> AsyncGenerator[str, None]:
        """Streams AI responses with relevant memory context injection and failover."""
        messages = self._prepare_messages(history, memory_context)

        # 1. Primary Provider: Groq. Chunks are forwarded as they arrive (reasoning blocks removed incrementally).
        if settings.AI_PRIMARY_PROVIDER == "groq" and self.groq_provider.api_key:
            print("[AI Router] Primary provider: Groq")
            stripper = ThinkStripper()
            emitted = False
            try:
                async for chunk in self.groq_provider.stream(messages):
                    text = stripper.feed(chunk)
                    if text:
                        emitted = True
                        yield text
                tail = stripper.flush()
                if tail:
                    emitted = True
                    yield tail
                if emitted:
                    return
                # The whole answer was inside <think>: fall back to the concluding line of the reasoning.
                inner = stripper.reasoning_text().strip()
                if inner:
                    lines = [l.strip() for l in inner.split('\n') if l.strip() and not l.strip().startswith('Thinking') and not l.strip().startswith('1.') and not l.strip().startswith('2.') and not l.strip().startswith('*Self')]
                    if lines:
                        yield lines[-1]
                        return
            except Exception as e:
                if emitted:
                    # Text was already forwarded (and possibly spoken): never restart with another provider.
                    logger.warning(f"[AI Router] Groq stream interrupted mid-response ({type(e).__name__})")
                    raise StreamInterrupted("groq") from e
                logger.warning(f"[AI Router] Groq failed, trying Gemini: {e}")
                print(f"[AI Router] Groq failed, trying Gemini: {e}")

        # 2. Fallback Provider: Gemini
        if self.gemini_provider.api_key:
            has_yielded = False
            try:
                async for chunk in self.gemini_provider.stream(messages):
                    has_yielded = True
                    yield chunk
                if has_yielded:
                    return
            except Exception as e:
                if has_yielded:
                    logger.warning(f"[AI Router] Gemini stream interrupted mid-response ({type(e).__name__})")
                    raise StreamInterrupted("gemini") from e
                logger.error(f"[AI Router] Gemini failed: {e}")
                print(f"[AI Router] Gemini failed: {e}")

        # 3. Graceful Error Event Output
        print("[AI Router] All providers failed. Emitting safe fallback message.")
        yield "ByteX AI is currently unavailable. Check the backend provider configuration."

ai_router = AIRouter()
