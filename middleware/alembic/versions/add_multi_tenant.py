"""add multi-tenant support

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("odoo_webhook_url", sa.Text(), nullable=False),
        sa.Column("odoo_api_key", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("max_instances", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("api_key"),
    )

    # 2. Insert default tenant for existing data
    op.execute(
        "INSERT INTO tenants (slug, display_name, odoo_webhook_url, odoo_api_key, api_key) "
        "VALUES ('default', 'Default Tenant', 'http://placeholder', 'placeholder', 'placeholder-update-me')"
    )

    # 3. Add tenant_id to instances (nullable first for backfill)
    op.add_column("instances", sa.Column("tenant_id", sa.Integer(), nullable=True))

    # 4. Backfill existing instances to default tenant
    op.execute("UPDATE instances SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default')")

    # 5. Make tenant_id NOT NULL
    op.alter_column("instances", "tenant_id", nullable=False)

    # 6. Add FK constraint
    op.create_foreign_key("fk_instances_tenant", "instances", "tenants", ["tenant_id"], ["id"])

    # 7. Drop old unique constraint on instance_name, add composite
    op.drop_constraint("instances_instance_name_key", "instances", type_="unique")
    op.create_unique_constraint("uq_instance_name_tenant", "instances", ["instance_name", "tenant_id"])
    op.create_index("idx_instances_tenant", "instances", ["tenant_id"])

    # 8. Drop odoo_channel_id (replaced by tenant relationship)
    op.drop_column("instances", "odoo_channel_id")

    # 9. Add tenant_id to webhook_events (nullable, no backfill needed)
    op.add_column("webhook_events", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_webhook_events_tenant", "webhook_events", "tenants", ["tenant_id"], ["id"])
    op.create_index("idx_webhook_events_tenant", "webhook_events", ["tenant_id"])


def downgrade() -> None:
    # webhook_events
    op.drop_index("idx_webhook_events_tenant", table_name="webhook_events")
    op.drop_constraint("fk_webhook_events_tenant", "webhook_events", type_="foreignkey")
    op.drop_column("webhook_events", "tenant_id")

    # instances: restore odoo_channel_id
    op.add_column("instances", sa.Column("odoo_channel_id", sa.Integer(), nullable=True))

    # instances: restore original unique constraint
    op.drop_index("idx_instances_tenant", table_name="instances")
    op.drop_constraint("uq_instance_name_tenant", "instances", type_="unique")
    op.create_unique_constraint("instances_instance_name_key", "instances", ["instance_name"])

    # instances: drop tenant_id
    op.drop_constraint("fk_instances_tenant", "instances", type_="foreignkey")
    op.drop_column("instances", "tenant_id")

    # Drop tenants table
    op.drop_table("tenants")
