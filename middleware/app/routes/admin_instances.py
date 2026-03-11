import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_admin_key, AdminKeyDep
from app.exceptions import EvolutionAPIError
from app.schemas.instance import (
    AdminCreateInstanceRequest,
    AdminInstanceResponse,
    AdminSendMessageRequest,
)
from app.services.evolution import evolution_service
from app.services.instances import (
    delete_instance_by_name,
    get_all_instances_admin,
    get_instance,
    upsert_instance,
)
from app.services.tenants import get_tenant_by_slug, tenant_cache

log = structlog.get_logger()
router = APIRouter(prefix="/api/admin/instances", dependencies=[AdminKeyDep])


def _strip_prefix(slug: str, evo_name: str) -> str:
    prefix = f"{slug}_"
    return evo_name[len(prefix):] if evo_name.startswith(prefix) else evo_name


@router.get("", response_model=list[AdminInstanceResponse])
async def list_admin_instances(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all instances. Optional ?tenant=<slug> filter."""
    rows = await get_all_instances_admin(db, tenant_slug=tenant)
    return [
        AdminInstanceResponse(
            instance_name=_strip_prefix(t.slug, inst.instance_name),
            evolution_name=inst.instance_name,
            tenant_slug=t.slug,
            state=inst.state,
            phone_number=inst.phone_number,
            last_event_at=last_event,
        )
        for inst, t, last_event in rows
    ]


@router.post("", response_model=AdminInstanceResponse, status_code=201)
async def create_admin_instance(
    body: AdminCreateInstanceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create instance for a tenant using admin key."""
    tenant = await get_tenant_by_slug(db, body.tenant_slug)
    if not tenant:
        raise HTTPException(404, f"Tenant '{body.tenant_slug}' not found")

    evo_name = f"{tenant.slug}_{body.instance_name}"
    try:
        result = await evolution_service.create_instance(evo_name)
    except EvolutionAPIError as e:
        if e.status_code == 403 and "already in use" in (e.message or ""):
            await upsert_instance(db, evo_name, tenant.id, state="connecting")
            tenant_cache.register_instance(evo_name, tenant)
            return AdminInstanceResponse(
                instance_name=body.instance_name,
                evolution_name=evo_name,
                tenant_slug=tenant.slug,
                state="connecting",
            )
        raise

    hash_val = result.get("hash")
    instance_token = hash_val if isinstance(hash_val, str) else (hash_val or {}).get("apikey")
    await upsert_instance(
        db, evo_name, tenant.id,
        state="created",
        evolution_id=result.get("instance", {}).get("instanceId"),
        instance_token=instance_token,
        qr_code_base64=result.get("qrcode", {}).get("base64"),
    )
    tenant_cache.register_instance(evo_name, tenant)
    return AdminInstanceResponse(
        instance_name=body.instance_name,
        evolution_name=evo_name,
        tenant_slug=tenant.slug,
        state="created",
    )


@router.put("/{name}/restart")
async def restart_admin_instance(name: str, db: AsyncSession = Depends(get_db)):
    """Restart instance by evolution_name."""
    instance = await get_instance(db, name)
    if not instance:
        raise HTTPException(404, f"Instance '{name}' not found")
    result = await evolution_service.restart_instance(name)
    await upsert_instance(db, name, instance.tenant_id, state="connecting")
    return result


@router.delete("/{name}")
async def delete_admin_instance(name: str, db: AsyncSession = Depends(get_db)):
    """Delete instance by evolution_name."""
    instance = await get_instance(db, name)
    if not instance:
        raise HTTPException(404, f"Instance '{name}' not found")
    try:
        result = await evolution_service.delete_instance(name)
    except EvolutionAPIError:
        result = {"status": "SUCCESS"}
    await delete_instance_by_name(db, name)
    tenant_cache.unregister_instance(name)
    return result


@router.delete("/{name}/logout")
async def logout_admin_instance(name: str, db: AsyncSession = Depends(get_db)):
    """Logout instance by evolution_name."""
    instance = await get_instance(db, name)
    if not instance:
        raise HTTPException(404, f"Instance '{name}' not found")
    result = await evolution_service.logout_instance(name)
    await upsert_instance(db, name, instance.tenant_id, state="close")
    return result


@router.post("/{name}/send")
async def send_admin_message(
    name: str,
    body: AdminSendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send test message via instance."""
    instance = await get_instance(db, name)
    if not instance:
        raise HTTPException(404, f"Instance '{name}' not found")
    return await evolution_service.send_text(
        instance_name=name,
        number=body.number,
        text=body.text,
        quoted=None,
    )
