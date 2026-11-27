"""CPA demo mode, issue 3.2: the per-answer audit deep-link
(GET /api/chat/messages/{id}/audit) and its authorization rules."""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.database import Base  # noqa: E402
from backend.dependencies import get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models.audit_event import AuditEvent  # noqa: E402
from backend.models.conversation import Conversation  # noqa: E402
from backend.services.auth_service import AuthService  # noqa: E402

SOURCES = [
    {"document_id": 7, "filename": "SAMPLE_whitfield_2025_form1040_summary.txt",
     "chunk_text": "Line 11 adjusted gross income (AGI): $89,214", "similarity": 0.81, "chunk_index": 0},
]


@pytest.fixture(autouse=True)
def setup_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestSessionLocal
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db(setup_db):
    s = setup_db()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)


def _user(db, email, role="user"):
    auth = AuthService(db)
    u = auth.create_user(email=email, password="pw-123456", display_name=email.split("@")[0], role=role)
    return u, auth.create_session(u.id)


@pytest.fixture
def sarah(db):
    return _user(db, "sarah.chen@gantry-demo.example.com")


@pytest.fixture
def bob(db):
    return _user(db, "bob@example.com")


@pytest.fixture
def admin(db):
    return _user(db, "admin@gantry-demo.example.com", role="admin")


def _scoped_conversation(client, db, token):
    conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
    c = db.get(Conversation, conv["id"])
    c.document_scope = json.dumps([{"type": "collection", "id": 1}])
    db.commit()
    return conv["id"]


def _send(client, conv_id, token, sources):
    mem = MagicMock()
    mem.search_similar = AsyncMock(return_value=[])
    mem.embed_message = AsyncMock()
    graph = MagicMock()
    graph.extract_entities.return_value = []
    graph.get_related.return_value = []

    async def fake_stream(messages, model=None, temperature=None):
        yield "AGI was $89,214 [1]."

    with patch("backend.routers.chat.LLMService") as MockLLM, \
         patch("backend.routers.chat._create_memory_service", return_value=mem), \
         patch("backend.routers.chat._create_graph_service", return_value=graph), \
         patch("backend.routers.chat._create_document_service") as mk_docs:
        mk_docs.return_value.retrieve_sources.return_value = sources
        MockLLM.return_value = MagicMock(stream_chat=fake_stream, last_usage=None)
        r = client.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": "What AGI?"},
                        cookies={"session_token": token})
    assert r.status_code == 200
    return r


def _assistant_id(client, conv_id, token):
    detail = client.get(f"/api/chat/conversations/{conv_id}", cookies={"session_token": token}).json()
    return [m for m in detail["messages"] if m["role"] == "assistant"][-1]["id"]


