from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Integer, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base
from core.enums import AuctionStatus

if TYPE_CHECKING:
    from db.models.user import User


class Auction(Base):
    """
    Таблица 'auctions' — Государственные аукционы конфискованного имущества.
    Вырученные с аукционов средства зачисляются в Государственную казну города.
    """
    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    initiator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    initiator_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    start_price: Mapped[int] = mapped_column(Integer, nullable=False)
    current_price: Mapped[int] = mapped_column(Integer, nullable=False)
    min_step: Mapped[int] = mapped_column(Integer, default=500)

    current_winner_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    current_winner_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    current_winner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=AuctionStatus.ACTIVE.value, index=True)
    bids_count: Mapped[int] = mapped_column(Integer, default=0)

    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    initiator: Mapped["User"] = relationship(
        "User",
        foreign_keys=[initiator_id]
    )
    current_winner: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[current_winner_id]
    )

    def __repr__(self) -> str:
        return f"<Auction #{self.id} lot='{self.title}' price={self.current_price} status={self.status}>"
