"""Canonical default system prompt for unscoped / no-persona chats.

The text lives in ``backend/fixtures/personas/cpa_assistant.json`` so the
seed script and the chat fallback stay in lockstep.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.config import settings

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


# CPA demo mode shows the pane as "Client Files"; the prompt must use the visible name.
_VAULT_NAME = "Knowledge Vault"
_DEMO_VAULT_NAME = "Client Files"


def demo_prompt(prompt: str) -> str:
    """The demo-mode variant of a persona prompt: the pane is called Client Files.

    Applied at chat time only while GANTRY_DEMO_MODE is on. The stored persona
    (and the prompt with the flag off) is unchanged.
    """
    return prompt.replace(_VAULT_NAME, _DEMO_VAULT_NAME)


def chat_system_prompt(persona_prompt: str | None, model_name: str | None = None) -> str:
    """Build the system message for a chat turn.

    Uses the assigned persona prompt when provided, otherwise the CPA
    default fixture. Optionally notes the local model name. Never falls
    back to a hardcoded identity that disagrees with the fixtures.
    """
    base = persona_prompt or default_system_prompt()
    if settings.demo_mode:
        base = demo_prompt(base)
    if model_name and model_name not in ("an AI assistant", "default"):
        return f"{base}\n\nThe local model for this session is {model_name}."
    return base
