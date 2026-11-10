from typing import Union, List, Optional
from aiogram.filters import BaseFilter
from aiogram.types import Message
from db.models import User
from core.enums import PositionLevel, GovernmentRole
from core.hierarchy_service import HierarchyService
from config import settings


class RoleFilter(BaseFilter):
    """Фильтр проверки минимальной должности гражданина."""

    def __init__(self, min_level: int | PositionLevel):
        if isinstance(min_level, PositionLevel):
            self.min_level = min_level.value
        else:
            self.min_level = min_level

    async def __call__(self, message: Message, db_user: Optional[User] = None) -> bool:
        if not db_user:
            return False
        if HierarchyService.is_owner(db_user):
            return True
        if db_user.is_enemy:
            return False
        return db_user.role_level >= self.min_level


class MinRankFilter(BaseFilter):
    """Фильтр проверки минимального государственного ранга (0-4)."""

    def __init__(self, min_rank: int):
        self.min_rank = min_rank

    async def __call__(self, message: Message, db_user: Optional[User] = None) -> bool:
        if not db_user:
            return False
        if HierarchyService.is_owner(db_user):
            return True
        if db_user.is_enemy:
            return False
        return db_user.government_rank >= self.min_rank


class SpecificRoleFilter(BaseFilter):
    """Фильтр проверки наличия одной из конкретных должностей (например, Мэр, Премьер-министр)."""

    def __init__(self, allowed_roles: Union[List[str], str]):
        if isinstance(allowed_roles, str):
            self.allowed_roles = [allowed_roles.lower()]
        else:
            self.allowed_roles = [r.lower() for r in allowed_roles]

    async def __call__(self, message: Message, db_user: Optional[User] = None) -> bool:
        if not db_user:
            return False
        if HierarchyService.is_owner(db_user):
            return True
        title = (db_user.custom_title or db_user.position_title).lower()
        return title in self.allowed_roles


class IsOwnerFilter(BaseFilter):
    """Пропускает только Овнера/Владельца города."""

    async def __call__(self, message: Message, db_user: Optional[User] = None) -> bool:
        return HierarchyService.is_owner(db_user)


class NotEnemyFilter(BaseFilter):
    """Пропускает только тех, кто не имеет статуса 'Враг города'."""

    async def __call__(self, message: Message, db_user: Optional[User] = None) -> bool:
        if not db_user:
            return True
        return not db_user.is_enemy
