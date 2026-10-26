from typing import List, Tuple, Optional
from memory.manager import memory_manager
from memory.retrieval import memory_retriever
from memory.preferences import preference_manager, UserPreference
from memory.models import MemoryItem, MemoryCreate, MemoryListResponse

class MemoryService:
    @staticmethod
    def get_all(category: Optional[str] = None) -> MemoryListResponse:
        memories = memory_manager.get_all_memories(category=category)
        return MemoryListResponse(count=len(memories), memories=memories)

    @staticmethod
    def create(payload: MemoryCreate) -> Tuple[bool, str, Optional[MemoryItem]]:
        return memory_manager.add_memory(
            content=payload.content,
            category=payload.category,
            key=payload.key,
            value=payload.value,
            source=payload.source,
            importance=payload.importance,
            confidence=payload.confidence
        )

    @staticmethod
    def delete(memory_id: str) -> bool:
        return memory_manager.delete_memory(memory_id)

    @staticmethod
    def clear_all() -> int:
        return memory_manager.clear_all_memories()

    @staticmethod
    def get_preference(key: str) -> Optional[UserPreference]:
        return preference_manager.get_preference(key)

    @staticmethod
    def get_all_preferences() -> List[UserPreference]:
        return preference_manager.get_all_preferences()

    @staticmethod
    def set_preference(key: str, value: str) -> Tuple[bool, str, Optional[UserPreference]]:
        return preference_manager.set_explicit_preference(key, value)

    @staticmethod
    def delete_preference(key: str) -> bool:
        return preference_manager.delete_preference(key)

    @staticmethod
    def get_context_for_prompt(prompt: str) -> str:
        """
        Retrieves and formats relevant user memories and preferences for AI System Prompt context.
        Applies strict priority rules: Current prompt instructions ALWAYS override stored memories.
        """
        context_parts = []

        # 1. Relevant Preferences
        rel_prefs = preference_manager.get_relevant_preferences(prompt)
        if rel_prefs:
            pref_lines = ["\n[STORED USER PREFERENCES]"]
            for p in rel_prefs:
                pref_lines.append(f"- [{p.key.upper()}]: {p.value}")
            context_parts.append("\n".join(pref_lines))

        # 2. Relevant Memories
        relevant_memories = memory_retriever.get_relevant_memories(prompt, limit=5)
        if relevant_memories:
            memory_lines = ["\n[RELEVANT LONG-TERM MEMORY]"]
            for m in relevant_memories:
                memory_lines.append(f"- [{m.category}] {m.content}")
            context_parts.append("\n".join(memory_lines))

        if context_parts:
            context_parts.append(
                "\n[MEMORY PRIORITY INSTRUCTIONS]\n"
                "1. The user's current explicit instruction in this message ALWAYS overrides any stored memory or preference.\n"
                "2. If the user explicitly asks for a detailed explanation, provide a detailed explanation even if a concise preference is stored."
            )
            return "\n".join(context_parts)

        return ""

memory_service = MemoryService()
