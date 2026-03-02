from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("whatsapp_id", "session", name="uq_messages_whatsapp_id_session"),
        CheckConstraint("direction IN ('incoming', 'outgoing')", name="ck_messages_direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session: Mapped[str] = mapped_column(String, nullable=False, index=True)
    remote_jid: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(String, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String, nullable=True)
    message_type: Mapped[str] = mapped_column(String, default="text")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="sent")
    odoo_synced: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    odoo_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_sync_error: Mapped[str | None] = mapped_column(String, nullable=True)
    odoo_sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
