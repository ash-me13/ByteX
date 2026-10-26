"""
Regression tests: a chat message must never make the /ws handler drop the connection (browser close code 1006).

Runs the REAL api/websocket.py, core/assistant.py, core/events.py, core/response_sanitizer.py and models/schemas.py
with a fake AI router / command router / memory service (no network, no provider keys, no desktop actions).
Needs pydantic (skipped otherwise).

    PYTHONPATH=backend python3 -m unittest tests.test_ws_chat_resilience -v
"""
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent / "backend"

try:
    import pydantic  # noqa: F401
    HAVE_PYDANTIC = True
except Exception:
    HAVE_PYDANTIC = False


class WebSocketDisconnect(Exception):
    pass


class FakeWS:
    def __init__(self, incoming):
        self.sent, self.queue = [], list(incoming)

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def receive_text(self):
        if self.queue:
            return self.queue.pop(0)
        raise WebSocketDisconnect()


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed")
class WebSocketChatResilienceTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sys.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.path.insert(0, str(BACKEND))
        self.addCleanup(lambda: sys.path.remove(str(BACKEND)))
        for name in ("api.websocket", "ai.stream_safety", "core.assistant", "core.events", "core.response_sanitizer", "core.confirmation",
                     "models.schemas", "config.settings"):
            sys.modules.pop(name, None)

        def stub(name, **attrs):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m
            return m

        fastapi = stub("fastapi", WebSocket=object, WebSocketDisconnect=WebSocketDisconnect)
        fastapi.APIRouter = type("APIRouter", (), {"websocket": lambda self, path: (lambda fn: fn)})
        self.reply = "Hello from the fake AI"

        outer = self

        class FakeAIRouter:
            async def stream_response(self, history, memory_context=""):
                yield outer.reply

        class FakeCommandRouter:
            @staticmethod
            async def route_command(message, history=None):
                return (False, None, None, None)

        # `ai` stays a real (namespace) package so core.assistant can import the real ai.stream_safety.
        stub("ai.router", ai_router=FakeAIRouter(), StreamInterrupted=type("StreamInterrupted", (Exception,), {}))
        stub("core.command_router", CommandRouter=FakeCommandRouter)
        stub("memory")
        stub("memory.service", memory_service=types.SimpleNamespace(get_context_for_prompt=lambda m: ""))
        stub("monitoring")
        stub("monitoring.service", live_system_monitor=types.SimpleNamespace(add_event_listener=lambda f: None))
        stub("monitoring.models", SystemEvent=object)
        import importlib
        with mock.patch("builtins.print"):
            self.ws = importlib.import_module("api.websocket")

    def run_ws(self, *messages):
        sock = FakeWS(json.dumps({"message": m}) if not m.startswith("{") else m for m in messages)
        with mock.patch("builtins.print"):
            asyncio.run(self.ws.websocket_endpoint(sock))
        return sock.sent

    def test_hi_gets_an_assistant_response(self):
        events = self.run_ws("hi")
        completes = [e for e in events if e["type"] == "ASSISTANT_COMPLETE"]
        self.assertEqual([e["message"] for e in completes], [self.reply])
        self.assertEqual(events[-1]["state"], "idle")

    def test_broken_stdout_does_not_kill_the_chat_turn(self):
        """A backend whose stdout/stderr was closed (launcher exited) makes print() raise; chat must still answer."""
        sock = FakeWS([json.dumps({"message": "hi"})])
        with mock.patch("builtins.print", side_effect=BrokenPipeError("stdout closed")), \
                mock.patch("traceback.print_exc", side_effect=BrokenPipeError("stderr closed")):
            asyncio.run(self.ws.websocket_endpoint(sock))
        self.assertIn(self.reply, [e.get("message") for e in sock.sent if e["type"] == "ASSISTANT_COMPLETE"])

    def test_unexpected_exception_returns_error_event_and_keeps_connection(self):
        secret = "SECRET-DO-NOT-LEAK"
        calls = {"n": 0}
        real = self.ws.bytex_core.process_user_message

        async def flaky(message):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError(secret)
                yield  # pragma: no cover  (makes this an async generator)
            async for ev in real(message):
                yield ev

        with mock.patch.object(self.ws.bytex_core, "process_user_message", flaky):
            events = self.run_ws("first", "second")
        errors = [e for e in events if e["type"] == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("ValueError", errors[0]["message"])
        self.assertNotIn(secret, json.dumps(events))
        self.assertIn(self.reply, [e.get("message") for e in events if e["type"] == "ASSISTANT_COMPLETE"],
                      "the connection must stay usable after a failed message")

    def test_invalid_payloads_still_report_errors(self):
        events = self.run_ws("{not json", '{"nothing": 1}')
        self.assertEqual([e["type"] for e in events if e["type"] == "ERROR"], ["ERROR", "ERROR"])

    def test_handler_source_catches_unexpected_exceptions(self):
        src = (BACKEND / "api" / "websocket.py").read_text()
        self.assertIn("except Exception as exc", src)
        self.assertIn("except WebSocketDisconnect:\n                raise", src)


if __name__ == "__main__":
    unittest.main()
