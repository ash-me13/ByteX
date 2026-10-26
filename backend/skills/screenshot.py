import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple
from PIL import Image, ImageStat
from skills.base import BaseSkill, ToolResult
from security.audit_logger import audit_logger

def _default_screenshot_dir() -> Path:
    """Screenshot folder: $BYTEX_SCREENSHOT_DIR if set, otherwise ~/Pictures/ByteX Screenshots (any OS)."""
    override = os.environ.get("BYTEX_SCREENSHOT_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / "Pictures" / "ByteX Screenshots"

SCREENSHOT_DIR = _default_screenshot_dir()
HELPER_SCRIPT = Path(__file__).resolve().parent.parent / "services" / "screenshot_helper.py"

def verify_screenshot_image(filepath: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """
    6-Point Empirical Screenshot Verification Suite:
    1. File exists on disk
    2. File size > 0
    3. Image parses cleanly
    4. Image width > 0
    5. Image height > 0
    6. Image is NOT completely black (max_pixel > 10 and mean > 0.5)
    """
    if not filepath.exists():
        return False, "Capture file was not created on disk.", {}

    file_size = filepath.stat().st_size
    if file_size <= 0:
        return False, "Capture file exists but is 0 bytes.", {"size": 0}

    try:
        with Image.open(filepath) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                return False, f"Invalid image dimensions ({width}x{height}).", {"size": file_size, "dimensions": f"{width}x{height}"}

            stat = ImageStat.Stat(img.convert("L"))
            max_pixel = stat.extrema[0][1]
            mean_val = stat.mean[0]

            print(f"[PC Screenshot Verification] Size={width}x{height}, Bytes={file_size}, Mean={mean_val:.2f}, Max Pixel={max_pixel}")

            if max_pixel <= 10 or mean_val < 0.5:
                return False, f"Captured image is completely black (Max pixel: {max_pixel}, Mean: {mean_val:.2f}).", {
                    "size": file_size,
                    "dimensions": f"{width}x{height}",
                    "max_pixel": max_pixel,
                    "mean_brightness": round(mean_val, 2)
                }

            return True, f"Verified non-black desktop capture ({width}x{height}, {file_size} bytes)", {
                "size": file_size,
                "dimensions": f"{width}x{height}",
                "max_pixel": max_pixel,
                "mean_brightness": round(mean_val, 2)
            }

    except Exception as e:
        return False, f"Image corruption error: {e}", {"size": file_size}

class TakeScreenshotSkill(BaseSkill):
    def __init__(self):
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[TakeScreenshotSkill] Could not create {SCREENSHOT_DIR}: {e}")

    @property
    def name(self) -> str:
        return "take_screenshot"

    @property
    def description(self) -> str:
        return "Captures and empirically verifies Windows desktop screenshots."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = SCREENSHOT_DIR / filename

            print(f"[ByteX PC Control] Initiating desktop screenshot capture -> {filepath}")

            # 1. Execute interactive desktop screenshot helper
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(HELPER_SCRIPT),
                    str(filepath),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
                stdout_str = stdout.decode('utf-8', errors='ignore').strip()
                stderr_str = stderr.decode('utf-8', errors='ignore').strip()
                if stdout_str:
                    print(f"[ByteX PC Control] Helper Output: {stdout_str}")
                if stderr_str:
                    print(f"[ByteX PC Control] Helper Stderr: {stderr_str}")
            except Exception as ex:
                print(f"[ByteX PC Control] Helper Process Error: {ex}")

            # 2. Complete 6-Point Empirical Verification
            is_valid, reason, data = verify_screenshot_image(filepath)

            if is_valid:
                msg = "Screenshot captured."
                print(f"[ByteX PC Control] Screenshot SUCCESS: {filepath} ({reason})")
                audit_logger.log_action(self.name, "SUCCESS", f"{msg} - {reason}")
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="take_screenshot",
                    message=msg,
                    data={"filename": filename, "path": str(filepath), **data}
                )
            else:
                msg = f"Screenshot capture failed: {reason}"
                print(f"[ByteX PC Control] Screenshot FAILURE: {reason}")
                audit_logger.log_action(self.name, "FAILED", msg)
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="take_screenshot",
                    message=msg,
                    error=reason,
                    data=data
                )

        except Exception as e:
            msg = f"Screenshot failed: {e}"
            audit_logger.log_action(self.name, "FAILED", msg)
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="take_screenshot",
                message=msg,
                error=str(e)
            )
