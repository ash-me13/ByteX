"""
Backend streaming tests: incremental forwarding, protocol/reasoning filtering, provider errors, tool confirmation.

Everything runs against the REAL ai/stream_safety.py, ai/router.py, ai/providers/*.py and core/assistant.py with
scripted fake providers (no network, no keys, no desktop actions). Parts that need pydantic skip without it.

    PYTHONPATH=backend python3 -m unittest tests.test_ai_streaming_safety -v
"""
import asyncio
import importlib
import json
import random
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from ai.stream_safety import ProtocolGate, ThinkStripper, partial_marker_suffix_len  # noqa: E402

try:
    import pydantic  # noqa: F401
    HAVE_PYDANTIC = True
except Exception:
    HAVE_PYDANTIC = False

MARKERS = ("<think>", "<tool>", "<tool_call>", "</think>")


def chunkings(text, rng):
    yield [text]
    yield list(text)
    for _ in range(25):
        parts, i = [], 0
        while i < len(text):
            n = rng.randint(1, 6)
            parts.append(text[i:i + n])
            i += n
        yield parts


def run_gate(parts):
    gate, out = ProtocolGate(), []
    for p in parts:
        out.append(gate.feed(p))
    out.append(gate.flush())
    return out


def run_stripper(parts):
    st, out = ThinkStripper(), []
    for p in parts:
        out.append(st.feed(p))
    out.append(st.flush())
    return "".join(out), st


class ThinkStripperTests(unittest.TestCase):
    SAMPLES = [
        "Hello there.",
        "<think>reasoning here</think>The answer is 4.",
        "<think>a</think>\n\nSecond <think>b</think>part.",
        "Plain with a < sign and 2<3.",
        "<think>only thoughts</think>",
    ]

    def test_equivalent_to_regex_for_every_chunking(self):
        rng = random.Random(7)
        for text in self.SAMPLES:
            expected = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            for parts in chunkings(text, rng):
                got, _ = run_stripper(parts)
                self.assertEqual(got.strip(), expected, (text, parts))

    def test_first_text_is_available_before_the_stream_ends(self):
        st = ThinkStripper()
        self.assertEqual(st.feed("<think>hmm</think>Hel"), "Hel")
        self.assertEqual(st.feed("lo"), "lo")

    def test_unterminated_think_emits_nothing_and_keeps_reasoning(self):
        got, st = run_stripper(["<think>all of the answer is", " in here"])
        self.assertEqual(got, "")
        self.assertTrue(st.unterminated_think)
        self.assertIn("in here", st.reasoning_text())

    def test_partial_marker_at_end_is_released_when_it_was_not_a_marker(self):
        got, _ = run_stripper(["value <thi"])
        self.assertEqual(got, "value <thi")


class ProtocolGateTests(unittest.TestCase):
    def test_plain_answer_is_forwarded_in_full_and_incrementally(self):
        rng = random.Random(1)
        text = "Sure. Here is a short answer with 2 < 3 and a <b> tag."
        for parts in chunkings(text, rng):
            out = run_gate(parts)
            self.assertTrue(text.startswith("".join(out)) and len(text) - len("".join(out)) <= 5, (parts, out))

    def test_first_words_are_not_held_until_the_end(self):
        gate = ProtocolGate()
        self.assertEqual(gate.feed("Hello "), "Hello ")
        self.assertEqual(gate.feed("wor"), "wor")

    def test_protocol_streams_never_leak_in_any_chunking(self):
        rng = random.Random(3)
        calls = [
            '<tool>{"name": "delete_file", "arguments": {"path": "x"}}</tool>',
            '<tool_call>{"name": "x"}</tool_call>',
            '{"tool_use": {"name": "open_application", "arguments": {}}}',
            '```json\n{"name": "x", "arguments": {}}\n```',
            '<think>secret reasoning</think>',
            '  \n <tool>{"name": "x"}',          # truncated, leading whitespace
        ]
        for text in calls:
            for parts in chunkings(text, rng):
                emitted = "".join(run_gate(parts))
                self.assertEqual(emitted, "", (text, parts, emitted))

    def test_text_before_an_inline_tool_call_is_forwarded_but_the_call_is_not(self):
        rng = random.Random(5)
        text = 'Let me check that. <tool>{"name": "web_search", "arguments": {"q": "x"}}</tool>'
        for parts in chunkings(text, rng):
            emitted = "".join(run_gate(parts))
            self.assertTrue(emitted.startswith("Let me check that."), (parts, emitted))
            self.assertNotIn("<tool", emitted)
            self.assertNotIn("web_search", emitted)

    def test_emitted_text_never_contains_or_ends_in_a_protocol_marker(self):
        rng = random.Random(11)
        texts = ["Fine <to", "a <tool_ b", 'Go <tool>{"x":1}', "x <think>y</think> z", "100 < 200 <", "end <tool_call"]
        for text in texts:
            for parts in chunkings(text, rng):
                emitted = "".join(run_gate(parts))
                for m in MARKERS:
                    self.assertNotIn(m, emitted)
                self.assertEqual(partial_marker_suffix_len(emitted, ("<think>", "<tool>", "<tool_call>")), 0, (text, emitted))

    def test_marker_lookalike_is_released_once_resolved(self):
        gate = ProtocolGate()
        self.assertEqual(gate.feed("<"), "")          # could still become <tool>
        self.assertEqual(gate.feed("to"), "")
        self.assertEqual(gate.feed("day is Monday"), "<today is Monday")


