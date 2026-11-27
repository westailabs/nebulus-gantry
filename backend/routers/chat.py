import asyncio
import json
import logging
import os
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy.orm import Session as DBSession

from backend.config import settings
from backend.dependencies import get_db
from backend.routers.auth import get_current_user
from backend.models.audit_event import AuditEvent
from backend.models.conversation import Conversation
from backend.models.message import Message
from backend.services.audit_service import AuditService, client_ip, event_to_dict
from backend.services.chat_service import ChatService
from backend.services.document_service import (
    RetrievalError,
    format_sources_context,
    sources_to_citations,
)
from backend.services.llm_service import EMPTY_ANSWER_MESSAGE, LLMService
from backend.services.model_service import ModelService
from backend.platform import get_default_model
from backend.services.system_prompt import chat_system_prompt
from backend.schemas.chat import (
    ConversationResponse,
    ConversationDetailResponse,
    SendMessageRequest,
    SearchResult,
    SearchResponse,
)
from backend.schemas.dispatch import DispatchRequest
from backend.schemas.persona import SetConversationPersonaRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

NO_SOURCE_MESSAGE = (
    "I couldn't find anything about that in the selected documents, so I "
    "won't guess. Try rephrasing, or check that the right client documents "
    "are in scope."
)


RETRIEVAL_ERROR_MESSAGE = (
    "Document search is unavailable right now, so I can't answer from your "
    "documents. Please try again shortly or contact your administrator."
)


def _refuse_without_sources() -> bool:
    return os.getenv("GANTRY_REFUSE_WITHOUT_SOURCES", "true").lower() in ("true", "1", "yes")


def _build_token_meta(
    llm: "LLMService",
    messages: list[dict],
    full_response: str,
    generation_time_ms: int,
) -> dict:
    """Build token usage and timing metadata for SSE stream.

    Args:
        llm: LLM service instance (may have last_usage from API).
        messages: The prompt messages sent to the LLM.
        full_response: The complete generated response text.
        generation_time_ms: Wall-clock generation time in milliseconds.

    Returns:
        Metadata dict with token counts, timing, and generation speed.
    """
    generation_time_s = generation_time_ms / 1000.0
    meta: dict = {"generation_time_ms": generation_time_ms}

    if isinstance(llm.last_usage, dict):
        meta["prompt_tokens"] = llm.last_usage.get("prompt_tokens", 0)
        meta["completion_tokens"] = llm.last_usage.get("completion_tokens", 0)
        meta["total_tokens"] = llm.last_usage.get("total_tokens", 0)
    else:
        prompt_text = " ".join(m.get("content", "") for m in messages)
        meta["prompt_tokens"] = len(prompt_text) // 4
        meta["completion_tokens"] = len(full_response) // 4
        meta["total_tokens"] = meta["prompt_tokens"] + meta["completion_tokens"]
        meta["tokens_estimated"] = True

    if generation_time_s > 0 and meta.get("completion_tokens", 0) > 0:
        meta["tokens_per_second"] = round(
            meta["completion_tokens"] / generation_time_s, 2
        )
    else:
        meta["tokens_per_second"] = 0

    return meta


def get_chat_service(db: DBSession = Depends(get_db)) -> ChatService:
    return ChatService(db)


def build_ltm_context(similar_messages: list, related_facts: list) -> str:
    """Build a context string from long-term memory results.

    Args:
        similar_messages: List of dicts from MemoryService.search_similar,
            each containing 'content', 'score', and 'metadata'.
        related_facts: List of dicts from GraphService.get_related,
            each containing 'entity', 'relationship', and 'connected_entity'.

    Returns:
        A formatted string to inject into the system prompt, or empty string
        if no relevant context is available.
    """
    parts = []
    if similar_messages:
        parts.append("Relevant past context:")
        for msg in similar_messages[:3]:
            parts.append(f"- {msg['content'][:200]}")

    if related_facts:
        parts.append("\nKnown facts:")
        for fact in related_facts[:5]:
            parts.append(
                f"- {fact['entity']} {fact['relationship']} {fact['connected_entity']}"
            )

    return "\n".join(parts) if parts else ""


def _create_memory_service(user_id: int):
    """Factory for MemoryService. Lazy import to handle missing chromadb gracefully."""
    from backend.services.memory_service import MemoryService
    return MemoryService(user_id)


