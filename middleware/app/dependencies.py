import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    if not secrets.compare_digest(x_api_key, settings.MIDDLEWARE_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return x_api_key


ApiKeyDep = Depends(verify_api_key)
DbDep = Depends(get_db)
