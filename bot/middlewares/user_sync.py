from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.enums import PositionLevel
from config import settings


class UserSyncMiddleware(BaseMiddleware):
    """
    Middleware автоматической регистрации и актуализации
    профиля гражданина в базе данных.
    Автоматически присваивает права Старшей Администрации (уровень 5) Овнеру (@DivniDed).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        session: AsyncSession = data.get("session")
        event_from_user: TgUser = data.get("event_from_user") or getattr(event, "from_user", None)

        if session and event_from_user and not event_from_user.is_bot:
            query = select(User).where(User.telegram_id == event_from_user.id)
            user = await session.scalar(query)

            is_owner = (
                event_from_user.id == settings.OWNER_ID or
                (event_from_user.username and event_from_user.username.lower() == settings.OWNER_USERNAME.lower())
            )
            initial_role = PositionLevel.OWNER.value if is_owner else PositionLevel.CITIZEN.value

            if not user:
                user = User(
                    telegram_id=event_from_user.id,
                    username=event_from_user.username,
                    full_name=event_from_user.full_name,
                    role_level=initial_role,
                    is_enemy=False,
                )
                session.add(user)
                await session.flush()
            else:
                # Актуализация имени и username
                if user.username != event_from_user.username:
                    user.username = event_from_user.username
                if user.full_name != event_from_user.full_name:
                    user.full_name = event_from_user.full_name
                # Если это Овнер, гарантируем максимальные полномочия (Ранг 5)
                if is_owner and (user.role_level < PositionLevel.OWNER.value or user.is_enemy):
                    user.role_level = PositionLevel.OWNER.value
                    user.is_enemy = False

            data["db_user"] = user

        return await handler(event, data)
