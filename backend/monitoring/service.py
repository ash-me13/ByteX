import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, List, Set, Callable, Awaitable, Dict, Any

from monitoring.models import (
    SystemMetricSnapshot,
    SystemEvent,
    MonitoringConfig,
    EventSeverity,
)
from monitoring.collector import SystemMetricsCollector

logger = logging.getLogger("bytex.monitoring")

class LiveSystemMonitor:
    """
    Live System Monitoring Service for ByteX AI Assistant.
    
    Observes hardware metrics periodically (default 5.0s), detects meaningful
    state changes with threshold hysteresis, and produces structured events.
    
    Security & Structural Invariants:
    1. Read-Only: Strictly observes system telemetry; never performs actions or kills processes.
    2. Zero LLM Overhead: Never calls Groq/Gemini APIs during periodic polling.
    3. Single Background Loop: Runs as a single lightweight asyncio task with zero orphan threads.
    4. Stateful Deduplication: Emits events on state transitions rather than spamming every 5 seconds.
    5. Clean Lifecycle: Fully supports start, stop, pause, and resume.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None):
        self.config = config or MonitoringConfig()
        self._is_running: bool = False
        self._is_paused: bool = False
        self._task: Optional[asyncio.Task] = None
        self._latest_snapshot: Optional[SystemMetricSnapshot] = None
        self._active_alert_states: Set[str] = set()
        self._event_history: deque[SystemEvent] = deque(maxlen=100)
        self._event_listeners: List[Callable[[SystemEvent], Awaitable[None]]] = []
        self._poll_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def poll_count(self) -> int:
        return self._poll_count

    async def start(self) -> None:
        """Starts the background live monitoring loop."""
        if self._is_running:
            print("[ByteX LiveMonitor] Service is already running.")
            return

        self._is_running = True
        self._is_paused = False
        self._task = asyncio.create_task(self._monitor_loop(), name="bytex_live_monitor_loop")
        print(f"[ByteX LiveMonitor] Service started (Polling Interval: {self.config.polling_interval_seconds}s)")

    async def stop(self) -> None:
        """Stops the monitoring service and cleans up background tasks."""
        if not self._is_running:
            return

        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        print("[ByteX LiveMonitor] Service stopped cleanly.")

    def pause(self) -> None:
        """Pauses metric evaluation and event emission."""
        self._is_paused = True
        print("[ByteX LiveMonitor] Service paused.")

    def resume(self) -> None:
        """Resumes metric evaluation and event emission."""
        self._is_paused = False
        print("[ByteX LiveMonitor] Service resumed.")

    def get_latest_metrics(self) -> Optional[SystemMetricSnapshot]:
        """Returns the most recent system metrics snapshot."""
        return self._latest_snapshot

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns recent structured telemetry events."""
        events = list(self._event_history)[-limit:]
        return [e.to_dict() for e in events]

    def add_event_listener(self, listener: Callable[[SystemEvent], Awaitable[None]]) -> None:
        """Registers an asynchronous callback for system events."""
        if listener not in self._event_listeners:
            self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[SystemEvent], Awaitable[None]]) -> None:
        """Removes a registered callback."""
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    def evaluate_snapshot(self, snapshot: SystemMetricSnapshot) -> List[SystemEvent]:
        """
        Evaluates a metric snapshot against configured thresholds with stateful hysteresis.
        Returns a list of newly generated events.
        """
        new_events: List[SystemEvent] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. CPU High
        if snapshot.cpu_percent >= self.config.cpu_high_threshold:
            if "CPU_HIGH" not in self._active_alert_states:
                self._active_alert_states.add("CPU_HIGH")
                new_events.append(SystemEvent(
                    event_type="CPU_HIGH",
                    timestamp=now_iso,
                    severity=EventSeverity.WARNING.value,
                    message=f"CPU usage is high ({snapshot.cpu_percent}%).",
                    value=snapshot.cpu_percent,
                    threshold=self.config.cpu_high_threshold,
                ))
        elif snapshot.cpu_percent <= self.config.cpu_clear_threshold:
            if "CPU_HIGH" in self._active_alert_states:
                self._active_alert_states.remove("CPU_HIGH")

        # 2. RAM High
        if snapshot.ram_percent >= self.config.ram_high_threshold:
            if "RAM_HIGH" not in self._active_alert_states:
                self._active_alert_states.add("RAM_HIGH")
                new_events.append(SystemEvent(
                    event_type="RAM_HIGH",
                    timestamp=now_iso,
                    severity=EventSeverity.WARNING.value,
                    message=f"RAM usage is high ({snapshot.ram_percent}%). Available: {snapshot.ram_available_gb} GB.",
                    value=snapshot.ram_percent,
                    threshold=self.config.ram_high_threshold,
                    metadata={"available_gb": snapshot.ram_available_gb, "total_gb": snapshot.ram_total_gb},
                ))
        elif snapshot.ram_percent <= self.config.ram_clear_threshold:
            if "RAM_HIGH" in self._active_alert_states:
                self._active_alert_states.remove("RAM_HIGH")

        # 3. Disk High
        if snapshot.disk_percent >= self.config.disk_high_threshold:
            if "DISK_HIGH" not in self._active_alert_states:
                self._active_alert_states.add("DISK_HIGH")
                new_events.append(SystemEvent(
                    event_type="DISK_HIGH",
                    timestamp=now_iso,
                    severity=EventSeverity.WARNING.value,
                    message=f"Primary disk space is running low ({snapshot.disk_percent}% used). Free: {snapshot.disk_free_gb} GB.",
                    value=snapshot.disk_percent,
                    threshold=self.config.disk_high_threshold,
                    metadata={"free_gb": snapshot.disk_free_gb},
                ))
        elif snapshot.disk_percent <= self.config.disk_clear_threshold:
            if "DISK_HIGH" in self._active_alert_states:
                self._active_alert_states.remove("DISK_HIGH")

        # 4. Battery Low
        if snapshot.battery_percent is not None:
            is_low = snapshot.battery_percent <= self.config.battery_low_threshold and not bool(snapshot.battery_plugged)
            if is_low:
                if "BATTERY_LOW" not in self._active_alert_states:
                    self._active_alert_states.add("BATTERY_LOW")
                    new_events.append(SystemEvent(
                        event_type="BATTERY_LOW",
                        timestamp=now_iso,
                        severity=EventSeverity.WARNING.value,
                        message=f"Battery level is low ({snapshot.battery_percent}%). Please connect to power.",
                        value=snapshot.battery_percent,
                        threshold=self.config.battery_low_threshold,
                        metadata={"plugged": snapshot.battery_plugged},
                    ))
            elif snapshot.battery_percent >= self.config.battery_clear_threshold or bool(snapshot.battery_plugged):
                if "BATTERY_LOW" in self._active_alert_states:
                    self._active_alert_states.remove("BATTERY_LOW")

        # 5. Network Availability Transitions
        if not snapshot.network_online:
            if "NETWORK_DISCONNECTED" not in self._active_alert_states:
                self._active_alert_states.add("NETWORK_DISCONNECTED")
                new_events.append(SystemEvent(
                    event_type="NETWORK_DISCONNECTED",
                    timestamp=now_iso,
                    severity=EventSeverity.WARNING.value,
                    message="Network connection appears to be unavailable.",
                ))
        else:
            if "NETWORK_DISCONNECTED" in self._active_alert_states:
                self._active_alert_states.remove("NETWORK_DISCONNECTED")
                new_events.append(SystemEvent(
                    event_type="NETWORK_RECONNECTED",
                    timestamp=now_iso,
                    severity=EventSeverity.INFO.value,
                    message="Network connection has been restored.",
                ))

        return new_events

    async def _emit_events(self, events: List[SystemEvent]) -> None:
        """Dispatches new structured events to registered listeners and saves to history."""
        for event in events:
            self._event_history.append(event)
            print(f"[ByteX LiveMonitor] Event Detected: [{event.severity.upper()}] {event.event_type} - {event.message}")
            for listener in self._event_listeners:
                try:
                    await listener(event)
                except Exception as e:
                    logger.warning(f"Error in monitoring event listener: {e}")

    async def _monitor_loop(self) -> None:
        """Periodic background evaluation loop."""
        while self._is_running:
            try:
                if not self._is_paused:
                    snapshot = SystemMetricsCollector.collect_metrics()
                    self._latest_snapshot = snapshot
                    self._poll_count += 1

                    new_events = self.evaluate_snapshot(snapshot)
                    if new_events:
                        await self._emit_events(new_events)

                await asyncio.sleep(self.config.polling_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ByteX LiveMonitor] Error in monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(self.config.polling_interval_seconds)

live_system_monitor = LiveSystemMonitor()
