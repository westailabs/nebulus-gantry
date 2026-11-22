"""Tests for the audit log, structured citations, reasoning stripping, and
no-source refusal (feat/audit-log-citations)."""
import csv
import io
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.database import Base  # noqa: E402
from backend.dependencies import get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models.audit_event import AuditEvent  # noqa: E402
from backend.models.conversation import Conversation  # noqa: E402
from backend.models.document import Document  # noqa: E402
from backend.services.audit_service import AuditService, events_to_csv  # noqa: E402
from backend.services.auth_service import AuthService  # noqa: E402
from backend.services.reasoning_filter import ThinkTagFilter, strip_reasoning  # noqa: E402


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


def _user(db, email, role="user"):
    auth = AuthService(db)
    u = auth.create_user(email=email, password="pw-123456", display_name=email.split("@")[0], role=role)
    return u, auth.create_session(u.id)


@pytest.fixture
def admin(db):
    return _user(db, "admin@example.com", role="admin")


@pytest.fixture
def alice(db):
    return _user(db, "alice@example.com")


def _mock_ltm():
    mem = MagicMock()
    mem.search_similar = AsyncMock(return_value=[])
    mem.embed_message = AsyncMock()
    graph = MagicMock()
    graph.extract_entities.return_value = []
    graph.get_related.return_value = []
    return mem, graph


def _parse_sse(body):
    events, ev = [], None
    for line in body.split("\n"):
        if line.startswith("event: "):
            ev = line[7:].strip()
        elif line.startswith("data: "):
            events.append((ev or "message", json.loads(line[6:])))
            ev = None
    return events


SOURCES = [
    {"document_id": 7, "filename": "dana_whitfield_2025_1040.txt", "chunk_text": "AGI line 11: $84,210",
     "similarity": 0.81, "chunk_index": 0},
    {"document_id": 9, "filename": "dana_whitfield_engagement_2025.txt", "chunk_text": "Engagement letter",
     "similarity": 0.55, "chunk_index": 2},
]


# ── Audit service ────────────────────────────────────────────────────────────


class TestAuditService:
    def test_record_and_list(self, db, alice):
        user, _ = alice
        svc = AuditService(db)
        svc.record("chat.query", user=user, resource_type="conversation", resource_id=3,
                   doc_ids=[7, 9], query_text="what did we file?", detail={"model": "m"})
        events, total = svc.list_events()
        assert total == 1
        e = events[0]
        assert e.action == "chat.query"
        assert e.user_email == "alice@example.com"
        assert json.loads(e.doc_ids) == [7, 9]
        assert e.timestamp is not None

    def test_query_text_not_stored_by_default(self, db, alice, monkeypatch):
        monkeypatch.delenv("GANTRY_AUDIT_STORE_QUERY_TEXT", raising=False)
        user, _ = alice
        AuditService(db).record("chat.query", user=user, query_text="secret client question")
        e = db.query(AuditEvent).one()
        assert e.query_text is None
        assert json.loads(e.detail)["query_chars"] == len("secret client question")

    def test_query_text_stored_when_enabled(self, db, alice, monkeypatch):
        monkeypatch.setenv("GANTRY_AUDIT_STORE_QUERY_TEXT", "true")
        user, _ = alice
        AuditService(db).record("chat.query", user=user, query_text="synthetic q")
        assert db.query(AuditEvent).one().query_text == "synthetic q"

    def test_record_never_raises(self, alice):
        broken = MagicMock()
        broken.add.side_effect = RuntimeError("db down")
        AuditService(broken).record("auth.login", user=alice[0])  # must not raise

    def test_filters(self, db, alice, admin):
        svc = AuditService(db)
        svc.record("auth.login", user=alice[0])
        svc.record("document.upload", user=alice[0], resource_id=1)
        svc.record("auth.login", user=admin[0])
        _, total = svc.list_events(action="auth.login")
        assert total == 2
        _, total = svc.list_events(user_id=alice[0].id)
        assert total == 2

    def test_csv(self, db, alice):
        svc = AuditService(db)
        svc.record("document.upload", user=alice[0], resource_type="document", resource_id=5, doc_ids=[5])
        events, _ = svc.list_events()
        rows = list(csv.reader(io.StringIO(events_to_csv(events))))
        assert rows[0][:4] == ["id", "timestamp", "user_id", "user_email"]
        assert rows[1][4] == "document.upload"


