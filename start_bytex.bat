@echo off
title ByteX AI Launcher
echo ==================================================
echo   Starting ByteX AI (Unified Edge Architecture)
echo ==================================================
echo.

echo [1/3] Starting FastAPI Backend Server on port 8000...
start "ByteX AI Backend" cmd /k "title ByteX Backend && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

timeout /t 2 /nobreak >nul

echo [2/3] Starting React Frontend App on port 5173...
start "ByteX AI Frontend" cmd /k "title ByteX Frontend && cd ByteX && npm run dev"

timeout /t 3 /nobreak >nul

echo [3/3] Launching Visible Microsoft Edge (Profile 1) with CDP Debugging on port 9222...
start "" "msedge.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Microsoft\Edge\User Data\Profile 1" http://localhost:5173

echo.
echo ByteX AI is fully online!
echo Backend : http://localhost:8000
echo Frontend: http://localhost:5173
echo CDP Port: 9222
echo.
pause
