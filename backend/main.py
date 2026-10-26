import sys
from pathlib import Path

# Configure stdout and stderr for UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add backend directory to Python import path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import settings
from api.routes import router as api_router
from api.websocket import router as ws_router
from monitoring.service import live_system_monitor
from security.local_guard import LocalOnlyGuardMiddleware
from api.phone_routes import ws_router as phone_ws_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runtime Path Diagnostics
    import core.command_router as _cr
    import skills.coding as _cd
    print("=" * 60)
    print(f"[ByteX Runtime Diagnostic] Active Backend Root : {backend_dir}")
    print(f"[ByteX Runtime Diagnostic] command_router.py   : {_cr.__file__}")
    print(f"[ByteX Runtime Diagnostic] coding.py           : {_cd.__file__}")
    print("=" * 60)

    # Startup: Start Live System Monitor
    await live_system_monitor.start()
    
    # Startup: Run enabled Startup Automations (Feature #36.14)
    try:
        from agent.automation import automation_manager
        import asyncio
        asyncio.create_task(automation_manager.run_startup_automations())
    except Exception as e:
        print(f"[Main] Error launching startup automations: {e}")

    yield
    # Shutdown: Cleanly Stop Live System Monitor
    await live_system_monitor.stop()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local-only guard. Added AFTER CORS so it is the outermost layer and runs first.
# It rejects non-loopback peers, non-loopback Host headers (DNS rebinding) and cross-site browser
# requests (WebSocket handshakes and state-changing HTTP methods). It is NOT authentication.
app.add_middleware(LocalOnlyGuardMiddleware, allowed_origins=settings.CORS_ORIGINS)

# Register routes
# - /api/*       : REST API. The phone REST routes (/api/phone/*) are included by api.routes, exactly once.
# - /ws          : UI WebSocket.
# - /ws/phone    : Android companion WebSocket (the app connects to this exact path).
app.include_router(api_router, prefix=settings.API_PREFIX)
app.include_router(ws_router)
app.include_router(phone_ws_router)

@app.get("/")
async def root():
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    # Loopback only: this API can control the computer and has no login. Do not bind 0.0.0.0.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
