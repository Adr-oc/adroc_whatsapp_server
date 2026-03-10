from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_tenant, get_db
from app.models.tenant import Tenant
from app.schemas.message import SendMessageRequest
from app.services.evolution import evolution_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/instances", dependencies=[Depends(get_current_tenant)])


class GetBase64Request(BaseModel):
    key: dict[str, Any]
    message: dict[str, Any]


@router.post("/{name}/send")
async def send_message(
    name: str,
    body: SendMessageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Send a message via WhatsApp through Evolution API."""
    evo_name = f"{tenant.slug}_{name}"
    has_media = bool(
        (body.media_url or body.media_base64) and body.media_type
    )

    if has_media:
        media = body.media_base64 or body.media_url or ""

        result = await evolution_service.send_media(
            instance_name=evo_name,
            number=body.number,
            media=media,
            media_type=body.media_type or "document",
            caption=body.text,
            mimetype=body.media_mimetype,
            filename=body.media_filename,
            quoted=body.quoted,
        )
    else:
        result = await evolution_service.send_text(
            instance_name=evo_name,
            number=body.number,
            text=body.text or "",
            quoted=body.quoted,
        )

    log.info("message_sent", instance=evo_name, number=body.number, tenant=tenant.slug)
    return result


@router.post("/{name}/media-base64")
async def get_media_base64(
    name: str,
    body: GetBase64Request,
    tenant: Tenant = Depends(get_current_tenant),
):
    """Download media as base64 from Evolution API for a given message."""
    evo_name = f"{tenant.slug}_{name}"
    result = await evolution_service.get_base64_from_media(
        instance_name=evo_name,
        message_key=body.key,
        message_content=body.message,
    )
    log.info(
        "media_base64_fetched",
        instance=evo_name,
        has_base64=bool(result.get("base64")),
    )
    return result
