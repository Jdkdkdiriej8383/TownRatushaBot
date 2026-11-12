from typing import Callable, Dict, Any, Awaitable, Optional
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
    Middleware автоматической регистрации и актуализации профилей жителей (как в Ирисе):
    1. Автоматически регистрирует каждого пользователя при ЛЮБОМ сообщении (текст, стикер, медиа).
    2. Привязывает к ChatMember конкретной группы для изоляции данных и работы /созвать (/all).
    3. Автоматически регистрирует адресатов реплаев (reply_to_message).
    4. Автоматически регистрирует новых участников при вступлении в группу (new_chat_members, ChatMemberUpdated).
    5. Автоматически присваивает права Старшей Администрации (уровень 5) Овнеру (@DivniDed).
    """

    async def _sync_single_user(
        self,
        session: AsyncSession,
        tg_user: TgUser,
        chat_id: Optional[int] = None,
        is_active: bool = True
    ) -> Optional[User]:
        if not tg_user or getattr(tg_user, "is_bot", False):
            return None

        query = select(User).where(User.telegram_id == tg_user.id)
        user = await session.scalar(query)

        is_owner = (
            tg_user.id == settings.OWNER_ID or
            (tg_user.username and tg_user.username.lower() == settings.OWNER_USERNAME.lower())
        )
        initial_role = PositionLevel.OWNER.value if is_owner else PositionLevel.CITIZEN.value

        if not user:
            user = User(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name or f"User {tg_user.id}",
                role_level=initial_role,
                balance=5000,
                is_enemy=False,
            )
            session.add(user)
            await session.flush()
        else:
            if tg_user.username and user.username != tg_user.username:
                user.username = tg_user.username
            if tg_user.full_name and user.full_name != tg_user.full_name:
                user.full_name = tg_user.full_name
            if is_owner and (user.role_level < PositionLevel.OWNER.value or user.is_enemy):
                user.role_level = PositionLevel.OWNER.value
                user.is_enemy = False

        # Привязка к конкретному групповому чату
        if chat_id and chat_id < 0:
            cm = await session.scalar(
                select(ChatMember).where(
                    ChatMember.chat_id == chat_id,
                    ChatMember.telegram_id == user.telegram_id
                )
            )
            if not cm:
                cm = ChatMember(
                    chat_id=chat_id,
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    is_active=is_active,
                )
                session.add(cm)
            else:
                cm.is_active = is_active
                if is_active:
                    cm.last_seen_at = datetime.now(timezone.utc)
            await session.flush()

        return user

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        session: AsyncSession = data.get("session")

        # Определяем чат события
        event_chat = getattr(event, "chat", None)
        if not event_chat and hasattr(event, "message") and getattr(event, "message"):
            event_chat = getattr(event.message, "chat", None)

        chat_id = (
            event_chat.id
            if event_chat and getattr(event_chat, "type", "") in ("group", "supergroup") and getattr(event_chat, "id", 0) < 0
            else None
        )

        # 1. Синхронизируем автора события (from_user)
        event_from_user: TgUser = data.get("event_from_user") or getattr(event, "from_user", None)
        if session and event_from_user and not event_from_user.is_bot:
            user = await self._sync_single_user(session, event_from_user, chat_id=chat_id)
            if user:
                data["db_user"] = user

        # 2. Если в сообщении есть reply_to_message — синхронизируем адресата реплая
        reply = getattr(event, "reply_to_message", None)
        if session and reply:
            reply_user = getattr(reply, "forward_from", None) or getattr(reply, "from_user", None)
            if reply_user and not getattr(reply_user, "is_bot", False):
                await self._sync_single_user(session, reply_user, chat_id=chat_id)

        # 3. Если в группу добавлены новые участники (message.new_chat_members)
        new_members = getattr(event, "new_chat_members", None)
        if session and new_members:
            for new_m in new_members:
                await self._sync_single_user(session, new_m, chat_id=chat_id)

        # 4. Если это событие смены статуса участника (ChatMemberUpdated)
        new_cm = getattr(event, "new_chat_member", None)
        if session and new_cm and hasattr(new_cm, "user"):
            status = getattr(new_cm, "status", "")
            is_active = status in ("member", "administrator", "creator", "restricted")
            await self._sync_single_user(session, new_cm.user, chat_id=chat_id, is_active=is_active)

        return await handler(event, data)
