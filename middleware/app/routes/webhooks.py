import structlog
from fastapi import APIRouter

from app.schemas.webhook import EvolutionWebhookPayload

log = structlog.get_logger()
router = APIRouter()


@router.post("/webhooks/evolution", status_code=200)
async def receive_evolution_webhook(payload: EvolutionWebhookPayload):
    """Receive webhooks from Evolution API.

    Flow: persist raw event → return 200 → parse → persist message → forward to Odoo.
    Full implementation in Phase 1.
    """
    log.info(
        "webhook_received",
        webhook_event=payload.event,
        instance=payload.instance,
    )

    # TODO Phase 1: persist to webhook_events, process async, forward to Odoo
    return {"status": "received"}
