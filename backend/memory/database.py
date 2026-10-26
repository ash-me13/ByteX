import sqlite3
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("bytex.memory_db")

DB_PATH = Path(__file__).resolve().parent.parent / "bytex_memory.db"

class DatabaseManager:
    """SQLite Database Manager for ByteX Persistent Memory."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes memories and user_preferences tables and indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    importance REAL DEFAULT 0.8,
                    key TEXT,
                    value TEXT,
                    source TEXT DEFAULT 'explicit_user_request',
                    confidence REAL DEFAULT 1.0,
                    confidence_level TEXT DEFAULT 'EXPLICIT',
                    last_used_at TEXT,
                    metadata_json TEXT,
                    expires_at TEXT
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)
            """)

            # Safe column migration for existing databases
            cursor.execute("PRAGMA table_info(memories)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if "key" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN key TEXT")
            if "value" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN value TEXT")
            if "source" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'explicit_user_request'")
            if "confidence" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0")
            if "confidence_level" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN confidence_level TEXT DEFAULT 'EXPLICIT'")
            if "last_used_at" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN last_used_at TEXT")
            if "metadata_json" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN metadata_json TEXT")
            if "expires_at" not in existing_cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN expires_at TEXT")
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)
            """)

            # Active Project Context table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_project_context (
                    id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    workspace_path TEXT,
                    framework TEXT,
                    metadata_json TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_preferences_category ON user_preferences(category)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_history (
                    task_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0.0,
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_history_timestamp ON task_history(timestamp DESC)
            """)

            cursor.execute("PRAGMA table_info(task_history)")
            existing_task_cols = {row["name"] for row in cursor.fetchall()}
            if "summary" not in existing_task_cols:
                cursor.execute("ALTER TABLE task_history ADD COLUMN summary TEXT")
            if "recovery_occurred" not in existing_task_cols:
                cursor.execute("ALTER TABLE task_history ADD COLUMN recovery_occurred INTEGER DEFAULT 0")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_routines (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automations (
                    automation_id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    trigger TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    conditions TEXT,
                    steps_json TEXT NOT NULL,
                    requires_confirmation INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at REAL,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    schedule_type TEXT DEFAULT 'COMMAND',
                    schedule_details TEXT,
                    next_run_at REAL,
                    last_result TEXT,
                    last_error TEXT,
                    max_retries INTEGER DEFAULT 1,
                    retry_count INTEGER DEFAULT 0,
                    timeout_seconds INTEGER DEFAULT 60
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_automations_name ON automations(name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_automations_trigger ON automations(trigger)
            """)

            # Safe column migration for automations table
            cursor.execute("PRAGMA table_info(automations)")
            existing_auto_cols = {row["name"] for row in cursor.fetchall()}
            if "schedule_type" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN schedule_type TEXT DEFAULT 'COMMAND'")
            if "schedule_details" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN schedule_details TEXT")
            if "next_run_at" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN next_run_at REAL")
            if "last_result" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN last_result TEXT")
            if "last_error" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN last_error TEXT")
            if "max_retries" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN max_retries INTEGER DEFAULT 1")
            if "retry_count" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN retry_count INTEGER DEFAULT 0")
            if "timeout_seconds" not in existing_auto_cols:
                cursor.execute("ALTER TABLE automations ADD COLUMN timeout_seconds INTEGER DEFAULT 60")

            conn.commit()

db_manager = DatabaseManager()
