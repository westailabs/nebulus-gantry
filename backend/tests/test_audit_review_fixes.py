"""Tests for PR #4 review fixes (Plumb): stream-abort auditing, CSV injection,
retrieval/LLM error outcomes, scoped retrieval + similarity floor, orphan
</think>, UTC timestamps, privilege-change auditing, 401s, bounds."""
import asyncio
import csv
import io
import json
import os
from datetime import datetime
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
from backend.models.message import Message  # noqa: E402
from backend.services.audit_service import (  # noqa: E402
    AuditService, event_to_dict, events_to_csv, redact,
)
from backend.services.auth_service import AuthService  # noqa: E402
from backend.services.document_service import DocumentService, RetrievalError  # noqa: E402
from backend.services.reasoning_filter import ThinkTagFilter, strip_reasoning  # noqa: E402


@pytest.fixture(autouse=True)
def setup_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TS = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TS
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
def alice(db):
    return _user(db, "alice@example.com")


@pytest.fixture
def admin(db):
    return _user(db, "admin@example.com", role="admin")


SOURCES = [{"document_id": 7, "filename": "a.txt", "chunk_text": "AGI $1", "similarity": 0.8, "chunk_index": 0}]


def _ltm():
    mem = MagicMock()
    mem.search_similar = AsyncMock(return_value=[])
    mem.embed_message = AsyncMock()
    graph = MagicMock()
    graph.extract_entities.return_value = []
    graph.get_related.return_value = []
    return mem, graph


def _scoped(client, db, token):
    conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
    c = db.get(Conversation, conv["id"])
    c.document_scope = json.dumps([{"type": "collection", "id": 1}])
    db.commit()
    return conv["id"]


def _chat(client, conv_id, token, stream, sources=SOURCES, retrieve_side_effect=None, last_error=None):
    mem, graph = _ltm()
    with patch("backend.routers.chat.LLMService") as MockLLM, \
         patch("backend.routers.chat._create_memory_service", return_value=mem), \
         patch("backend.routers.chat._create_graph_service", return_value=graph), \
         patch("backend.routers.chat._create_document_service") as mk:
        if retrieve_side_effect:
            mk.return_value.retrieve_sources.side_effect = retrieve_side_effect
        else:
            mk.return_value.retrieve_sources.return_value = sources
        llm = MagicMock()
        llm.stream_chat = stream
        llm.last_usage = None
        llm.last_error = last_error
        MockLLM.return_value = llm
        return client.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": "q 123-45-6789"},
                           cookies={"session_token": token})


def _chat_event(db):
    return db.query(AuditEvent).filter_by(action="chat.query").one()


# ── Blocker 1: audit on abort / error ───────────────────────────────────────


