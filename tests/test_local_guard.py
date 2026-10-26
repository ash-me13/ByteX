"""
Regression tests for security.local_guard.LocalOnlyGuardMiddleware.

These drive the ASGI middleware directly (no network, no FastAPI needed) so they are
safe to run anywhere. Run with:  PYTHONPATH=backend python -m pytest tests/test_local_guard.py
"""

import asyncio
import unittest

from security.local_guard import LocalOnlyGuardMiddleware, is_loopback_address

UI_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


async def _inner_app(scope, receive, send):
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    else:
        await send({"type": "websocket.accept"})


def _scope(kind="http", path="/api/chat", method="POST", client=("127.0.0.1", 50000), host="127.0.0.1:8000", origin=None):
    headers = []
    if host is not None:
        headers.append((b"host", host.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    scope = {"type": kind, "path": path, "headers": headers, "client": client}
    if kind == "http":
        scope["method"] = method
    return scope


def _run(scope):
    """Returns the list of ASGI messages the middleware sent."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    guard = LocalOnlyGuardMiddleware(_inner_app, allowed_origins=UI_ORIGINS)
    asyncio.run(guard(scope, receive, send))
    return sent


def _allowed(scope):
    msgs = _run(scope)
    first = msgs[0]
    if scope["type"] == "http":
        return first["type"] == "http.response.start" and first["status"] == 200
    return first["type"] == "websocket.accept"


def _blocked(scope):
    msgs = _run(scope)
    first = msgs[0]
    if scope["type"] == "http":
        return first["type"] == "http.response.start" and first["status"] == 403
    return first["type"] == "websocket.close"


class LoopbackHelperTests(unittest.TestCase):
    def test_loopback_variants(self):
        for ok in ["127.0.0.1", "127.5.5.5", "::1", "::ffff:127.0.0.1", "localhost", "LOCALHOST"]:
            self.assertTrue(is_loopback_address(ok), ok)

    def test_non_loopback(self):
        for bad in ["192.168.1.20", "10.0.0.5", "8.8.8.8", "evil.example.com", "", None, "::ffff:192.168.1.2"]:
            self.assertFalse(is_loopback_address(bad), bad)


class HttpGuardTests(unittest.TestCase):
    def test_ui_post_from_allowed_origin_passes(self):
        self.assertTrue(_allowed(_scope(origin="http://localhost:5173")))

    def test_no_origin_client_passes(self):
        # curl / python scripts / Android app do not send Origin
        self.assertTrue(_allowed(_scope(origin=None)))

    def test_cross_site_simple_post_is_blocked(self):
        # e.g. a web page POSTing to /api/memory/clear (no body => no CORS preflight)
        self.assertTrue(_blocked(_scope(path="/api/memory/clear", origin="https://evil.example")))

    def test_cross_site_delete_and_put_blocked(self):
        for method in ("DELETE", "PUT", "PATCH"):
            self.assertTrue(_blocked(_scope(method=method, origin="https://evil.example")), method)

    def test_null_origin_blocked(self):
        self.assertTrue(_blocked(_scope(origin="null")))

    def test_cross_site_get_left_to_cors(self):
        # Safe methods are not state changing; CORS already stops the page from reading the answer.
        self.assertTrue(_allowed(_scope(method="GET", origin="https://evil.example")))

    def test_lan_client_blocked_for_rest(self):
        self.assertTrue(_blocked(_scope(client=("192.168.1.50", 40000), host="192.168.1.10:8000")))

    def test_lan_client_cannot_use_pairing_rest_endpoints(self):
        for path in ("/api/phone/pairing/create", "/api/phone/pairing/approve", "/phone/devices"):
            self.assertTrue(_blocked(_scope(path=path, client=("192.168.1.50", 40000), host="192.168.1.10:8000")), path)

    def test_dns_rebinding_host_blocked(self):
        self.assertTrue(_blocked(_scope(host="attacker.example:8000", origin=None)))

    def test_ipv6_loopback_host_header_ok(self):
        self.assertTrue(_allowed(_scope(client=("::1", 1), host="[::1]:8000")))


class WebSocketGuardTests(unittest.TestCase):
    def test_ui_websocket_from_allowed_origin_passes(self):
        self.assertTrue(_allowed(_scope("websocket", "/ws", origin="http://localhost:5173")))

    def test_python_websocket_client_without_origin_passes(self):
        self.assertTrue(_allowed(_scope("websocket", "/ws", origin=None)))

    def test_cross_site_websocket_hijack_blocked(self):
        self.assertTrue(_blocked(_scope("websocket", "/ws", origin="https://evil.example")))

    def test_lan_client_cannot_reach_ui_websocket(self):
        self.assertTrue(_blocked(_scope("websocket", "/ws", client=("192.168.1.50", 40000), host="192.168.1.10:8000")))

    def test_phone_websocket_not_reachable_from_lan_by_default(self):
        for path in ("/ws/phone", "/api/ws/phone"):
            self.assertTrue(_blocked(_scope("websocket", path, client=("192.168.1.50", 40000), host="192.168.1.10:8000")), path)

    def test_phone_websocket_works_on_loopback(self):
        self.assertTrue(_allowed(_scope("websocket", "/ws/phone", origin=None)))

    def test_explicit_public_path_exception_is_opt_in(self):
        guard = LocalOnlyGuardMiddleware(_inner_app, allowed_origins=UI_ORIGINS, public_ws_paths=("/ws/phone",))
        self.assertIsNone(guard._violation(_scope("websocket", "/ws/phone", client=("192.168.1.50", 1), host="192.168.1.10:8000")))
        self.assertIsNotNone(guard._violation(_scope("http", "/api/phone/pairing/approve", client=("192.168.1.50", 1), host="192.168.1.10:8000")))

    def test_spoofed_forwarding_headers_are_ignored(self):
        # The guard trusts only the socket peer (scope["client"]), never X-Forwarded-For / X-Real-IP.
        s = _scope(client=("192.168.1.50", 1), host="127.0.0.1:8000")
        s["headers"] += [(b"x-forwarded-for", b"127.0.0.1"), (b"x-real-ip", b"127.0.0.1")]
        self.assertTrue(_blocked(s))

    def test_malformed_host_and_origin_do_not_crash(self):
        for host in ["", "[", "]:", ":::", "\x00bad", "localhost:notaport"]:
            _run(_scope(host=host))
        _run(_scope(origin=""))

    def test_lifespan_scope_untouched(self):
        sent = []

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(message):
            sent.append(message)

        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        guard = LocalOnlyGuardMiddleware(inner, allowed_origins=UI_ORIGINS)
        asyncio.run(guard({"type": "lifespan"}, receive, send))
        self.assertEqual(seen, ["lifespan"])


if __name__ == "__main__":
    unittest.main()
