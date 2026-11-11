from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Integer, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base
from core.enums import TicketStatus

if TYPE_CHECKING:
    from db.models.user import User


class Ticket(Base):
    """
    Таблица 'tickets' — Обращения граждан в государственные органы.
    Каждое обращение может создавать персональный топик форума.
    """
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Чат супергруппы
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Заявитель
    creator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    creator_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Инстанция и ответственный орган
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    target_role: Mapped[str] = mapped_column(String(64), nullable=False, default="Администрация")

    # Персональный топик форума
    topic_thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Статус
    status: Mapped[str] = mapped_column(String(32), default=TicketStatus.OPEN.value, index=True)
    claimed_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # Содержимое и решение
    initial_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    creator: Mapped["User"] = relationship(
        "User",
        foreign_keys=[creator_id],
        back_populates="tickets_created"
    )
    claimed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[claimed_by_id]
    )

    def __repr__(self) -> str:
        return f"<Ticket #{self.id} cat={self.category} status={self.status} topic={self.topic_thread_id}>"
