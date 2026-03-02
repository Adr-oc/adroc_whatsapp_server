from __future__ import annotations

from pydantic import BaseModel


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
