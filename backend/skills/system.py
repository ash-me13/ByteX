import psutil
from typing import Dict, Any
from skills.base import BaseSkill, ToolResult
from security.audit_logger import audit_logger

class SystemStatusSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "system_status"

    @property
    def description(self) -> str:
        return "Retrieves current Windows CPU usage, RAM stats (total, available, used), and battery/power status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        try:
            # 1. CPU Usage
            cpu_percent = psutil.cpu_percent(interval=0.2)

            # 2. RAM Information
            mem = psutil.virtual_memory()
            ram_percent = mem.percent
            total_ram_gb = round(mem.total / (1024 ** 3), 2)
            available_ram_gb = round(mem.available / (1024 ** 3), 2)
            used_ram_gb = round(mem.used / (1024 ** 3), 2)

            # 3. Battery & Power Information
            battery = psutil.sensors_battery()
            if battery:
                has_battery = True
                battery_percent = battery.percent
                power_plugged = battery.power_plugged
                battery_status_str = f"Battery: {battery_percent}% ({'Plugged in' if power_plugged else 'On Battery'})"
            else:
                has_battery = False
                battery_percent = None
                power_plugged = None
                battery_status_str = "Power: AC Connected (No battery detected)"

            status_data = {
                "cpu_percent": cpu_percent,
                "ram_percent": ram_percent,
                "total_ram_gb": total_ram_gb,
                "available_ram_gb": available_ram_gb,
                "used_ram_gb": used_ram_gb,
                "has_battery": has_battery,
                "battery_percent": battery_percent,
                "power_plugged": power_plugged,
            }

            msg = (
                f"System Status: CPU {cpu_percent}% | RAM {ram_percent}% "
                f"(Available {available_ram_gb} GB / Total {total_ram_gb} GB) | {battery_status_str}."
            )

            print(f"[ByteX PC Control] System Status Retrieved: {msg}")
            audit_logger.log_action(self.name, "SUCCESS", msg)
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="system_status",
                message=msg,
                data=status_data
            )
        except Exception as e:
            msg = f"Failed to retrieve system status: {e}"
            audit_logger.log_action(self.name, "FAILED", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="system_status",
                message=msg,
                error=str(e)
            )

# Backward-compatibility alias
GetSystemStatsSkill = SystemStatusSkill
