from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.enums import PositionLevel


class UserSyncMiddleware(BaseMiddleware):
    """
    Middleware автоматической регистрации и актуализации
    профиля гражданина в базе данных.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        session: AsyncSession = data.get("session")
        event_from_user: TgUser = data.get("event_from_user")

        if session and event_from_user and not event_from_user.is_bot:
            query = select(User).where(User.telegram_id == event_from_user.id)
            user = await session.scalar(query)

            if not user:
                user = User(
                    telegram_id=event_from_user.id,
                    username=event_from_user.username,
                    full_name=event_from_user.full_name,
                    role_level=PositionLevel.CITIZEN.value,
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

            data["db_user"] = user

        return await handler(event, data)
