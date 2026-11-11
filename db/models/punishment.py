from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Integer, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class Punishment(Base):
    """
    Таблица 'punishments' — Протокол городского суда и реестр правонарушений.
    Используется для формирования команды /досье @юзер.
    """
    __tablename__ = "punishments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    issuer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    issuer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    punishment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    law_article: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    target_user: Mapped["User"] = relationship(
        "User",
        back_populates="punishments_received",
        foreign_keys=[user_id]
    )
    issuer_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[issuer_id]
    )

    def __repr__(self) -> str:
        return f"<Punishment #{self.id} user={self.target_telegram_id} type={self.punishment_type}>"
