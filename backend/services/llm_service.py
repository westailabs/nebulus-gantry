import json
import os
import httpx
from typing import AsyncGenerator

from backend.platform import get_llm_base_url, get_default_model
from backend.services.reasoning_filter import ThinkTagFilter, strip_reasoning

EMPTY_ANSWER_MESSAGE = (
    "[The model returned no answer text (it may have spent its budget on "
    "hidden reasoning). Please try again or rephrase.]"
)


def _reasoning_prefilled() -> bool:
    """True when the model's chat template prefills <think> (only </think> is emitted)."""
    return os.getenv("GANTRY_REASONING_PREFILLED", "false").lower() in ("true", "1", "yes")


def _get_max_tokens() -> int | None:
    """Optional completion cap from NEBULUS_LLM_MAX_TOKENS (unset = server default)."""
    raw = os.getenv("NEBULUS_LLM_MAX_TOKENS")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _get_llm_headers() -> dict:
    """Build auth headers for LLM API if NEBULUS_LLM_API_KEY is set."""
    api_key = os.getenv("NEBULUS_LLM_API_KEY")
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


class LLMService:
    """OpenAI-compatible LLM client for streaming and non-streaming chat.

    CONCURRENCY NOTE: This class stores per-call state in self.last_usage.
    It is safe ONLY because callers instantiate a new LLMService() per
    request (see chat.py send_message / dispatch_message).  Do NOT convert
    this to a singleton or shared dependency without first removing the
    mutable instance state.
    """

    def __init__(self):
        self.base_url = get_llm_base_url()
        self.headers = _get_llm_headers()
        self.last_usage: dict | None = None
        self.last_finish_reason: str | None = None
        # Out-of-band status for the last stream_chat call:
        # last_error: None | "empty_answer" | "connect_error" | "http_<code>" | "<ExceptionType>"
        self.last_error: str | None = None
        # Set when an orphan </think> showed the streamed text included reasoning;
        # holds the cleaned answer the caller should show/store instead.
        self.reasoning_leak_cleaned: str | None = None

    async def stream_chat(  # noqa: C901
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion from the LLM inference server (OpenAI-compatible).

        Yields chunks of the assistant's response.

        Args:
            messages: List of message dicts with role and content.
            model: Model ID to use (default: "default").
            temperature: Optional temperature override (0.0-2.0).

        After iteration completes, self.last_usage contains token usage
        data if the API provided it (prompt_tokens, completion_tokens,
        total_tokens).
        """
        self.last_usage = None
        self.last_error = None
        self.reasoning_leak_cleaned = None
        self.last_finish_reason = None
        raw_parts: list[str] = []
        request_body = {
            "model": model or get_default_model(),
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            request_body["temperature"] = temperature
        max_tokens = _get_max_tokens()
        if max_tokens:
            request_body["max_tokens"] = max_tokens

        think_filter = ThinkTagFilter(assume_open=_reasoning_prefilled())
        emitted = False

        # Reasoning models can think for a while before the first answer token,
        # so allow a longer read timeout than the default.
        async with httpx.AsyncClient(timeout=180.0, headers=self.headers) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    json=request_body,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        done, content = self._parse_sse_line(line)
                        if done:
                            break
                        if content:
                            raw_parts.append(content)
                            visible = think_filter.feed(content)
                            if visible:
                                emitted = emitted or bool(visible.strip())
                                yield visible
                    # finish_reason=length before </think> means the held text is cut-off
                    # reasoning, not an answer: drop it (prefill mode).
                    tail = think_filter.flush(truncated=self.last_finish_reason == "length")
                    if tail:
                        emitted = emitted or bool(tail.strip())
                        yield tail
                    if think_filter.saw_orphan_close:
                        self.reasoning_leak_cleaned = strip_reasoning("".join(raw_parts))
                        emitted = bool(self.reasoning_leak_cleaned.strip())
                    if not emitted:
                        self.last_error = "empty_answer"
                        yield EMPTY_ANSWER_MESSAGE
            except httpx.HTTPStatusError as e:
                self.last_error = f"http_{e.response.status_code}"
                yield f"[Error: LLM service returned {e.response.status_code}]"
            except httpx.ConnectError:
                self.last_error = "connect_error"
                yield "[Error: Could not connect to LLM service. Is the LLM service running?]"
            except Exception as e:
                # Don't echo raw exception text to the client.
                self.last_error = type(e).__name__
                yield "[Error: LLM request failed]"

    def _parse_sse_line(self, line: str) -> tuple[bool, str | None]:
        """Parse one SSE line. Returns (done, visible_content_delta).

        Captures token usage into self.last_usage. Only ``content`` is
        user-visible; ``reasoning_content`` (hidden thoughts) is ignored.
        """
        if not line.startswith("data: "):
            return False, None
        data = line[6:]
        if data == "[DONE]":
            return True, None
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return False, None
        if chunk.get("usage"):
            self.last_usage = chunk["usage"]
        choices = chunk.get("choices") or [{}]
        if choices[0].get("finish_reason"):
            self.last_finish_reason = choices[0]["finish_reason"]
        return False, choices[0].get("delta", {}).get("content")

    async def chat(self, messages: list[dict], model: str | None = None) -> str:
        """
        Non-streaming chat completion. Returns full response.
        """
        async with httpx.AsyncClient(timeout=60.0, headers=self.headers) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": model or get_default_model(),
                        "messages": messages,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return strip_reasoning(data["choices"][0]["message"].get("content") or "")
            except Exception as e:
                return f"[Error: {str(e)}]"
