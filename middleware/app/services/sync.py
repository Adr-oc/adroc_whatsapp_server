import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.services.odoo import odoo_forwarder

log = structlog.get_logger()

# In-memory job tracking (Phase 1: move to DB or Redis)
_resync_jobs: dict[str, dict] = {}


async def start_resync(
    db: AsyncSession,
    from_date: datetime,
    session_filter: str | None = None,
) -> str:
    """Start an async resync job. Returns a job_id."""
    job_id = str(uuid.uuid4())
    _resync_jobs[job_id] = {
        "status": "pending",
        "total": 0,
        "processed": 0,
        "errors": 0,
        "started_at": datetime.utcnow().isoformat(),
    }

    # TODO Phase 1: implement actual resync logic
    # Query messages from from_date, batch-forward to Odoo via queue
    log.info(
        "resync_started",
        job_id=job_id,
        from_date=from_date.isoformat(),
        session=session_filter,
    )

    return job_id


def get_resync_status(job_id: str) -> dict | None:
    return _resync_jobs.get(job_id)
