from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("whatsapp_number", "session", name="uq_contacts_number_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    whatsapp_number: Mapped[str] = mapped_column(String, nullable=False)
    session: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_pic_url: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    odoo_partner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
