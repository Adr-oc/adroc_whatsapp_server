"""phase 1: drop messages/contacts, extend instances

Revision ID: a1b2c3d4e5f6
Revises: 20b81f051d74
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "20b81f051d74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop messages table and its indexes
    op.drop_index(op.f("ix_messages_timestamp"), table_name="messages")
    op.drop_index(op.f("ix_messages_session"), table_name="messages")
    op.drop_index(op.f("ix_messages_odoo_synced"), table_name="messages")
    op.drop_table("messages")

    # Drop contacts table and its indexes
    op.drop_index(op.f("ix_contacts_session"), table_name="contacts")
    op.drop_table("contacts")

    # Add new columns to instances
    op.add_column("instances", sa.Column("evolution_id", sa.String(), nullable=True))
    op.add_column("instances", sa.Column("instance_token", sa.String(), nullable=True))
    op.add_column("instances", sa.Column("odoo_channel_id", sa.Integer(), nullable=True))
    op.add_column("instances", sa.Column("qr_code_base64", sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove new columns from instances
    op.drop_column("instances", "qr_code_base64")
    op.drop_column("instances", "odoo_channel_id")
    op.drop_column("instances", "instance_token")
    op.drop_column("instances", "evolution_id")

    # Recreate contacts table
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("whatsapp_number", sa.String(), nullable=False),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("profile_pic_url", sa.String(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("odoo_partner_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("whatsapp_number", "session", name="uq_contacts_number_session"),
    )
    op.create_index(op.f("ix_contacts_session"), "contacts", ["session"], unique=False)

    # Recreate messages table
    from sqlalchemy.dialects import postgresql

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("whatsapp_id", sa.String(), nullable=True),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("remote_jid", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=True),
        sa.Column("media_url", sa.String(), nullable=True),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("odoo_synced", sa.Boolean(), nullable=False),
        sa.Column("odoo_message_id", sa.Integer(), nullable=True),
        sa.Column("odoo_sync_error", sa.String(), nullable=True),
        sa.Column("odoo_sync_attempts", sa.Integer(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("direction IN ('incoming', 'outgoing')", name="ck_messages_direction"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("whatsapp_id", "session", name="uq_messages_whatsapp_id_session"),
    )
    op.create_index(op.f("ix_messages_odoo_synced"), "messages", ["odoo_synced"], unique=False)
    op.create_index(op.f("ix_messages_session"), "messages", ["session"], unique=False)
    op.create_index(op.f("ix_messages_timestamp"), "messages", ["timestamp"], unique=False)
