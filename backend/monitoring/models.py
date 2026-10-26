from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum

class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class SystemMetricSnapshot:
    """Read-only telemetry snapshot of current hardware metrics."""
    cpu_percent: float
    ram_percent: float
    ram_available_gb: float
    ram_total_gb: float
    disk_percent: float
    disk_free_gb: float
    battery_percent: Optional[float]
    battery_plugged: Optional[bool]
    network_online: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class SystemEvent:
    """Structured telemetry event emitted on significant state changes."""
    event_type: str
    timestamp: str
    severity: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "metadata": self.metadata,
        }

@dataclass
class MonitoringConfig:
    """Configurable polling and threshold settings for live monitoring."""
    polling_interval_seconds: float = 5.0
    cpu_high_threshold: float = 90.0
    cpu_clear_threshold: float = 85.0
    ram_high_threshold: float = 90.0
    ram_clear_threshold: float = 85.0
    battery_low_threshold: float = 15.0
    battery_clear_threshold: float = 20.0
    disk_high_threshold: float = 90.0
    disk_clear_threshold: float = 85.0
    enabled: bool = True