# ── Audit hooks through the API ─────────────────────────────────────────────


class TestAuditHooks:
    def test_login_success_and_failure_audited(self, client, db, alice):
        client.post("/api/auth/login", json={"email": "alice@example.com", "password": "pw-123456"})
        client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong"})
        actions = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)]
        assert actions == ["auth.login", "auth.login_failed"]
        failed = db.query(AuditEvent).filter_by(action="auth.login_failed").one()
        assert failed.user_id is None
        assert failed.user_email == "alice@example.com"

    def test_logout_audited(self, client, db, alice):
        _, token = alice
        client.post("/api/auth/logout", cookies={"session_token": token})
        assert db.query(AuditEvent).filter_by(action="auth.logout").count() == 1

    def test_upload_audited(self, client, db, alice):
        _, token = alice
        fake_doc = MagicMock(id=42, filename="a.txt", content_type="txt", file_size=3, chunk_count=1,
                             status="ready", error_message=None, collection_id=None)
        with patch("backend.routers.documents.DocumentService") as MockSvc:
            MockSvc.return_value.upload_document.return_value = fake_doc
            # route returns DocumentResponse; mimic model fields
            from datetime import datetime, timezone
            fake_doc.created_at = datetime.now(timezone.utc)
            fake_doc.user_id = alice[0].id
            r = client.post("/api/documents/upload", files={"file": ("a.txt", b"abc", "text/plain")},
                            cookies={"session_token": token})
        assert r.status_code == 200, r.text
        e = db.query(AuditEvent).filter_by(action="document.upload").one()
        assert e.resource_id == 42
        assert json.loads(e.doc_ids) == [42]

    def test_export_audited(self, client, db, alice):
        _, token = alice
        conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
        client.get(f"/api/chat/conversations/{conv['id']}/export?format=json", cookies={"session_token": token})
        e = db.query(AuditEvent).filter_by(action="conversation.export").one()
        assert e.resource_id == conv["id"]
        assert json.loads(e.detail)["format"] == "json"

    def test_admin_audit_endpoints(self, client, db, admin, alice):
        AuditService(db).record("auth.login", user=alice[0])
        _, atoken = admin
        r = client.get("/api/admin/audit?limit=10", cookies={"session_token": atoken})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert {"id", "timestamp", "user_email", "action", "doc_ids"} <= set(body["events"][0])
        r = client.get("/api/admin/audit/export.csv", cookies={"session_token": atoken})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "auth.login" in r.text
        # the CSV export itself is audited
        assert db.query(AuditEvent).filter_by(action="audit.export").count() == 1

    def test_audit_requires_admin(self, client, alice):
        _, token = alice
        assert client.get("/api/admin/audit", cookies={"session_token": token}).status_code == 403
        assert client.get("/api/admin/audit/export.csv", cookies={"session_token": token}).status_code == 403


# ── Citations + refusal in chat ─────────────────────────────────────────────


def _scoped_conversation(client, db, token):
    conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
    c = db.get(Conversation, conv["id"])
    c.document_scope = json.dumps([{"type": "collection", "id": 1}])
    db.commit()
    return conv["id"]