class TestStreamOutcomeAudit:
    def test_completed_outcome(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "ok [1]"
        _chat(client, conv, alice[1], s)
        d = json.loads(_chat_event(db).detail)
        assert d["outcome"] == "completed"
        assert "correlation_id" in d

    def test_stream_raises_is_audited_as_error(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "partial"
            raise RuntimeError("boom secret detail")
        try:
            _chat(client, conv, alice[1], s)
        except RuntimeError:
            pass
        e = _chat_event(db)
        d = json.loads(e.detail)
        assert d["outcome"] == "error"
        assert d["error_type"] == "RuntimeError"
        assert json.loads(e.doc_ids) == [7]

    def test_client_abort_is_audited(self, db, alice):
        """Simulate a disconnect: close the generator after the first chunk."""
        from backend.routers import chat as chat_router

        user, _ = alice
        conv = Conversation(user_id=user.id, title="t",
                            document_scope=json.dumps([{"type": "collection", "id": 1}]))
        db.add(conv)
        db.commit()

        async def s(messages, model=None, temperature=None):
            yield "a"
            yield "b"
        mem, graph = _ltm()
        req = MagicMock()
        req.client.host = "127.0.0.1"

        async def run():
            with patch("backend.routers.chat.LLMService") as MockLLM, \
                 patch("backend.routers.chat._create_memory_service", return_value=mem), \
                 patch("backend.routers.chat._create_graph_service", return_value=graph), \
                 patch("backend.routers.chat._create_document_service") as mk, \
                 patch("backend.routers.chat.ModelService") as MS:
                MS.return_value.get_active_model = AsyncMock(return_value=None)
                mk.return_value.retrieve_sources.return_value = SOURCES
                MockLLM.return_value = MagicMock(stream_chat=s, last_usage=None, last_error=None)
                from backend.schemas.chat import SendMessageRequest
                resp = await chat_router.send_message(
                    conv.id, SendMessageRequest(content="q"), req, user=user,
                    chat=chat_router.ChatService(db), db=db)
                gen = resp.body_iterator
                await gen.__anext__()  # sources
                await gen.__anext__()  # first chunk
                await gen.aclose()     # client went away
        asyncio.run(run())
        d = json.loads(_chat_event(db).detail)
        assert d["outcome"] == "client_aborted"

    def test_llm_error_outcome_no_citations_no_raw_error(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "[Error: LLM request failed]"
        r = _chat(client, conv, alice[1], s, last_error="ConnectError")
        assert r.status_code == 200
        d = json.loads(_chat_event(db).detail)
        assert d["outcome"] == "llm_error"
        asst = db.query(Message).filter_by(role="assistant").one()
        assert asst.sources is None


# ── Blocker 2: CSV injection ────────────────────────────────────────────────


class TestCsvInjection:
    @pytest.mark.parametrize("bad", ["=HYPERLINK(\"http://x\")@x.com", "+1", "-2", "@SUM(A1)", "\tx", "\rx"])
    def test_formula_cells_are_neutralised(self, db, bad):
        AuditService(db).record("auth.login_failed", user_email=bad, detail={"filename": bad})
        events, _ = AuditService(db).list_events()
        rows = list(csv.reader(io.StringIO(events_to_csv(events))))
        email = rows[1][3]
        assert email.startswith("'")
        assert email[1:] == bad
        assert not rows[1][9].startswith(("=", "+", "-", "@"))

    def test_login_failed_formula_email_via_api(self, client, db, admin):
        client.post("/api/auth/login", json={"email": "=cmd|x@example.com", "password": "nope"})
        r = client.get("/api/admin/audit/export.csv", cookies={"session_token": admin[1]})
        assert "'=cmd|x@example.com" in r.text


# ── Should-fix 3/4: scoped retrieval, similarity floor, retrieval errors ────


class TestRetrieval:
    def test_document_and_collection_scope_in_where_filter(self, db):
        svc = DocumentService(db)
        svc._chroma_available = True
        svc._vector_client = MagicMock()
        svc._vector_client.search.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        svc.retrieve_sources(1, "q", [{"type": "collection", "id": 2}, {"type": "document", "id": 9}])
        where = svc._vector_client.search.call_args.kwargs["where"]
        assert where == {"$or": [{"collection_id": {"$in": [2]}}, {"document_id": {"$in": [9]}}]}

    def test_document_only_scope(self, db):
        svc = DocumentService(db)
        svc._chroma_available = True
        svc._vector_client = MagicMock()
        svc._vector_client.search.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        svc.retrieve_sources(1, "q", [{"type": "document", "id": 9}])
        assert svc._vector_client.search.call_args.kwargs["where"] == {"document_id": {"$in": [9]}}

    def test_similarity_floor(self, db, monkeypatch):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.5")
        svc = DocumentService(db)
        hits = [dict(SOURCES[0], similarity=0.8), dict(SOURCES[0], document_id=8, similarity=0.3)]
        with patch.object(svc, "_search", return_value=hits):
            out = svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])
        assert [h["document_id"] for h in out] == [7]

    def test_drops_hits_without_document_id(self, db):
        svc = DocumentService(db)
        with patch.object(svc, "_search", return_value=[dict(SOURCES[0], document_id=0)]):
            assert svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}]) == []

    def test_unavailable_raises(self, db):
        svc = DocumentService(db)
        svc._chroma_available = False
        with pytest.raises(RetrievalError):
            svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])

    def test_search_failure_raises(self, db):
        svc = DocumentService(db)
        svc._chroma_available = True
        svc._vector_client = MagicMock()
        svc._vector_client.search.side_effect = RuntimeError("chroma down")
        with pytest.raises(RetrievalError):
            svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])

    def test_retrieval_error_message_and_audit(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "never"
        r = _chat(client, conv, alice[1], s, retrieve_side_effect=RetrievalError("down"))
        assert "document search is unavailable" in r.text.lower()
        assert "never" not in r.text
        d = json.loads(_chat_event(db).detail)
        assert d["outcome"] == "retrieval_error"
        assert d["retrieval_error"] is True

    def test_no_match_outcome(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "never"
        _chat(client, conv, alice[1], s, sources=[])
        d = json.loads(_chat_event(db).detail)
        assert d["outcome"] == "no_match"
        assert d["refused"] is True


# ── Should-fix 6: orphan </think>, case, other tags ─────────────────────────


class TestReasoningLeaks:
    def test_strip_orphan_close(self):
        assert strip_reasoning("secret plan</think>Answer") == "Answer"

    def test_case_insensitive_and_other_tags(self):
        assert strip_reasoning("<THINK>x</THINK>A") == "A"
        assert strip_reasoning("<thinking>x</thinking>B") == "B"
        assert strip_reasoning("<reasoning>x</reasoning>C") == "C"

    def test_stream_orphan_close_swallows_tag(self):
        f = ThinkTagFilter()
        out = f.feed("plan </thi") + f.feed("nk>Answer") + f.flush()
        assert "</think>" not in out
        assert out.endswith("Answer")
        assert f.saw_orphan_close is True

    def test_chat_replaces_leaked_reasoning(self, client, db, alice):
        conv = client.post("/api/chat/conversations", cookies={"session_token": alice[1]}).json()["id"]

        async def s(messages, model=None, temperature=None):
            yield "secret plan "
            yield "Answer"
        mem, graph = _ltm()
        with patch("backend.routers.chat.LLMService") as MockLLM, \
             patch("backend.routers.chat._create_memory_service", return_value=mem), \
             patch("backend.routers.chat._create_graph_service", return_value=graph):
            llm = MagicMock(stream_chat=s, last_usage=None, last_error=None)
            llm.reasoning_leak_cleaned = "Answer"
            MockLLM.return_value = llm
            r = client.post(f"/api/chat/conversations/{conv}/messages", json={"content": "q"},
                            cookies={"session_token": alice[1]})
        assert "event: replace" in r.text
        assert db.query(Message).filter_by(role="assistant").one().content == "Answer"


# ── Should-fix 7: UTC ───────────────────────────────────────────────────────


def test_timestamps_are_utc_marked(db, alice):
    AuditService(db).record("auth.login", user=alice[0])
    e = db.query(AuditEvent).one()
    ts = event_to_dict(e)["timestamp"]
    assert ts.endswith("+00:00")
    assert datetime.fromisoformat(ts).tzinfo is not None


# ── Should-fix 8: privilege/account changes ─────────────────────────────────


class TestPrivilegeAudit:
    def test_user_create_update_delete(self, client, db, admin):
        t = admin[1]
        r = client.post("/api/admin/users", json={"email": "bob@example.com", "password": "Passw0rd!x",
                                                  "display_name": "Bob", "role": "user"},
                        cookies={"session_token": t})
        uid = r.json()["id"]
        client.patch(f"/api/admin/users/{uid}", json={"role": "admin", "password": "N3wpassw0rd!"},
                     cookies={"session_token": t})
        client.delete(f"/api/admin/users/{uid}", cookies={"session_token": t})
        acts = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)]
        assert acts == ["user.create", "user.update", "user.delete"]
        upd = json.loads(db.query(AuditEvent).filter_by(action="user.update").one().detail)
        assert upd["role_before"] == "user" and upd["role_after"] == "admin"
        assert upd["password_changed"] is True
        assert "N3wpassw0rd" not in json.dumps(upd)

    def test_password_change(self, client, db, alice):
        client.post("/api/auth/change-password", json={"current_password": "pw-123456",
                                                       "new_password": "Another1!pw"},
                    cookies={"session_token": alice[1]})
        assert db.query(AuditEvent).filter_by(action="auth.password_change").count() == 1


