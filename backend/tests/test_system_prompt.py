"""Tests for the shared default / CPA system prompt helper."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.services.system_prompt import (  # noqa: E402
    chat_system_prompt,
    default_system_prompt,
)


REQUIRED_PHRASES = (
    "local only",
    "Knowledge Vault",
    "Docs control",
    "in scope",
    "persona",
    "in-app memory",
    "not an organization-wide long-term memory",
    "environment variables",
    "filesystem",
    "cannot run code",
    "Do not ask for those capabilities",
)

FORBIDDEN_PHRASES = (
    "You are Moto",
    "SECRET",
    "password",
    "api_key",
    "NEO4J",
    "7688",
    "8002",
)


def test_default_prompt_describes_real_gantry_capabilities():
    prompt = default_system_prompt()
    lowered = prompt.lower()
    for phrase in REQUIRED_PHRASES:
        assert phrase.lower() in lowered, f"missing: {phrase}"
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in lowered, f"forbidden: {phrase}"
    assert "West AI Labs" in prompt
    assert "CPA" in prompt


def test_chat_system_prompt_falls_back_to_fixture_not_moto():
    prompt = chat_system_prompt(None, model_name="nemotron-bolt")
    assert "You are Moto" not in prompt
    assert "CPA Assistant" in prompt
    assert "The local model for this session is nemotron-bolt." in prompt


def test_chat_system_prompt_uses_assigned_persona():
    prompt = chat_system_prompt("You are a tax reviewer.", model_name="nemotron-bolt")
    assert prompt.startswith("You are a tax reviewer.")
    assert "CPA Assistant" not in prompt
    assert "The local model for this session is nemotron-bolt." in prompt


def test_chat_system_prompt_skips_generic_model_name():
    prompt = chat_system_prompt("Just the persona.", model_name="an AI assistant")
    assert prompt == "Just the persona."


def test_demo_mode_prompt_says_client_files_not_knowledge_vault(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    for prompt in (chat_system_prompt(None), chat_system_prompt(default_system_prompt(), "bolt")):
        assert "Client Files" in prompt
        assert "Knowledge Vault" not in prompt
        assert "Docs control" in prompt  # the rest of the prompt is untouched


def test_flag_off_prompt_is_unchanged(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    assert chat_system_prompt(None) == default_system_prompt()
    assert "Knowledge Vault" in chat_system_prompt(None)
    assert "Client Files" not in chat_system_prompt(None)


def test_stored_persona_fixture_is_never_rewritten(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    assert "Knowledge Vault" in default_system_prompt()
