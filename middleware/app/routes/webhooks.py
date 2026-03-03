import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.exceptions import OdooForwardError
from app.schemas.webhook import EvolutionWebhookPayload
from app.services.odoo import odoo_forwarder

log = structlog.get_logger()
router = APIRouter()

FORWARD_EVENTS = {
    "messages.upsert",
    "messages.update",
    "connection.update",
    "qrcode.updated",
    "contacts.update",
}


@router.post("/webhooks/evolution", status_code=200)
async def receive_evolution_webhook(payload: EvolutionWebhookPayload):
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
        try:
            await odoo_forwarder.enqueue(forward_payload)
        except OdooForwardError:
            log.error(
                "webhook_queue_full",
                webhook_event=payload.event,
                instance=payload.instance,
                queue_size=odoo_forwarder.queue.qsize(),
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Forwarding queue at capacity, retry later"},
            )

    return {"status": "received"}
