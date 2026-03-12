import asyncio

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import get_db
from app.exceptions import OdooForwardError
from app.models.webhook_event import WebhookEvent
from app.schemas.webhook import ConnectionUpdateData, EvolutionWebhookPayload, QRCodeData
from app.services.instances import update_instance_qr, update_instance_state
from app.services.odoo import odoo_forwarder
from app.services.tenants import tenant_cache

log = structlog.get_logger()
router = APIRouter()

FORWARD_EVENTS = {
    "messages.upsert",
    "messages.update",
    "connection.update",
    "qrcode.updated",
    "contacts.update",
}


async def _save_audit_trail(
    event_type: str,
    instance: str,
    raw_payload: dict,
    processed: bool,
    error: str | None = None,
    tenant_id: int | None = None,
) -> None:
    """Write a webhook event to the audit trail using its own session."""
    try:
        async with async_session() as db:
            event = WebhookEvent(
                event_type=event_type,
                instance=instance,
                raw_payload=raw_payload,
                processed=processed,
                error=error,
                tenant_id=tenant_id,
            )
            db.add(event)
            await db.commit()
    except Exception as e:
        log.error("audit_trail_write_failed", error=str(e))


@router.post("/webhooks/evolution", status_code=200)
async def receive_evolution_webhook(
    payload: EvolutionWebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """Receive webhooks from Evolution API, track instance state, forward to tenant's Odoo."""
    # Resolve tenant from Evolution instance name
    tenant = tenant_cache.get_by_instance_name(payload.instance)
    tenant_id = tenant.id if tenant else None

    log.info(
        "webhook_received",
        webhook_event=payload.event,
        instance=payload.instance,
        tenant=tenant.slug if tenant else None,
    )

    # Instance state tracking (inline, before forwarding)
    if payload.event == "connection.update":
        try:
            data = ConnectionUpdateData(**payload.data)
            await update_instance_state(db, payload.instance, data.state)
        except Exception as e:
            log.error("instance_state_update_failed", error=str(e), instance=payload.instance)
    elif payload.event == "qrcode.updated":
        try:
            data = QRCodeData(**payload.data)
            qr_base64 = data.qrcode.get("base64", "")
            if qr_base64:
                await update_instance_qr(db, payload.instance, qr_base64)
        except Exception as e:
            log.error("instance_qr_update_failed", error=str(e), instance=payload.instance)

    # Forward to tenant's Odoo
    enqueue_error: str | None = None
    if payload.event in FORWARD_EVENTS:
        if tenant:
            # Strip tenant prefix from instance name so Odoo sees the
            # name it created (e.g. "demo_TARS INSTANCE" → "TARS INSTANCE")
            odoo_instance_name = payload.instance
            prefix = f"{tenant.slug}_"
            if odoo_instance_name.startswith(prefix):
                odoo_instance_name = odoo_instance_name[len(prefix):]
            forward_payload = {
                "event": payload.event,
                "instance": odoo_instance_name,
                "data": payload.data,
            }
            try:
                await odoo_forwarder.enqueue(
                    forward_payload,
                    tenant_odoo_url=tenant.odoo_webhook_url,
                    tenant_odoo_key=tenant.odoo_api_key,
                )
            except OdooForwardError as e:
                enqueue_error = str(e)
                log.error(
                    "webhook_queue_full",
                    webhook_event=payload.event,
                    instance=payload.instance,
                    queue_size=odoo_forwarder.queue.qsize(),
                )
        else:
            enqueue_error = "no_tenant"
            log.warning(
                "webhook_no_tenant",
                webhook_event=payload.event,
                instance=payload.instance,
            )

    # Audit trail (fire-and-forget with its own session)
    raw = payload.model_dump(mode="json")
    asyncio.create_task(
        _save_audit_trail(
            event_type=payload.event,
            instance=payload.instance,
            raw_payload=raw,
            processed=enqueue_error is None,
            error=enqueue_error,
            tenant_id=tenant_id,
        )
    )

    if enqueue_error and enqueue_error != "no_tenant":
        return JSONResponse(
            status_code=503,
            content={"detail": "Forwarding queue at capacity, retry later"},
        )

    return {"status": "received"}
