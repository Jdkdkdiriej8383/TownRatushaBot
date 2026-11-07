from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Integer, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base
from core.enums import FineStatus

if TYPE_CHECKING:
    from db.models.user import User


class Fine(Base):
    """
    Таблица 'fines' — Билеты штрафов.
    Срок оплаты: 48 часов по закону (п. 3.12).
    При неуплате в срок: автоматическое удвоение (х2) и объявление жителя в розыск.
    """
    __tablename__ = "fines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    issuer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    issuer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    law_article: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    original_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    is_doubled: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default=FineStatus.ACTIVE.value, index=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="fines",
        foreign_keys=[user_id]
    )
    issuer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[issuer_id]
    )

    def __repr__(self) -> str:
        return f"<Fine #{self.id} user={self.target_telegram_id} amount={self.amount} status={self.status}>"
