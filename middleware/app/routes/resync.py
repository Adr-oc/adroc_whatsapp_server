import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_tenant, get_db
from app.models.tenant import Tenant
from app.schemas.message import ResyncRequest, ResyncResponse
from app.services.sync import get_resync_status, start_resync

log = structlog.get_logger()
router = APIRouter(prefix="/api", dependencies=[Depends(get_current_tenant)])


@router.post("/resync", response_model=ResyncResponse, status_code=202)
async def trigger_resync(
    body: ResyncRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Start an async resync job to re-send webhook events to tenant's Odoo."""
    job_id = await start_resync(
        db,
        body.from_date,
        body.session,
        tenant_id=tenant.id,
        tenant_odoo_url=tenant.odoo_webhook_url,
        tenant_odoo_key=tenant.odoo_api_key,
    )
    return ResyncResponse(
        job_id=job_id,
        status="accepted",
        message="Resync job started",
    )


@router.get("/resync/{job_id}")
async def resync_status(job_id: str):
    """Get the status of a resync job."""
    result = get_resync_status(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **result}
