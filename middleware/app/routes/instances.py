import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_api_key
from app.exceptions import EvolutionAPIError
from app.schemas.instance import (
    CreateInstanceRequest,
    InstanceResponse,
    InstanceStatusResponse,
    QRCodeResponse,
)
from app.services.evolution import evolution_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/instances", dependencies=[Depends(verify_api_key)])


@router.post("", response_model=InstanceResponse)
async def create_instance(
    body: CreateInstanceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new WhatsApp instance via Evolution API.

    If the instance already exists, reconnect it and return its QR code.
    """
    try:
        result = await evolution_service.create_instance(body.instance_name)
    except EvolutionAPIError as e:
        if e.status_code == 403 and "already in use" in (e.message or ""):
            log.info("instance_exists_reconnecting", instance=body.instance_name)
            connect_result = await evolution_service.connect(body.instance_name)
            return InstanceResponse(
                instance_name=body.instance_name,
                state="created",
                qrcode_base64=connect_result.get("base64"),
            )
        raise

    # TODO Phase 1: persist instance to local DB
    return InstanceResponse(
        instance_name=body.instance_name,
        state="created",
        qrcode_base64=result.get("qrcode", {}).get("base64"),
    )


@router.get("", response_model=list[InstanceResponse])
async def list_instances(db: AsyncSession = Depends(get_db)):
    """List all instances."""
    instances = await evolution_service.fetch_instances()
    return [
        InstanceResponse(
            instance_name=inst.get("name", ""),
            state=inst.get("connectionStatus", "unknown"),
        )
        for inst in instances
    ]


@router.get("/{name}/qr", response_model=QRCodeResponse)
async def get_qr_code(name: str):
    """Get QR code for pairing."""
    result = await evolution_service.connect(name)
    return QRCodeResponse(
        instance_name=name,
        base64=result.get("base64"),
        code=result.get("code"),
    )


@router.get("/{name}/status", response_model=InstanceStatusResponse)
async def get_instance_status(name: str):
    """Get connection state of an instance."""
    result = await evolution_service.connection_state(name)
    state = result.get("instance", {}).get("state", "unknown")
    return InstanceStatusResponse(instance_name=name, state=state)


@router.delete("/{name}")
async def delete_instance(name: str, db: AsyncSession = Depends(get_db)):
    """Delete an instance."""
    result = await evolution_service.delete_instance(name)
    # TODO Phase 1: remove from local DB
    return result


@router.put("/{name}/restart")
async def restart_instance(name: str):
    """Restart an instance."""
    return await evolution_service.restart_instance(name)


@router.delete("/{name}/logout")
async def logout_instance(name: str, db: AsyncSession = Depends(get_db)):
    """Logout (disconnect WhatsApp) from an instance."""
    result = await evolution_service.logout_instance(name)
    # TODO Phase 1: update local DB state
    return result
