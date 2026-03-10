import structlog
from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.database import async_session
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.services.evolution import evolution_service
from app.services.odoo import odoo_forwarder

log = structlog.get_logger()
router = APIRouter()


@router.get("/api/health")
async def health_check():
    result: dict = {"status": "ok"}

    # Check database
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))

            # Pending webhook events
            count_result = await session.execute(
                select(func.count()).select_from(WebhookEvent).where(WebhookEvent.processed == False)  # noqa: E712
            )
            pending = count_result.scalar() or 0

            # Tenant counts
            total_tenants = (await session.execute(
                select(func.count()).select_from(Tenant)
            )).scalar() or 0
            active_tenants = (await session.execute(
                select(func.count()).select_from(Tenant).where(Tenant.is_active == True)  # noqa: E712
            )).scalar() or 0

        result["database"] = {"status": "connected", "pending_events": pending}
        result["tenants"] = {"total": total_tenants, "active": active_tenants}
    except Exception:
        result["database"] = {"status": "disconnected"}
        result["status"] = "degraded"

    # Check Evolution API
    try:
        if await evolution_service.is_reachable():
            result["evolution_api"] = {"status": "reachable"}
        else:
            result["evolution_api"] = {"status": "unreachable"}
    except Exception:
        result["evolution_api"] = {"status": "unreachable"}

    # Worker stats
    result["workers"] = {
        "active": len(odoo_forwarder._workers),
        "queue_size": odoo_forwarder.queue.qsize(),
    }

    return result
