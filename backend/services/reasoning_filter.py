"""Hide model reasoning from user-visible answers.

Reasoning models either send hidden thoughts in a separate
``reasoning_content`` delta (llama.cpp, vLLM) -- which LLMService ignores --
or inline them as ``<think>...</think>`` in the content. ``ThinkTagFilter``
removes the inline form from a token stream, even when tags are split
across chunks.
"""
import re

OPEN = "<think>"
CLOSE = "</think>"
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_reasoning(text: str) -> str:
    text = _THINK_RE.sub("", text)
    if OPEN in text:  # unclosed block: drop everything after it
        text = text.split(OPEN, 1)[0]
    return text


class ThinkTagFilter:
    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    @staticmethod
    def _partial_suffix(s: str, tag: str) -> int:
        """Length of the longest suffix of s that is a proper prefix of tag."""
        for n in range(min(len(tag) - 1, len(s)), 0, -1):
            if s.endswith(tag[:n]):
                return n
        return 0

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = []
        while True:
            if self._in_think:
                i = self._buf.find(CLOSE)
                if i == -1:
                    keep = self._partial_suffix(self._buf, CLOSE)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    break
                self._buf = self._buf[i + len(CLOSE):]
                self._in_think = False
            else:
                i = self._buf.find(OPEN)
                if i == -1:
                    keep = self._partial_suffix(self._buf, OPEN)
                    emit = self._buf[: len(self._buf) - keep]
                    out.append(emit)
                    self._buf = self._buf[len(emit):]
                    break
                out.append(self._buf[:i])
                self._buf = self._buf[i + len(OPEN):]
                self._in_think = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._in_think else self._buf
        self._buf = ""
        return rest
