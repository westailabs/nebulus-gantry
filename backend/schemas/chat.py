from datetime import datetime
from enum import Enum
import json

from pydantic import BaseModel, field_validator


class ConversationResponse(BaseModel):
    id: int
    title: str
    pinned: bool = False
    persona_id: int | None = None
    persona_name: str | None = None  # For display
    document_scope: str | None = None  # JSON string
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CitationResponse(BaseModel):
    n: int
    document_id: int
    filename: str
    chunk_index: int
    similarity: float | None = None
    snippet: str | None = None


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime
    sources: list[CitationResponse] | None = None

    model_config = {"from_attributes": True}

    @field_validator("sources", mode="before")
    @classmethod
    def _parse_sources(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return None
        return v


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    content: str
    model: str | None = None


class SearchResult(BaseModel):
    conversation_id: int
    conversation_title: str
    message_snippet: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    results: list[SearchResult]


class ExportFormat(str, Enum):
    json = "json"
    pdf = "pdf"


class ConversationExport(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]
    exported_at: datetime

    model_config = {"from_attributes": True}
