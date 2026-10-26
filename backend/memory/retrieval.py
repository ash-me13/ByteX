import re
from typing import List, Optional, Dict
from memory.database import db_manager
from memory.models import MemoryItem, MemoryCategory

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "to", "from", "in", "out",
    "on", "off", "over", "under", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "s", "t",
    "can", "will", "just", "don", "should", "now", "me", "my", "myself",
    "i", "you", "your", "what", "which", "who", "whom", "this", "that",
    "please", "tell", "give", "help"
}

# Actions that are self-contained and should NOT be polluted with unrelated coding/profile memories
AUTOMATION_KEYWORDS = {
    "open", "launch", "close", "quit", "exit", "click", "tap", "type", "press",
    "screenshot", "battery", "cpu", "ram", "system stats", "volume", "mute"
}

INTENT_KEY_MAP = {
    "editor": ["preferred_editor", "editor"],
    "browser": ["preferred_browser", "browser"],
    "project": ["main_project", "project", "active_project"],
    "language": ["preferred_language", "coding_language_dsa"],
    "theme": ["theme"],
}

class MemoryRetriever:
    """Relevance Ranker for ByteX Persistent Memory 2.0 Context Retrieval."""
    
    @staticmethod
    def extract_keywords(prompt: str) -> List[str]:
        words = re.findall(r"\b[a-zA-Z0-9_\+\#-]{2,}\b", prompt.lower())
        return [w for w in words if w not in STOP_WORDS]

    @classmethod
    def get_relevant_memories(cls, prompt: str, category: Optional[str] = None, limit: int = 5) -> List[MemoryItem]:
        """
        Retrieves top relevant stored memories matching prompt keywords and general interaction preferences.
        Guards against polluting pure PC automation commands with unrelated domain facts.
        """
        clean_prompt = prompt.strip().lower()
        keywords = cls.extract_keywords(prompt)

        # Check if the prompt is an automation/telemetry command
        is_automation = any(clean_prompt.startswith(f"{ak} ") or clean_prompt == ak for ak in AUTOMATION_KEYWORDS)

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                if category and category.upper() != "ALL":
                    cursor.execute("SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC", (category,))
                else:
                    cursor.execute("SELECT * FROM memories ORDER BY updated_at DESC")
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[MEMORY] Retrieval database error: {e}")
            return []

        if not rows:
            return []

        all_memories = []
        for r in rows:
            d = dict(r)
            all_memories.append(MemoryItem(
                id=d["id"],
                category=d["category"],
                content=d["content"],
                key=d.get("key"),
                value=d.get("value"),
                source=d.get("source", "explicit_user_request"),
                confidence=d.get("confidence", 1.0),
                confidence_level=d.get("confidence_level", "EXPLICIT"),
                importance=d.get("importance", 0.8),
                created_at=d["created_at"],
                updated_at=d["updated_at"],
                last_used_at=d.get("last_used_at"),
                expires_at=d.get("expires_at")
            ))

        scored_memories = []

        # Check for target abstract intents in prompt (e.g., "my editor", "my browser", "my project")
        for topic, target_keys in INTENT_KEY_MAP.items():
            if topic in clean_prompt:
                for item in all_memories:
                    if item.key in target_keys or (item.value and topic in item.content.lower()):
                        scored_memories.append((15.0, item))

        for item in all_memories:
            content_lower = item.content.lower()
            key_lower = (item.key or "").lower()
            cat_upper = item.category.upper()

            # Global style preferences (e.g. response_style) apply to informational Q&A
            if not is_automation and (item.key == "response_style" or "concise" in content_lower or "detailed" in content_lower or "bullet" in content_lower):
                scored_memories.append((10.0, item))
                continue

            # If pure automation command and memory is not application/project preference, skip
            if is_automation and cat_upper not in ["APPLICATION_PREFERENCE", "PROJECT", "USER_PREFERENCE"]:
                continue

            # Keyword matching score
            match_count = sum(1 for kw in keywords if kw in content_lower or (key_lower and kw in key_lower))
            if match_count > 0:
                rank_score = (match_count * 3.0) + (item.importance * 2.0)
                scored_memories.append((rank_score, item))

        # Sort descending by rank score and remove duplicate items
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        
        seen_ids = set()
        unique_results = []
        for _, item in scored_memories:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                unique_results.append(item)
            if len(unique_results) >= limit:
                break

        return unique_results

memory_retriever = MemoryRetriever()