def _create_graph_service(user_id: int):
    """Factory for GraphService. Lazy import to handle missing networkx gracefully."""
    from backend.services.graph_service import GraphService
    return GraphService(user_id)


def _create_document_service(db: DBSession):
    """Factory for DocumentService."""
    from backend.services.document_service import DocumentService
    return DocumentService(db)


def _create_persona_service(db: DBSession):
    """Factory for PersonaService."""
    from backend.services.persona_service import PersonaService
    return PersonaService(db)


@router.get("/search", response_model=SearchResponse)
def search_conversations(
    q: str,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    """Search messages and conversation titles across the user's conversations."""
    if not q or not q.strip():
        return SearchResponse(results=[])

    from sqlalchemy import or_
    from backend.models.message import Message
    from backend.models.conversation import Conversation

    # Search messages belonging to user's conversations (message content OR title match)
    results = (
        chat.db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.user_id == user.id,
            or_(
                Message.content.ilike(f"%{q.strip()}%"),
                Conversation.title.ilike(f"%{q.strip()}%"),
            ),
        )
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )

    # Build response with snippets
    search_results = []
    for msg in results:
        conversation = msg.conversation

        # Create a snippet around the matched text
        content = msg.content
        lower_content = content.lower()
        lower_q = q.strip().lower()
        idx = lower_content.find(lower_q)
        if idx != -1:
            start = max(0, idx - 60)
            end = min(len(content), idx + len(q.strip()) + 60)
            snippet = content[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
        else:
            snippet = content[:150]
            if len(content) > 150:
                snippet += "..."

        search_results.append(
            SearchResult(
                conversation_id=conversation.id,
                conversation_title=conversation.title,
                message_snippet=snippet,
                role=msg.role,
                created_at=msg.created_at.isoformat(),
            )
        )

    return SearchResponse(results=search_results)


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    return chat.create_conversation(user.id)


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    return chat.get_conversations(user.id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: int,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    conversation = chat.get_conversation(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = chat.get_messages(conversation_id)
    return {"conversation": conversation, "messages": messages}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    if not chat.delete_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Conversation deleted"}


@router.patch("/conversations/{conversation_id}/pin", response_model=ConversationResponse)
def toggle_pin_conversation(
    conversation_id: int,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    """Toggle the pinned status of a conversation."""
    conversation = chat.toggle_pin(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/conversations/{conversation_id}/export")
def export_conversation(
    conversation_id: int,
    http_request: Request,
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Export a conversation as JSON, PDF, or Excel.

    Args:
        conversation_id: The conversation to export.
        format: Export format - "json", "pdf", or "excel" (default: json).

    Returns:
        JSON data, PDF file download, or Excel file download.
    """
    from backend.services.export_service import ExportService

    export_service = ExportService(db)

    def _audit_export():
        AuditService(db).record(
            "conversation.export", user=user, resource_type="conversation",
            resource_id=conversation_id, detail={"format": format}, ip_address=client_ip(http_request),
        )

    if format == "json":
        data = export_service.export_json(conversation_id, user.id)
        if not data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        _audit_export()
        return JSONResponse(
            content=data,
            headers={
                "Content-Disposition": f"attachment; filename=conversation-{conversation_id}.json"
            },
        )
    elif format == "pdf":
        pdf_bytes = export_service.export_pdf(conversation_id, user.id)
        if not pdf_bytes:
            raise HTTPException(status_code=404, detail="Conversation not found")
        _audit_export()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=conversation-{conversation_id}.pdf"
            },
        )
    else:  # excel
        excel_bytes = export_service.export_spreadsheet(conversation_id, user.id)
        if not excel_bytes:
            raise HTTPException(status_code=404, detail="Conversation not found")
        _audit_export()
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=conversation-{conversation_id}.xlsx"
            },
        )


@router.get("/conversations/{conversation_id}/report")
def export_report(
    conversation_id: int,
    http_request: Request,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Export conversation as a structured PDF report.

    Creates a business report with:
    - Cover page with title and date
    - Executive Summary with AI-extracted insights
    - Key findings and recommendations

    Args:
        conversation_id: The conversation to export as a report.

    Returns:
        PDF file download.
    """
    from backend.services.export_service import ExportService

    export_service = ExportService(db)
    report_bytes = export_service.export_report(conversation_id, user.id)
    if not report_bytes:
        raise HTTPException(status_code=404, detail="Conversation not found")
    AuditService(db).record(
        "conversation.export", user=user, resource_type="conversation",
        resource_id=conversation_id, detail={"format": "report"}, ip_address=client_ip(http_request),
    )

    return Response(
        content=report_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report-{conversation_id}.pdf"
        },
    )


# Fields of a chat.query audit row a user may see for their own answer (no IP address).
_MESSAGE_AUDIT_DETAIL_KEYS = ("outcome", "refused", "scoped", "model", "correlation_id", "message_id",
                              "retrieval_error", "error_type", "generation_time_ms", "query_chars")


def _user_audit_entry(row: AuditEvent, detail: dict) -> dict:
    entry = event_to_dict(row)
    entry.pop("ip_address", None)
    entry["detail"] = {k: detail[k] for k in _MESSAGE_AUDIT_DETAIL_KEYS if k in detail}
    return entry


def _own_chat_query_rows(db: DBSession, user_id: int, conversation_id: int) -> list[tuple[AuditEvent, dict]]:
    """The caller's own chat.query rows for one conversation, newest first, with parsed detail."""
    rows = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == "chat.query",
            AuditEvent.user_id == user_id,
            AuditEvent.resource_type == "conversation",
            AuditEvent.resource_id == conversation_id,
        )
        .order_by(AuditEvent.id.desc())
        .all()
    )
    out = []
    for row in rows:
        try:
            out.append((row, json.loads(row.detail) if row.detail else {}))
        except ValueError:
            continue
    return out


@router.get("/messages/{message_id}/audit")
def get_message_audit_entry(
    message_id: int,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """The ``chat.query`` audit row behind one of *your own* assistant answers.

    CPA demo mode only (404 otherwise): lets a non-admin open the logged entry for
    an answer in one click without exposing the admin audit list or CSV export.
    Audit rows already store ``message_id`` in their JSON ``detail`` (no schema
    change); only rows the caller wrote for a conversation they own are returned.
    Rows written before refusals recorded a message id are reachable through
    ``GET /conversations/{id}/audit`` instead.
    """
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")
    not_found = HTTPException(status_code=404, detail="No audit entry for this message")
    msg = (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Message.id == message_id, Conversation.user_id == user.id)
        .first()
    )
    if msg is None or msg.role != "assistant":
        raise not_found
    for row, detail in _own_chat_query_rows(db, user.id, msg.conversation_id):
        if detail.get("message_id") == message_id:
            return _user_audit_entry(row, detail)
    raise not_found


@router.get("/conversations/{conversation_id}/audit")
def get_conversation_audit_entries(
    conversation_id: int,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Your own ``chat.query`` audit rows for one of your threads (CPA demo mode only).

    The thread-level fallback for answers whose audit row has no ``message_id``
    (refusals logged before that was recorded). Never lists other users' rows or
    other threads, and leaves out ip_address.
    """
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")
    owned = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == user.id
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = _own_chat_query_rows(db, user.id, conversation_id)
    return {"conversation_id": conversation_id, "entries": [_user_audit_entry(r, d) for r, d in rows]}


@router.post("/conversations/{conversation_id}/messages")
async def send_message(  # noqa: C901
    conversation_id: int,
    request: SendMessageRequest,
    http_request: Request,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
    db: DBSession = Depends(get_db),
):
    # Verify conversation exists and belongs to user
    conversation = chat.get_conversation(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save user message
    user_msg = chat.add_message(conversation_id, "user", request.content)

    # --- LTM: Query long-term memory for context ---
    memory_service = None
    graph_service = None
    similar_messages = []
    related_facts = []

    try:
        memory_service = _create_memory_service(user.id)
        similar_messages = await memory_service.search_similar(
            request.content, limit=3
        )
    except Exception as e:
        logger.warning(f"MemoryService query failed: {e}")
        similar_messages = []

    try:
        graph_service = _create_graph_service(user.id)
        entities = graph_service.extract_entities(request.content)
        related_facts = []
        for entity_info in entities:
            facts = graph_service.get_related(entity_info["value"])
            related_facts.extend(facts)
    except Exception as e:
        logger.warning(f"GraphService query failed: {e}")
        related_facts = []

    ltm_context = build_ltm_context(similar_messages, related_facts)

    # --- RAG: Query document knowledge vault ---
    rag_context = ""
    rag_scoped = bool(conversation.document_scope)
    citations: list[dict] = []
    retrieval_error = False
    if rag_scoped:
        try:
            document_service = _create_document_service(db)
            document_scope = json.loads(conversation.document_scope)
            results = document_service.retrieve_sources(
                user_id=user.id,
                query=request.content,
                document_scope=document_scope,
                top_k=3,
            )
            citations = sources_to_citations(results)
            rag_context = format_sources_context(results)
        except RetrievalError as e:
            logger.error(f"Document retrieval failed: {e}")
            retrieval_error = True
        except Exception as e:
            logger.error(f"RAG context build failed: {e}")
            retrieval_error = True
    refused = rag_scoped and (retrieval_error or (not citations and _refuse_without_sources()))
    audit = AuditService(db)
    ip = client_ip(http_request)
    correlation_id = uuid.uuid4().hex[:12]

    if refused:
        message = RETRIEVAL_ERROR_MESSAGE if retrieval_error else NO_SOURCE_MESSAGE
        outcome = "retrieval_error" if retrieval_error else "no_match"

        async def refuse():
            nonlocal outcome
            start_time = time.monotonic()
            refusal_message_id = None
            try:
                yield f"data: {json.dumps({'content': message})}\n\n"
                meta = {"generation_time_ms": int((time.monotonic() - start_time) * 1000),
                        "sources": [], "refused": True, "correlation_id": correlation_id}
                yield f"event: done\ndata: {json.dumps(meta)}\n\n"
                refusal_message_id = chat.add_message(conversation_id, "assistant", message).id
            except (GeneratorExit, asyncio.CancelledError):
                outcome = "client_aborted"
                raise
            finally:
                audit.record(
                    "chat.query", user=user, resource_type="conversation", resource_id=conversation_id,
                    doc_ids=[], query_text=request.content, ip_address=ip,
                    detail={"outcome": outcome, "refused": True, "retrieval_error": retrieval_error,
                            "scoped": True, "model": None, "correlation_id": correlation_id,
                            "message_id": refusal_message_id},
                )

        return StreamingResponse(refuse(), media_type="text/event-stream")

    # --- Persona: assigned persona, else the system default (CPA Assistant) ---
    persona = None
    persona_temperature = None
    try:
        persona_service = _create_persona_service(db)
        if conversation.persona_id:
            persona = persona_service.get_persona(conversation.persona_id, user.id)
        if persona is None:
            persona = persona_service.get_default_system_persona()
        if persona:
            persona_temperature = persona.temperature
    except Exception as e:
        logger.warning(f"Failed to load persona: {e}")

    # CPA demo mode: the model picker is hidden for non-admins, and the API enforces it. A
    # non-admin's model override is ignored (the instance's configured model is used), so
    # they cannot trigger a server-side model switch. Flag off: unchanged for every role.
    requested_model = request.model
    if settings.demo_mode and getattr(user, "role", None) != "admin":
        requested_model = None

    # Ensure requested model is loaded (auto-switch if needed)
    model_service = ModelService()
    if requested_model:
        active_model = await model_service.get_active_model()
        if not active_model or active_model["id"] != requested_model:
            logger.info(f"Switching model from {active_model['id'] if active_model else 'none'} to {requested_model}")
            switch_success = await model_service.switch_model(requested_model)
            if not switch_success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load model '{requested_model}'. Please try again or select a different model."
                )
            logger.info(f"Model switched successfully to {requested_model}")

    # Query active model name for system prompt
    active_model = await model_service.get_active_model()
    model_name = active_model["name"] if active_model else "an AI assistant"

    # Build system message: assigned/default persona, else the CPA fixture prompt.
    system_content = chat_system_prompt(
        persona.system_prompt if persona else None,
        model_name,
    )

    # Append context from LTM and RAG
    if ltm_context:
        system_content = f"{system_content}\n\n{ltm_context}"
    if rag_context:
        system_content = f"{system_content}\n\n{rag_context}"

    # Get conversation history for context
    messages = chat.get_messages(conversation_id)
    llm_messages = [
        {"role": "system", "content": system_content},
    ]
    for msg in messages:
        llm_messages.append({"role": msg.role, "content": msg.content})

    # Stream response from LLM — use requested model or default
    llm = LLMService()
    llm_model = requested_model or get_default_model()

    async def generate():  # noqa: C901
        full_response = ""
        start_time = time.monotonic()
        outcome = "client_aborted"  # until proven otherwise (disconnect/cancel)
        error_type = None
        message_id = None
        meta: dict = {}
        try:
            if citations:
                # Structured citations first, so the UI can render clickable sources.
                yield f"event: sources\ndata: {json.dumps(citations)}\n\n"
            async for chunk in llm.stream_chat(
                llm_messages, model=llm_model, temperature=persona_temperature
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"

            cleaned = getattr(llm, "reasoning_leak_cleaned", None)
            if isinstance(cleaned, str):
                # Reasoning leaked before an orphan </think>: replace what was streamed.
                # Never replace with blank text (Plumb N1).
                if not cleaned.strip():
                    cleaned = EMPTY_ANSWER_MESSAGE
                full_response = cleaned
                yield f"event: replace\ndata: {json.dumps({'content': cleaned})}\n\n"

            last_error = getattr(llm, "last_error", None)
            llm_failed = isinstance(last_error, str)
            if llm_failed:
                error_type = last_error
            outcome = ("empty_answer" if last_error == "empty_answer" else "llm_error") if llm_failed \
                else "completed"

            generation_time_ms = int((time.monotonic() - start_time) * 1000)
            meta = _build_token_meta(llm, llm_messages, full_response, generation_time_ms)
            meta["correlation_id"] = correlation_id
            if rag_scoped:
                meta["sources"] = [] if llm_failed else citations
            yield f"event: done\ndata: {json.dumps(meta)}\n\n"

            # Save assistant response after streaming completes
            assistant_msg = chat.add_message(conversation_id, "assistant", full_response)
            message_id = assistant_msg.id
            if citations and not llm_failed:
                try:
                    assistant_msg.sources = json.dumps(citations)
                    chat.db.commit()
                except Exception as e:
                    # Roll back so the session stays usable for the audit row in finally.
                    chat.db.rollback()
                    logger.warning(f"Failed to persist citations: {e}")
        except (GeneratorExit, asyncio.CancelledError):
            outcome = "client_aborted"
            raise
        except Exception as e:
            outcome = "error"
            error_type = type(e).__name__
            raise
        finally:
            audit.record(
                "chat.query", user=user, resource_type="conversation", resource_id=conversation_id,
                doc_ids=[c["document_id"] for c in citations], query_text=request.content, ip_address=ip,
                detail={"outcome": outcome, "error_type": error_type, "refused": False,
                        "scoped": rag_scoped, "model": llm_model, "correlation_id": correlation_id,
                        "message_id": message_id,
                        "generation_time_ms": int((time.monotonic() - start_time) * 1000),
                        "completion_tokens": meta.get("completion_tokens")},
            )

        if outcome != "completed":
            return

        # --- LTM: Update long-term memory asynchronously ---
        # Embed user message into ChromaDB
        if memory_service is not None:
            try:
                await memory_service.embed_message(
                    message_id=user_msg.id,
                    content=request.content,
                    metadata={
                        "conversation_id": str(conversation_id),
                        "role": "user",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to embed user message: {e}")

            # Embed assistant message into ChromaDB
            try:
                await memory_service.embed_message(
                    message_id=assistant_msg.id,
                    content=full_response,
                    metadata={
                        "conversation_id": str(conversation_id),
                        "role": "assistant",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to embed assistant message: {e}")

        # Extract entities and update knowledge graph
        if graph_service is not None:
            try:
                for entity in graph_service.extract_entities(full_response):
                    graph_service.add_fact(
                        entity1=entity["value"],
                        relationship="mentioned_in",
                        entity2=f"conversation_{conversation_id}",
                    )
                graph_service.save()
            except Exception as e:
                logger.warning(f"Failed to update knowledge graph: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.patch("/conversations/{conversation_id}/persona", response_model=ConversationResponse)
def set_conversation_persona(
    conversation_id: int,
    request: SetConversationPersonaRequest,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Set the persona for a conversation."""
    persona_service = _create_persona_service(db)
    conversation = persona_service.set_conversation_persona(
        conversation_id=conversation_id,
        persona_id=request.persona_id,
        user_id=user.id,
    )
    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversation or persona not found",
        )
    return conversation


class ScopeItem(BaseModel):
    """One document-scope entry; validated so bad input is a 422 before any commit."""
    type: Literal["document", "collection"]
    id: StrictInt


class SetDocumentScopeRequest(BaseModel):
    """Request to set document scope for RAG."""
    document_scope: list[ScopeItem] | None = Field(default=None, max_length=200)


@router.patch("/conversations/{conversation_id}/document-scope", response_model=ConversationResponse)
def set_conversation_document_scope(
    conversation_id: int,
    request: SetDocumentScopeRequest,
    http_request: Request,
    user=Depends(get_current_user),
    chat: ChatService = Depends(get_chat_service),
):
    """Set the document scope for RAG in a conversation."""
    conversation = chat.get_conversation(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Serialize document scope as JSON
    scope = [item.model_dump() for item in request.document_scope or []]
    if scope:
        conversation.document_scope = json.dumps(scope)
    else:
        conversation.document_scope = None

    chat.db.commit()
    chat.db.refresh(conversation)
    AuditService(chat.db).record(
        "conversation.scope_change", user=user, resource_type="conversation",
        resource_id=conversation_id, ip_address=client_ip(http_request),
        doc_ids=[i["id"] for i in scope if i["type"] == "document"],
        detail={"scope": scope},
    )
    return conversation


# ── Overlord Dispatch Endpoint ───────────────────────────────────────────────


@router.post("/dispatch")
async def dispatch_message(  # noqa: C901
    request: DispatchRequest,
    http_request: Request,
    user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Route a message through Overlord's dispatch layer.

    Returns a Server-Sent Events stream of DispatchEvent objects.
    Falls back to direct LLM if Overlord routing is disabled.
    Every call is audited as ``chat.dispatch`` (outcome recorded in finally).
    """
    audit = AuditService(db)
    ip = client_ip(http_request)

    def _audit(outcome: str, error_type: str | None, routed: str, start: float) -> None:
        audit.record(
            "chat.dispatch", user=user, query_text=request.user_message, ip_address=ip,
            detail={"outcome": outcome, "error_type": error_type, "route": routed,
                    "generation_time_ms": int((time.monotonic() - start) * 1000)},
        )

    if not settings.overlord_routing_enabled:
        # Fallback: route directly to LLM without Overlord
        from backend.schemas.dispatch import content_event, error_event, result_event

        llm = LLMService()
        messages = [
            {"role": "system", "content": "You are Nebulus Gantry, a helpful AI assistant."},
        ]
        for msg in request.conversation_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": request.user_message})

        async def fallback_generate():
            start_time = time.monotonic()
            full_text = ""
            outcome, error_type = "client_aborted", None
            try:
                try:
                    async for chunk in llm.stream_chat(messages):
                        full_text += chunk
                        yield content_event(chunk, source="local").to_sse()
                    yield result_event("", source="local").to_sse()
                    last_error = getattr(llm, "last_error", None)
                    if isinstance(last_error, str):
                        outcome, error_type = "llm_error", last_error
                    else:
                        outcome = "completed"
                except (GeneratorExit, asyncio.CancelledError):
                    raise
                except Exception as e:
                    outcome, error_type = "error", type(e).__name__
                    yield error_event("LLM request failed").to_sse()

                generation_time_ms = int((time.monotonic() - start_time) * 1000)
                meta = _build_token_meta(llm, messages, full_text, generation_time_ms)
                yield f"event: done\ndata: {json.dumps(meta)}\n\n"
            finally:
                _audit(outcome, error_type, "local", start_time)

        return StreamingResponse(fallback_generate(), media_type="text/event-stream")

    # Overlord routing enabled — use conversation router
    from backend.services.conversation_router import get_conversation_router

    router_svc = get_conversation_router()

    async def generate():
        start_time = time.monotonic()
        outcome, error_type = "client_aborted", None
        try:
            async for event in router_svc.route_message(request):
                yield event.to_sse()
            yield "data: [DONE]\n\n"
            outcome = "completed"
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except Exception as e:
            outcome, error_type = "error", type(e).__name__
            raise
        finally:
            _audit(outcome, error_type, "overlord", start_time)

    return StreamingResponse(generate(), media_type="text/event-stream")
