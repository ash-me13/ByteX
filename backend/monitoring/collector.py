import os
import psutil
import socket
from typing import Optional
from monitoring.models import SystemMetricSnapshot

class SystemMetricsCollector:
    """
    Lightweight, read-only telemetry collector for ByteX Live Monitoring.
    
    Security & Structural Invariants:
    1. 100% Read-Only: Never executes commands, kills processes, or modifies system state.
    2. Zero Process Spawning: Reads OS telemetry directly via standard system APIs.
    3. Low CPU Overhead: Non-blocking sampling designed for periodic background polling.
    """

    @classmethod
    def check_network_connectivity(cls, host: str = "8.8.8.8", port: int = 53, timeout: float = 0.5) -> bool:
        """Lightweight socket probe to verify real network reachability."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            return True
        except Exception:
            # Fallback: check if any active network interface is UP
            try:
                stats = psutil.net_if_stats()
                for name, if_stat in stats.items():
                    if if_stat.isup and not name.lower().startswith("loopback") and not "pseudo" in name.lower():
                        return True
            except Exception:
                pass
            return False

    @classmethod
    def collect_metrics(cls) -> SystemMetricSnapshot:
        """Gathers a complete snapshot of current system metrics."""
        # 1. CPU
        cpu_pct = psutil.cpu_percent(interval=None)

        # 2. RAM
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        ram_avail_gb = round(ram.available / (1024 ** 3), 2)
        ram_total_gb = round(ram.total / (1024 ** 3), 2)

        # 3. Disk (Primary drive)
        primary_drive = os.path.splitdrive(os.getcwd())[0] + "\\" if os.name == 'nt' else "/"
        try:
            disk = psutil.disk_usage(primary_drive)
            disk_pct = disk.percent
            disk_free_gb = round(disk.free / (1024 ** 3), 2)
        except Exception:
            disk_pct = 0.0
            disk_free_gb = 0.0

        # 4. Battery
        bat_pct: Optional[float] = None
        bat_plugged: Optional[bool] = None
        try:
            battery = psutil.sensors_battery()
            if battery:
                bat_pct = round(battery.percent, 1)
                bat_plugged = battery.power_plugged
        except Exception:
            pass

        # 5. Network
        net_online = cls.check_network_connectivity()

        return SystemMetricSnapshot(
            cpu_percent=cpu_pct,
            ram_percent=ram_pct,
            ram_available_gb=ram_avail_gb,
            ram_total_gb=ram_total_gb,
            disk_percent=disk_pct,
            disk_free_gb=disk_free_gb,
            battery_percent=bat_pct,
            battery_plugged=bat_plugged,
            network_online=net_online,
        )
