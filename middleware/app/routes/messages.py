import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_api_key
from app.schemas.message import SendMessageRequest
from app.services.evolution import evolution_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/instances", dependencies=[Depends(verify_api_key)])


@router.post("/{name}/send")
async def send_message(
    name: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a message via WhatsApp through Evolution API."""
    if body.media_url and body.media_type:
        result = await evolution_service.send_media(
            instance_name=name,
            number=body.number,
            media_url=body.media_url,
            media_type=body.media_type,
            caption=body.text,
        )
    else:
        result = await evolution_service.send_text(
            instance_name=name,
            number=body.number,
            text=body.text or "",
        )

    # TODO Phase 1: persist outgoing message to DB
    log.info("message_sent", instance=name, number=body.number)
    return result
