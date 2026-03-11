from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreateInstanceRequest(BaseModel):
    """Request body for POST /api/instances."""

    instance_name: str


class InstanceResponse(BaseModel):
    """Instance info returned by the API."""

    instance_name: str
    state: str
    phone_number: str | None = None
    qrcode_base64: str | None = None

    model_config = {"from_attributes": True}


class InstanceStatusResponse(BaseModel):
    """Connection state for an instance."""

    instance_name: str
    state: str


class QRCodeResponse(BaseModel):
    """QR code for pairing."""

    instance_name: str
    base64: str | None = None
    code: str | None = None


class AdminCreateInstanceRequest(BaseModel):
    tenant_slug: str
    instance_name: str


class AdminSendMessageRequest(BaseModel):
    number: str
    text: str


class AdminInstanceResponse(BaseModel):
    instance_name: str      # stripped display name (prefix removed)
    evolution_name: str     # full prefixed name for URL paths
    tenant_slug: str
    state: str
    phone_number: str | None = None
    last_event_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
