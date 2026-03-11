from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import Instance
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent

log = structlog.get_logger()


async def upsert_instance(
    db: AsyncSession, instance_name: str, tenant_id: int, **kwargs: Any
) -> Instance:
    """Insert or update an instance by (name, tenant_id)."""
    stmt = (
        insert(Instance)
        .values(instance_name=instance_name, tenant_id=tenant_id, **kwargs)
        .on_conflict_do_update(
            constraint="uq_instance_name_tenant",
            set_={k: v for k, v in kwargs.items() if v is not None},
        )
        .returning(Instance)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


async def get_instance(db: AsyncSession, instance_name: str) -> Instance | None:
    """Get instance from local DB by Evolution name."""
    result = await db.execute(
        select(Instance).where(Instance.instance_name == instance_name)
    )
    return result.scalar_one_or_none()


async def get_instance_for_tenant(
    db: AsyncSession, instance_name: str, tenant_id: int
) -> Instance | None:
    """Get instance scoped to a tenant."""
    result = await db.execute(
        select(Instance).where(
            Instance.instance_name == instance_name,
            Instance.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_tenant_instances(db: AsyncSession, tenant_id: int) -> list[Instance]:
    """List instances for a specific tenant."""
    result = await db.execute(
        select(Instance)
        .where(Instance.tenant_id == tenant_id)
        .order_by(Instance.created_at)
    )
    return list(result.scalars().all())


async def delete_instance_by_name(db: AsyncSession, instance_name: str) -> None:
    """Remove instance from local DB."""
    instance = await get_instance(db, instance_name)
    if instance:
        await db.delete(instance)
        await db.commit()


async def update_instance_state(db: AsyncSession, instance_name: str, state: str) -> None:
    """Update connection state. Called from connection.update webhook.

    Uses get_instance to find the instance first (webhook context, no tenant_id available).
    """
    instance = await get_instance(db, instance_name)
    if instance:
        instance.state = state
        await db.commit()
        log.info("instance_state_updated", instance=instance_name, state=state)
    else:
        log.warning("instance_state_update_skipped", instance=instance_name, reason="not_found")


async def update_instance_qr(db: AsyncSession, instance_name: str, qr_base64: str) -> None:
    """Store QR code. Called from qrcode.updated webhook."""
    instance = await get_instance(db, instance_name)
    if instance:
        instance.qr_code_base64 = qr_base64
        await db.commit()
        log.info("instance_qr_updated", instance=instance_name)
    else:
        log.warning("instance_qr_update_skipped", instance=instance_name, reason="not_found")


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
