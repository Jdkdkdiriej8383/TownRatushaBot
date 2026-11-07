from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, Text, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class Law(Base):
    """
    Таблица 'laws' — Городской Свод Законов.
    Поддерживает динамическое редактирование блюстителями 4-5 уровня
    и автоматическое применение через референдумы.
    """
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_number: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    section: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sanction_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Параметры санкции по умолчанию для авто-применения
    default_mute_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    default_fine_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_ban_applicable: Mapped[bool] = mapped_column(Boolean, default=False)

    # Аудит изменений
    last_edited_by_tg_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Law article={self.article_number} title='{self.title[:20]}'>"
