import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("EVOLUTION_API_KEY", "test-evo-key")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("LOG_FORMAT", "console")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.tenants import tenant_cache  # noqa: E402

ADMIN_KEY = "test-admin-key"
TENANT_KEY = "test-tenant-key"

# A real Tenant object for tests that exercise tenant-scoped routes
TEST_TENANT = Tenant(
    id=1,
    slug="acme",
    display_name="Acme Corp",
    odoo_webhook_url="https://acme.odoo.com/whatsapp/webhook",
    odoo_api_key="odoo-key",
    api_key=TENANT_KEY,
    is_active=True,
    max_instances=10,
)


@pytest.fixture(autouse=True)
def seed_tenant_cache():
    """Populate in-memory cache so tenant-scoped routes don't 403 in tests."""
    tenant_cache._by_api_key[TENANT_KEY] = TEST_TENANT
    tenant_cache._by_instance_name["acme_ventas"] = TEST_TENANT
    yield
    tenant_cache._by_api_key.pop(TENANT_KEY, None)
    tenant_cache._by_instance_name.pop("acme_ventas", None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}


@pytest.fixture
def tenant_headers():
    return {"X-API-Key": TENANT_KEY}


# Keep auth_headers as alias for tenant_headers for existing tests
@pytest.fixture
def auth_headers():
    return {"X-API-Key": TENANT_KEY}
