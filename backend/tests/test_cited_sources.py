"""Phantom-citation guard: only sources whose [n] appears in the reply are shown.

Numbering policy under test: ORIGINAL numbering is kept (no renumbering of the text).
The audit row keeps the full retrieval set.
"""
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
from backend.services.auth_service import AuthService  # noqa: E402
from backend.services.document_service import (  # noqa: E402
    cited_citations,
    cited_numbers,
    format_sources_context,
    sources_to_citations,
)

RESULTS = [
    {"document_id": 7, "filename": "a.txt", "chunk_index": 0, "similarity": 0.8, "chunk_text": "alpha"},
    {"document_id": 8, "filename": "b.txt", "chunk_index": 0, "similarity": 0.7, "chunk_text": "bravo"},
    {"document_id": 9, "filename": "c.txt", "chunk_index": 1, "similarity": 0.6, "chunk_text": "charlie"},
]
CITES = sources_to_citations(RESULTS)


def _ns(text):
    return [c["n"] for c in cited_citations(text, CITES)]


class TestCitedFilter:
    def test_no_marker_means_no_sources(self):
        assert _ns("I could not find that in the selected documents.") == []
        assert _ns("") == []

    def test_only_cited_sources_are_kept(self):
        assert _ns("AGI was $89,214 [1].") == [1]
        assert _ns("From [3] and [1].") == [1, 3]

    def test_original_numbering_is_kept_not_renumbered(self):
        out = cited_citations("Only the second one matters [2].", CITES)
        assert [c["n"] for c in out] == [2]
        assert out[0]["document_id"] == 8 and out[0]["filename"] == "b.txt"

    def test_comma_lists_and_adjacent_markers(self):
        assert _ns("Both agree [1, 3].") == [1, 3]
        assert _ns("Both agree [1][2].") == [1, 2]
        assert _ns("x [1 , 3]") == [1, 3]

    def test_out_of_range_markers_are_ignored(self):
        assert _ns("See [5].") == []
        assert _ns("See [0] and [4].") == []
        assert _ns("See [2] and [9].") == [2]

    def test_markdown_links_and_non_markers_do_not_count(self):
        assert _ns("see [1](http://example.com)") == []
        assert _ns("[a] and (1) and [] ") == []
        assert cited_numbers("list of [x] and [1a]") == set()

    def test_empty_citation_list(self):
        assert cited_citations("[1]", []) == []

    def test_prompt_tells_the_model_not_to_emit_markers_when_unanswerable(self):
        p = format_sources_context(RESULTS)
        assert "could not find it in the documents" in p
        assert "do not write any [n] citation marker" in p


# ── through the chat route ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield Session
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
def token(db):
    auth = AuthService(db)
    u = auth.create_user(email="u@example.com", password="pw-123456", display_name="u", role="user")
    return auth.create_session(u.id)


def _events(body):
    out, ev = [], None
    for line in body.splitlines():
        if line.startswith("event: "):
            ev = line[7:].strip()
        elif line.startswith("data: "):
            out.append((ev or "message", json.loads(line[6:])))
            ev = None
    return out


def _chat(client, db, token, reply):
    conv = client.post("/api/chat/conversations", cookies={"session_token": token}).json()
    db.get(Conversation, conv["id"]).document_scope = json.dumps([{"type": "collection", "id": 1}])
    db.commit()
    mem = MagicMock()
    mem.search_similar = AsyncMock(return_value=[])
    mem.embed_message = AsyncMock()
    graph = MagicMock()
    graph.extract_entities.return_value = []
    graph.get_related.return_value = []

    async def fake_stream(messages, model=None, temperature=None):
        yield reply

    with patch("backend.routers.chat.LLMService") as MockLLM, \
         patch("backend.routers.chat._create_memory_service", return_value=mem), \
         patch("backend.routers.chat._create_graph_service", return_value=graph), \
         patch("backend.routers.chat._create_document_service") as mk_docs:
        mk_docs.return_value.retrieve_sources.return_value = RESULTS
        MockLLM.return_value = MagicMock(stream_chat=fake_stream, last_usage=None)
        r = client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "q"},
                        cookies={"session_token": token})
    assert r.status_code == 200
    detail = client.get(f"/api/chat/conversations/{conv['id']}", cookies={"session_token": token}).json()
    saved = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    return _events(r.text), saved


class TestChatRoute:
    def test_could_not_find_without_marker_has_no_sources_anywhere(self, db, token):
        events, saved = _chat(TestClient(app), db, token, "I could not find a client named Zed Quinn.")
        assert not [d for ev, d in events if ev == "sources"]
        done = [d for ev, d in events if ev == "done"][0]
        assert done["sources"] == []
        assert not saved.get("sources")
        # the full retrieval set stays in the audit row
        e = db.query(AuditEvent).filter_by(action="chat.query").one()
        assert json.loads(e.doc_ids) == [7, 8, 9]
        detail = json.loads(e.detail)
        assert detail["retrieved_n"] == [1, 2, 3] and detail["cited_n"] == []

    def test_cited_subset_keeps_original_numbers(self, db, token):
        events, saved = _chat(TestClient(app), db, token, "It is bravo [2], plus charlie [3]. Also [7].")
        src = [d for ev, d in events if ev == "sources"]
        assert len(src) == 1 and [s["n"] for s in src[0]] == [2, 3]
        done = [d for ev, d in events if ev == "done"][0]
        assert [s["n"] for s in done["sources"]] == [2, 3]
        assert [s["n"] for s in saved["sources"]] == [2, 3]
        e = db.query(AuditEvent).filter_by(action="chat.query").one()
        assert json.loads(e.doc_ids) == [7, 8, 9]
        assert json.loads(e.detail)["cited_n"] == [2, 3]

    def test_sources_event_comes_after_the_text_and_before_done(self, db, token):
        events, _ = _chat(TestClient(app), db, token, "Alpha [1].")
        kinds = [ev for ev, _ in events]
        assert kinds.index("sources") > kinds.index("message")
        assert kinds.index("sources") < kinds.index("done")