# ── Should-fix 10: query-text flag on chat path + redaction ─────────────────


class TestQueryTextPrivacy:
    def test_chat_query_text_null_by_default(self, client, db, alice, monkeypatch):
        monkeypatch.delenv("GANTRY_AUDIT_STORE_QUERY_TEXT", raising=False)
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "ok"
        _chat(client, conv, alice[1], s)
        assert _chat_event(db).query_text is None

    def test_redaction_when_stored(self, client, db, alice, monkeypatch):
        monkeypatch.setenv("GANTRY_AUDIT_STORE_QUERY_TEXT", "true")
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "ok"
        _chat(client, conv, alice[1], s)
        q = _chat_event(db).query_text
        assert "123-45-6789" not in q and "[SSN]" in q

    def test_redact_helper(self):
        assert redact("ein 12-3456789 mail a@b.com ssn 123-45-6789") == "ein [EIN] mail [EMAIL] ssn [SSN]"


# ── Should-fix 11: 401s and bounds ──────────────────────────────────────────


class TestAuditEndpointGuards:
    def test_unauthenticated(self, client):
        assert client.get("/api/admin/audit").status_code == 401
        assert client.get("/api/admin/audit/export.csv").status_code == 401

    @pytest.mark.parametrize("qs", ["limit=0", "limit=1001", "offset=-1"])
    def test_bounds(self, client, admin, qs):
        assert client.get(f"/api/admin/audit?{qs}", cookies={"session_token": admin[1]}).status_code == 422

    def test_csv_export_detail_has_rows_and_truncated(self, client, db, admin):
        client.get("/api/admin/audit/export.csv", cookies={"session_token": admin[1]})
        d = json.loads(db.query(AuditEvent).filter_by(action="audit.export").one().detail)
        assert d["truncated"] is False and "rows" in d
