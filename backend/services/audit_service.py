"""Audit trail service.

Records who did what and when (logins, uploads, queries, source views,
exports). Recording never raises: an audit failure is logged but must not
break the user's request.

Query text is stored *in the audit table* only when
``GANTRY_AUDIT_STORE_QUERY_TEXT`` is truthy (default off); with it off only
the query length is kept. The flag does NOT control chat history
(``messages``) or long-term memory -- see docs/audit-log-and-citations.md.
Stored query text is redacted (SSN/EIN/email) unless
``GANTRY_AUDIT_REDACT=false``.
"""
import csv
import io
import json
import logging
import os
import re
from datetime import timezone

from sqlalchemy.orm import Session as DBSession

from backend.models.audit_event import AuditEvent

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "id", "timestamp", "user_id", "user_email", "action", "resource_type",
    "resource_id", "doc_ids", "query_text", "detail", "ip_address",
]


_REDACTIONS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}-\d{7}\b"), "[EIN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# Count of audit writes that failed in this process; returned by GET /api/admin/audit
# as ``audit_write_failures`` (resets on restart).
write_failures = 0


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _redact_enabled() -> bool:
    return os.getenv("GANTRY_AUDIT_REDACT", "true").lower() in ("true", "1", "yes")


def _safe_cell(value) -> str:
    """Neutralise spreadsheet formula injection (OWASP CSV injection)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _iso_utc(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; values are written in UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def store_query_text_enabled() -> bool:
    return os.getenv("GANTRY_AUDIT_STORE_QUERY_TEXT", "false").lower() in ("true", "1", "yes")


class AuditService:
    def __init__(self, db: DBSession):
        self.db = db

    def record(
        self,
        action: str,
        user=None,
        *,
        user_email: str | None = None,
        resource_type: str | None = None,
        resource_id: int | None = None,
        doc_ids: list[int] | None = None,
        query_text: str | None = None,
        detail: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        try:
            detail = dict(detail or {})
            stored_query = None
            if query_text is not None:
                if store_query_text_enabled():
                    stored_query = redact(query_text) if _redact_enabled() else query_text
                else:
                    detail["query_chars"] = len(query_text)
            event = AuditEvent(
                user_id=getattr(user, "id", None),
                user_email=getattr(user, "email", None) or user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                doc_ids=json.dumps(doc_ids) if doc_ids is not None else None,
                query_text=stored_query,
                detail=json.dumps(detail) if detail else None,
                ip_address=ip_address,
            )
            self.db.add(event)
            self.db.commit()
        except Exception as e:  # never break the request because of auditing
            global write_failures
            write_failures += 1
            logger.error("AUDIT WRITE FAILED for %s (%d failures so far): %s", action, write_failures, e)
            try:
                self.db.rollback()
            except Exception:
                pass

    def list_events(
        self,
        action: str | None = None,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        q = self.db.query(AuditEvent)
        if action:
            q = q.filter(AuditEvent.action == action)
        if user_id is not None:
            q = q.filter(AuditEvent.user_id == user_id)
        total = q.count()
        events = q.order_by(AuditEvent.id.desc()).offset(offset).limit(limit).all()
        return events, total


def event_to_dict(e: AuditEvent) -> dict:
    return {
        "id": e.id,
        "timestamp": _iso_utc(e.timestamp),
        "user_id": e.user_id,
        "user_email": e.user_email,
        "action": e.action,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "doc_ids": json.loads(e.doc_ids) if e.doc_ids else [],
        "query_text": e.query_text,
        "detail": json.loads(e.detail) if e.detail else {},
        "ip_address": e.ip_address,
    }


def events_to_csv(events: list[AuditEvent]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for e in events:
        d = event_to_dict(e)
        w.writerow([_safe_cell(v) for v in (
            d["id"], d["timestamp"], d["user_id"], d["user_email"], d["action"], d["resource_type"],
            d["resource_id"], ";".join(str(i) for i in d["doc_ids"]), d["query_text"],
            json.dumps(d["detail"]) if d["detail"] else "", d["ip_address"],
        )])
    return buf.getvalue()


def client_ip(request) -> str | None:
    try:
        return request.client.host if request and request.client else None
    except Exception:
        return None
