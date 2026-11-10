from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Integer, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base
from core.enums import ReportStatus

if TYPE_CHECKING:
    from db.models.user import User


class Report(Base):
    """
    Таблица 'reports' — Жалобы граждан на нарушения в темах форума.
    Маршрутизируются конфиденциально дежурным сотрудникам (Блюстителям и Администрации).
    """
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Чат, где произошел инцидент
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Заявитель (подавший /report)
    reporter_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reporter_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Нарушитель
    violator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    violator_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Контекст инцидента
    incident_topic_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    incident_topic_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)

    # Статус рассмотрения
    status: Mapped[str] = mapped_column(String(32), default=ReportStatus.PENDING.value, index=True)
    claimed_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ID отправленной интерактивной карточки в REPORTS_TOPIC_ID
    card_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    reporter: Mapped["User"] = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reports_filed"
    )
    violator: Mapped["User"] = relationship(
        "User",
        foreign_keys=[violator_id]
    )
    claimed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[claimed_by_id]
    )

    def __repr__(self) -> str:
        return f"<Report #{self.id} violator={self.violator_telegram_id} status={self.status}>"
