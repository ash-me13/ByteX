import os
import sys
import subprocess
import time
import httpx
import asyncio
from pathlib import Path

def start():
    print("=" * 60)
    print("  Starting ByteX AI (Unified Edge Architecture)")
    print("=" * 60)
    
    root_dir = Path(__file__).resolve().parent
    bytex_frontend_dir = root_dir / "ByteX"

    # Locate Python executable (prefer workspace .venv if available)
    venv_py_posix = root_dir / ".venv" / "bin" / "python"
    venv_py_win = root_dir / ".venv" / "Scripts" / "python.exe"
    if venv_py_posix.exists():
        py_exe = str(venv_py_posix)
    elif venv_py_win.exists():
        py_exe = str(venv_py_win)
    else:
        py_exe = sys.executable

    # 1. Start Backend if not already running
    backend_running = False
    try:
        r = httpx.get("http://127.0.0.1:8000/", timeout=1.0)
        if r.status_code == 200:
            backend_running = True
            print("[Backend] FastAPI is already running on http://127.0.0.1:8000")
    except Exception:
        pass

    if not backend_running:
        print("[Backend] Starting FastAPI backend on http://127.0.0.1:8000...")
        env = os.environ.copy()
        backend_str = str(root_dir / "backend")
        env["PYTHONPATH"] = f"{backend_str}:{str(root_dir)}" if "PYTHONPATH" not in env else f"{backend_str}:{str(root_dir)}:{env['PYTHONPATH']}"
        is_windows = sys.platform == "win32"
        subprocess.Popen(
            [py_exe, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(root_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            start_new_session=not is_windows,
            shell=False
        )
        time.sleep(1.5)

    # 2. Start Frontend if not already running
    frontend_running = False
    try:
        r = httpx.get("http://localhost:5173/", timeout=1.0)
        if r.status_code == 200:
            frontend_running = True
            print("[Frontend] Vite React app is already running on http://localhost:5173")
    except Exception:
        pass

    if not frontend_running:
        print("[Frontend] Starting Vite React app on http://localhost:5173...")
        is_windows = sys.platform == "win32"
        subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(bytex_frontend_dir),
            stdin=subprocess.DEVNULL,
            start_new_session=not is_windows,
            shell=is_windows
        )
        time.sleep(2.5)

    # 3. Launch or Connect to Controlled Chromium Browser with CDP enabled on port 9222
    cdp_running = False
    try:
        r = httpx.get("http://127.0.0.1:9222/json", timeout=1.0)
        if r.status_code == 200:
            cdp_running = True
            print("[Browser] Active browser session with CDP is already running on port 9222")
    except Exception:
        pass

    is_macos = sys.platform == "darwin"
    is_windows = sys.platform == "win32"
    home = Path.home()

    if is_macos:
        browser_user_data = str(home / "Library" / "Application Support" / "ByteX" / "ByteX_Browser_Profile")
        browser_candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            str(home / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"),
            str(home / "Applications" / "Brave Browser.app" / "Contents" / "MacOS" / "Brave Browser"),
            str(home / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge"),
        ]
    elif is_windows:
        local_app = os.environ.get('LOCALAPPDATA', r'C:\Users\Default\AppData\Local')
        browser_user_data = os.path.join(local_app, 'ByteX_Browser_Profile')
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        browser_candidates = [
            os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"),
        ]
    else:
        browser_user_data = str(home / ".config" / "bytex" / "ByteX_Browser_Profile")
        import shutil
        browser_candidates = [
            cmd for cmd in ["google-chrome", "google-chrome-stable", "brave-browser", "microsoft-edge", "chromium-browser", "chromium"]
            if shutil.which(cmd)
        ]

    os.makedirs(browser_user_data, exist_ok=True)
    browser_exe = next((c for c in browser_candidates if os.path.exists(c) or (not os.path.isabs(c) and shutil.which(c))), None)

    if not cdp_running and browser_exe:
        print(f"[Browser] Launching Visible Single Controlled Browser ({os.path.basename(browser_exe)}) on port 9222...")
        browser_cmd = [
            browser_exe,
            "--remote-debugging-port=9222",
            f"--user-data-dir={browser_user_data}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=msEdgeStartupBoost",
            "--new-window",
            "http://localhost:5173"
        ]
        try:
            subprocess.Popen(browser_cmd)
        except Exception as e:
            print(f"[Browser] Could not launch browser directly: {e}")
            import webbrowser
            webbrowser.open("http://localhost:5173")
        
        # Wait up to 10s for CDP to be ready
        for _ in range(20):
            time.sleep(0.5)
            try:
                r = httpx.get("http://127.0.0.1:9222/json", timeout=1.0)
                if r.status_code == 200:
                    cdp_running = True
                    break
            except Exception:
                pass
    elif not cdp_running and not browser_exe:
        print("[Browser] No local Chromium binary detected. Opening system default browser...")
        import webbrowser
        webbrowser.open("http://localhost:5173")

    # Ensure http://localhost:5173 is open in this EXACT CDP browser instance
    bytex_target_id = None
    if cdp_running:
        try:
            r = httpx.get("http://127.0.0.1:9222/json", timeout=2.0)
            tabs = r.json()
            bytex_tab = next((t for t in tabs if "5173" in t.get("url", "") or "bytex" in t.get("title", "").lower()), None)
            if not bytex_tab:
                new_tab = httpx.put("http://127.0.0.1:9222/json/new?http://localhost:5173", timeout=2.0).json()
                bytex_target_id = new_tab.get("id")
            else:
                bytex_target_id = bytex_tab.get("id")
            
            if bytex_target_id:
                httpx.get(f"http://127.0.0.1:9222/json/activate/{bytex_target_id}", timeout=2.0)
        except Exception as e:
            print(f"[Browser] ByteX tab setup error: {e}")

    print("\n" + "=" * 60)
    print("  ByteX AI is fully online and ready!")
    print("  UI URL          : http://localhost:5173")
    print("  Backend         : http://localhost:8000")
    print(f"  CDP Port        : {'9222 (Connected)' if cdp_running else 'Disabled / External Browser'}")
    print(f"  ByteX Target ID : {bytex_target_id}")
    print("=" * 60)

if __name__ == "__main__":
    start()
