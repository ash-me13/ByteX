from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any

class AIProvider(ABC):
    """Abstract base class for all ByteX AI Providers."""
    
    @abstractmethod
    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """Generates a complete response synchronously/async."""
        pass

    @abstractmethod
    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncGenerator[str, None]:
        """Streams response tokens/chunks progressively."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verifies provider API availability."""
        pass
