from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import BigInteger, String, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.base import Base
from core.enums import PositionLevel

if TYPE_CHECKING:
    from db.models.fine import Fine
    from db.models.punishment import Punishment


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Иерархия должностей (0-5, либо -1 для Врага города)
    # Запрещено слово 'ранг', поле названо role_level / position_level
    role_level: Mapped[int] = mapped_column(Integer, default=PositionLevel.CITIZEN, index=True)

    # Спец-статус: Враг города
    is_enemy: Mapped[bool] = mapped_column(Boolean, default=False)
    enemy_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Minecraft паспортные данные
    minecraft_nick: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True, nullable=True)

    # Статус отпуска (по п. 3.25 Городского Свода Законов)
    on_vacation: Mapped[bool] = mapped_column(Boolean, default=False)
    vacation_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Розыск (при неуплате штрафов свыше 48ч)
    is_wanted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Счетчики нарушений
    warns_count: Mapped[int] = mapped_column(Integer, default=0)
    reprimands_count: Mapped[int] = mapped_column(Integer, default=0)  # Служебные выговоры (при 3/3 - отстранение)

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    fines: Mapped[List["Fine"]] = relationship(
        "Fine",
        back_populates="user",
        foreign_keys="Fine.user_id",
        cascade="all, delete-orphan"
    )
    punishments_received: Mapped[List["Punishment"]] = relationship(
        "Punishment",
        back_populates="target_user",
        foreign_keys="Punishment.user_id",
        cascade="all, delete-orphan"
    )

    @property
    def position_title(self) -> str:
        if self.is_enemy:
            return "Враг города"
        return PositionLevel.get_title(self.role_level)

    @property
    def is_citizen_or_higher(self) -> bool:
        return not self.is_enemy and self.role_level >= PositionLevel.CITIZEN

    def __repr__(self) -> str:
        return f"<User tg={self.telegram_id} nick={self.minecraft_nick} role={self.role_level} rep={self.reprimands_count}>"