class TestChatCitations:
    def _send(self, client, conv_id, token, sources, chunks=("The AGI was ", "$84,210 [1].")):
        mem, graph = _mock_ltm()

        async def fake_stream(messages, model=None, temperature=None):
            for ch in chunks:
                yield ch

        with patch("backend.routers.chat.LLMService") as MockLLM, \
             patch("backend.routers.chat._create_memory_service", return_value=mem), \
             patch("backend.routers.chat._create_graph_service", return_value=graph), \
             patch("backend.routers.chat._create_document_service") as mk_docs:
            mk_docs.return_value.retrieve_sources.return_value = sources
            llm = MagicMock()
            llm.stream_chat = fake_stream
            llm.last_usage = None
            MockLLM.return_value = llm
            r = client.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": "What AGI?"},
                            cookies={"session_token": token})
            return r, MockLLM

    def test_sources_event_and_persistence(self, client, db, alice):
        _, token = alice
        conv_id = _scoped_conversation(client, db, token)
        r, _ = self._send(client, conv_id, token, SOURCES)
        assert r.status_code == 200
        events = _parse_sse(r.text)
        src = [d for ev, d in events if ev == "sources"]
        assert len(src) == 1
        assert src[0][0] == {"n": 1, "document_id": 7, "filename": "dana_whitfield_2025_1040.txt",
                             "chunk_index": 0, "similarity": 0.81, "snippet": "AGI line 11: $84,210"}
        done = [d for ev, d in events if ev == "done"][0]
        assert [s["document_id"] for s in done["sources"]] == [7, 9]
        # persisted on the assistant message and returned on reload
        detail = client.get(f"/api/chat/conversations/{conv_id}", cookies={"session_token": token}).json()
        asst = [m for m in detail["messages"] if m["role"] == "assistant"][0]
        assert [s["n"] for s in asst["sources"]] == [1, 2]
        # audit records the retrieved doc ids
        e = db.query(AuditEvent).filter_by(action="chat.query").one()
        assert json.loads(e.doc_ids) == [7, 9]
        assert json.loads(e.detail)["refused"] is False

    def test_numbered_sources_in_system_prompt(self, client, db, alice):
        _, token = alice
        conv_id = _scoped_conversation(client, db, token)
        captured = {}
        mem, graph = _mock_ltm()

        async def fake_stream(messages, model=None, temperature=None):
            captured["system"] = messages[0]["content"]
            yield "ok"

        with patch("backend.routers.chat.LLMService") as MockLLM, \
             patch("backend.routers.chat._create_memory_service", return_value=mem), \
             patch("backend.routers.chat._create_graph_service", return_value=graph), \
             patch("backend.routers.chat._create_document_service") as mk_docs:
            mk_docs.return_value.retrieve_sources.return_value = SOURCES
            MockLLM.return_value = MagicMock(stream_chat=fake_stream, last_usage=None)
            client.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": "q"},
                        cookies={"session_token": token})
        assert "[1] dana_whitfield_2025_1040.txt" in captured["system"]
        assert "cite" in captured["system"].lower()

    def test_refuses_without_sources(self, client, db, alice):
        _, token = alice
        conv_id = _scoped_conversation(client, db, token)
        r, MockLLM = self._send(client, conv_id, token, [])
        events = _parse_sse(r.text)
        text = "".join(d.get("content", "") for ev, d in events if ev == "message")
        assert "couldn't find" in text.lower()
        assert MockLLM.call_count == 0  # LLM never called when refusing
        assert not any(ev == "sources" and d for ev, d in events)
        e = db.query(AuditEvent).filter_by(action="chat.query").one()
        assert json.loads(e.detail)["refused"] is True

    def test_refusal_can_be_disabled(self, client, db, alice, monkeypatch):
        monkeypatch.setenv("GANTRY_REFUSE_WITHOUT_SOURCES", "false")
        _, token = alice
        conv_id = _scoped_conversation(client, db, token)
        r, _ = self._send(client, conv_id, token, [], chunks=("general answer",))
        assert "general answer" in r.text

    def test_unscoped_chat_has_no_sources_and_no_refusal(self, client, db, alice):
        _, token = alice
        conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
        r, _ = self._send(client, conv["id"], token, SOURCES, chunks=("hello",))
        assert "hello" in r.text
        assert "event: sources" not in r.text


# ── Chunk viewer ─────────────────────────────────────────────────────────────


class TestChunkViewer:
    def test_get_chunk(self, client, db, alice):
        user, token = alice
        doc = Document(user_id=user.id, filename="n.txt", content_type="txt", file_size=10,
                       chunk_count=2, status="ready")
        db.add(doc)
        db.commit()
        with patch("backend.routers.documents.DocumentService") as MockSvc:
            inst = MockSvc.return_value
            inst.get_document.return_value = doc
            inst.get_chunk_text.return_value = "CP2000 proposed amount due $1,234"
            r = client.get(f"/api/documents/{doc.id}/chunks/1", cookies={"session_token": token})
        assert r.status_code == 200
        assert r.json() == {"document_id": doc.id, "filename": "n.txt", "chunk_index": 1, "chunk_count": 2,
                            "text": "CP2000 proposed amount due $1,234"}
        assert db.query(AuditEvent).filter_by(action="document.view_source").count() == 1

    def test_chunk_out_of_range_404(self, client, db, alice):
        user, token = alice
        doc = Document(user_id=user.id, filename="n.txt", content_type="txt", file_size=10,
                       chunk_count=1, status="ready")
        db.add(doc)
        db.commit()
        with patch("backend.routers.documents.DocumentService") as MockSvc:
            MockSvc.return_value.get_document.return_value = doc
            r = client.get(f"/api/documents/{doc.id}/chunks/5", cookies={"session_token": token})
        assert r.status_code == 404

    def test_other_users_doc_404(self, client, db, alice):
        _, token = alice
        with patch("backend.routers.documents.DocumentService") as MockSvc:
            MockSvc.return_value.get_document.return_value = None
            r = client.get("/api/documents/99/chunks/0", cookies={"session_token": token})
        assert r.status_code == 404


