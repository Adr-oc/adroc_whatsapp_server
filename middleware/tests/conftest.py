import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("EVOLUTION_API_KEY", "test-evo-key")
os.environ.setdefault("ODOO_WEBHOOK_URL", "https://test.odoo.com/whatsapp/webhook")
os.environ.setdefault("ODOO_API_KEY", "test-odoo-key")
os.environ.setdefault("MIDDLEWARE_API_KEY", "test-middleware-key")
os.environ.setdefault("LOG_FORMAT", "console")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402

API_KEY = "test-middleware-key"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"X-API-Key": API_KEY}
