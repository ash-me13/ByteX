import uuid
import re
import json
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
from memory.database import db_manager
from memory.models import (
    MemoryItem, MemoryCreate, MemoryUpdate, MemoryCategory,
    normalize_category, is_sensitive_content, ActiveProjectContext
)

MAX_MEMORY_COUNT = 1000
MAX_CONTENT_LENGTH = 2000
MAX_VALUE_LENGTH = 2000

def extract_memory_metadata(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extracts canonical category, key, and value from natural language memory content.
    Returns: (category, key, value)
    """
    t_clean = text.strip()
    t_lower = t_clean.lower()

    # 1. Editor Preference
    if any(e in t_lower for e in ["vscode", "vs code", "cursor", "notepad", "sublime", "vim", "pycharm", "intellij"]):
        for e in ["vscode", "vs code", "cursor", "notepad", "sublime", "vim", "pycharm", "intellij"]:
            if e in t_lower:
                val = "VS Code" if e in ["vscode", "vs code"] else e.title()
                return MemoryCategory.APPLICATION_PREFERENCE.value, "preferred_editor", val

    # 2. Browser Preference
    if any(b in t_lower for b in ["chrome", "edge", "brave", "firefox", "opera", "safari"]):
        for b in ["edge", "chrome", "brave", "firefox", "opera", "safari"]:
            if b in t_lower:
                return MemoryCategory.APPLICATION_PREFERENCE.value, "preferred_browser", b.capitalize()

    # 3. Project Information & Tech Stack
    m_proj = re.search(r"(?:project|working on)\s+(?:is|called)?\s*([a-zA-Z0-9_\-\s]+)", t_lower)
    if m_proj or "project" in t_lower:
        val = m_proj.group(1).strip() if m_proj else t_clean
        return MemoryCategory.PROJECT.value, "main_project", val

    # 4. Programming Language / DSA
    if "c++" in t_lower or "cpp" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "coding_language_dsa", "C++"
    if "python" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "preferred_language", "Python"
    if "rust" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "preferred_language", "Rust"
    if "javascript" in t_lower or "typescript" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "preferred_language", "TypeScript"

    # 5. Response Style Preference
    if any(w in t_lower for w in ["concise", "brief", "short answers", "detailed", "bullet points", "in simple terms"]):
        val = "concise" if any(w in t_lower for w in ["concise", "brief", "short"]) else "detailed" if "detailed" in t_lower else "bullet_points"
        return MemoryCategory.USER_PREFERENCE.value, "response_style", val

    # 6. Theme Preference
    if "dark mode" in t_lower or "dark theme" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "theme", "dark"
    if "light mode" in t_lower or "light theme" in t_lower:
        return MemoryCategory.USER_PREFERENCE.value, "theme", "light"

    # 7. User Profile / Personal Info
    m_name = re.search(r"(?:my name is|call me|i am)\s+([a-zA-Z0-9_\s]+)", t_clean, re.IGNORECASE)
    if m_name:
        return MemoryCategory.USER_PREFERENCE.value, "user_name", m_name.group(1).strip()

    # Default category classification
    if any(w in t_lower for w in ["prefer", "like", "love", "favorite", "always use", "default", "use"]):
        return MemoryCategory.USER_PREFERENCE.value, None, None
    elif any(w in t_lower for w in ["workflow", "routine", "every morning", "step by step", "daily"]):
        return MemoryCategory.WORKFLOW.value, None, None
    elif any(w in t_lower for w in ["alias", "call", "shortcut"]):
        return MemoryCategory.ALIAS.value, None, None

    return MemoryCategory.FACT.value, None, None

class MemoryManager:
    """Central Persistent Memory 2.0 Manager handling storage, conflict resolution, & context."""
    
    @classmethod
    def add_memory(
        cls,
        content: str,
        category: Optional[str] = None,
        key: Optional[str] = None,
        value: Optional[str] = None,
        source: str = "explicit_user_request",
        importance: float = 0.8,
        confidence: float = 1.0,
        confidence_level: str = "EXPLICIT",
        metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MemoryItem]]:
        """
        Saves or updates a persistent memory entry in SQLite with automatic conflict resolution.
        """
        clean_content = content.strip()
        if not clean_content:
            return False, "Memory content cannot be empty.", None

        if len(clean_content) > MAX_CONTENT_LENGTH:
            return False, f"Memory content exceeds maximum limit of {MAX_CONTENT_LENGTH} characters.", None

        if is_sensitive_content(clean_content):
            return False, "I can't store passwords or authentication secrets in memory.", None

        # Check total count limit
        all_existing = cls.get_all_memories()
        if len(all_existing) >= MAX_MEMORY_COUNT:
            return False, f"Memory storage limit reached ({MAX_MEMORY_COUNT} memories). Please delete old memories before saving new ones.", None

        # Auto-derive metadata if not explicitly provided
        derived_cat, derived_key, derived_val = extract_memory_metadata(clean_content)
        final_cat = normalize_category(category) if category else derived_cat
        final_key = key or derived_key
        final_val = value or derived_val
        meta_json = json.dumps(metadata) if metadata else None

        now_iso = datetime.utcnow().isoformat()

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # 1. Conflict Check: Look for existing memory matching canonical key or exact topic
                existing_id = None
                if final_key:
                    cursor.execute("SELECT id FROM memories WHERE key = ?", (final_key,))
                    row = cursor.fetchone()
                    if row:
                        existing_id = row["id"]

                if not existing_id:
                    # Check for similar content substring in same category
                    cursor.execute("SELECT id, content, key FROM memories WHERE category = ?", (final_cat,))
                    for row in cursor.fetchall():
                        ex_content = row["content"].lower()
                        if final_key and final_key.replace("_", " ") in ex_content:
                            existing_id = row["id"]
                            break

                # 2. Update existing or Insert new
                if existing_id:
                    cursor.execute(
                        """
                        UPDATE memories
                        SET category = ?, content = ?, key = ?, value = ?, source = ?, updated_at = ?,
                            importance = ?, confidence = ?, confidence_level = ?, metadata_json = ?, expires_at = ?
                        WHERE id = ?
                        """,
                        (final_cat, clean_content, final_key, final_val, source, now_iso,
                         importance, confidence, confidence_level, meta_json, expires_at, existing_id)
                    )
                    conn.commit()
                    item = MemoryItem(
                        id=existing_id,
                        category=final_cat,
                        content=clean_content,
                        key=final_key,
                        value=final_val,
                        source=source,
                        confidence=confidence,
                        confidence_level=confidence_level,
                        importance=importance,
                        created_at=now_iso,
                        updated_at=now_iso,
                        metadata=metadata,
                        expires_at=expires_at
                    )
                    print(f"[MEMORY] Memory updated: {existing_id[:8]}*** (Key: {final_key})")
                    return True, "Memory updated successfully.", item
                else:
                    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
                    cursor.execute(
                        """
                        INSERT INTO memories (id, category, content, key, value, source, created_at, updated_at,
                                              importance, confidence, confidence_level, metadata_json, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (memory_id, final_cat, clean_content, final_key, final_val, source, now_iso, now_iso,
                         importance, confidence, confidence_level, meta_json, expires_at)
                    )
                    conn.commit()
                    item = MemoryItem(
                        id=memory_id,
                        category=final_cat,
                        content=clean_content,
                        key=final_key,
                        value=final_val,
                        source=source,
                        confidence=confidence,
                        confidence_level=confidence_level,
                        importance=importance,
                        created_at=now_iso,
                        updated_at=now_iso,
                        metadata=metadata,
                        expires_at=expires_at
                    )
                    print(f"[MEMORY] Memory created: {memory_id[:8]}*** (Category: {final_cat})")
                    return True, "Memory saved successfully.", item
        except Exception as e:
            print(f"[MEMORY] Storage failure: {e}")
            return False, "I couldn't save that memory.", None

    @classmethod
    def get_memory(cls, memory_id: str) -> Optional[MemoryItem]:
        """Retrieves a single memory by ID and updates its last_used_at timestamp."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                
                now_iso = datetime.utcnow().isoformat()
                cursor.execute("UPDATE memories SET last_used_at = ? WHERE id = ?", (now_iso, memory_id))
                conn.commit()

                d = dict(row)
                meta = json.loads(d["metadata_json"]) if d.get("metadata_json") else None
                return MemoryItem(
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
                    last_used_at=now_iso,
                    metadata=meta,
                    expires_at=d.get("expires_at")
                )
        except Exception as e:
            print(f"[MEMORY] Error fetching memory: {e}")
            return None

    @classmethod
    def update_memory(cls, memory_id: str, updates: MemoryUpdate) -> Tuple[bool, str, Optional[MemoryItem]]:
        """Updates an existing memory entry."""
        if updates.content and is_sensitive_content(updates.content):
            return False, "I can't store passwords or authentication secrets in memory.", None

        now_iso = datetime.utcnow().isoformat()
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
                row = cursor.fetchone()
                if not row:
                    return False, "Memory not found.", None

                curr = dict(row)
                new_cat = normalize_category(updates.category) if updates.category else curr["category"]
                new_content = updates.content.strip() if updates.content else curr["content"]
                new_key = updates.key if updates.key is not None else curr.get("key")
                new_val = updates.value if updates.value is not None else curr.get("value")
                new_imp = updates.importance if updates.importance is not None else curr.get("importance", 0.8)
                new_conf = updates.confidence if updates.confidence is not None else curr.get("confidence", 1.0)
                new_conf_lvl = updates.confidence_level or curr.get("confidence_level", "EXPLICIT")
                new_meta = json.dumps(updates.metadata) if updates.metadata is not None else curr.get("metadata_json")
                new_exp = updates.expires_at if updates.expires_at is not None else curr.get("expires_at")

                cursor.execute(
                    """
                    UPDATE memories
                    SET category = ?, content = ?, key = ?, value = ?, importance = ?, confidence = ?,
                        confidence_level = ?, metadata_json = ?, expires_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_cat, new_content, new_key, new_val, new_imp, new_conf, new_conf_lvl, new_meta, new_exp, now_iso, memory_id)
                )
                conn.commit()

                item = MemoryItem(
                    id=memory_id,
                    category=new_cat,
                    content=new_content,
                    key=new_key,
                    value=new_val,
                    source=curr.get("source", "explicit_user_request"),
                    confidence=new_conf,
                    confidence_level=new_conf_lvl,
                    importance=new_imp,
                    created_at=curr["created_at"],
                    updated_at=now_iso,
                    metadata=updates.metadata,
                    expires_at=new_exp
                )
                print(f"[MEMORY] Memory updated: {memory_id[:8]}***")
                return True, "Memory updated successfully.", item
        except Exception as e:
            print(f"[MEMORY] Update failure: {e}")
            return False, "I couldn't update that memory.", None

    @classmethod
    def delete_memory(cls, memory_id: str) -> bool:
        """Deletes a single memory by ID."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    print(f"[MEMORY] Memory deleted: {memory_id[:8]}***")
                return deleted
        except Exception as e:
            print(f"[MEMORY] Deletion error: {e}")
            return False

    @classmethod
    def clear_all_memories(cls) -> int:
        """Clears all memories from database."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM memories")
                count = cursor.rowcount
                cursor.execute("DELETE FROM user_preferences")
                cursor.execute("DELETE FROM active_project_context")
                conn.commit()
                print(f"[MEMORY] All memories cleared ({count} records).")
                return count
        except Exception as e:
            print(f"[MEMORY] Clear error: {e}")
            return 0

    @classmethod
    def get_all_memories(cls, category: Optional[str] = None, search: Optional[str] = None) -> List[MemoryItem]:
        """Retrieves all stored memories with optional category and keyword search filters."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                if category and category.upper() != "ALL":
                    norm_cat = normalize_category(category)
                    cursor.execute("SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC", (norm_cat,))
                else:
                    cursor.execute("SELECT * FROM memories ORDER BY updated_at DESC")
                rows = cursor.fetchall()
                
                items = []
                for r in rows:
                    d = dict(r)
                    meta = json.loads(d["metadata_json"]) if d.get("metadata_json") else None
                    item = MemoryItem(
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
                        metadata=meta,
                        expires_at=d.get("expires_at")
                    )
                    items.append(item)

                if search and search.strip():
                    q = search.strip().lower()
                    items = [it for it in items if q in it.content.lower() or (it.key and q in it.key.lower()) or (it.value and q in it.value.lower())]

                return items
        except Exception as e:
            print(f"[MEMORY] Get all memories error: {e}")
            return []

    @classmethod
    def search_memories(cls, query: str, limit: int = 10) -> List[MemoryItem]:
        """Searches memories relevant to a query string."""
        return cls.get_all_memories(search=query)[:limit]

    # --- ACTIVE PROJECT CONTEXT (Feature #39.24) ---

    @classmethod
    def set_active_project(cls, project_name: str, workspace_path: Optional[str] = None, framework: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> ActiveProjectContext:
        """Sets or updates the current active project context."""
        now_iso = datetime.utcnow().isoformat()
        meta_json = json.dumps(metadata) if metadata else None
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM active_project_context")
            cursor.execute(
                """
                INSERT INTO active_project_context (id, project_name, workspace_path, framework, metadata_json, updated_at)
                VALUES ('active', ?, ?, ?, ?, ?)
                """,
                (project_name, workspace_path, framework, meta_json, now_iso)
            )
            conn.commit()

        # Also register a PROJECT memory for permanent reference
        cls.add_memory(
            content=f"Active project is {project_name}" + (f" at {workspace_path}" if workspace_path else ""),
            category=MemoryCategory.PROJECT.value,
            key="main_project",
            value=project_name
        )

        return ActiveProjectContext(
            project_name=project_name,
            workspace_path=workspace_path,
            framework=framework,
            metadata=metadata,
            updated_at=now_iso
        )

    @classmethod
    def get_active_project(cls) -> Optional[ActiveProjectContext]:
        """Retrieves the active project context if set."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM active_project_context WHERE id = 'active'")
                row = cursor.fetchone()
                if not row:
                    return None
                d = dict(row)
                meta = json.loads(d["metadata_json"]) if d.get("metadata_json") else None
                return ActiveProjectContext(
                    project_name=d["project_name"],
                    workspace_path=d.get("workspace_path"),
                    framework=d.get("framework"),
                    metadata=meta,
                    updated_at=d["updated_at"]
                )
        except Exception as e:
            print(f"[MEMORY] Get active project error: {e}")
            return None

    @classmethod
    def clear_active_project(cls) -> bool:
        """Clears the active project context."""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM active_project_context")
                conn.commit()
                return True
        except Exception as e:
            print(f"[MEMORY] Clear active project error: {e}")
            return False

    @classmethod
    def handle_natural_command(cls, user_message: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        Interprets natural language memory requests (English, Hinglish, Hindi).
        Returns: (is_memory_command, response_text, state, data)
        """
        msg_norm = user_message.strip()
        msg_clean = re.sub(r"[.!?,\"\']+$", "", msg_norm).strip()
        msg_lower = msg_clean.lower()

        # -------------------------------------------------------------
        # 1. Clear All Command (Requires Confirmation)
        # -------------------------------------------------------------
        if msg_lower in [
            "clear all memories",
            "clear my memories",
            "clear memories",
            "clear memory",
            "forget everything you remember about me",
            "forget everything about me",
            "forget all memories",
            "delete all memories",
            "wipe all memories",
            "saari memories delete karo",
            "saari memory bhool jao",
            "सारी मेमोरी भूल जाओ",
            "सब कुछ भूल जाओ",
        ]:
            from core.confirmation import confirmation_manager
            prompt_msg = confirmation_manager.set_pending(
                tool="clear_all_memories",
                action="clear_all_memories",
                description="This will permanently delete all saved ByteX memories. Continue?",
                arguments={}
            )
            return True, prompt_msg, "speaking", {"confirmation_required": True, "action": "clear_all_memories"}

        # -------------------------------------------------------------
        # 2. Active Project Commands
        # -------------------------------------------------------------
        # Set Active Project
        m_set_proj = re.match(r"^(?:set\s+)?([a-zA-Z0-9_\-\s]+)\s+as\s+(?:my\s+)?active\s+project$", msg_lower)
        if m_set_proj:
            proj_name = m_set_proj.group(1).strip()
            cls.set_active_project(project_name=proj_name)
            return True, f"Active project set to '{proj_name}'.", "speaking", {"active_project": proj_name}

        # What's my active project?
        if msg_lower in [
            "what's my active project",
            "what is my active project",
            "what is my active project?",
            "what's my active project?",
            "show active project",
            "active project",
            "active project kya hai",
            "एक्टिव प्रोजेक्ट क्या है",
        ]:
            act = cls.get_active_project()
            if act:
                return True, f"Your active project is '{act.project_name}'" + (f" ({act.workspace_path})" if act.workspace_path else "") + ".", "speaking", {"active_project": act.model_dump()}
            else:
                return True, "No active project is currently set. You can set one by saying 'Set ByteX as my active project'.", "speaking", None

        # Clear active project
        if msg_lower in [
            "clear active project",
            "remove active project",
            "reset active project",
            "clear active project context",
            "active project hatao",
            "एक्टिव प्रोजेक्ट हटाओ",
        ]:
            cls.clear_active_project()
            return True, "Active project context has been cleared.", "speaking", None

        # -------------------------------------------------------------
        # 3. Query / Inspect Memories Command
        # -------------------------------------------------------------
        if (
            msg_lower in [
                "what do you remember about me",
                "what do you remember",
                "what do you remember about me?",
                "what do you remember?",
                "list my memories",
                "show my memories",
                "show memories",
                "what memories do you have",
                "view my memories",
                "show my saved preferences",
                "mere baare mein kya yaad hai",
                "meri preferences dikhao",
                "तुम्हें मेरे बारे में क्या याद है",
                "मेरी मेमोरी दिखाओ",
            ]
            or re.match(r"^what\s+do\s+you\s+remember\s+about\s+(?:my\s+)?(.+)$", msg_lower)
            or re.match(r"^(?:find|show|search)\s+(?:my\s+)?memories\s+about\s+(.+)$", msg_lower)
        ):
            m_target = (
                re.match(r"^what\s+do\s+you\s+remember\s+about\s+(?:my\s+)?(.+)$", msg_lower)
                or re.match(r"^(?:find|show|search)\s+(?:my\s+)?memories\s+about\s+(.+)$", msg_lower)
            )
            query_topic = m_target.group(1).strip().lower() if m_target else None

            all_items = cls.get_all_memories()
            if not all_items:
                return True, "I don't have any saved memories about you yet. You can tell me things like 'Remember that I prefer VS Code.'", "speaking", None

            if query_topic and query_topic not in ["me", "myself", "everything"]:
                matching = []
                for it in all_items:
                    it_text = f"{it.content} {it.key or ''} {it.category}".lower()
                    if any(kw in it_text for kw in query_topic.split()):
                        matching.append(it)
                if matching:
                    lines = [f"Here is what I remember about '{query_topic}':"]
                    for it in matching:
                        lines.append(f"• [{it.category}] {it.content}")
                    return True, "\n".join(lines), "speaking", {"count": len(matching)}
                else:
                    return True, f"I don't have any specific memories about '{query_topic}' yet.", "speaking", None

            lines = [f"Here is what I remember about you ({len(all_items)} item{'s' if len(all_items) != 1 else ''}):"]
            for item in all_items:
                lines.append(f"• [{item.category}] {item.content}")
            return True, "\n".join(lines), "speaking", {"count": len(all_items)}

        # -------------------------------------------------------------
        # 4. Explicit "Remember..." Command (English, Hinglish, Hindi)
        # -------------------------------------------------------------
        remember_match = re.match(
            r"^(?:remember\s+(?:that\s+)?|save\s+this\s+as\s+a\s+preference\s*[:\s]*|don't\s+forget\s+(?:that\s+)?|yaad\s+rakhna\s+(?:ki\s+)?|याद\s+रखना\s+(?:कि\s+)?)(.+)$",
            msg_norm,
            re.IGNORECASE
        )
        if remember_match:
            raw_fact = remember_match.group(1).strip()
            
            # Privacy check
            if is_sensitive_content(raw_fact) or is_sensitive_content(msg_norm):
                return True, "I can't store passwords or authentication secrets in memory.", "speaking", None

            success, message, item = cls.add_memory(content=raw_fact)
            if success:
                return True, f"Got it. I'll remember that: '{raw_fact}'.", "speaking", {"memory": item.model_dump() if item else None}
            else:
                return True, message, "speaking", None

        # -------------------------------------------------------------
        # 5. Explicit "Forget..." Command (English, Hinglish, Hindi)
        # -------------------------------------------------------------
        forget_match = re.match(
            r"^(?:forget\s+(?:that\s+)?|delete\s+memory\s+|remove\s+memory\s+|bhool\s+jao\s+|भूल\s+जाओ\s+)(.+)$",
            msg_norm,
            re.IGNORECASE
        )
        # Also check trailing Hinglish/Hindi: "VS Code wali preference bhool jao"
        trailing_forget = re.search(r"^(.*?)\s*(?:wali\s+preference\s+|ki\s+preference\s+|wali\s+memory\s+)?(?:bhool\s+jao|भूल\s+जाओ)$", msg_norm, re.IGNORECASE)
        
        if forget_match or trailing_forget:
            target_text = forget_match.group(1).strip().lower() if forget_match else trailing_forget.group(1).strip().lower()
            target_text = re.sub(r"^(?:my\s+|the\s+|ki\s+|that\s+)", "", target_text).strip()
            target_text = re.sub(r"\s*(?:preference|memory|info|information)$", "", target_text).strip()
            
            all_mems = cls.get_all_memories()
            deleted_count = 0
            
            for item in all_mems:
                item_content = item.content.lower()
                item_key = (item.key or "").lower()
                item_val = (item.value or "").lower()
                
                if (
                    target_text in item_content
                    or (item_key and (item_key in target_text or target_text in item_key))
                    or (item_val and (item_val in target_text or target_text in item_val))
                    or any(w in item_content for w in target_text.split() if len(w) > 3)
                ):
                    if cls.delete_memory(item.id):
                        deleted_count += 1
            
            if deleted_count > 0:
                return True, f"Forgotten. Removed {deleted_count} matching memory entry.", "speaking", {"deleted_count": deleted_count}
            else:
                return True, f"I couldn't find any memory matching '{target_text}' to forget.", "speaking", None

        return False, None, None, None

memory_manager = MemoryManager()
