# Manager TUI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `scripts/manage.py` argparse CLI with a Textual TUI admin dashboard for the multi-tenant WhatsApp SaaS platform.

**Architecture:** Two phases executed sequentially: (1) Add 6 admin instance endpoints, `/api/logs` SSE endpoint, and update health/tenant-list endpoints in the middleware; (2) Build the full Textual TUI in `scripts/manage.py`. The TUI uses only `ADMIN_API_KEY` — no per-tenant keys needed.

**Tech Stack:** Textual, httpx (existing), python-dotenv, FastAPI SSE via StreamingResponse, structlog custom processor.

**Spec:** `docs/superpowers/specs/2026-03-11-manager-tui-design.md`

---

## Chunk 1: Middleware Foundations

### Task 1: Fix conftest.py for multi-tenant auth

The existing conftest uses `MIDDLEWARE_API_KEY` and sets up no tenant in the cache, which breaks all tenant-scoped route tests. Fix it.

**Files:**
- Modify: `middleware/tests/conftest.py`

- [ ] **Step 1: Replace conftest.py**

```python
# middleware/tests/conftest.py
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
```

- [ ] **Step 2: Run existing tests to see what breaks**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware
pip install -r requirements-dev.txt
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/ -v --tb=short 2>&1 | head -60
```

Expected: most tests pass; any failures are due to changed auth logic, not the conftest itself.

- [ ] **Step 3: Fix `TestAuth.test_timing_safe_comparison`** — update it to reference `verify_admin_key`:

In `tests/test_routes.py`, find `TestAuth` class and replace:

```python
class TestAuth:
    async def test_valid_key_passes(self, client, tenant_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.fetch_instances = AsyncMock(return_value=[])
            resp = await client.get("/api/instances", headers=tenant_headers)
        assert resp.status_code == 200

    async def test_missing_key_fails(self, client):
        resp = await client.get("/api/instances")
        assert resp.status_code in (403, 422)

    async def test_wrong_key_returns_403(self, client):
        resp = await client.get("/api/instances", headers={"X-API-Key": "totally-wrong"})
        assert resp.status_code == 403

    async def test_admin_timing_safe_comparison(self):
        """verify_admin_key uses secrets.compare_digest, not ==."""
        import inspect
        from app.dependencies import verify_admin_key

        source = inspect.getsource(verify_admin_key)
        assert "compare_digest" in source
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/ -v --tb=short
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add middleware/tests/conftest.py middleware/tests/test_routes.py
git commit -m "test: fix conftest for multi-tenant auth — add tenant cache seeding"
```

---

### Task 2: Add new schemas

**Files:**
- Modify: `middleware/app/schemas/instance.py`
- Modify: `middleware/app/schemas/tenant.py`

- [ ] **Step 1: Add `AdminInstanceResponse` and `AdminCreateInstanceRequest` to instance schemas**

At the top of `middleware/app/schemas/instance.py`, add these imports (merge with existing imports):

```python
from datetime import datetime
from pydantic import ConfigDict
```

Then append at the bottom of `middleware/app/schemas/instance.py`:

```python
class AdminCreateInstanceRequest(BaseModel):
    tenant_slug: str
    instance_name: str


class AdminSendMessageRequest(BaseModel):
    number: str
    text: str


class AdminInstanceResponse(BaseModel):
    instance_name: str      # stripped display name (prefix removed)
    evolution_name: str     # full prefixed name for URL paths
    tenant_slug: str
    state: str
    phone_number: str | None = None
    last_event_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Add `TenantListItem` and `LogsResponse` to tenant and a new logs schema**

Append to `middleware/app/schemas/tenant.py`:

```python
class TenantListItem(TenantResponse):
    """Used only by GET /api/admin/tenants — adds instance_count."""
    instance_count: int = 0
```

Create `middleware/app/schemas/logs.py`:

```python
from pydantic import BaseModel


class LogsResponse(BaseModel):
    lines: list[str]
```

- [ ] **Step 3: Write schema tests**

Add to `middleware/tests/test_schemas.py`:

```python
class TestAdminSchemas:
    def test_admin_instance_response_fields(self):
        from app.schemas.instance import AdminInstanceResponse
        r = AdminInstanceResponse(
            instance_name="ventas",
            evolution_name="acme_ventas",
            tenant_slug="acme",
            state="open",
        )
        assert r.instance_name == "ventas"
        assert r.evolution_name == "acme_ventas"
        assert r.last_event_at is None

    def test_tenant_list_item_has_instance_count(self):
        from app.schemas.tenant import TenantListItem
        from datetime import datetime
        item = TenantListItem(
            slug="acme",
            display_name="Acme Corp",
            odoo_webhook_url="https://x.com",
            is_active=True,
            max_instances=10,
            created_at=datetime.now(),
            instance_count=3,
        )
        assert item.instance_count == 3
```

- [ ] **Step 4: Run schema tests**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_schemas.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add middleware/app/schemas/instance.py middleware/app/schemas/tenant.py \
        middleware/app/schemas/logs.py middleware/tests/test_schemas.py
git commit -m "feat: add AdminInstanceResponse, TenantListItem, LogsResponse schemas"
```

---

### Task 3: Add log buffer module + wire into main.py

**Files:**
- Create: `middleware/app/log_buffer.py`
- Modify: `middleware/app/main.py`

- [ ] **Step 1: Create `middleware/app/log_buffer.py`**

```python
"""Shared in-memory log buffer for /api/logs endpoint.

Kept in its own module to avoid circular imports between main.py and routes/logs.py.
"""
import json

_log_seq: int = 0
_log_buffer: list[tuple[int, str]] = []   # (seq, json_str), append-only, capped at 1000
_LOG_BUFFER_MAX = 1000


def buffer_log_processor(logger, method, event_dict: dict) -> dict:
    """Structlog processor: capture each log entry into the in-memory ring buffer."""
    global _log_seq
    _log_seq += 1
    _log_buffer.append((_log_seq, json.dumps(event_dict, default=str)))
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        del _log_buffer[:-_LOG_BUFFER_MAX]
    return event_dict   # pass through unchanged
```

- [ ] **Step 2: Import and wire into `main.py`**

Add this import at the top of `middleware/app/main.py` (with other imports):

```python
from app.log_buffer import buffer_log_processor
```

Then find the `shared_processors` list in `main.py` and add `buffer_log_processor` after `format_exc_info`:

```python
shared_processors = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    buffer_log_processor,   # ← add this line
]
```

- [ ] **Step 3: Verify app still starts cleanly**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestHealthRoute -v
```
Expected: all pass (log buffer doesn't affect app behaviour).

- [ ] **Step 4: Commit**

```bash
git add middleware/app/log_buffer.py middleware/app/main.py
git commit -m "feat: add in-memory log buffer and BufferProcessor to structlog chain"
```

---

## Chunk 2: Admin Instance Endpoints + Health Update

### Task 4: Admin instance service function

**Files:**
- Modify: `middleware/app/services/instances.py`

- [ ] **Step 1: Write failing test**

Add to `middleware/tests/test_routes.py` in a new class `TestAdminInstanceRoutes`:

```python
class TestAdminInstanceRoutes:
    PREFIX = "/api/admin/instances"

    async def test_list_all_instances(self, client, admin_headers):
        """GET /api/admin/instances returns all instances with tenant info."""
        resp = await client.get(self.PREFIX, headers=admin_headers)
        # DB is empty in unit tests — just verify auth works and shape is right
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_instances_requires_admin_key(self, client, tenant_headers):
        resp = await client.get(self.PREFIX, headers=tenant_headers)
        assert resp.status_code == 403

    async def test_list_instances_no_auth_returns_error(self, client):
        resp = await client.get(self.PREFIX)
        assert resp.status_code in (403, 422)
```

- [ ] **Step 2: Run — expect 404 (route doesn't exist yet)**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestAdminInstanceRoutes::test_list_all_instances -v
```
Expected: FAIL with 404 or connection error.

- [ ] **Step 3: Add `get_all_instances_admin` to instances service**

At the top of `middleware/app/services/instances.py`, add these imports (merge with existing):

```python
from datetime import datetime
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from sqlalchemy import func
```

Then append the function at the bottom of `middleware/app/services/instances.py`:

```python
async def get_all_instances_admin(
    db: AsyncSession, tenant_slug: str | None = None
) -> list[tuple[Instance, Tenant, datetime | None]]:
    """List all instances across all tenants with last webhook event time.

    Join key: WebhookEvent.instance == Instance.instance_name (both store full prefixed name).
    Returns list of (Instance, Tenant, last_event_at) tuples.
    """
    from app.models.tenant import Tenant as TenantModel
    from app.models.webhook_event import WebhookEvent as WH

    last_event_sub = (
        select(func.max(WebhookEvent.created_at))
        .where(WebhookEvent.instance == Instance.instance_name)
        .correlate(Instance)
        .scalar_subquery()
    )

    query = (
        select(Instance, TenantModel, last_event_sub.label("last_event_at"))
        .join(TenantModel, Instance.tenant_id == TenantModel.id)
        .where(TenantModel.is_active == True)  # noqa: E712
        .order_by(TenantModel.slug, Instance.instance_name)
    )

    if tenant_slug:
        query = query.where(TenantModel.slug == tenant_slug)

    result = await db.execute(query)
    return [(row.Instance, row.Tenant, row.last_event_at) for row in result.all()]
```

- [ ] **Step 4: Create admin instances route file**

Create `middleware/app/routes/admin_instances.py`:

```python
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
```

- [ ] **Step 5: Register router in main.py**

In `middleware/app/main.py`, add:

```python
from app.routes import admin_instances   # add with other route imports
```

And in the routes section:

```python
app.include_router(admin_instances.router)
```

- [ ] **Step 6: Run tests**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestAdminInstanceRoutes -v
```
Expected: all 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add middleware/app/services/instances.py middleware/app/routes/admin_instances.py \
        middleware/app/main.py middleware/tests/test_routes.py
git commit -m "feat: add admin instance endpoints (list, create, restart, delete, logout, send)"
```

---

### Task 5: Update tenant list + health endpoints

**Files:**
- Modify: `middleware/app/routes/tenants.py`
- Modify: `middleware/app/routes/health.py`

- [ ] **Step 1: Write failing tests**

Add to `TestAdminInstanceRoutes` (or a new class `TestTenantListUpdate`):

```python
class TestTenantListUpdate:
    async def test_list_tenants_includes_instance_count(self, client, admin_headers):
        """GET /api/admin/tenants returns instance_count per tenant."""
        resp = await client.get("/api/admin/tenants", headers=admin_headers)
        assert resp.status_code == 200
        for item in resp.json():
            assert "instance_count" in item

    async def test_health_includes_instances_total(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "instances" in body
        assert "total" in body["instances"]
```

- [ ] **Step 2: Run — expect fail**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestTenantListUpdate -v
```
Expected: FAIL (missing fields).

- [ ] **Step 3: Update `list_tenants_endpoint` in tenants.py**

First, add these module-level imports at the top of `middleware/app/routes/tenants.py` (merge with existing imports):

```python
from sqlalchemy import func, select
from app.models.instance import Instance
from app.schemas.tenant import TenantListItem   # add to existing tenant schema imports
```

Then replace the `list_tenants_endpoint` function:

```python
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
```

Also add `TenantListItem` to the import from `app.schemas.tenant`.

- [ ] **Step 4: Update health endpoint to include `instances.total`**

In `middleware/app/routes/health.py`, inside the `try` block after the `active_tenants` query, add:

```python
from app.models.instance import Instance

# Instance count
total_instances = (await session.execute(
    select(func.count()).select_from(Instance)
)).scalar() or 0
```

And update the result dict to include:

```python
result["instances"] = {"total": total_instances}
```

Also update the `status` logic — add `"error"` case: if DB is disconnected AND Evolution is unreachable, set `status = "error"`. Current logic sets `"degraded"` on DB down. Add after Evolution check:

```python
if result.get("database", {}).get("status") == "disconnected" and \
   result.get("evolution_api", {}).get("status") == "unreachable":
    result["status"] = "error"
```

- [ ] **Step 5: Fix pre-existing broken TestHealthRoute assertions, then run tests**

The existing `TestHealthRoute` tests assert `body["database"] == "connected"` (a string), but the endpoint already returns `body["database"]["status"] == "connected"` (a dict). Fix them in `middleware/tests/test_routes.py` before running. Find lines like:

```python
assert body["database"] == "connected"
```

Replace with:

```python
assert body["database"]["status"] == "connected"
```

Similarly, if any assertion checks `body["database"] == "disconnected"`, change it to `body["database"]["status"] == "disconnected"`.

After fixing, run:

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestTenantListUpdate tests/test_routes.py::TestHealthRoute -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add middleware/app/routes/tenants.py middleware/app/routes/health.py \
        middleware/tests/test_routes.py
git commit -m "feat: add instance_count to tenant list, instances.total to health endpoint"
```

---

## Chunk 3: /api/logs Endpoint

### Task 6: Create /api/logs route

**Files:**
- Create: `middleware/app/routes/logs.py`
- Modify: `middleware/app/main.py`

- [ ] **Step 1: Write failing test**

Add to `middleware/tests/test_routes.py`:

```python
class TestLogsRoute:
    async def test_logs_no_follow_returns_json(self, client, admin_headers):
        resp = await client.get("/api/logs?lines=10", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "lines" in body
        assert isinstance(body["lines"], list)

    async def test_logs_requires_admin_key(self, client):
        resp = await client.get("/api/logs")
        assert resp.status_code in (403, 422)

    async def test_logs_wrong_key_returns_403(self, client):
        resp = await client.get("/api/logs", headers={"X-API-Key": "bad"})
        assert resp.status_code == 403
```

- [ ] **Step 2: Run — expect 404**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestLogsRoute -v
```

- [ ] **Step 3: Create `middleware/app/routes/logs.py`**

```python
import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.dependencies import AdminKeyDep
from app.log_buffer import _log_buffer, _LOG_BUFFER_MAX   # import from log_buffer, NOT main
from app.schemas.logs import LogsResponse

router = APIRouter(prefix="/api", dependencies=[AdminKeyDep])


@router.get("/logs", response_model=None)
async def get_logs(
    lines: int = Query(default=100, ge=1, le=_LOG_BUFFER_MAX),
    follow: bool = Query(default=False),
):
    """Stream or snapshot middleware logs.

    - follow=false: returns last `lines` entries as JSON
    - follow=true: SSE stream, flushes history then tails new entries
    """
    if not follow:
        recent = _log_buffer[-lines:] if _log_buffer else []
        return LogsResponse(lines=[line for _, line in recent])

    async def event_stream():
        last_seq = 0
        # Flush history
        recent = _log_buffer[-lines:] if _log_buffer else []
        for seq, line in recent:
            last_seq = max(last_seq, seq)
            yield f"data: {line}\n\n"
        # Tail new entries
        while True:
            new = [(s, l) for s, l in _log_buffer if s > last_seq]
            for seq, line in new:
                last_seq = seq
                yield f"data: {line}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Note:** `logs.py` imports from `app.log_buffer` (created in Task 3) — no circular import. The buffer and processor both live in `log_buffer.py`; `main.py` imports and wires the processor; `logs.py` reads the buffer directly.

- [ ] **Step 4: Register logs router in main.py**

```python
from app.routes import logs as logs_router   # add with other imports
# ...
app.include_router(logs_router.router)
```

- [ ] **Step 5: Run tests**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/test_routes.py::TestLogsRoute -v
```
Expected: all 3 pass.

- [ ] **Step 6: Commit**

```bash
git add middleware/app/log_buffer.py middleware/app/routes/logs.py \
        middleware/app/main.py middleware/tests/test_routes.py
git commit -m "feat: add /api/logs endpoint with SSE streaming and in-memory ring buffer"
```

- [ ] **Step 7: Rebuild Docker and verify health**

```bash
cd /home/adroc/dev/adroc_whatsapp_server
docker compose up -d --build middleware
sleep 8
curl -s http://localhost:8000/api/health | python3 -m json.tool
curl -s -H "X-API-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)" \
     "http://localhost:8000/api/logs?lines=5"
```
Expected: health returns 200, logs returns `{"lines": [...]}`.

- [ ] **Step 8: Commit docker rebuild**

```bash
git add middleware/
git commit -m "feat: complete middleware admin API — all new endpoints ready"
```

---

## Chunk 4: TUI — App Shell + Dashboard

### Task 7: Scaffold manage.py — config loading, API client, error screen

**Files:**
- Create (replaces): `scripts/manage.py`

- [ ] **Step 1: Install TUI dependencies**

```bash
pip install textual python-dotenv
```

Verify:

```bash
python -c "import textual; print(textual.__version__)"
```

- [ ] **Step 2: Write the config loading and API client skeleton**

Replace `scripts/manage.py` entirely:

```python
#!/usr/bin/env python3
"""Adroc WhatsApp Server — Interactive TUI Manager.

Usage:
    python scripts/manage.py
    MIDDLEWARE_URL=http://server:8000 ADMIN_API_KEY=xxx python scripts/manage.py

Config loaded from (in order): env vars → .env in current directory.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env from current working directory before reading env vars
load_dotenv(Path.cwd() / ".env")

MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8000").rstrip("/")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class ApiClient:
    def __init__(self, base_url: str, admin_key: str) -> None:
        self.base_url = base_url
        self._headers = {"X-API-Key": admin_key, "Content-Type": "application/json"}

    def _raise(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ApiError(resp.status_code, str(detail))

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/health")
            self._raise(r)
            return r.json()

    async def list_tenants(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/tenants", headers=self._headers)
            self._raise(r)
            return r.json()

    async def create_tenant(self, slug: str, display_name: str,
                            odoo_url: str, odoo_key: str, max_instances: int) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/tenants", headers=self._headers,
                             json={"slug": slug, "display_name": display_name,
                                   "odoo_webhook_url": odoo_url, "odoo_api_key": odoo_key,
                                   "max_instances": max_instances})
            self._raise(r)
            return r.json()

    async def get_tenant(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/tenants/{slug}", headers=self._headers)
            self._raise(r)
            return r.json()

    async def update_tenant(self, slug: str, **kwargs: Any) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.patch(f"{self.base_url}/api/admin/tenants/{slug}",
                              headers=self._headers, json=kwargs)
            self._raise(r)
            return r.json()

    async def deactivate_tenant(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/tenants/{slug}", headers=self._headers)
            self._raise(r)
            return r.json()

    async def rotate_key(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/tenants/{slug}/rotate-key",
                             headers=self._headers)
            self._raise(r)
            return r.json()

    async def list_instances(self, tenant: str | None = None) -> list[dict]:
        params = {"tenant": tenant} if tenant else {}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/instances",
                            headers=self._headers, params=params)
            self._raise(r)
            return r.json()

    async def create_instance(self, tenant_slug: str, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/instances", headers=self._headers,
                             json={"tenant_slug": tenant_slug, "instance_name": instance_name})
            self._raise(r)
            return r.json()

    async def restart_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.put(f"{self.base_url}/api/admin/instances/{evo_name}/restart",
                            headers=self._headers)
            self._raise(r)
            return r.json()

    async def delete_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/instances/{evo_name}",
                               headers=self._headers)
            self._raise(r)
            return r.json()

    async def logout_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/instances/{evo_name}/logout",
                               headers=self._headers)
            self._raise(r)
            return r.json()

    async def send_message(self, evo_name: str, number: str, text: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/instances/{evo_name}/send",
                             headers=self._headers, json={"number": number, "text": text})
            self._raise(r)
            return r.json()


# ---------------------------------------------------------------------------
# Entry point (TUI classes added in subsequent tasks)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not ADMIN_API_KEY:
        print("ERROR: ADMIN_API_KEY not set.")
        print("  Set it in your shell:  export ADMIN_API_KEY=<key>")
        print("  Or add it to .env:     echo 'ADMIN_API_KEY=<key>' >> .env")
        raise SystemExit(1)
    print("API client ready — TUI coming in next task")
```

- [ ] **Step 3: Verify the script runs and fails gracefully without key**

```bash
cd /home/adroc/dev/adroc_whatsapp_server
ADMIN_API_KEY="" python scripts/manage.py
```
Expected: prints error message and exits 1.

- [ ] **Step 4: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: scaffold manage.py — config loading and API client"
```

---

### Task 8: TUI app shell with sidebar

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Add Textual imports and CSS constant**

Add after the existing imports in `scripts/manage.py`:

```python
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, ContentSwitcher, DataTable, Footer, Input,
    Label, Log, Select, Static, TextArea,
)

ADROC_CSS = """
Screen {
    layout: horizontal;
}
#sidebar {
    width: 20;
    background: $panel;
    border-right: tall $primary;
    padding: 1 1;
}
.nav-item {
    width: 1fr;
    height: 2;
    background: transparent;
    border: none;
    color: $text-muted;
    text-align: left;
    padding: 0 1;
}
.nav-item:hover {
    background: $boost;
    color: $text;
}
.nav-item.active {
    background: $primary 20%;
    border-left: outer $primary;
    color: $text;
}
#sidebar-status {
    color: $success;
    text-style: bold;
    padding: 0 1;
}
#content {
    width: 1fr;
    height: 1fr;
}
ContentSwitcher {
    width: 1fr;
    height: 1fr;
}
/* Status cards */
.status-card {
    width: 1fr;
    height: 7;
    border: round $primary;
    padding: 1;
    margin: 0 1;
}
.card-ok { border: round $success; }
.card-warn { border: round $warning; }
.card-err { border: round $error; }
.card-value { text-style: bold; font-size: 4; }
.card-label { color: $text-muted; }
/* Tables */
DataTable { height: 1fr; }
/* Modals */
ConfirmModal > Container {
    width: 60;
    height: auto;
    background: $surface;
    border: round $primary;
    padding: 2 4;
}
FormModal > Container {
    width: 70;
    height: auto;
    background: $surface;
    border: round $primary;
    padding: 2 4;
}
.form-row { height: 3; margin-bottom: 1; }
.form-label { width: 20; color: $text-muted; }
.error-banner {
    background: $error 30%;
    color: $error;
    padding: 0 2;
    height: 1;
}
.success-banner {
    background: $success 30%;
    color: $success;
    padding: 0 2;
    height: 1;
}
"""
```

- [ ] **Step 2: Add Sidebar widget**

```python
class Sidebar(Vertical):
    """Fixed left navigation sidebar."""

    active: reactive[str] = reactive("dashboard")

    SCREENS = [
        ("dashboard",  "📊", "Dashboard",  "1"),
        ("tenants",    "🏢", "Tenants",    "2"),
        ("instances",  "📱", "Instancias", "3"),
        ("logs",       "📋", "Logs",       "4"),
        ("send",       "💬", "Test Msg",   "5"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("⚡ Adroc WA", id="sidebar-title")
        yield Label("─" * 16)
        for screen_id, icon, label, key in self.SCREENS:
            yield Button(
                f"{icon} {label}  [{key}]",
                id=f"nav-{screen_id}",
                classes="nav-item" + (" active" if screen_id == "dashboard" else ""),
            )
        yield Label("─" * 16)
        yield Label("● connecting...", id="sidebar-status")

    def watch_active(self, new_id: str) -> None:
        for screen_id, _, _, _ in self.SCREENS:
            btn = self.query_one(f"#nav-{screen_id}", Button)
            if screen_id == new_id:
                btn.add_class("active")
            else:
                btn.remove_class("active")

    def set_status(self, text: str, ok: bool = True) -> None:
        label = self.query_one("#sidebar-status", Label)
        color = "green" if ok else "red"
        label.update(f"[{color}]●[/{color}] {text}")
```

- [ ] **Step 3: Add ConfirmModal**

```python
class ConfirmModal(ModalScreen[bool]):
    """Generic destructive action confirmation."""

    def __init__(self, message: str, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self._message, id="confirm-msg")
            yield Label("")
            with Horizontal():
                yield Button(self._confirm_label, variant="error", id="btn-confirm")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-confirm")
    def do_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)
```

- [ ] **Step 4: Add main App class with ContentSwitcher (placeholder views)**

```python
class DashboardView(Vertical):
    """Placeholder — replaced in Task 9."""
    def compose(self) -> ComposeResult:
        yield Label("Dashboard loading...")

class TenantsView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Tenants loading...")

class InstancesView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Instances loading...")

class LogsView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Logs loading...")

class SendMessageView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Send Message loading...")


class AdroCApp(App[None]):
    CSS = ADROC_CSS
    TITLE = "Adroc WhatsApp Manager"
    BINDINGS = [
        Binding("1", "show('dashboard')", "Dashboard", show=False),
        Binding("2", "show('tenants')", "Tenants", show=False),
        Binding("3", "show('instances')", "Instances", show=False),
        Binding("4", "show('logs')", "Logs", show=False),
        Binding("5", "show('send')", "Send Msg", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api

    def compose(self) -> ComposeResult:
        yield Sidebar(id="sidebar")
        with Container(id="content"):
            yield ContentSwitcher(
                DashboardView(id="dashboard"),
                TenantsView(id="tenants"),
                InstancesView(id="instances"),
                LogsView(id="logs"),
                SendMessageView(id="send"),
                initial="dashboard",
            )

    def action_show(self, screen_id: str) -> None:
        self.query_one(ContentSwitcher).current = screen_id
        self.query_one(Sidebar).active = screen_id

    def action_refresh(self) -> None:
        current = self.query_one(ContentSwitcher).current
        # Each view handles its own refresh via on_show or explicit method
        view = self.query_one(f"#{current}")
        if hasattr(view, "refresh_data"):
            view.refresh_data()


# Replace the entry point at the bottom:
if __name__ == "__main__":
    if not ADMIN_API_KEY:
        print("ERROR: ADMIN_API_KEY not set.")
        print("  Set it in your shell:  export ADMIN_API_KEY=<key>")
        print("  Or add it to .env:     echo 'ADMIN_API_KEY=<key>' >> .env")
        raise SystemExit(1)

    api = ApiClient(MIDDLEWARE_URL, ADMIN_API_KEY)
    AdroCApp(api).run()
```

- [ ] **Step 5: Test app launches**

```bash
cd /home/adroc/dev/adroc_whatsapp_server
python scripts/manage.py
```
Expected: TUI opens, sidebar visible, pressing 1-5 switches placeholder views, Q quits.

- [ ] **Step 6: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI app shell — sidebar, ContentSwitcher, ConfirmModal, keybindings"
```

---

### Task 9: Dashboard screen

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Replace `DashboardView` with full implementation**

```python
class StatusCard(Vertical):
    """A colored card showing a single metric."""

    def __init__(self, card_id: str, label: str) -> None:
        super().__init__(id=f"card-{card_id}", classes="status-card")
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label("…", classes="card-value", id=f"val-{self.id}")
        yield Label(self._label, classes="card-label")

    def update(self, value: str, state: str = "ok") -> None:
        self.query_one(f"#val-{self.id}", Label).update(value)
        for cls in ("card-ok", "card-warn", "card-err"):
            self.remove_class(cls)
        self.add_class({"ok": "card-ok", "warn": "card-warn", "err": "card-err"}[state])


class DashboardView(Vertical):
    BORDER_TITLE = "Dashboard"

    def compose(self) -> ComposeResult:
        with Horizontal(id="cards-row"):
            yield StatusCard("middleware", "Middleware")
            yield StatusCard("evolution", "Evolution API")
            yield StatusCard("db", "Database")
            yield StatusCard("tenants", "Tenants activos")
            yield StatusCard("instances", "Instancias totales")
            yield StatusCard("queue", "Cola Odoo")
        yield Label("TENANTS", id="tenants-title")
        yield DataTable(id="dash-tenant-table", cursor_type="none")
        yield Label("", id="last-refresh")

    def on_mount(self) -> None:
        table = self.query_one("#dash-tenant-table", DataTable)
        table.add_columns("TENANT", "NOMBRE", "INST", "MAX", "ESTADO")
        self.refresh_data()
        self.set_interval(30, self.refresh_data)

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            health = await self.app.api.health()
            tenants = await self.app.api.list_tenants()
        except Exception as e:
            self.app.query_one(Sidebar).set_status("error", ok=False)
            return

        # Update cards
        status = health.get("status", "error")
        self._update_card("middleware", status.upper(),
                          "ok" if status == "ok" else "warn" if status == "degraded" else "err")

        evo = health.get("evolution_api", {}).get("status", "unreachable")
        self._update_card("evolution", evo, "ok" if evo == "reachable" else "err")

        db = health.get("database", {}).get("status", "disconnected")
        self._update_card("db", db, "ok" if db == "connected" else "err")

        active_t = health.get("tenants", {}).get("active", 0)
        self._update_card("tenants", str(active_t), "ok" if active_t > 0 else "err")

        total_i = health.get("instances", {}).get("total", 0)
        self._update_card("instances", str(total_i), "ok")

        queue = health.get("workers", {}).get("queue_size", 0)
        q_state = "ok" if queue == 0 else "warn" if queue <= 50 else "err"
        self._update_card("queue", str(queue), q_state)

        # Update sidebar status
        self.app.query_one(Sidebar).set_status(
            f"{MIDDLEWARE_URL.split('//')[1]}", ok=(status == "ok")
        )

        # Update tenant table
        table = self.query_one("#dash-tenant-table", DataTable)
        table.clear()
        for t in tenants:
            state_icon = "✓" if t.get("is_active") else "✗"
            table.add_row(
                t["slug"],
                t["display_name"],
                str(t.get("instance_count", 0)),
                str(t.get("max_instances", "?")),
                state_icon,
            )

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.query_one("#last-refresh", Label).update(f"Refreshed: {ts}  [dim](R to force)[/dim]")

    def _update_card(self, card_id: str, value: str, state: str) -> None:
        self.query_one(f"#card-{card_id}", StatusCard).update(value, state)
```

- [ ] **Step 2: Test dashboard**

```bash
python scripts/manage.py
```
Expected: Dashboard shows 6 cards with real data (green), tenant table populated.

- [ ] **Step 3: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI Dashboard screen — status cards, tenant table, auto-refresh"
```

---

## Chunk 5: TUI — Tenants + Instances Screens

### Task 10: Tenants screen

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Replace `TenantsView` with full implementation**

```python
class TenantDetailPanel(Vertical):
    """Right panel showing selected tenant details and actions."""

    def compose(self) -> ComposeResult:
        yield Label("Select a tenant", id="detail-title")
        yield Label("", id="detail-slug")
        yield Label("", id="detail-name")
        yield Label("", id="detail-url")
        yield Label("", id="detail-instances")
        yield Label("", id="detail-created")
        yield Label("")
        yield Button("📱 Ver instancias", id="btn-view-instances", disabled=True)
        yield Button("✏️  Editar",         id="btn-edit",          disabled=True)
        yield Button("🔑 Rotar API key",   id="btn-rotate",        disabled=True)
        yield Button("⛔ Desactivar",      id="btn-deactivate",    variant="error", disabled=True)

    def show_tenant(self, t: dict) -> None:
        self.query_one("#detail-title", Label).update(f"[bold]{t['slug']}[/bold]")
        self.query_one("#detail-slug", Label).update(f"Slug: {t['slug']}")
        self.query_one("#detail-name", Label).update(f"Nombre: {t['display_name']}")
        url = t.get("odoo_webhook_url", "")
        self.query_one("#detail-url", Label).update(f"URL: [link]{url[:40]}[/link]")
        cnt = t.get("instance_count", "?")
        mx = t.get("max_instances", "?")
        self.query_one("#detail-instances", Label).update(f"Instancias: {cnt}/{mx}")
        created = t.get("created_at", "")[:10]
        self.query_one("#detail-created", Label).update(f"Creado: {created}")
        for btn_id in ("btn-view-instances", "btn-edit", "btn-rotate", "btn-deactivate"):
            self.query_one(f"#{btn_id}", Button).disabled = False

    def clear(self) -> None:
        self.query_one("#detail-title", Label).update("Select a tenant")
        for btn_id in ("btn-view-instances", "btn-edit", "btn-rotate", "btn-deactivate"):
            self.query_one(f"#{btn_id}", Button).disabled = True


class TenantsView(Horizontal):
    BORDER_TITLE = "Tenants"

    _selected_tenant: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="tenant-left"):
            with Horizontal(id="tenant-toolbar"):
                yield Label("Tenants", id="tenant-count")
                yield Button("+ Nuevo", id="btn-new-tenant", variant="primary")
            yield DataTable(id="tenant-table", cursor_type="row")
            yield Label("/ para buscar  N nuevo  E editar  K rotar key  D desactivar",
                        id="tenant-hint")
        yield TenantDetailPanel(id="tenant-detail")

    def on_mount(self) -> None:
        table = self.query_one("#tenant-table", DataTable)
        table.add_columns("SLUG", "NOMBRE", "INST", "ESTADO")
        self.refresh_data()

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            tenants = await self.app.api.list_tenants()
        except ApiError as e:
            self.notify(f"Error: {e.detail}", severity="error")
            return
        self._tenants = tenants
        table = self.query_one("#tenant-table", DataTable)
        table.clear()
        for t in tenants:
            state = "✓ activo" if t.get("is_active") else "✗ inactivo"
            cnt = t.get("instance_count", 0)
            mx = t.get("max_instances", "?")
            table.add_row(t["slug"], t["display_name"], f"{cnt}/{mx}", state,
                          key=t["slug"])
        self.query_one("#tenant-count", Label).update(f"{len(tenants)} tenants")

    @on(DataTable.RowSelected, "#tenant-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        slug = str(event.row_key.value)
        self._selected_tenant = next((t for t in self._tenants if t["slug"] == slug), None)
        if self._selected_tenant:
            self.query_one(TenantDetailPanel).show_tenant(self._selected_tenant)

    @on(Button.Pressed, "#btn-new-tenant")
    async def new_tenant(self) -> None:
        result = await self.app.push_screen_wait(CreateTenantModal())
        if result:
            try:
                data = await self.app.api.create_tenant(**result)
                api_key = data.get("api_key", "")
                self.notify(f"Tenant creado. API KEY: {api_key}", severity="information",
                            timeout=30)
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-view-instances")
    def view_instances(self) -> None:
        if self._selected_tenant:
            self.app.action_show("instances")
            # Pass filter to instances view — see InstancesView.filter_by_tenant
            inst_view = self.app.query_one(InstancesView)
            inst_view.filter_slug = self._selected_tenant["slug"]

    @on(Button.Pressed, "#btn-edit")
    async def edit_tenant(self) -> None:
        if not self._selected_tenant:
            return
        result = await self.app.push_screen_wait(EditTenantModal(self._selected_tenant))
        if result:
            try:
                await self.app.api.update_tenant(self._selected_tenant["slug"], **result)
                self.notify("Tenant actualizado.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-rotate")
    async def rotate_key(self) -> None:
        if not self._selected_tenant:
            return
        slug = self._selected_tenant["slug"]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Rotar API key de '{slug}'?\nLa clave actual quedará inválida.")
        )
        if confirmed:
            try:
                data = await self.app.api.rotate_key(slug)
                new_key = data.get("api_key", "")
                self.notify(f"Nueva API KEY: {new_key}", severity="information", timeout=60)
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-deactivate")
    async def deactivate_tenant(self) -> None:
        if not self._selected_tenant:
            return
        slug = self._selected_tenant["slug"]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Desactivar tenant '{slug}'?", confirm_label="Desactivar")
        )
        if confirmed:
            try:
                await self.app.api.deactivate_tenant(slug)
                self.notify(f"Tenant '{slug}' desactivado.", severity="warning")
                self.query_one(TenantDetailPanel).clear()
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")
```

- [ ] **Step 2: Add Create/Edit tenant modals**

```python
class CreateTenantModal(ModalScreen[dict | None]):
    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nuevo Tenant", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Slug:", classes="form-label")
                yield Input(placeholder="acme", id="f-slug")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(placeholder="Acme Corp", id="f-name")
            with Horizontal(classes="form-row"):
                yield Label("Odoo URL:", classes="form-label")
                yield Input(placeholder="https://acme.odoo.com/whatsapp/webhook", id="f-url")
            with Horizontal(classes="form-row"):
                yield Label("Odoo API key:", classes="form-label")
                yield Input(placeholder="secret", id="f-key", password=True)
            with Horizontal(classes="form-row"):
                yield Label("Max instancias:", classes="form-label")
                yield Input(value="10", id="f-max")
            yield Label("")
            with Horizontal():
                yield Button("Crear", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        slug = self.query_one("#f-slug", Input).value.strip()
        name = self.query_one("#f-name", Input).value.strip()
        url  = self.query_one("#f-url", Input).value.strip()
        key  = self.query_one("#f-key", Input).value.strip()
        try:
            max_inst = int(self.query_one("#f-max", Input).value.strip() or "10")
        except ValueError:
            max_inst = 10
        if not all([slug, name, url, key]):
            self.notify("Todos los campos son requeridos.", severity="error")
            return
        self.dismiss({"slug": slug, "display_name": name, "odoo_url": url,
                      "odoo_key": key, "max_instances": max_inst})

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class EditTenantModal(ModalScreen[dict | None]):
    def __init__(self, tenant: dict) -> None:
        super().__init__()
        self._tenant = tenant

    def compose(self) -> ComposeResult:
        t = self._tenant
        with Container():
            yield Label(f"Editar: {t['slug']}", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(value=t.get("display_name", ""), id="f-name")
            with Horizontal(classes="form-row"):
                yield Label("Odoo URL:", classes="form-label")
                yield Input(value=t.get("odoo_webhook_url", ""), id="f-url")
            with Horizontal(classes="form-row"):
                yield Label("Odoo API key:", classes="form-label")
                yield Input(placeholder="(leave blank to keep)", id="f-key", password=True)
            with Horizontal(classes="form-row"):
                yield Label("Max instancias:", classes="form-label")
                yield Input(value=str(t.get("max_instances", 10)), id="f-max")
            yield Label("")
            with Horizontal():
                yield Button("Guardar", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        updates: dict = {}
        name = self.query_one("#f-name", Input).value.strip()
        if name:
            updates["display_name"] = name
        url = self.query_one("#f-url", Input).value.strip()
        if url:
            updates["odoo_webhook_url"] = url
        key = self.query_one("#f-key", Input).value.strip()
        if key:
            updates["odoo_api_key"] = key
        max_val = self.query_one("#f-max", Input).value.strip()
        try:
            updates["max_instances"] = int(max_val)
        except ValueError:
            pass
        self.dismiss(updates if updates else None)

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
```

- [ ] **Step 3: Test tenants screen**

```bash
python scripts/manage.py
```
Press `2`. Expected: tenant table loads, selecting a row shows detail panel, N opens create modal, buttons work.

- [ ] **Step 4: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI Tenants screen — table, detail panel, create/edit/rotate/deactivate"
```

---

### Task 11: Instances screen

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Replace `InstancesView` with full implementation**

```python
def _state_display(state: str) -> str:
    icons = {"open": "[green]● open[/green]", "connecting": "[yellow]◉ connecting[/yellow]"}
    return icons.get(state, f"[red]○ {state}[/red]")


def _rel_time(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return dt_str[:16]


class CreateInstanceModal(ModalScreen[dict | None]):
    def __init__(self, tenant_options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._options = tenant_options

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nueva Instancia", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Tenant:", classes="form-label")
                yield Select(self._options, id="f-tenant")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(placeholder="ventas", id="f-name")
            yield Label("")
            with Horizontal():
                yield Button("Crear", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        tenant_slug = self.query_one("#f-tenant", Select).value
        name = self.query_one("#f-name", Input).value.strip()
        if not tenant_slug or not name:
            self.notify("Tenant y nombre son requeridos.", severity="error")
            return
        self.dismiss({"tenant_slug": str(tenant_slug), "instance_name": name})

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class InstancesView(Vertical):
    BORDER_TITLE = "Instancias"

    filter_slug: reactive[str | None] = reactive(None)
    _instances: list[dict] = []
    _tenants: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="inst-toolbar"):
            yield Label("Tenant:", id="inst-filter-label")
            yield Select([("— Todos —", "")], id="inst-filter", value="")
            yield Label("", id="inst-count")
            yield Button("+ Nueva", id="btn-new-inst", variant="primary")
        yield DataTable(id="inst-table", cursor_type="row")
        yield Label(
            "N nueva  R restart  L logout  Del eliminar  X exportar  / buscar",
            id="inst-hint"
        )

    def on_mount(self) -> None:
        table = self.query_one("#inst-table", DataTable)
        table.add_columns("INSTANCIA", "ESTADO", "TELÉFONO", "TENANT", "ÚLTIMO WEBHOOK")
        self.refresh_data()

    def watch_filter_slug(self, slug: str | None) -> None:
        sel = self.query_one("#inst-filter", Select)
        sel.value = slug or ""

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            tenant_filter = self.query_one("#inst-filter", Select).value or None
            self._instances = await self.app.api.list_instances(tenant=tenant_filter or None)
            self._tenants = await self.app.api.list_tenants()
        except ApiError as e:
            self.notify(f"Error: {e.detail}", severity="error")
            return

        # Update filter dropdown
        sel = self.query_one("#inst-filter", Select)
        options: list[tuple[str, str]] = [("— Todos —", "")]
        options += [(t["display_name"], t["slug"]) for t in self._tenants]
        sel.set_options(options)

        # Update table
        table = self.query_one("#inst-table", DataTable)
        table.clear()
        for inst in self._instances:
            table.add_row(
                inst["instance_name"],
                _state_display(inst.get("state", "unknown")),
                inst.get("phone_number") or "—",
                inst.get("tenant_slug", ""),
                _rel_time(inst.get("last_event_at")),
                key=inst["evolution_name"],
            )
        self.query_one("#inst-count", Label).update(f"{len(self._instances)} instancias")

    @on(Select.Changed, "#inst-filter")
    def filter_changed(self, event: Select.Changed) -> None:
        self.refresh_data()

    def _selected_inst(self) -> dict | None:
        table = self.query_one("#inst-table", DataTable)
        if table.cursor_row < 0:
            return None
        evo_name = str(table.get_row_at(table.cursor_row)[0])  # uses evolution_name as key
        row_key = table.get_row_at(table.cursor_row)
        # Use row key instead
        cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        evo_name = str(cursor_key.row_key.value)
        return next((i for i in self._instances if i["evolution_name"] == evo_name), None)

    @on(Button.Pressed, "#btn-new-inst")
    async def new_instance(self) -> None:
        if not self._tenants:
            self.notify("No hay tenants disponibles.", severity="error")
            return
        options = [(t["display_name"], t["slug"]) for t in self._tenants]
        result = await self.app.push_screen_wait(CreateInstanceModal(options))
        if result:
            try:
                await self.app.api.create_instance(**result)
                self.notify("Instancia creada.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    def on_key(self, event) -> None:
        key = event.key
        if key == "r":
            self.app.call_later(self._restart_selected)
        elif key == "l":
            self.app.call_later(self._logout_selected)
        elif key == "delete":
            self.app.call_later(self._delete_selected)
        elif key == "x":
            self.app.call_later(self._export)

    async def _restart_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Restart '{inst['instance_name']}'?")
        )
        if confirmed:
            try:
                await self.app.api.restart_instance(inst["evolution_name"])
                self.notify("Instancia reiniciada.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    async def _logout_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Logout '{inst['instance_name']}'?", confirm_label="Logout")
        )
        if confirmed:
            try:
                await self.app.api.logout_instance(inst["evolution_name"])
                self.notify("Instancia desconectada.", severity="warning")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    async def _delete_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"ELIMINAR '{inst['instance_name']}'?", confirm_label="ELIMINAR")
        )
        if confirmed:
            try:
                await self.app.api.delete_instance(inst["evolution_name"])
                self.notify("Instancia eliminada.", severity="warning")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    async def _export(self) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = Path.cwd() / f"instances-export-{ts}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "instance_name", "evolution_name", "tenant_slug",
                "state", "phone_number", "last_event_at"
            ])
            w.writeheader()
            w.writerows(self._instances)
        self.notify(f"Exportado: {path.name}", severity="information")
```

- [ ] **Step 2: Test instances screen**

```bash
python scripts/manage.py
```
Press `3`. Expected: instances table with filter dropdown, all keyboard shortcuts work.

- [ ] **Step 3: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI Instances screen — filter, table, create/restart/logout/delete/export"
```

---

## Chunk 6: TUI — Logs + Test Message + Help

### Task 12: Logs screen

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Replace `LogsView`**

```python
class LogsView(Vertical):
    BORDER_TITLE = "Logs"
    BINDINGS = [
        Binding("f", "toggle_format", "Toggle JSON/Pretty", show=False),
        Binding("space", "toggle_pause", "Pause/Resume", show=False),
        Binding("c", "clear_logs", "Clear", show=False),
    ]

    _pretty: bool = False
    _paused: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="logs-toolbar"):
            yield Label("[green]● Live[/green]", id="logs-status")
            yield Label("  F: JSON/Pretty  Space: Pause  C: Clear", id="logs-hint")
        yield Log(id="log-widget", highlight=True, auto_scroll=True)

    def on_mount(self) -> None:
        self.start_stream()

    def on_show(self) -> None:
        # Re-start stream when navigating back to this screen
        self.start_stream()

    @work(exclusive=True)
    async def start_stream(self) -> None:
        url = f"{MIDDLEWARE_URL}/api/logs?follow=true&lines=100"
        headers = self.app.api._headers
        log_widget = self.query_one("#log-widget", Log)
        status = self.query_one("#logs-status", Label)

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 403:
                        log_widget.write_line("[red]Error: Invalid admin key[/red]")
                        return
                    status.update("[green]● Live[/green]")
                    async for line in resp.aiter_lines():
                        if self._paused:
                            continue
                        if line.startswith("data: "):
                            self._write_log(line[6:])
        except httpx.ConnectError:
            log_widget.write_line("[red]Error: Cannot connect to middleware[/red]")
            status.update("[red]● Disconnected[/red]")
        except Exception as e:
            log_widget.write_line(f"[red]Stream error: {e}[/red]")
            status.update("[yellow]● Error[/yellow]")

    def _write_log(self, json_str: str) -> None:
        log_widget = self.query_one("#log-widget", Log)
        if not self._pretty:
            log_widget.write_line(json_str)
            return
        try:
            data = json.loads(json_str)
            level = data.get("level", "info").upper()
            event = data.get("event", "")
            ts = str(data.get("timestamp", ""))[:19]
            color = {"ERROR": "red", "WARNING": "yellow", "INFO": "green"}.get(level, "white")
            extra = {k: v for k, v in data.items()
                     if k not in ("level", "event", "timestamp")}
            extra_str = " ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
            log_widget.write_line(
                f"[{color}][{ts}] [{level}][/{color}] {event}  [dim]{extra_str}[/dim]"
            )
        except json.JSONDecodeError:
            log_widget.write_line(json_str)

    def action_toggle_format(self) -> None:
        self._pretty = not self._pretty
        mode = "Pretty" if self._pretty else "JSON"
        self.notify(f"Modo: {mode}", timeout=1)

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        status = self.query_one("#logs-status", Label)
        if self._paused:
            status.update("[yellow]⏸ Paused[/yellow]")
        else:
            status.update("[green]● Live[/green]")

    def action_clear_logs(self) -> None:
        self.query_one("#log-widget", Log).clear()
```

- [ ] **Step 2: Test logs screen**

```bash
python scripts/manage.py
```
Press `4`. Expected: real-time logs appear, `F` toggles format, `Space` pauses.

- [ ] **Step 3: Commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI Logs screen — SSE live tail, JSON/pretty toggle, pause/clear"
```

---

### Task 13: Test Message screen + help overlay

**Files:**
- Modify: `scripts/manage.py`

- [ ] **Step 1: Replace `SendMessageView` and add HelpOverlay**

```python
class SendMessageView(Vertical):
    BORDER_TITLE = "Test Mensaje"

    _tenants: list[dict] = []
    _instances: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Label("Enviar mensaje de prueba", id="send-title")
        yield Label("")
        with Horizontal(classes="form-row"):
            yield Label("Tenant:", classes="form-label")
            yield Select([("Cargando...", "")], id="send-tenant")
        with Horizontal(classes="form-row"):
            yield Label("Instancia:", classes="form-label")
            yield Select([("Selecciona tenant primero", "")], id="send-instance")
        with Horizontal(classes="form-row"):
            yield Label("Número:", classes="form-label")
            yield Input(placeholder="502XXXXXXXX", id="send-number")
        yield Label("Mensaje:")
        yield TextArea(id="send-text")
        yield Label("")
        with Horizontal():
            yield Button("Enviar  [Ctrl+Enter]", variant="primary", id="btn-send")
        yield Label("", id="send-result")

    def on_mount(self) -> None:
        self.load_tenants()

    @work(exclusive=True)
    async def load_tenants(self) -> None:
        try:
            self._tenants = await self.app.api.list_tenants()
            options = [(t["display_name"], t["slug"]) for t in self._tenants]
            sel = self.query_one("#send-tenant", Select)
            sel.set_options(options)
        except ApiError as e:
            self.notify(f"Error cargando tenants: {e.detail}", severity="error")

    @on(Select.Changed, "#send-tenant")
    async def tenant_changed(self, event: Select.Changed) -> None:
        slug = str(event.value)
        if not slug:
            return
        try:
            self._instances = await self.app.api.list_instances(tenant=slug)
            options = [
                (f"{i['instance_name']} ({i['state']})", i["evolution_name"])
                for i in self._instances
            ]
            self.query_one("#send-instance", Select).set_options(options)
        except ApiError as e:
            self.notify(f"Error cargando instancias: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-send")
    async def send_message(self) -> None:
        evo_name = str(self.query_one("#send-instance", Select).value or "")
        number = self.query_one("#send-number", Input).value.strip()
        text = self.query_one("#send-text", TextArea).text.strip()

        if not all([evo_name, number, text]):
            self.notify("Completa todos los campos.", severity="error")
            return

        result_label = self.query_one("#send-result", Label)
        result_label.update("[yellow]Enviando...[/yellow]")
        try:
            data = await self.app.api.send_message(evo_name, number, text)
            msg_id = data.get("key", {}).get("id", "?")
            result_label.update(f"[green]✓ Enviado! Message ID: {msg_id}[/green]")
        except ApiError as e:
            result_label.update(f"[red]✗ Error: {e.detail}[/red]")

    def on_key(self, event) -> None:
        if event.key == "ctrl+enter":
            self.app.call_later(self.send_message)


class HelpOverlay(ModalScreen):
    HELP_TEXT = """\
# Adroc WA Manager — Atajos de teclado

## Navegación
  1-5     Cambiar pantalla
  Q       Salir
  R       Refrescar pantalla actual
  ?       Mostrar/ocultar esta ayuda

## Tenants (pantalla 2)
  N       Nuevo tenant
  E       Editar tenant seleccionado
  K       Rotar API key
  D       Desactivar tenant
  Enter   Ver instancias del tenant

## Instancias (pantalla 3)
  N       Nueva instancia
  R       Restart instancia seleccionada
  L       Logout instancia seleccionada
  Del     Eliminar instancia seleccionada
  X       Exportar tabla a CSV

## Logs (pantalla 4)
  F       Toggle JSON / Pretty print
  Space   Pausar / Reanudar stream
  C       Limpiar pantalla

## Modales
  Enter   Confirmar
  Esc     Cancelar
"""

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            from textual.widgets import Markdown
            yield Markdown(self.HELP_TEXT)
            yield Button("Cerrar  [Esc]", id="btn-close")

    @on(Button.Pressed, "#btn-close")
    def close(self) -> None:
        self.dismiss()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
```

- [ ] **Step 2: Add `?` binding to `AdroCApp`**

In `AdroCApp.BINDINGS`, add:

```python
Binding("question_mark", "show_help", "Help", show=False),
```

And add the action method:

```python
async def action_show_help(self) -> None:
    await self.push_screen(HelpOverlay())
```

- [ ] **Step 3: Full end-to-end test**

```bash
python scripts/manage.py
```

Walk through:
- `1` Dashboard — cards green, tenant table populated
- `2` Tenants — table loads, select row shows detail panel
- `3` Instances — filter dropdown works
- `4` Logs — real logs streaming in
- `5` Test Message — tenant dropdown populates
- `?` — help overlay appears, `Esc` closes it
- `Q` — quits cleanly

- [ ] **Step 4: Final commit**

```bash
git add scripts/manage.py
git commit -m "feat: TUI Test Message screen, help overlay — manager TUI complete"
```

- [ ] **Step 5: Run full test suite to ensure middleware changes haven't broken anything**

```bash
cd /home/adroc/dev/adroc_whatsapp_server/middleware
cd /home/adroc/dev/adroc_whatsapp_server/middleware && python -m pytest tests/ -v --tb=short
```
Expected: all green.

- [ ] **Step 6: Rebuild docker + final smoke test**

```bash
cd /home/adroc/dev/adroc_whatsapp_server
docker compose up -d --build
sleep 10
python scripts/manage.py
```
Expected: TUI connects to running middleware, all screens functional.
