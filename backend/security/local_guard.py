"""
Local-only guard for the ByteX backend (pure ASGI, no third-party imports).

Why this exists
---------------
The backend can drive the user's computer (commands, files, browser, automations).
It has no login, so it must only ever be reachable by ByteX's own UI on this
machine. Two kinds of outsiders could otherwise reach it:

1. Other machines on the network, when the server is bound to 0.0.0.0
   (``python backend/main.py`` does this).
2. Web pages open in the user's own browser. CORS does NOT protect WebSockets,
   and "simple" POST requests with no body are sent without any preflight, so a
   random website could talk to ``ws://127.0.0.1:8000/ws`` or POST to
   ``http://127.0.0.1:8000/api/memory/clear``. DNS-rebinding pages can do the
   same by pointing their own hostname at 127.0.0.1.

Rules enforced for every HTTP and WebSocket request:

* The TCP peer must be a loopback address. There are no exceptions by default.
* The ``Host`` header must name a loopback host (blocks DNS rebinding).
* If a browser sent an ``Origin`` header, it must be one of the allowed UI
  origins for every WebSocket and every state-changing HTTP method.
  Requests with no ``Origin`` (curl, Python clients, the Android app) are not
  browser cross-site requests and are allowed.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Iterable, Optional, Sequence

# No path is reachable from other machines by default. Letting the Android companion connect over Wi-Fi
# needs a separately designed, narrowly scoped listener (see docs/PHONE_PAIRING_SECURITY.md); a path
# exception in this middleware is NOT enough, because pairing also uses REST endpoints and the general
# API shares the same port.
DEFAULT_PUBLIC_WS_PATHS: tuple = ()

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOOPBACK_NAMES = {"localhost", "testclient", "testserver"}


def is_loopback_address(host: Optional[str]) -> bool:
    """True for 127.0.0.0/8, ::1, IPv4-mapped loopback, 'localhost' and Starlette's test client."""
    if not host:
        return False
    host = host.strip().lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _hostname_from_host_header(value: str) -> str:
    """'localhost:8000' -> 'localhost', '[::1]:8000' -> '::1', '127.0.0.1' -> '127.0.0.1'."""
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


class LocalOnlyGuardMiddleware:
    def __init__(
        self,
        app,
        allowed_origins: Iterable[str] = (),
        public_ws_paths: Sequence[str] = DEFAULT_PUBLIC_WS_PATHS,
    ):
        self.app = app
        self.allowed_origins = {o.rstrip("/").lower() for o in allowed_origins}
        self.public_ws_paths = tuple(public_ws_paths)

    async def __call__(self, scope, receive, send):
        scope_type = scope["type"]
        if scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        reason = self._violation(scope)
        if reason is None:
            await self.app(scope, receive, send)
            return

        print(f"[LocalGuard] Blocked {scope_type} {scope.get('path')} ({reason})")
        if scope_type == "websocket":
            # Closing before accept makes the server answer the handshake with HTTP 403.
            await send({"type": "websocket.close", "code": 1008})
            return

        body = json.dumps({"detail": "Forbidden"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    # ------------------------------------------------------------------
    def _violation(self, scope) -> Optional[str]:
        scope_type = scope["type"]
        path = scope.get("path", "")

        # Phone companion channel: reachable from the LAN, authenticated by pairing secret / device token.
        if scope_type == "websocket" and path in self.public_ws_paths:
            return None

        client = scope.get("client")
        if client is not None and not is_loopback_address(client[0]):
            return "non-loopback client"

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

        host_header = headers.get("host")
        if host_header and not is_loopback_address(_hostname_from_host_header(host_header)):
            return "non-loopback Host header"

        origin = headers.get("origin")
        if origin is not None:
            needs_origin_check = scope_type == "websocket" or scope.get("method", "GET").upper() not in _SAFE_METHODS
            if needs_origin_check and origin.rstrip("/").lower() not in self.allowed_origins:
                return "origin not allowed"

        return None
