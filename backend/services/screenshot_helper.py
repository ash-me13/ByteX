import sys
import os
import subprocess
import ctypes
from pathlib import Path
from PIL import Image, ImageStat, ImageGrab

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

user32 = None
kernel32 = None

if IS_WINDOWS and hasattr(ctypes, "windll"):
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        pass

def is_image_valid_and_not_black(img: Image.Image) -> bool:
    try:
        stat = ImageStat.Stat(img.convert("L"))
        max_p = stat.extrema[0][1]
        mean_p = stat.mean[0]
        return max_p > 10 and mean_p > 0.5
    except Exception:
        return False

def capture_desktop(output_path: str) -> bool:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if IS_MACOS:
        # Method 1: macOS native screencapture
        try:
            res = subprocess.run(
                ["/usr/sbin/screencapture", "-x", str(target.resolve())],
                capture_output=True,
                text=True,
                timeout=5.0
            )
            if res.returncode == 0 and target.exists() and target.stat().st_size > 0:
                try:
                    with Image.open(target) as img:
                        if is_image_valid_and_not_black(img):
                            print(f"SUCCESS: Desktop captured via screencapture ({img.size[0]}x{img.size[1]}) -> {target}")
                            return True
                except Exception:
                    pass
            err_msg = res.stderr.strip() if res.stderr else "screen recording permission denied or display unavailable"
            print(f"[Helper] macOS screencapture: {err_msg}")
        except Exception as ex:
            print(f"[Helper] screencapture execution error: {ex}")

        # Method 2: mss fallback
        try:
            from mss import MSS
            with MSS() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(mon)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                if is_image_valid_and_not_black(img):
                    img.save(target, "PNG")
                    if target.exists() and target.stat().st_size > 0:
                        print(f"SUCCESS: Desktop captured via mss ({img.size[0]}x{img.size[1]}) -> {target}")
                        return True
        except Exception as ex:
            print(f"[Helper] mss attempt: {ex}")

        return False

    if not IS_WINDOWS or user32 is None:
        return False

    # 1. Attach current thread to the interactive user's 'Default' desktop
    DESKTOP_ACCESS = 0x01FF # DESKTOP_READOBJECTS | DESKTOP_WRITEOBJECTS | etc.
    h_default = user32.OpenDesktopW("Default", 0, False, DESKTOP_ACCESS)
    if not h_default:
        h_default = user32.OpenInputDesktop(0, False, DESKTOP_ACCESS)

    old_desk = None
    if h_default:
        old_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        user32.SetThreadDesktop(h_default)

    img_captured = None

    # Method A: PIL ImageGrab from Default desktop context
    try:
        img = ImageGrab.grab(all_screens=True)
        if img and is_image_valid_and_not_black(img):
            img_captured = img
    except Exception as ex:
        print(f"[Helper] ImageGrab attempt: {ex}")

    # Method B: mss capture if ImageGrab didn't succeed
    if not img_captured:
        try:
            from mss import MSS
            with MSS() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(mon)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                if is_image_valid_and_not_black(img):
                    img_captured = img
        except Exception as ex:
            print(f"[Helper] mss attempt: {ex}")

    # Restore thread desktop context
    if h_default and old_desk:
        user32.SetThreadDesktop(old_desk)
        user32.CloseDesktop(h_default)

    # Save and verify image
    if img_captured:
        img_captured.save(target, "PNG")
        if target.exists() and target.stat().st_size > 0:
            print(f"SUCCESS: Desktop captured ({img_captured.size[0]}x{img_captured.size[1]}) -> {target}")
            return True

    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR: Target path argument required.")
        sys.exit(1)

    dest = sys.argv[1]
    if capture_desktop(dest):
        sys.exit(0)
    else:
        print("ERROR: Screenshot capture failed.")
        sys.exit(2)
