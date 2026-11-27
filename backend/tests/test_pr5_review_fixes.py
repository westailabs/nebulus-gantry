"""PR #5 review fixes, ported from Plumb's repro suite. The former test_FINDING_* cases now
assert the fixed behaviour."""
import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.config import settings
from backend.models.audit_event import AuditEvent
from backend.models.conversation import Conversation
from backend.models.message import Message
from backend.services import audit_service
from backend.services.audit_service import AuditService
from backend.services.document_service import DocumentService
from backend.services.llm_service import EMPTY_ANSWER_MESSAGE, LLMService
from backend.tests import test_audit_review_fixes as base
from backend.tests.test_audit_review_fixes import SOURCES, _ltm, _scoped

setup_db, db, client = base.setup_db, base.db, base.client
alice, admin = base.alice, base.admin

_RealAsyncClient = httpx.AsyncClient


def _sse(deltas, finish=None):
    lines = []
    for d in deltas:
        lines.append("data: " + json.dumps({"choices": [{"delta": d}]}))
    if finish:
        lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}))
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def _fake_llm_server(deltas, finish=None):
    body = _sse(deltas, finish)

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*a, **k)
    return patch("backend.services.llm_service.httpx.AsyncClient", side_effect=factory)


async def _collect(llm):
    return [c async for c in llm.stream_chat([{"role": "user", "content": "q"}])]


def _events(text):
    return [b for b in text.split("\n\n") if b.strip()]


def _chat_real_llm(client, conv, token, deltas, sources=SOURCES, finish=None):
    mem, graph = _ltm()
    with _fake_llm_server(deltas, finish), \
         patch("backend.routers.chat._create_memory_service", return_value=mem), \
         patch("backend.routers.chat._create_graph_service", return_value=graph), \
         patch("backend.routers.chat._create_document_service") as mk, \
         patch("backend.routers.chat.ModelService") as MS:
        MS.return_value.get_active_model = AsyncMock(return_value=None)
        mk.return_value.retrieve_sources.return_value = sources
        return client.post(f"/api/chat/conversations/{conv}/messages", json={"content": "q"},
                           cookies={"session_token": token})


def _query_detail(db, action="chat.query"):
    return json.loads(db.query(AuditEvent).filter_by(action=action).one().detail)


# ── Item 1: N1 blank / reasoning-only replies (real LLMService, fake server) ──
class TestItem1BlankReply:
    def test_orphan_close_blank_answer_end_to_end(self, client, db, alice):
        conv = _scoped(client, db, alice[1])
        r = _chat_real_llm(client, conv, alice[1], [{"content": "secret plan"}, {"content": "</think>  \n"}])
        evs = _events(r.text)
        reps = [e for e in evs if e.startswith("event: replace")]
        assert reps and json.loads(reps[-1].split("data: ", 1)[1])["content"] == EMPTY_ANSWER_MESSAGE
        done = json.loads(next(e for e in evs if e.startswith("event: done")).split("data: ", 1)[1])
        assert done["sources"] == []
        asst = db.query(Message).filter_by(role="assistant").one()
        assert asst.content == EMPTY_ANSWER_MESSAGE and asst.sources is None
        assert _query_detail(db)["outcome"] == "empty_answer"

    def test_reasoning_content_only_end_to_end(self, client, db, alice):
        conv = _scoped(client, db, alice[1])
        r = _chat_real_llm(client, conv, alice[1], [{"reasoning_content": "hidden"}] * 3)
        assert not [e for e in _events(r.text) if e.startswith("event: replace")]
        asst = db.query(Message).filter_by(role="assistant").one()
        assert asst.content == EMPTY_ANSWER_MESSAGE
        assert _query_detail(db)["outcome"] == "empty_answer"

    def test_whitespace_only_content(self):
        with _fake_llm_server([{"content": "   "}, {"content": "\n"}]):
            llm = LLMService()
            out = asyncio.run(_collect(llm))
        assert out[-1] == EMPTY_ANSWER_MESSAGE and llm.last_error == "empty_answer"


