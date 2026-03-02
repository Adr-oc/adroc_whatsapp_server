import structlog
from fastapi import APIRouter
from sqlalchemy import text

from app.database import async_session
from app.services.evolution import evolution_service

log = structlog.get_logger()
router = APIRouter()


@router.get("/api/health")
async def health_check():
    result = {"status": "ok", "database": "unknown", "evolution_api": "unknown"}

    # Check database
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        result["database"] = "connected"
    except Exception:
        result["database"] = "disconnected"
        result["status"] = "degraded"

    # Check Evolution API (non-blocking, don't fail health on this)
    try:
        if await evolution_service.is_reachable():
            result["evolution_api"] = "reachable"
        else:
            result["evolution_api"] = "unreachable"
    except Exception:
        result["evolution_api"] = "unreachable"

    return result
