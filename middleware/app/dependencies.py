import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.tenant import Tenant
from app.services.tenants import tenant_cache


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def verify_admin_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """Validate the global admin API key."""
    if not secrets.compare_digest(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )
    return x_api_key


async def get_current_tenant(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> Tenant:
    """Resolve tenant from API key using in-memory cache."""
    tenant = tenant_cache.get_by_api_key(x_api_key)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return tenant


AdminKeyDep = Depends(verify_admin_key)
TenantDep = Depends(get_current_tenant)
DbDep = Depends(get_db)
