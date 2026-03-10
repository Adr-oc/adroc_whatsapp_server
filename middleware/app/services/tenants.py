import secrets
from typing import Any

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import Instance
from app.models.tenant import Tenant

log = structlog.get_logger()


class TenantCache:
    """In-memory cache for O(1) tenant lookups."""

    def __init__(self) -> None:
        self._by_api_key: dict[str, Tenant] = {}
        self._by_instance_name: dict[str, Tenant] = {}

    async def refresh(self, db: AsyncSession) -> None:
        """Reload all active tenants and their instances from DB."""
        result = await db.execute(
            select(Tenant).where(Tenant.is_active == True)  # noqa: E712
        )
        tenants = list(result.scalars().all())

        by_api_key: dict[str, Tenant] = {}
        by_instance_name: dict[str, Tenant] = {}

        for tenant in tenants:
            by_api_key[tenant.api_key] = tenant

        # Load instance→tenant mappings
        inst_result = await db.execute(
            select(Instance).where(Instance.tenant_id.in_([t.id for t in tenants]))
        )
        for instance in inst_result.scalars().all():
            matching = by_api_key.get(
                next((t.api_key for t in tenants if t.id == instance.tenant_id), "")
            )
            if matching:
                by_instance_name[instance.instance_name] = matching

        self._by_api_key = by_api_key
        self._by_instance_name = by_instance_name
        log.info("tenant_cache_refreshed", tenants=len(tenants), instances=len(by_instance_name))

    def get_by_api_key(self, key: str) -> Tenant | None:
        """Timing-safe lookup by API key."""
        for stored_key, tenant in self._by_api_key.items():
            if secrets.compare_digest(key, stored_key):
                return tenant
        return None

    def get_by_instance_name(self, instance_name: str) -> Tenant | None:
        """Direct lookup by Evolution instance name (e.g. 'acme_ventas')."""
        return self._by_instance_name.get(instance_name)

    def register_instance(self, instance_name: str, tenant: Tenant) -> None:
        """Register an instance→tenant mapping without full refresh."""
        self._by_instance_name[instance_name] = tenant

    def unregister_instance(self, instance_name: str) -> None:
        """Remove an instance→tenant mapping."""
        self._by_instance_name.pop(instance_name, None)


tenant_cache = TenantCache()


async def create_tenant(
    db: AsyncSession,
    slug: str,
    display_name: str,
    odoo_webhook_url: str,
    odoo_api_key: str,
    max_instances: int = 10,
) -> tuple[Tenant, str]:
    """Create a new tenant. Returns (tenant, raw_api_key). Key shown once."""
    raw_key = secrets.token_hex(32)
    tenant = Tenant(
        slug=slug,
        display_name=display_name,
        odoo_webhook_url=odoo_webhook_url,
        odoo_api_key=odoo_api_key,
        api_key=raw_key,
        max_instances=max_instances,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    # Update cache
    tenant_cache._by_api_key[raw_key] = tenant
    log.info("tenant_created", slug=slug)
    return tenant, raw_key


async def list_tenants(db: AsyncSession) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.created_at))
    return list(result.scalars().all())


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def update_tenant(db: AsyncSession, slug: str, **kwargs: Any) -> Tenant | None:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        return None

    for key, value in kwargs.items():
        if value is not None and hasattr(tenant, key):
            setattr(tenant, key, value)

    await db.commit()
    await db.refresh(tenant)

    # Refresh cache to pick up changes
    await tenant_cache.refresh(db)
    return tenant


async def deactivate_tenant(db: AsyncSession, slug: str) -> Tenant | None:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        return None

    tenant.is_active = False
    await db.commit()
    await db.refresh(tenant)

    # Refresh cache (removes inactive tenant)
    await tenant_cache.refresh(db)
    log.info("tenant_deactivated", slug=slug)
    return tenant


async def rotate_tenant_key(db: AsyncSession, slug: str) -> tuple[Tenant, str] | None:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        return None

    # Remove old key from cache
    tenant_cache._by_api_key.pop(tenant.api_key, None)

    new_key = secrets.token_hex(32)
    tenant.api_key = new_key
    await db.commit()
    await db.refresh(tenant)

    # Register new key in cache
    tenant_cache._by_api_key[new_key] = tenant
    log.info("tenant_key_rotated", slug=slug)
    return tenant, new_key


async def get_tenant_instance_count(db: AsyncSession, tenant_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Instance).where(Instance.tenant_id == tenant_id)
    )
    return result.scalar() or 0
