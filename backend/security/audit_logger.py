import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger("bytex.audit_logger")

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
LOG_FILE = STORAGE_DIR / "action_logs.json"

class AuditLogger:
    """Action auditor logging local tool executions safely."""
    
    def __init__(self, log_file: Path = LOG_FILE):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            self._write_logs([])

    def _read_logs(self) -> List[Dict[str, Any]]:
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[AuditLogger] Read exception: {e}")
            return []

    def _write_logs(self, logs: List[Dict[str, Any]]):
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2)
        except Exception as e:
            logger.error(f"[AuditLogger] Write exception: {e}")

    def log_action(self, tool_name: str, status: str, details: str):
        logs = self._read_logs()
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "actor": "ByteX",
            "tool": tool_name,
            "status": status.upper(),
            "details": details,
        }
        logs.append(entry)
        # Keep last 200 log entries
        self._write_logs(logs[-200:])

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        logs = self._read_logs()
        return list(reversed(logs[-limit:]))

audit_logger = AuditLogger()
