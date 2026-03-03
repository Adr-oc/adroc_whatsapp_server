from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_api_key
from app.schemas.message import SendMessageRequest
from app.services.evolution import evolution_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/instances", dependencies=[Depends(verify_api_key)])


class GetBase64Request(BaseModel):
    key: dict[str, Any]
    message: dict[str, Any]


@router.post("/{name}/send")
async def send_message(
    name: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a message via WhatsApp through Evolution API."""
    has_media = bool(
        (body.media_url or body.media_base64) and body.media_type
    )

    if has_media:
        media = body.media_base64 or body.media_url or ""

        result = await evolution_service.send_media(
            instance_name=name,
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
            instance_name=name,
            number=body.number,
            text=body.text or "",
            quoted=body.quoted,
        )

    log.info("message_sent", instance=name, number=body.number)
    return result


@router.post("/{name}/media-base64")
async def get_media_base64(name: str, body: GetBase64Request):
    """Download media as base64 from Evolution API for a given message."""
    result = await evolution_service.get_base64_from_media(
        instance_name=name,
        message_key=body.key,
        message_content=body.message,
    )
    log.info(
        "media_base64_fetched",
        instance=name,
        has_base64=bool(result.get("base64")),
    )
    return result
