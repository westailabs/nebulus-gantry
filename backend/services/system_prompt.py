"""Canonical default system prompt for unscoped / no-persona chats.

The text lives in ``backend/fixtures/personas/cpa_assistant.json`` so the
seed script and the chat fallback stay in lockstep.
"""
from __future__ import annotations

import json
from pathlib import Path

_CPA_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "personas" / "cpa_assistant.json"
)


def default_system_prompt() -> str:
    """Return the CPA Assistant fixture prompt (no secrets, no live config)."""
    data = json.loads(_CPA_FIXTURE.read_text(encoding="utf-8"))
    prompt = data.get("system_prompt")
    if not prompt:
        raise ValueError("cpa_assistant.json is missing system_prompt")
    return prompt


def chat_system_prompt(persona_prompt: str | None, model_name: str | None = None) -> str:
    """Build the system message for a chat turn.

    Uses the assigned persona prompt when provided, otherwise the CPA
    default fixture. Optionally notes the local model name. Never falls
    back to a hardcoded identity that disagrees with the fixtures.
    """
    base = persona_prompt or default_system_prompt()
    if model_name and model_name not in ("an AI assistant", "default"):
        return f"{base}\n\nThe local model for this session is {model_name}."
    return base
