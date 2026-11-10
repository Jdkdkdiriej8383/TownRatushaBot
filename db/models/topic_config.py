from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, BigInteger, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class TopicConfig(Base):
    """
    Таблица 'topic_configs' — Конфигурация привязки тем форума (Forum Topics).
    Позволяет динамически настраивать топики через команду /settopic <тип>.
    """
    __tablename__ = "topic_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    topic_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_name: Mapped[str] = mapped_column(String(128), default="Тема")

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
        return f"<TopicConfig chat={self.chat_id} type={self.topic_type} thread={self.thread_id}>"
