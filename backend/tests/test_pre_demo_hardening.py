"""Plumb re-review (PR #4) pre-demo items: N1 blank replace, prefilled <think>
buffering, /dispatch auditing, persona + doc-scope auditing, audit-failure
counter exposure, correlation id, refusal abort outcome."""
import json
from unittest.mock import MagicMock, patch

from backend.models.audit_event import AuditEvent
from backend.services import audit_service
from backend.services.llm_service import EMPTY_ANSWER_MESSAGE
from backend.services.reasoning_filter import ThinkTagFilter
from backend.tests import test_audit_review_fixes as base
from backend.tests.test_audit_review_fixes import _chat, _chat_event, _scoped

# Reuse the review-fix fixtures (in-memory DB, client, users).
setup_db, db, client = base.setup_db, base.db, base.client
alice, admin = base.alice, base.admin


def _gen(*chunks):
    async def stream(*a, **k):
        for c in chunks:
            yield c
    return stream


def _events(text):
    return [b for b in text.split("\n\n") if b.strip()]


# ── N1: blank cleaned text must not replace the answer ─────────────────────
class TestBlankReplace:
    def test_blank_cleaned_replaced_with_empty_notice(self, client, db, alice):
        conv = _scoped(client, db, alice[1])
        mem_llm = MagicMock()
        mem_llm.last_usage = None
        mem_llm.last_error = "empty_answer"
        mem_llm.reasoning_leak_cleaned = "   "
        mem_llm.stream_chat = _gen("secret plan", EMPTY_ANSWER_MESSAGE)
        with patch("backend.routers.chat.LLMService", return_value=mem_llm), \
             patch("backend.routers.chat._create_memory_service", return_value=None), \
             patch("backend.routers.chat._create_graph_service", return_value=None), \
             patch("backend.routers.chat._create_document_service") as mk:
            mk.return_value.retrieve_sources.return_value = []
            from backend.models.conversation import Conversation
            c = db.get(Conversation, conv)
            c.document_scope = None
            db.commit()
            r = client.post(f"/api/chat/conversations/{conv}/messages", json={"content": "q"},
                            cookies={"session_token": alice[1]})
        reps = [e for e in _events(r.text) if e.startswith("event: replace")]
        assert reps, r.text
        assert json.loads(reps[-1].split("data: ", 1)[1])["content"] == EMPTY_ANSWER_MESSAGE
        from backend.models.message import Message
        msg = db.query(Message).filter_by(role="assistant").one()
        assert msg.content == EMPTY_ANSWER_MESSAGE


# ── Prefilled <think> templates: buffer until </think> ─────────────────────
class TestPrefilledThink:
    def test_reasoning_never_emitted(self):
        f = ThinkTagFilter(assume_open=True)
        out = f.feed("secret ") + f.feed("plan</th") + f.feed("ink>Answer") + f.flush()
        assert out == "Answer"

    def test_no_close_releases_buffer_at_end(self):
        f = ThinkTagFilter(assume_open=True)
        out = f.feed("Just an ") + f.feed("answer") + f.flush()
        assert out == "Just an answer"

    def test_env_enables_prefill(self, monkeypatch):
        from backend.services import llm_service
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        assert llm_service._reasoning_prefilled() is True
        monkeypatch.delenv("GANTRY_REASONING_PREFILLED")
        assert llm_service._reasoning_prefilled() is False


# ── N2: /dispatch audited ──────────────────────────────────────────────────
def test_dispatch_is_audited(client, db, alice, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "overlord_routing_enabled", False)  # exercise the local path
    llm = MagicMock()
    llm.last_usage = None
    llm.last_error = None
    llm.stream_chat = _gen("hi")
    with patch("backend.routers.chat.LLMService", return_value=llm):
        r = client.post("/api/chat/dispatch", json={"user_message": "hello 123-45-6789"},
                        cookies={"session_token": alice[1]})
    assert r.status_code == 200
    ev = db.query(AuditEvent).filter_by(action="chat.dispatch").one()
    d = json.loads(ev.detail)
    assert d["outcome"] == "completed" and d["route"] == "local" and ev.user_id == alice[0].id


# ── #8: persona + doc-scope auditing ───────────────────────────────────────
def test_system_persona_crud_audited(client, db, admin):
    t = {"session_token": admin[1]}
    p = client.post("/api/admin/personas", json={"name": "Tax", "system_prompt": "x"}, cookies=t).json()
    client.patch(f"/api/admin/personas/{p['id']}", json={"system_prompt": "y"}, cookies=t)
    client.delete(f"/api/admin/personas/{p['id']}", cookies=t)
    acts = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert acts == ["persona.create", "persona.update", "persona.delete"]


def test_user_persona_crud_audited(client, db, alice):
    t = {"session_token": alice[1]}
    p = client.post("/api/personas", json={"name": "Mine", "system_prompt": "x"}, cookies=t).json()
    client.patch(f"/api/personas/{p['id']}", json={"name": "Mine2"}, cookies=t)
    client.delete(f"/api/personas/{p['id']}", cookies=t)
    acts = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert acts == ["persona.create", "persona.update", "persona.delete"]


def test_document_scope_change_audited(client, db, alice):
    t = {"session_token": alice[1]}
    conv = client.post("/api/chat/conversations", cookies=t).json()["id"]
    client.patch(f"/api/chat/conversations/{conv}/document-scope",
                 json={"document_scope": [{"type": "document", "id": 3}]}, cookies=t)
    ev = db.query(AuditEvent).filter_by(action="conversation.scope_change").one()
    assert ev.resource_id == conv
    assert json.loads(ev.doc_ids) == [3]
    assert json.loads(ev.detail)["scope"] == [{"type": "document", "id": 3}]


# ── #9: failure counter exposed ────────────────────────────────────────────
def test_audit_list_exposes_write_failures(client, db, admin, monkeypatch):
    monkeypatch.setattr(audit_service, "write_failures", 2)
    r = client.get("/api/admin/audit", cookies={"session_token": admin[1]})
    assert r.json()["audit_write_failures"] == 2


# ── N5: correlation id in done meta and audit message id ───────────────────
def test_correlation_id_in_done_meta(client, db, alice):
    conv = _scoped(client, db, alice[1])
    r = _chat(client, conv, alice[1], _gen("ok [1]"))
    done = next(e for e in _events(r.text) if e.startswith("event: done"))
    meta = json.loads(done.split("data: ", 1)[1])
    d = json.loads(_chat_event(db).detail)
    assert meta["correlation_id"] == d["correlation_id"]
    assert d["message_id"]
