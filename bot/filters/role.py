from aiogram.filters import BaseFilter
from aiogram.types import Message
from db.models import User
from core.enums import PositionLevel


class RoleFilter(BaseFilter):
    """Фильтр проверки минимальной должности гражданина."""

    def __init__(self, min_level: int | PositionLevel):
        if isinstance(min_level, PositionLevel):
            self.min_level = min_level.value
        else:
            self.min_level = min_level

    async def __call__(self, message: Message, db_user: User | None = None) -> bool:
        if not db_user:
            return False
        if db_user.is_enemy:
            return False
        return db_user.role_level >= self.min_level


class NotEnemyFilter(BaseFilter):
    """Пропускает только тех, кто не имеет статуса 'Враг города'."""

    async def __call__(self, message: Message, db_user: User | None = None) -> bool:
        if not db_user:
            return True
        return not db_user.is_enemy
