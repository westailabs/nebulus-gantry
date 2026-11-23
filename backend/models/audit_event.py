"""Append-only audit trail of user and system actions."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.database import Base


class AuditEvent(Base):
    """One audited action (login, upload, query, export, ...).

    ``user_id`` is deliberately not a foreign key so audit rows survive user
    deletion. ``doc_ids`` and ``detail`` are JSON strings.
    """

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    user_id = Column(Integer, nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(Integer, nullable=True)
    doc_ids = Column(Text, nullable=True)
    query_text = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
