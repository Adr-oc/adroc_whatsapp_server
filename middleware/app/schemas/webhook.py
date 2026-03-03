from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EvolutionWebhookPayload(BaseModel):
    """Top-level envelope from Evolution API webhooks."""

    event: str
    instance: str
    data: dict[str, Any]
    date_time: datetime | None = None
    server_url: str | None = None
    apikey: str | None = None


class MessageKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str


class MessageUpsertData(BaseModel):
    key: MessageKey
    pushName: str | None = None
    message: dict[str, Any] | None = None
    messageType: str | None = None
    messageTimestamp: int | None = None


class MessageUpdateData(BaseModel):
    key: MessageKey
    update: dict[str, Any]


class ConnectionUpdateData(BaseModel):
    state: str
    statusReason: int | None = None


class QRCodeData(BaseModel):
    qrcode: dict[str, str]
