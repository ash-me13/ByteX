"""
Incremental (token-by-token) safety filters for streamed model output. Pure stdlib, no I/O.

* ThinkStripper  - removes <think>...</think> reasoning blocks while streaming (used by the AI router).
* ProtocolGate   - decides, chunk by chunk, which text may be forwarded to the UI / speech as ASSISTANT_DELTA.
                   Internal agent protocol (tool calls, JSON tool requests, reasoning tags) is never forwarded,
                   and a possibly-incomplete marker at the end of the buffer (e.g. "<to") is held back until the
                   next chunk resolves it. Held-back text that never resolves is simply not forwarded as a delta;
                   the single ASSISTANT_COMPLETE event still carries the full, sanitized response.

The final tool-call detection in core/assistant.py still runs on the complete raw response, so confirmation and
risk-classification behaviour is unchanged by this module.
"""
from typing import Iterable, List

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

# Text that starts a message and marks it as internal protocol (never forwarded as deltas).
START_MARKERS = ("<think>", "<tool>", "<tool_call>", "```")
START_CHARS = ("{",)
# Markers that end deltas the moment they appear anywhere in the stream.
INLINE_MARKERS = ("<tool_call>", "<tool>", "<think>")


def partial_marker_suffix_len(text: str, markers: Iterable[str]) -> int:
    """Length of the longest suffix of `text` that is a PROPER prefix of one of `markers` (0 if none)."""
    best = 0
    for marker in markers:
        for k in range(min(len(marker) - 1, len(text)), 0, -1):
            if text.endswith(marker[:k]):
                best = max(best, k)
                break
    return best


class ThinkStripper:
    """Streaming equivalent of re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)."""

    def __init__(self) -> None:
        self._pending = ""
        self._in_think = False
        self._emitted = False
        self._think_parts: List[str] = []

    def feed(self, chunk: str) -> str:
        buf = self._pending + (chunk or "")
        self._pending = ""
        out: List[str] = []
        while buf:
            if self._in_think:
                i = buf.find(THINK_CLOSE)
                if i == -1:
                    keep = partial_marker_suffix_len(buf, (THINK_CLOSE,))
                    self._think_parts.append(buf[: len(buf) - keep])
                    self._pending = buf[len(buf) - keep:]
                    break
                self._think_parts.append(buf[:i])
                buf = buf[i + len(THINK_CLOSE):]
                self._in_think = False
            else:
                i = buf.find(THINK_OPEN)
                if i == -1:
                    keep = partial_marker_suffix_len(buf, (THINK_OPEN,))
                    out.append(buf[: len(buf) - keep])
                    self._pending = buf[len(buf) - keep:]
                    break
                out.append(buf[:i])
                buf = buf[i + len(THINK_OPEN):]
                self._in_think = True
        return self._emit("".join(out))

    def _emit(self, text: str) -> str:
        if not self._emitted:
            text = text.lstrip()
        if text:
            self._emitted = True
        return text

    def flush(self) -> str:
        """End of stream. Plain text held back as a possible marker prefix is released (it was not a marker)."""
        tail, self._pending = ("", "") if self._in_think else (self._pending, "")
        return self._emit(tail).rstrip() if tail else ""

    @property
    def unterminated_think(self) -> bool:
        return self._in_think

    def reasoning_text(self) -> str:
        return "".join(self._think_parts)


class ProtocolGate:
    """Chunk-by-chunk gate for ASSISTANT_DELTA text. feed() returns the part of the stream that is safe to forward."""

    def __init__(self) -> None:
        self._acc = ""
        self._emitted_len = 0
        self._decided = False
        self.blocked = False

    def feed(self, chunk: str) -> str:
        if self.blocked or not chunk:
            return ""
        self._acc += chunk

        if not self._decided:
            lead = self._acc.lstrip()
            if not lead:
                return ""
            if lead.startswith(START_MARKERS) or lead.startswith(START_CHARS):
                self.blocked = True
                return ""
            if any(m.startswith(lead) for m in START_MARKERS):
                return ""  # could still become a protocol marker ("<", "<to", "`", "``"): hold
            self._decided = True
            self._emitted_len = len(self._acc) - len(lead)

        hits = [i for i in (self._acc.find(m, self._emitted_len) for m in INLINE_MARKERS) if i != -1]
        if hits:
            cut = min(hits)
            safe = self._acc[self._emitted_len:cut]
            self._emitted_len = cut
            self.blocked = True
            return safe

        keep = partial_marker_suffix_len(self._acc, INLINE_MARKERS)
        end = len(self._acc) - keep
        safe = self._acc[self._emitted_len:end]
        self._emitted_len = end
        return safe

    def flush(self) -> str:
        """End of stream: anything still held back may be an incomplete protocol marker, so it is NOT forwarded."""
        return ""