class TestMessageAuditDeepLink:
    def test_own_answer_returns_matching_chat_query_row(self, client, db, sarah, demo_on):
        user, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        r = _send(client, conv_id, token, SOURCES)
        done = [json.loads(line[6:]) for line in r.text.split("\n")
                if line.startswith("data: ") and "correlation_id" in line][-1]
        # after a reload the same message id still resolves (nothing client-side to persist)
        msg_id = _assistant_id(client, conv_id, token)
        resp = client.get(f"/api/chat/messages/{msg_id}/audit", cookies={"session_token": token})
        assert resp.status_code == 200, resp.text
        entry = resp.json()
        assert entry["action"] == "chat.query"
        assert entry["user_email"] == user.email
        assert entry["timestamp"]
        assert entry["doc_ids"] == [7]
        assert entry["resource_id"] == conv_id
        assert entry["detail"]["message_id"] == msg_id
        assert entry["detail"]["correlation_id"] == done["correlation_id"]
        assert "ip_address" not in entry

    def test_refused_answer_is_linkable_too(self, client, db, sarah, demo_on):
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        r = _send(client, conv_id, token, [])
        assert '"refused": true' in r.text and "correlation_id" in r.text
        msg_id = _assistant_id(client, conv_id, token)
        resp = client.get(f"/api/chat/messages/{msg_id}/audit", cookies={"session_token": token})
        assert resp.status_code == 200, resp.text
        assert resp.json()["detail"]["refused"] is True

    def test_other_users_answer_is_not_visible(self, client, db, sarah, bob, demo_on):
        _, s_token = sarah
        _, b_token = bob
        conv_id = _scoped_conversation(client, db, s_token)
        _send(client, conv_id, s_token, SOURCES)
        msg_id = _assistant_id(client, conv_id, s_token)
        resp = client.get(f"/api/chat/messages/{msg_id}/audit", cookies={"session_token": b_token})
        assert resp.status_code == 404

    def test_admin_cannot_read_someone_elses_answer_through_this_route(self, client, db, sarah, admin, demo_on):
        _, s_token = sarah
        _, a_token = admin
        conv_id = _scoped_conversation(client, db, s_token)
        _send(client, conv_id, s_token, SOURCES)
        msg_id = _assistant_id(client, conv_id, s_token)
        assert client.get(f"/api/chat/messages/{msg_id}/audit",
                          cookies={"session_token": a_token}).status_code == 404

    def test_user_message_id_is_not_an_audit_handle(self, client, db, sarah, demo_on):
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        _send(client, conv_id, token, SOURCES)
        detail = client.get(f"/api/chat/conversations/{conv_id}", cookies={"session_token": token}).json()
        user_msg = [m for m in detail["messages"] if m["role"] == "user"][0]["id"]
        assert client.get(f"/api/chat/messages/{user_msg}/audit",
                          cookies={"session_token": token}).status_code == 404

    def test_row_written_by_another_user_is_never_returned(self, client, db, sarah, bob, demo_on):
        """Even a forged row pointing at Sarah's message must belong to Sarah."""
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        _send(client, conv_id, token, SOURCES)
        msg_id = _assistant_id(client, conv_id, token)
        db.query(AuditEvent).filter_by(action="chat.query").update({"user_id": bob[0].id})
        db.commit()
        assert client.get(f"/api/chat/messages/{msg_id}/audit",
                          cookies={"session_token": token}).status_code == 404

    def test_requires_login(self, client, db, sarah, demo_on):
        assert client.get("/api/chat/messages/1/audit").status_code == 401

    def test_route_is_off_when_demo_mode_is_off(self, client, db, sarah, monkeypatch):
        monkeypatch.setattr(settings, "demo_mode", False)
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        _send(client, conv_id, token, SOURCES)
        msg_id = _assistant_id(client, conv_id, token)
        assert client.get(f"/api/chat/messages/{msg_id}/audit",
                          cookies={"session_token": token}).status_code == 404


class TestNonAdminCannotListAudit:
    def test_admin_audit_list_and_csv_stay_admin_only(self, client, sarah, demo_on):
        _, token = sarah
        assert client.get("/api/admin/audit", cookies={"session_token": token}).status_code == 403
        assert client.get("/api/admin/audit/export.csv", cookies={"session_token": token}).status_code == 403


