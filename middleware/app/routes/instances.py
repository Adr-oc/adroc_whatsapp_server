import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_tenant, get_db
from app.exceptions import EvolutionAPIError
from app.models.tenant import Tenant
from app.schemas.instance import (
    CreateInstanceRequest,
    InstanceResponse,
    InstanceStatusResponse,
    QRCodeResponse,
)
from app.services.evolution import evolution_service
from app.services.instances import (
    delete_instance_by_name,
    get_instance_for_tenant,
    get_tenant_instances,
    upsert_instance,
)
from app.services.tenants import get_tenant_instance_count, tenant_cache

log = structlog.get_logger()
router = APIRouter(prefix="/api/instances", dependencies=[Depends(get_current_tenant)])


def _evo_name(tenant: Tenant, name: str) -> str:
    """Build the Evolution instance name with tenant prefix."""
    return f"{tenant.slug}_{name}"


def _strip_prefix(tenant: Tenant, evo_name: str) -> str:
    """Strip tenant prefix from Evolution name for API responses."""
    prefix = f"{tenant.slug}_"
    if evo_name.startswith(prefix):
        return evo_name[len(prefix):]
    return evo_name


@router.post("", response_model=InstanceResponse)
async def create_instance(
    body: CreateInstanceRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new WhatsApp instance via Evolution API."""
    # Check quota
    count = await get_tenant_instance_count(db, tenant.id)
    if count >= tenant.max_instances:
        raise HTTPException(400, f"Instance quota reached ({tenant.max_instances})")

    evo_name = _evo_name(tenant, body.instance_name)

    try:
        result = await evolution_service.create_instance(evo_name)
    except EvolutionAPIError as e:
        if e.status_code == 403 and "already in use" in (e.message or ""):
            log.info("instance_exists_reconnecting", instance=evo_name)
            connect_result = await evolution_service.connect(evo_name)
            await upsert_instance(db, evo_name, tenant.id, state="connecting")
            tenant_cache.register_instance(evo_name, tenant)
            return InstanceResponse(
                instance_name=body.instance_name,
                state="connecting",
                qrcode_base64=connect_result.get("base64"),
            )
        raise

    instance_data = result.get("instance", {})
    hash_value = result.get("hash")
    instance_token = hash_value if isinstance(hash_value, str) else (hash_value or {}).get("apikey")
    qr_base64 = result.get("qrcode", {}).get("base64")

    await upsert_instance(
        db,
        evo_name,
        tenant.id,
        state="created",
        evolution_id=instance_data.get("instanceId"),
        instance_token=instance_token,
        qr_code_base64=qr_base64,
    )
    tenant_cache.register_instance(evo_name, tenant)

    return InstanceResponse(
        instance_name=body.instance_name,
        state="created",
        qrcode_base64=qr_base64,
    )


@router.get("", response_model=list[InstanceResponse])
async def list_instances(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List this tenant's instances."""
    instances = await get_tenant_instances(db, tenant.id)
    return [
        InstanceResponse(
            instance_name=_strip_prefix(tenant, inst.instance_name),
            state=inst.state,
            phone_number=inst.phone_number,
            qrcode_base64=inst.qr_code_base64,
        )
        for inst in instances
    ]


@router.get("/{name}/qr", response_model=QRCodeResponse)
async def get_qr_code(
    name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get QR code for pairing. Returns from local DB, falls back to Evolution."""
    evo_name = _evo_name(tenant, name)
    instance = await get_instance_for_tenant(db, evo_name, tenant.id)
    if instance and instance.qr_code_base64:
        return QRCodeResponse(instance_name=name, base64=instance.qr_code_base64, code=None)

    result = await evolution_service.connect(evo_name)
    return QRCodeResponse(
        instance_name=name,
        base64=result.get("base64"),
        code=result.get("code"),
    )


@router.get("/{name}/status", response_model=InstanceStatusResponse)
async def get_instance_status(
    name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get connection state. Returns from local DB, falls back to Evolution."""
    evo_name = _evo_name(tenant, name)
    instance = await get_instance_for_tenant(db, evo_name, tenant.id)
    if instance:
        return InstanceStatusResponse(instance_name=name, state=instance.state)

    result = await evolution_service.connection_state(evo_name)
    state = result.get("instance", {}).get("state", "unknown")
    return InstanceStatusResponse(instance_name=name, state=state)


@router.delete("/{name}")
async def delete_instance(
    name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete an instance from Evolution and local DB."""
    evo_name = _evo_name(tenant, name)
    try:
        result = await evolution_service.delete_instance(evo_name)
    except EvolutionAPIError:
        result = {"status": "SUCCESS", "response": {"message": "Instance removed from local DB"}}
    await delete_instance_by_name(db, evo_name)
    tenant_cache.unregister_instance(evo_name)
    return result


@router.put("/{name}/restart")
async def restart_instance(
    name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Restart an instance."""
    evo_name = _evo_name(tenant, name)
    result = await evolution_service.restart_instance(evo_name)
    await upsert_instance(db, evo_name, tenant.id, state="connecting")
    return result


@router.delete("/{name}/logout")
async def logout_instance(
    name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Logout (disconnect WhatsApp) from an instance."""
    evo_name = _evo_name(tenant, name)
    result = await evolution_service.logout_instance(evo_name)
    await upsert_instance(db, evo_name, tenant.id, state="close")
    return result
