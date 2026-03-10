import asyncio
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.webhook_event import WebhookEvent
from app.services.odoo import odoo_forwarder

log = structlog.get_logger()

# In-memory job tracking
_resync_jobs: dict[str, dict] = {}


async def start_resync(
    db: AsyncSession,
    from_date: datetime,
    session_filter: str | None = None,
    tenant_id: int | None = None,
    tenant_odoo_url: str | None = None,
    tenant_odoo_key: str | None = None,
) -> str:
    """Start an async resync job that replays webhook_events to tenant's Odoo."""
    job_id = str(uuid.uuid4())
    _resync_jobs[job_id] = {
        "status": "running",
        "total": 0,
        "enqueued": 0,
        "errors": 0,
        "started_at": datetime.utcnow().isoformat(),
    }

    asyncio.create_task(
        _run_resync(job_id, from_date, session_filter, tenant_id, tenant_odoo_url, tenant_odoo_key)
    )

    log.info(
        "resync_started",
        job_id=job_id,
        from_date=from_date.isoformat(),
        session=session_filter,
        tenant_id=tenant_id,
    )
    return job_id


async def _run_resync(
    job_id: str,
    from_date: datetime,
    session_filter: str | None,
    tenant_id: int | None,
    tenant_odoo_url: str | None,
    tenant_odoo_key: str | None,
) -> None:
    """Background task: query webhook_events and re-enqueue to tenant's Odoo."""
    job = _resync_jobs[job_id]
    try:
        async with async_session() as db:
            query = (
                select(WebhookEvent)
                .where(WebhookEvent.created_at >= from_date)
                .order_by(WebhookEvent.created_at)
            )
            if session_filter:
                query = query.where(WebhookEvent.instance == session_filter)
            if tenant_id is not None:
                query = query.where(WebhookEvent.tenant_id == tenant_id)

            result = await db.execute(query)
            events = result.scalars().all()

        job["total"] = len(events)
        log.info("resync_events_found", job_id=job_id, total=len(events))

        if not tenant_odoo_url or not tenant_odoo_key:
            job["status"] = "failed"
            job["error"] = "Missing tenant Odoo URL or key"
            return

        for event in events:
            try:
                payload = {
                    "event": event.event_type,
                    "instance": event.instance,
                    "data": event.raw_payload.get("data", {}),
                }
                await odoo_forwarder.enqueue(payload, tenant_odoo_url, tenant_odoo_key)
                job["enqueued"] += 1
            except Exception as e:
                job["errors"] += 1
                log.warning("resync_enqueue_error", job_id=job_id, event_id=event.id, error=str(e))

        job["status"] = "completed"
        job["completed_at"] = datetime.utcnow().isoformat()
        log.info("resync_completed", job_id=job_id, enqueued=job["enqueued"], errors=job["errors"])

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        log.error("resync_failed", job_id=job_id, error=str(e))


def get_resync_status(job_id: str) -> dict | None:
    return _resync_jobs.get(job_id)
