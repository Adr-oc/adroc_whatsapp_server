import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_admin_key
from app.models.instance import Instance
from app.schemas.tenant import (
    CreateTenantRequest,
    TenantCreatedResponse,
    TenantListItem,
    TenantResponse,
    UpdateTenantRequest,
)
from app.services.tenants import (
    create_tenant,
    deactivate_tenant,
    get_tenant_by_slug,
    list_tenants,
    rotate_tenant_key,
    update_tenant,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/admin/tenants", dependencies=[Depends(verify_admin_key)])


@router.post("", response_model=TenantCreatedResponse, status_code=201)
async def create_tenant_endpoint(
    body: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tenant. Returns the API key (shown once)."""
    existing = await get_tenant_by_slug(db, body.slug)
    if existing:
        raise HTTPException(409, f"Tenant '{body.slug}' already exists")

    tenant, raw_key = await create_tenant(
        db,
        slug=body.slug,
        display_name=body.display_name,
        odoo_webhook_url=body.odoo_webhook_url,
        odoo_api_key=body.odoo_api_key,
        max_instances=body.max_instances,
    )
    return TenantCreatedResponse(
        tenant=TenantResponse.model_validate(tenant),
        api_key=raw_key,
    )


@router.get("", response_model=list[TenantListItem])
async def list_tenants_endpoint(db: AsyncSession = Depends(get_db)):
    """List all tenants with instance counts."""
    tenants = await list_tenants(db)
    result = []
    for tenant in tenants:
        count_result = await db.execute(
            select(func.count()).select_from(Instance)
            .where(Instance.tenant_id == tenant.id)
        )
        count = count_result.scalar() or 0
        item = TenantListItem.model_validate(tenant)
        item.instance_count = count
        result.append(item)
    return result


@router.get("/{slug}", response_model=TenantResponse)
async def get_tenant_endpoint(slug: str, db: AsyncSession = Depends(get_db)):
    """Get tenant details."""
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    return TenantResponse.model_validate(tenant)


@router.patch("/{slug}", response_model=TenantResponse)
async def update_tenant_endpoint(
    slug: str,
    body: UpdateTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update tenant configuration."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")

    tenant = await update_tenant(db, slug, **updates)
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    return TenantResponse.model_validate(tenant)


@router.delete("/{slug}", response_model=TenantResponse)
async def deactivate_tenant_endpoint(slug: str, db: AsyncSession = Depends(get_db)):
    """Deactivate a tenant (soft delete)."""
    tenant = await deactivate_tenant(db, slug)
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    return TenantResponse.model_validate(tenant)


@router.post("/{slug}/rotate-key", response_model=TenantCreatedResponse)
async def rotate_key_endpoint(slug: str, db: AsyncSession = Depends(get_db)):
    """Generate a new API key for the tenant. Old key is invalidated."""
    result = await rotate_tenant_key(db, slug)
    if not result:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    tenant, new_key = result
    return TenantCreatedResponse(
        tenant=TenantResponse.model_validate(tenant),
        api_key=new_key,
    )