class TestDocumentServiceSources:
    def test_retrieve_sources_filters_scope(self, db):
        from backend.services.document_service import DocumentService
        svc = DocumentService(db)
        with patch.object(svc, "search_documents", return_value=SOURCES):
            out = svc.retrieve_sources(1, "q", [{"type": "document", "id": 9}], top_k=3)
        assert [s["document_id"] for s in out] == [9]

    def test_get_chunk_text(self, db):
        from backend.services.document_service import DocumentService
        svc = DocumentService(db)
        coll = MagicMock()
        coll.get.return_value = {"ids": ["doc_3_chunk_1"], "documents": ["chunk text"]}
        svc._vector_client = MagicMock()
        svc._vector_client.get_or_create_collection.return_value = coll
        svc._chroma_available = True
        assert svc.get_chunk_text(user_id=1, document_id=3, chunk_index=1) == "chunk text"
        coll.get.assert_called_once_with(ids=["doc_3_chunk_1"])


# ── Reasoning stripping ─────────────────────────────────────────────────────


class TestReasoningFilter:
    def test_strip_reasoning(self):
        assert strip_reasoning("<think>hmm</think>Answer") == "Answer"
        assert strip_reasoning("A<think>x\ny</think> B") == "A B"
        assert strip_reasoning("no tags") == "no tags"

    def test_stream_filter_across_chunk_boundaries(self):
        f = ThinkTagFilter()
        out = "".join(f.feed(c) for c in ["<th", "ink>secret plan", " more</thi", "nk>Final", " answer"])
        out += f.flush()
        assert out == "Final answer"

    def test_stream_filter_unclosed_think_dropped(self):
        f = ThinkTagFilter()
        out = f.feed("Hi <think>never closed") + f.flush()
        assert out == "Hi "

    def test_stream_filter_lone_angle_bracket_kept(self):
        f = ThinkTagFilter()
        out = f.feed("a < b and 3<4") + f.flush()
        assert out == "a < b and 3<4"


class TestLLMServiceReasoning:
    @pytest.mark.asyncio
    async def test_reasoning_content_ignored_and_think_tags_stripped(self):
        from backend.services.llm_service import LLMService

        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}',
            'data: {"choices":[{"delta":{"content":"<think>x</think>"}}]}',
            'data: {"choices":[{"delta":{"content":"The answer"}}]}',
            "data: [DONE]",
        ]

        class Resp:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                for ln in lines:
                    yield ln

        class Ctx:
            async def __aenter__(self):
                return Resp()

            async def __aexit__(self, *a):
                return False

        class Client:
            def __init__(self, *a, **k):
                self.sent = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, json=None):
                Client.body = json
                return Ctx()

        with patch("backend.services.llm_service.httpx.AsyncClient", Client):
            svc = LLMService()
            out = [c async for c in svc.stream_chat([{"role": "user", "content": "q"}])]
        assert "".join(out) == "The answer"

    @pytest.mark.asyncio
    async def test_empty_answer_fallback(self):
        from backend.services.llm_service import LLMService, EMPTY_ANSWER_MESSAGE

        lines = ['data: {"choices":[{"delta":{"reasoning_content":"only thinking"}}]}', "data: [DONE]"]

        class Resp:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                for ln in lines:
                    yield ln

        class Ctx:
            async def __aenter__(self):
                return Resp()

            async def __aexit__(self, *a):
                return False

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, json=None):
                Client.body = json
                return Ctx()

        with patch("backend.services.llm_service.httpx.AsyncClient", Client), \
             patch.dict(os.environ, {"NEBULUS_LLM_MAX_TOKENS": "512"}):
            svc = LLMService()
            out = [c async for c in svc.stream_chat([{"role": "user", "content": "q"}])]
        assert "".join(out) == EMPTY_ANSWER_MESSAGE
        assert Client.body["max_tokens"] == 512
