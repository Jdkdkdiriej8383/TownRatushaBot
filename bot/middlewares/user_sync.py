from typing import Callable, Dict, Any, Awaitable
from datetime import datetime, timezone
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, ChatMember
from core.enums import PositionLevel
from config import settings


class UserSyncMiddleware(BaseMiddleware):
    """
    Middleware автоматической регистрации и актуализации
    профиля гражданина и привязки его к конкретным группам (ChatMember).
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

            # Изоляция и учет участников чатов: фиксируем принадлежность пользователя к текущей группе
            event_chat = getattr(event, "chat", None)
            if not event_chat and hasattr(event, "message") and getattr(event, "message"):
                event_chat = getattr(event.message, "chat", None)

            if event_chat and getattr(event_chat, "type", "") in ("group", "supergroup") and getattr(event_chat, "id", 0) < 0:
                chat_id = event_chat.id
                cm_query = select(ChatMember).where(
                    ChatMember.chat_id == chat_id,
                    ChatMember.telegram_id == user.telegram_id
                )
                cm = await session.scalar(cm_query)
                if not cm:
                    cm = ChatMember(
                        chat_id=chat_id,
                        user_id=user.id,
                        telegram_id=user.telegram_id,
                        is_active=True,
                    )
                    session.add(cm)
                else:
                    cm.is_active = True
                    cm.last_seen_at = datetime.now(timezone.utc)

        return await handler(event, data)