# ----------------------------------------------------------------------------------------------------------------
# Router / provider / assistant harness (stubbed providers, real router + gate + assistant)
# ----------------------------------------------------------------------------------------------------------------
class ScriptedProvider:
    """stream() yields str items and raises Exception items, in order. Records how often it was called."""

    def __init__(self, script, api_key="test-key"):
        self.script, self.api_key, self.calls = script, api_key, 0
        self.yield_log = []

    async def stream(self, messages, **kwargs):
        self.calls += 1
        for item in self.script:
            if isinstance(item, Exception):
                raise item
            self.yield_log.append(item)
            yield item


class RouterHarness(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sys.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("ai.router", "ai.stream_safety", "ai.providers.groq_provider", "ai.providers.gemini_provider",
                     "ai.prompts.system", "config.settings", "core.assistant"):
            sys.modules.pop(name, None)

        def stub(name, **attrs):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m
            return m

        self.settings = types.SimpleNamespace(AI_PRIMARY_PROVIDER="groq", GROQ_API_KEY="k", GEMINI_API_KEY="k",
                                              GROQ_MODEL="m1", GEMINI_MODEL="g1")
        stub("config.settings", settings=self.settings)
        stub("ai.providers.groq_provider", GroqProvider=lambda: ScriptedProvider([]))
        stub("ai.providers.gemini_provider", GeminiProvider=lambda: ScriptedProvider([]))
        stub("ai.prompts.system", get_system_prompt=lambda: "system")
        self.router_mod = importlib.import_module("ai.router")

    def make_router(self, groq, gemini):
        r = self.router_mod.AIRouter()
        r.groq_provider, r.gemini_provider = ScriptedProvider(groq), ScriptedProvider(gemini)
        return r

    def collect(self, router):
        async def go():
            out, err = [], None
            try:
                async for c in router.stream_response([{"role": "user", "content": "hi"}]):
                    out.append(c)
            except Exception as e:
                err = e
            return out, err
        with mock.patch("builtins.print"):
            return asyncio.run(go())


class RouterStreamingTests(RouterHarness):
    def test_groq_chunks_are_forwarded_incrementally_not_buffered(self):
        r = self.make_router(["Hel", "lo ", "world"], [])
        log = []

        async def go():
            async for c in r.stream_response([]):
                log.append(("out", c, len(r.groq_provider.yield_log)))
        with mock.patch("builtins.print"):
            asyncio.run(go())
        self.assertEqual([c for _, c, _ in log], ["Hel", "lo ", "world"])
        # The first chunk reached the consumer when the provider had produced only one chunk.
        self.assertEqual(log[0][2], 1)

    def test_reasoning_is_removed_incrementally(self):
        r = self.make_router(["<think>ponder", "ing</think>", "Answer", " here"], [])
        out, err = self.collect(r)
        self.assertIsNone(err)
        self.assertEqual("".join(out), "Answer here")
        self.assertNotIn("<think>", "".join(out))

    def test_answer_entirely_inside_think_still_falls_back_to_concluding_line(self):
        r = self.make_router(["<think>step one\nThe final answer is 42.", "</think>"], [])
        out, _ = self.collect(r)
        self.assertEqual("".join(out), "The final answer is 42.")

    def test_groq_failure_before_any_text_falls_back_to_gemini(self):
        r = self.make_router([RuntimeError("boom")], ["from ", "gemini"])
        out, err = self.collect(r)
        self.assertIsNone(err)
        self.assertEqual("".join(out), "from gemini")
        self.assertEqual(r.gemini_provider.calls, 1)

    def test_groq_failure_after_text_raises_interrupted_and_does_not_restart(self):
        r = self.make_router(["Partial ", "answer", RuntimeError("socket closed")], ["SHOULD NOT APPEAR"])
        out, err = self.collect(r)
        self.assertEqual("".join(out), "Partial answer")
        self.assertIsInstance(err, self.router_mod.StreamInterrupted)
        self.assertEqual(r.gemini_provider.calls, 0)

    def test_gemini_failure_after_text_raises_interrupted_without_unavailable_message(self):
        self.settings.AI_PRIMARY_PROVIDER = "other"
        r = self.make_router([], ["Some ", "words", RuntimeError("dropped")])
        out, err = self.collect(r)
        self.assertEqual("".join(out), "Some words")
        self.assertIsInstance(err, self.router_mod.StreamInterrupted)
        self.assertNotIn("unavailable", "".join(out))

    def test_all_providers_failing_before_text_gives_the_friendly_message(self):
        r = self.make_router([RuntimeError("a")], [RuntimeError("b")])
        out, err = self.collect(r)
        self.assertIsNone(err)
        self.assertIn("unavailable", "".join(out))


class GroqProviderMidStreamTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sys.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("ai.providers.groq_provider", "config.settings", "groq"):
            sys.modules.pop(name, None)
        sys.modules["config.settings"] = types.SimpleNamespace(settings=types.SimpleNamespace(GROQ_API_KEY="k", GROQ_MODEL="m1"))
        self.created = []
        outer = self

        def chunk(text):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])

        class Completions:
            async def create(self, model, **kw):
                outer.created.append(model)
                plan = outer.plans.pop(0)

                async def gen():
                    for item in plan:
                        if isinstance(item, Exception):
                            raise item
                        yield chunk(item)
                if isinstance(plan, Exception):
                    raise plan
                return gen()

        class FakeClient:
            def __init__(self, api_key=None):
                self.chat = types.SimpleNamespace(completions=Completions())
        groq_mod = types.ModuleType("groq")
        groq_mod.AsyncGroq = FakeClient
        sys.modules["groq"] = groq_mod
        self.mod = importlib.import_module("ai.providers.groq_provider")

    def collect(self, plans):
        self.plans = list(plans)
        self.created.clear()

        async def go():
            out, err = [], None
            try:
                async for c in self.mod.GroqProvider().stream([]):
                    out.append(c)
            except Exception as e:
                err = e
            return out, err
        with mock.patch("builtins.print"):
            return asyncio.run(go())

    def test_failure_before_any_text_tries_the_next_model(self):
        out, err = self.collect([RuntimeError("model 1 down"), ["ok ", "answer"]])
        self.assertIsNone(err)
        self.assertEqual("".join(out), "ok answer")
        self.assertEqual(len(self.created), 2)

    def test_failure_after_text_never_retries_another_model(self):
        out, err = self.collect([["half ", RuntimeError("reset")], ["WRONG SECOND ANSWER"]])
        self.assertEqual("".join(out), "half ")
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(len(self.created), 1)


class GeminiProviderTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sys.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("ai.providers.gemini_provider", "config.settings", "httpx"):
            sys.modules.pop(name, None)
        sys.modules["config.settings"] = types.SimpleNamespace(settings=types.SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="g1"))
        outer = self
        self.posted, self.streamed = [], []

        class Res:
            def __init__(self, status, lines=None, body=None):
                self.status_code, self._lines, self._body, self.text = status, lines or [], body or {}, ""

            async def aiter_lines(self):
                for item in self._lines:
                    if isinstance(item, Exception):
                        raise item
                    yield item

            def json(self):
                return self._body

        class StreamCtx:
            def __init__(self, res):
                self.res = res

            async def __aenter__(self):
                if isinstance(self.res, Exception):
                    raise self.res
                return self.res

            async def __aexit__(self, *a):
                return False

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, **kw):
                outer.streamed.append(url)
                return StreamCtx(outer.sse)

            async def post(self, url, **kw):
                outer.posted.append(url)
                return outer.single

        httpx = types.ModuleType("httpx")
        httpx.AsyncClient = Client
        httpx.Timeout = lambda *a, **k: None
        sys.modules["httpx"] = httpx
        self.Res = Res
        self.mod = importlib.import_module("ai.providers.gemini_provider")

    @staticmethod
    def sse(text):
        return "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]})

    def collect(self, sse, single=None):
        self.sse, self.single = sse, single

        async def go():
            out, err = [], None
            try:
                async for c in self.mod.GeminiProvider().stream([{"role": "user", "content": "hi"}]):
                    out.append(c)
            except Exception as e:
                err = e
            return out, err
        return asyncio.run(go())

    def test_extract_sse_texts_ignores_noise(self):
        f = self.mod.extract_sse_texts
        self.assertEqual(f(self.sse("Hi")), ["Hi"])
        for noise in ("", ": keepalive", "data: [DONE]", "data: {not json", "event: x", 'data: {"candidates": []}', "data: 5"):
            self.assertEqual(f(noise), [], noise)

    def test_sse_chunks_are_forwarded_and_non_streaming_is_not_used(self):
        out, err = self.collect(self.Res(200, [self.sse("Hel"), "", self.sse("lo")]))
        self.assertIsNone(err)
        self.assertEqual(out, ["Hel", "lo"])
        self.assertEqual(self.posted, [])

    def test_http_error_on_streaming_endpoint_falls_back_to_single_request(self):
        single = self.Res(200, body={"candidates": [{"content": {"parts": [{"text": "one shot answer"}]}}]})
        out, err = self.collect(self.Res(500), single)
        self.assertIsNone(err)
        self.assertEqual("".join(out), "one shot answer")
        self.assertEqual(len(self.posted), 1)

    def test_failure_after_text_does_not_fall_back_or_duplicate(self):
        single = self.Res(200, body={"candidates": [{"content": {"parts": [{"text": "DUPLICATE"}]}}]})
        out, err = self.collect(self.Res(200, [self.sse("Part"), OSError("reset")]), single)
        self.assertEqual(out, ["Part"])
        self.assertIsInstance(err, OSError)
        self.assertEqual(self.posted, [])

    def test_api_key_is_not_written_to_log_messages(self):
        with self.assertLogs("bytex.gemini_provider", level="WARNING") as cm:
            self.collect(self.Res(500), self.Res(200, body={"candidates": [{"content": {"parts": [{"text": "x"}]}}]}))
        self.assertNotIn("key=", "\n".join(cm.output))


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed")
class AssistantStreamingTests(RouterHarness):
    """Real core/assistant.py + real router + real gate; fake providers, fake skill registry."""

    def setUp(self):
        super().setUp()

        def stub(name, **attrs):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m
            return m

        for name in ("core.events", "core.response_sanitizer", "core.confirmation", "models.schemas", "core.command_router",
                     "memory.service", "skills.registry"):
            sys.modules.pop(name, None)
        self.executed = []
        outer = self

        class Result:
            def __init__(self, **kw):
                self.confirmation_required = kw.get("confirmation_required", False)
                self.tool, self.action = kw.get("tool"), kw.get("action")
                self.message, self.error, self.pending_action = kw.get("message", "done"), None, kw.get("pending_action")

        async def execute_tool(name, args, **kw):
            outer.executed.append(name)
            if name == "delete_file":
                return Result(confirmation_required=True, tool=name, action="delete_file",
                              message="Delete the file?", pending_action=dict(args))
            return Result(message="tool ran")

        stub("skills")
        stub("skills.registry", skill_registry=types.SimpleNamespace(execute_tool=execute_tool))

        class CR:
            @staticmethod
            async def route_command(m, h=None):
                return (False, None, None, None)
        stub("core.command_router", CommandRouter=CR)
        stub("memory.service", memory_service=types.SimpleNamespace(get_context_for_prompt=lambda m: ""))
        self.assistant_mod = importlib.import_module("core.assistant")
        from core.confirmation import set_conversation_id
        set_conversation_id("test-conversation")

    def run_turn(self, groq_script):
        core = self.assistant_mod.ByteXCore()
        r = self.make_router(groq_script, [])
        self.assistant_mod.ai_router = r

        async def go():
            return [e async for e in core.process_user_message("hi")]
        with mock.patch("builtins.print"):
            events = asyncio.run(go())
        return [json.loads(e.model_dump_json()) for e in events]

    def test_plain_answer_streams_deltas_and_one_complete_with_same_text(self):
        events = self.run_turn(["Hel", "lo, ", "this is ", "a test."])
        deltas = [e["content"] for e in events if e["type"] == "ASSISTANT_DELTA"]
        completes = [e["message"] for e in events if e["type"] == "ASSISTANT_COMPLETE"]
        self.assertGreaterEqual(len(deltas), 3)
        self.assertEqual("".join(deltas), "Hello, this is a test.")
        self.assertEqual(completes, ["Hello, this is a test."])

    def test_reasoning_and_tool_text_never_reach_deltas(self):
        events = self.run_turn(["<think>private</think>", "Okay. ", "<to", "ol>", '{"name": "echo", "arguments": {}}', "</tool>"])
        deltas = "".join(e["content"] for e in events if e["type"] == "ASSISTANT_DELTA")
        for bad in ("<think", "private", "<tool", '"name"', "echo"):
            self.assertNotIn(bad, deltas)
        self.assertTrue(deltas.startswith("Okay."))

    def test_model_tool_call_needing_approval_still_asks_the_user_and_is_not_spoken(self):
        call = '<tool>{"name": "delete_file", "arguments": {"path": "/tmp/x"}}</tool>'
        events = self.run_turn([call[:10], call[10:]])
        self.assertEqual(self.executed, ["delete_file"])  # routed through execute_tool (the policy gate), once
        deltas = "".join(e.get("content") or "" for e in events if e["type"] == "ASSISTANT_DELTA")
        self.assertEqual(deltas, "")
        complete = [e["message"] for e in events if e["type"] == "ASSISTANT_COMPLETE"][0]
        self.assertIn("confirm", complete.lower())

    def test_interrupted_stream_never_executes_a_truncated_tool_call(self):
        call = '<tool>{"name": "delete_file", "arguments": {"path": "/tmp/x"}}'  # complete JSON, no closing tag
        events = self.run_turn([call, RuntimeError("connection dropped")])
        self.assertEqual(self.executed, [])
        complete = [e["message"] for e in events if e["type"] == "ASSISTANT_COMPLETE"]
        self.assertEqual(len(complete), 1)
        self.assertIn("incomplete", complete[0])
        self.assertNotIn("delete_file", complete[0])

    def test_interrupted_plain_answer_keeps_the_text_and_adds_a_notice_once(self):
        events = self.run_turn(["The capital of ", "France is", RuntimeError("reset")])
        deltas = "".join(e["content"] for e in events if e["type"] == "ASSISTANT_DELTA")
        complete = [e["message"] for e in events if e["type"] == "ASSISTANT_COMPLETE"]
        self.assertEqual(len(complete), 1)
        self.assertTrue(complete[0].startswith("The capital of France is"))
        self.assertEqual(complete[0].count("incomplete"), 1)
        self.assertIn("incomplete", deltas)  # the notice is spoken too
        self.assertEqual(events[-1]["state"], "idle")

    def test_latency_logging_has_no_message_content(self):
        core = self.assistant_mod.ByteXCore()
        r = self.make_router(["SECRET-ANSWER-TEXT"], [])
        self.assistant_mod.ai_router = r
        printed = []

        async def go():
            return [e async for e in core.process_user_message("SECRET-QUESTION-TEXT")]
        with mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            asyncio.run(go())
        text = "\n".join(printed)
        self.assertIn("first_ai_text_ms=", text)
        self.assertIn("ai_total_ms=", text)
        self.assertNotIn("SECRET", text)


if __name__ == "__main__":
    unittest.main()
