"""Hide model reasoning from user-visible answers.

Reasoning models either send hidden thoughts in a separate
``reasoning_content`` delta (llama.cpp, vLLM) -- which LLMService ignores --
or inline them as ``<think>...</think>`` (also ``<thinking>``/``<reasoning>``,
any case) in the content. Some templates (DeepSeek-R1 distills, Qwen3)
prefill the opening tag, so the model emits only the closing tag; text
before such an orphan close is reasoning too.

``ThinkTagFilter`` removes the inline form from a token stream, even when
tags are split across chunks. An orphan close can only be detected after
the reasoning has streamed, so the filter sets ``saw_orphan_close`` and the
caller should replace the streamed text with ``strip_reasoning(raw)``.
"""
import re

TAGS = ("think", "thinking", "reasoning")
OPENS = tuple(f"<{t}>" for t in TAGS)
CLOSES = tuple(f"</{t}>" for t in TAGS)
_ALL = OPENS + CLOSES
_PAIR_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_OPEN_RE = re.compile(r"<(?:think|thinking|reasoning)>", re.IGNORECASE)
_CLOSE_RE = re.compile(r"</(?:think|thinking|reasoning)>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    text = _PAIR_RE.sub("", text)
    closes = list(_CLOSE_RE.finditer(text))
    if closes:  # orphan close: everything before it was reasoning
        text = text[closes[-1].end():]
    m = _OPEN_RE.search(text)
    if m:  # unclosed block: drop everything after it
        text = text[: m.start()]
    return text


def _find_first(lower: str, tags) -> tuple[int, str | None]:
    best, tag = -1, None
    for t in tags:
        i = lower.find(t)
        if i != -1 and (best == -1 or i < best):
            best, tag = i, t
    return best, tag


def _partial_suffix(lower: str, tags) -> int:
    """Length of the longest suffix of s that is a proper prefix of any tag."""
    longest = max(len(t) for t in tags) - 1
    for n in range(min(longest, len(lower)), 0, -1):
        suf = lower[-n:]
        if any(t.startswith(suf) and t != suf for t in tags):
            return n
    return 0


class ThinkTagFilter:
    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False
        self.saw_orphan_close = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = []
        while True:
            lower = self._buf.lower()
            if self._in_think:
                i, tag = _find_first(lower, CLOSES)
                if i == -1:
                    keep = _partial_suffix(lower, CLOSES)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    break
                self._buf = self._buf[i + len(tag):]
                self._in_think = False
                continue
            io_, otag = _find_first(lower, OPENS)
            ic, ctag = _find_first(lower, CLOSES)
            if ic != -1 and (io_ == -1 or ic < io_):
                # orphan close: drop the tag and the reasoning still buffered
                self.saw_orphan_close = True
                self._buf = self._buf[ic + len(ctag):]
                continue
            if io_ == -1:
                keep = _partial_suffix(lower, _ALL)
                emit = self._buf[: len(self._buf) - keep]
                out.append(emit)
                self._buf = self._buf[len(emit):]
                break
            out.append(self._buf[:io_])
            self._buf = self._buf[io_ + len(otag):]
            self._in_think = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._in_think else self._buf
        self._buf = ""
        return rest