# ── Item 2: similarity floor ────────────────────────────────────────────────
class TestItem2Floor:
    def _svc(self, db, hits):
        svc = DocumentService(db)
        p = patch.object(svc, "_search", return_value=hits)
        return svc, p

    def test_boundary_inclusive(self, db, monkeypatch):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.42")
        svc, p = self._svc(db, [dict(SOURCES[0], document_id=1, similarity=0.42),
                                dict(SOURCES[0], document_id=2, similarity=0.41999)])
        with p:
            out = svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])
        assert [h["document_id"] for h in out] == [1]

    def test_default_is_still_off(self, db, monkeypatch):
        monkeypatch.delenv("GANTRY_MIN_SOURCE_SIMILARITY", raising=False)
        svc, p = self._svc(db, [dict(SOURCES[0], similarity=0.05)])
        with p:
            assert len(svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])) == 1

    def test_typo_warns_and_falls_back_to_off(self, db, monkeypatch, caplog):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0,42")
        svc, p = self._svc(db, [dict(SOURCES[0], similarity=0.05)])
        with caplog.at_level(logging.WARNING), p:
            out = svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])
        assert len(out) == 1
        assert [r for r in caplog.records if "GANTRY_MIN_SOURCE_SIMILARITY" in r.getMessage()]

    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
    def test_non_finite_rejected(self, db, monkeypatch, caplog, raw):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", raw)
        svc, p = self._svc(db, [dict(SOURCES[0], similarity=0.99)])
        with caplog.at_level(logging.WARNING), p:
            assert len(svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])) == 1
        assert [r for r in caplog.records if "GANTRY_MIN_SOURCE_SIMILARITY" in r.getMessage()]

    @pytest.mark.parametrize("raw,expected", [("1.5", 1.0), ("-0.3", 0.0), ("0.42", 0.42), ("", 0.0)])
    def test_clamped_to_unit_interval(self, monkeypatch, raw, expected):
        from backend.services.document_service import _min_similarity
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", raw)
        assert _min_similarity() == expected

    def test_demo_value_committed_in_env_example_and_compose(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        assert "GANTRY_MIN_SOURCE_SIMILARITY=0.40" in (root / ".env.example").read_text()
        assert "GANTRY_MIN_SOURCE_SIMILARITY" in (root / "docker-compose.yml").read_text()
        assert (root / "scripts/cpa_demo_smoke.py").exists()

    def test_compose_has_no_hardcoded_secret_key(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        for name in ("docker-compose.yml", ".env.example"):
            for m in re.finditer(r"SECRET_KEY=(\S*)", (root / name).read_text()):
                assert m.group(1) in ("", "${SECRET_KEY:-}"), (name, "hardcoded SECRET_KEY")

    def test_off_topic_refusal_fires_end_to_end(self, client, db, alice, monkeypatch):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.42")
        conv = _scoped(client, db, alice[1])
        real = DocumentService(db)
        mem, graph = _ltm()
        with patch.object(real, "_search", return_value=[dict(SOURCES[0], similarity=0.41)]), \
             patch("backend.routers.chat._create_document_service", return_value=real), \
             patch("backend.routers.chat._create_memory_service", return_value=mem), \
             patch("backend.routers.chat._create_graph_service", return_value=graph), \
             patch("backend.routers.chat.LLMService") as MockLLM:
            r = client.post(f"/api/chat/conversations/{conv}/messages", json={"content": "weather?"},
                            cookies={"session_token": alice[1]})
        assert not MockLLM.return_value.stream_chat.called
        done = json.loads(next(e for e in _events(r.text) if e.startswith("event: done")).split("data: ", 1)[1])
        assert done["refused"] is True and done["sources"] == []
        d = _query_detail(db)
        assert d["outcome"] == "no_match" and d["refused"] is True


# ── Item 3: prefilled <think> templates ─────────────────────────────────────
class TestItem3Prefill:
    def test_reasoning_never_streamed(self, monkeypatch):
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        with _fake_llm_server([{"content": "secret "}, {"content": "reasoning</th"},
                               {"content": "ink>\n\nAnswer"}, {"content": " here"}]):
            out = asyncio.run(_collect(LLMService()))
        assert "secret" not in "".join(out) and "".join(out).strip() == "Answer here"

    def test_explicit_open_with_prefill_on(self, monkeypatch):
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        with _fake_llm_server([{"content": "<think>secret</think>Answer"}]):
            out = asyncio.run(_collect(LLMService()))
        assert "".join(out) == "Answer"

    def test_reasoning_only_then_close_gives_notice(self, monkeypatch):
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        with _fake_llm_server([{"content": "secret</think>"}]):
            llm = LLMService()
            out = asyncio.run(_collect(llm))
        assert out == [EMPTY_ANSWER_MESSAGE] and llm.last_error == "empty_answer"

    def test_truncated_reasoning_gives_empty_notice(self, monkeypatch):
        """finish_reason=length mid-reasoning: the held reasoning must not be released."""
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        with _fake_llm_server([{"content": "secret reasoning about client SSN "},
                               {"content": "still thinking"}], finish="length"):
            llm = LLMService()
            out = asyncio.run(_collect(llm))
        assert out == [EMPTY_ANSWER_MESSAGE] and llm.last_error == "empty_answer"

    def test_no_close_but_finished_normally_releases_answer(self, monkeypatch):
        monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
        with _fake_llm_server([{"content": "Plain answer"}], finish="stop"):
            llm = LLMService()
            out = asyncio.run(_collect(llm))
        assert "".join(out) == "Plain answer" and llm.last_error is None

    def test_prefill_off_orphan_close_is_replaced(self, client, db, alice, monkeypatch):
        monkeypatch.delenv("GANTRY_REASONING_PREFILLED", raising=False)
        conv = _scoped(client, db, alice[1])
        r = _chat_real_llm(client, conv, alice[1], [{"content": "secret"}, {"content": "</think>Answer [1]"}])
        reps = [e for e in _events(r.text) if e.startswith("event: replace")]
        assert json.loads(reps[-1].split("data: ", 1)[1])["content"] == "Answer [1]"
        assert db.query(Message).filter_by(role="assistant").one().content == "Answer [1]"


# ── Item 4: /api/chat/dispatch audit on every path ──────────────────────────
def _dispatch_direct(db, user, overlord, stream=None, route=None, steps=1, close=True):
    from backend.routers import chat as chat_router
    from backend.schemas.dispatch import DispatchRequest
    req = MagicMock()
    req.client.host = "127.0.0.1"
    out = []

    async def run():
        orig = settings.overlord_routing_enabled
        settings.overlord_routing_enabled = overlord
        try:
            with patch("backend.routers.chat.LLMService") as MockLLM, \
                 patch("backend.services.conversation_router.get_conversation_router") as gr:
                MockLLM.return_value = MagicMock(stream_chat=stream, last_usage=None, last_error=None)
                gr.return_value = MagicMock(route_message=route)
                resp = await chat_router.dispatch_message(DispatchRequest(user_message="hi 123-45-6789"),
                                                          req, user=user, db=db)
                gen = resp.body_iterator
                try:
                    for _ in range(steps):
                        out.append(await gen.__anext__())
                    if close:
                        await gen.aclose()
                    else:
                        async for x in gen:
                            out.append(x)
                except Exception as e:  # noqa: BLE001
                    out.append(e)
        finally:
            settings.overlord_routing_enabled = orig
    asyncio.run(run())
    return out


class TestItem4Dispatch:
    def test_local_abort(self, db, alice):
        async def s(messages, **k):
            yield "a"
            yield "b"
        _dispatch_direct(db, alice[0], overlord=False, stream=s, steps=1, close=True)
        d = _query_detail(db, "chat.dispatch")
        assert d["outcome"] == "client_aborted" and d["route"] == "local"

    def test_local_error_no_raw_text(self, db, alice):
        async def s(messages, **k):
            yield "a"
            raise RuntimeError("boom secret detail")
        out = _dispatch_direct(db, alice[0], overlord=False, stream=s, steps=1, close=False)
        d = _query_detail(db, "chat.dispatch")
        assert d["outcome"] == "error" and d["error_type"] == "RuntimeError"
        assert "boom secret" not in "".join(x for x in out if isinstance(x, str))
        ev = db.query(AuditEvent).filter_by(action="chat.dispatch").one()
        assert ev.query_text is None and d["query_chars"] == len("hi 123-45-6789")

    def test_overlord_abort(self, db, alice):
        from backend.schemas.dispatch import content_event

        async def route(request):
            yield content_event("x", source="local")
            yield content_event("y", source="local")
        _dispatch_direct(db, alice[0], overlord=True, route=route, steps=1, close=True)
        d = _query_detail(db, "chat.dispatch")
        assert d["outcome"] == "client_aborted" and d["route"] == "overlord"

    def test_overlord_error(self, db, alice):
        async def route(request):
            raise RuntimeError("overlord down")
            yield  # pragma: no cover
        out = _dispatch_direct(db, alice[0], overlord=True, route=route, steps=1, close=False)
        assert isinstance(out[-1], RuntimeError)
        d = _query_detail(db, "chat.dispatch")
        assert d["outcome"] == "error" and d["error_type"] == "RuntimeError"

    def test_overlord_completed(self, db, alice):
        from backend.schemas.dispatch import content_event

        async def route(request):
            yield content_event("x", source="local")
        _dispatch_direct(db, alice[0], overlord=True, route=route, steps=1, close=False)
        assert _query_detail(db, "chat.dispatch")["outcome"] == "completed"


# ── Item 5: persona + scope audit ───────────────────────────────────────────
class TestItem5PersonaScope:
    @pytest.mark.parametrize("bad", [[{"type": "document"}], [{"type": "folder", "id": 1}],
                                     [{"type": "document", "id": "x"}]])
    def test_bad_scope_is_422_before_commit(self, db, alice, bad):
        from fastapi.testclient import TestClient

        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        t = {"session_token": alice[1]}
        conv = c.post("/api/chat/conversations", cookies=t).json()["id"]
        r = c.patch(f"/api/chat/conversations/{conv}/document-scope",
                    json={"document_scope": bad}, cookies=t)
        assert r.status_code == 422
        db.expire_all()
        assert db.get(Conversation, conv).document_scope is None  # nothing committed
        assert db.query(AuditEvent).filter_by(action="conversation.scope_change").count() == 0

    def test_other_users_persona_update_not_audited(self, client, db, alice, admin):
        p = client.post("/api/personas", json={"name": "Mine", "system_prompt": "x"},
                        cookies={"session_token": alice[1]}).json()
        r = client.patch(f"/api/personas/{p['id']}", json={"name": "hijack"},
                         cookies={"session_token": admin[1]})
        assert r.status_code == 404
        assert db.query(AuditEvent).filter_by(action="persona.update").count() == 0


# ── Item 6: audit-failure counter ───────────────────────────────────────────
class _BoomDB:
    def add(self, _):
        raise RuntimeError("db down")

    def rollback(self):
        pass


class TestItem6Counter:
    def test_failure_counted_and_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(audit_service, "write_failures", 0)
        with caplog.at_level(logging.ERROR):
            AuditService(_BoomDB()).record("x.y")
        assert audit_service.write_failures == 1
        assert any("AUDIT WRITE FAILED" in r.getMessage() for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)  # traceback is logged

    def test_failed_session_still_writes_audit_row(self, db, monkeypatch):
        """A prior failed flush left un-rolled-back: record() rolls back and retries once."""
        monkeypatch.setattr(audit_service, "write_failures", 0)
        db.add(Message(conversation_id=None, role=None, content=None))  # NOT NULL violations
        try:
            db.commit()
        except Exception:  # noqa: BLE001,S110  -- swallowed without rollback, like chat.py:582
            pass
        AuditService(db).record("chat.query", detail={"outcome": "completed"})
        assert audit_service.write_failures == 0
        assert db.query(AuditEvent).count() == 1


# ── PR #4 blockers: no regression ───────────────────────────────────────────
class TestPR4Blockers:
    def test_chat_abort_and_error_still_audited(self, client, db, alice):
        conv = _scoped(client, db, alice[1])

        async def s(messages, model=None, temperature=None):
            yield "partial"
            raise RuntimeError("x")
        try:
            base._chat(client, conv, alice[1], s)
        except RuntimeError:
            pass
        assert _query_detail(db)["outcome"] == "error"

    @pytest.mark.parametrize("bad", ["=1+1", "+cmd", "-2", "@SUM(A1)", "\t=x", "\r=x"])
    def test_csv_guard(self, bad):
        assert audit_service._safe_cell(bad).startswith("'")

    def test_csv_export_new_actions_guarded(self, client, db, admin):
        t = {"session_token": admin[1]}
        client.post("/api/admin/personas", json={"name": "=HYPERLINK(\"http://x\")", "system_prompt": "x"}, cookies=t)
        r = client.get("/api/admin/audit/export.csv", cookies=t)
        assert r.status_code == 200
        import csv
        import io
        rows = list(csv.reader(io.StringIO(r.text)))
        assert len(rows) == 2 and "HYPERLINK" in rows[1][9]
        assert not any(c.startswith(("=", "+", "-", "@", "\t", "\r")) for row in rows for c in row)


# ── Round 2: expired ORM user on a failed session; prefill truncation end-to-end ──
def test_failed_session_with_expired_user_still_writes_row(db, alice, monkeypatch):
    from backend.models.user import User
    monkeypatch.setattr(audit_service, "write_failures", 0)
    user = db.get(User, alice[0].id)
    db.commit()  # expires user (expire_on_commit)
    db.add(Message(conversation_id=None, role=None, content=None))  # NOT NULL violations
    try:
        db.commit()
    except Exception:  # noqa: S110 -- left un-rolled-back on purpose
        pass
    AuditService(db).record("x.y", user=user)
    assert audit_service.write_failures == 0
    ev = db.query(AuditEvent).one()
    assert ev.user_id == alice[0].id and ev.user_email == "alice@example.com"


def test_prefill_truncated_end_to_end(client, db, alice, monkeypatch):
    monkeypatch.setenv("GANTRY_REASONING_PREFILLED", "true")
    conv = _scoped(client, db, alice[1])
    r = _chat_real_llm(client, conv, alice[1], [{"content": "secret reasoning"}], finish="length")
    assert "secret reasoning" not in r.text
    asst = db.query(Message).filter_by(role="assistant").one()
    assert asst.content == EMPTY_ANSWER_MESSAGE and asst.sources is None
    assert _query_detail(db)["outcome"] == "empty_answer"
