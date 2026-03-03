import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks

from app.config import settings
from app.schemas.webhook import EvolutionWebhookPayload

log = structlog.get_logger()
router = APIRouter()

FORWARD_EVENTS = {
    "messages.upsert",
    "messages.update",
    "connection.update",
    "qrcode.updated",
    "contacts.update",
}


async def _forward_to_odoo(payload: dict):
    """POST the webhook payload to Odoo's /whatsapp/webhook endpoint."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                settings.ODOO_WEBHOOK_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "call", "params": payload},
                headers={
                    "X-API-Key": settings.ODOO_API_KEY,
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 200:
                log.info(
                    "odoo_forward_ok",
                    status_code=response.status_code,
                    webhook_event=payload.get("event"),
                    instance=payload.get("instance"),
                    response_body=response.text[:500],
                )
            else:
                log.error(
                    "odoo_forward_error",
                    status_code=response.status_code,
                    webhook_event=payload.get("event"),
                    instance=payload.get("instance"),
                    response_body=response.text[:1000],
                )
    except Exception:
        log.error(
            "odoo_forward_failed",
            webhook_event=payload.get("event"),
            instance=payload.get("instance"),
            exc_info=True,
        )


@router.post("/webhooks/evolution", status_code=200)
async def receive_evolution_webhook(
    payload: EvolutionWebhookPayload,
    background_tasks: BackgroundTasks,
):
    """Receive webhooks from Evolution API and forward relevant ones to Odoo."""
    log.info(
        "webhook_received",
        webhook_event=payload.event,
        instance=payload.instance,
    )

    if payload.event in FORWARD_EVENTS:
        forward_payload = {
            "event": payload.event,
            "instance": payload.instance,
            "data": payload.data,
        }
        background_tasks.add_task(_forward_to_odoo, forward_payload)

    return {"status": "received"}