class TestConversationAuditFallback:
    """Thread-level fallback for rows that carry no message_id (older refusals)."""

    def test_message_id_is_stored_in_audit_detail_without_a_schema_change(self, client, db, sarah, demo_on):
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        _send(client, conv_id, token, SOURCES)
        row = db.query(AuditEvent).filter_by(action="chat.query").one()
        assert json.loads(row.detail)["message_id"] == _assistant_id(client, conv_id, token)
        assert "message_id" not in AuditEvent.__table__.columns

    def test_legacy_row_without_message_id_falls_back_to_the_thread_list(self, client, db, sarah, demo_on):
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        _send(client, conv_id, token, [])  # refusal
        msg_id = _assistant_id(client, conv_id, token)
        row = db.query(AuditEvent).filter_by(action="chat.query").one()
        detail = json.loads(row.detail)
        detail.pop("message_id")
        row.detail = json.dumps(detail)
        db.commit()
        assert client.get(f"/api/chat/messages/{msg_id}/audit", cookies={"session_token": token}).status_code == 404
        resp = client.get(f"/api/chat/conversations/{conv_id}/audit", cookies={"session_token": token})
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 1 and entries[0]["detail"]["refused"] is True
        assert "ip_address" not in entries[0]

    def test_thread_list_only_has_this_threads_own_rows(self, client, db, sarah, bob, demo_on):
        _, s_token = sarah
        _, b_token = bob
        c1 = _scoped_conversation(client, db, s_token)
        c2 = _scoped_conversation(client, db, s_token)
        _send(client, c1, s_token, SOURCES)
        _send(client, c2, s_token, SOURCES)
        entries = client.get(f"/api/chat/conversations/{c1}/audit", cookies={"session_token": s_token}).json()["entries"]
        assert [e["resource_id"] for e in entries] == [c1]
        # another user cannot read Sarah's thread; an admin gets no wider view either
        assert client.get(f"/api/chat/conversations/{c1}/audit", cookies={"session_token": b_token}).status_code == 404

    def test_thread_route_requires_login_and_demo_mode(self, client, db, sarah, monkeypatch):
        _, token = sarah
        conv_id = _scoped_conversation(client, db, token)
        monkeypatch.setattr(settings, "demo_mode", True)
        assert client.get(f"/api/chat/conversations/{conv_id}/audit").status_code == 401
        monkeypatch.setattr(settings, "demo_mode", False)
        assert client.get(f"/api/chat/conversations/{conv_id}/audit",
                          cookies={"session_token": token}).status_code == 404


class TestModelOverrideInDemoMode:
    """Lookout should-fix: the hidden model picker must be enforced server-side."""

    def _post(self, client, token, conv_id, model):
        mem = MagicMock()
        mem.search_similar = AsyncMock(return_value=[])
        mem.embed_message = AsyncMock()
        graph = MagicMock()
        graph.extract_entities.return_value = []
        graph.get_related.return_value = []
        seen = {}

        async def fake_stream(messages, model=None, temperature=None):
            seen["model"] = model
            yield "ok"

        with patch("backend.routers.chat.LLMService") as MockLLM, \
             patch("backend.routers.chat._create_memory_service", return_value=mem), \
             patch("backend.routers.chat._create_graph_service", return_value=graph), \
             patch("backend.routers.chat.get_default_model", return_value="instance-model"), \
             patch("backend.routers.chat.ModelService.get_active_model",
                   new=AsyncMock(return_value={"id": "loaded", "name": "loaded"})), \
             patch("backend.routers.chat.ModelService.switch_model", new=AsyncMock(return_value=True)) as sw:
            MockLLM.return_value = MagicMock(stream_chat=fake_stream, last_usage=None)
            r = client.post(f"/api/chat/conversations/{conv_id}/messages",
                            json={"content": "hi", "model": model}, cookies={"session_token": token})
        assert r.status_code == 200, r.text
        return sw.await_count, seen.get("model")

    def _conv(self, client, token):
        return client.post("/api/chat/conversations", cookies={"session_token": token}).json()["id"]

    def test_demo_mode_non_admin_cannot_trigger_a_model_switch(self, client, db, sarah, demo_on):
        _, token = sarah
        switches, used = self._post(client, token, self._conv(client, token), "attacker-pick")
        assert switches == 0
        assert used == "instance-model"

    def test_demo_mode_admin_can_still_switch(self, client, db, admin, demo_on):
        _, token = admin
        switches, used = self._post(client, token, self._conv(client, token), "other-model")
        assert switches == 1
        assert used == "other-model"

    def test_flag_off_non_admin_behavior_is_unchanged(self, client, db, sarah, monkeypatch):
        monkeypatch.setattr(settings, "demo_mode", False)
        _, token = sarah
        switches, used = self._post(client, token, self._conv(client, token), "other-model")
        assert switches == 1
        assert used == "other-model"
