from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class ChatMember(Base):
    """
    Таблица 'chat_members' — Принадлежность пользователей к конкретным чатам.
    Обеспечивает строгую изоляцию групп: бот знает, кто состоит в конкретной группе,
    и при вызове /all пингует исключительно реальных участников текущей группы.
    """
    __tablename__ = "chat_members"
    __table_args__ = (
        UniqueConstraint("chat_id", "telegram_id", name="uq_chat_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<ChatMember chat={self.chat_id} user={self.telegram_id} active={self.is_active}>"
