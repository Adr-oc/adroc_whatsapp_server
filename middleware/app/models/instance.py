from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Instance(Base):
    __tablename__ = "instances"
    __table_args__ = (
        UniqueConstraint("instance_name", "tenant_id", name="uq_instance_name_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_name: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="created")
    evolution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    instance_token: Mapped[str | None] = mapped_column(String, nullable=True)
    qr_code_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant = relationship("Tenant", back_populates="instances")
