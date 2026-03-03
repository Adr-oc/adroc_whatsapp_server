from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SendMessageRequest(BaseModel):
    """Request body for POST /api/instances/{name}/send."""

    number: str
    text: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    media_base64: str | None = None
    media_mimetype: str | None = None
    media_filename: str | None = None
    quoted: dict | None = None


class MessageResponse(BaseModel):
    """Response for message operations."""

    id: int
    whatsapp_id: str | None
    session: str
    remote_jid: str
    direction: str
    body: str | None
    message_type: str
    timestamp: datetime
    status: str
    odoo_synced: bool

    model_config = {"from_attributes": True}


class ResyncRequest(BaseModel):
    """Request body for POST /api/resync."""

    from_date: datetime
    session: str | None = None


class ResyncResponse(BaseModel):
    """Response for resync operation."""

    job_id: str
    status: str
    message: str
