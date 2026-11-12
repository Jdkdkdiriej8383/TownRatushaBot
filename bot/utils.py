import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, ChatMember
from core.enums import PositionLevel


async def _ensure_chat_member(session: AsyncSession, chat, user: User) -> None:
    """Гарантирует привязку пользователя к группе в таблице chat_members."""
    if not chat or not hasattr(chat, "id"):
        return
    try:
        chat_id = getattr(chat, "id", 0)
        chat_type = getattr(chat, "type", "")
        if chat_id >= 0 or chat_type not in ("group", "supergroup"):
            return

        cm = await session.scalar(
            select(ChatMember).where(
                ChatMember.chat_id == chat_id,
                ChatMember.telegram_id == user.telegram_id
            )
        )
        if not cm:
            session.add(ChatMember(
                chat_id=chat_id,
                user_id=user.id,
                telegram_id=user.telegram_id,
                is_active=True,
            ))
        else:
            cm.is_active = True
            cm.last_seen_at = datetime.now(timezone.utc)
        await session.flush()
    except Exception:
        pass


async def extract_target_user(
    message: Message,
    session: AsyncSession,
    args: list[str] | None = None
) -> Tuple[Optional[User], list[str]]:
    """
    Извлекает целевого пользователя:
    1. Из ответа на сообщение (reply_to_message, включая пересланные forward_from)
    2. Из entities сообщения (text_mention)
    3. Из первого аргумента (@username, telegram_id, minecraft_nick)
    Автоматически регистрирует нового пользователя на лету и привязывает к ChatMember.
    Возвращает (User | None, оставшиеся аргументы).
    """
    remaining_args = list(args) if args else []
    chat = getattr(message, "chat", None)
    bot = getattr(message, "bot", None)

    # 1. По реплаю (включая оригинального автора пересланного сообщения)
    reply_to = getattr(message, "reply_to_message", None)
    if reply_to:
        target_tg_user = (
            getattr(reply_to, "forward_from", None)
            or getattr(reply_to, "from_user", None)
        )
        if target_tg_user and not getattr(target_tg_user, "is_bot", False):
            query = select(User).where(User.telegram_id == target_tg_user.id)
            user = await session.scalar(query)
            if not user:
                user = User(
                    telegram_id=target_tg_user.id,
                    username=target_tg_user.username,
                    full_name=target_tg_user.full_name or f"User {target_tg_user.id}",
                    role_level=PositionLevel.CITIZEN.value,
                    balance=5000,
                    is_enemy=False,
                )
                session.add(user)
                await session.flush()
            else:
                if target_tg_user.username and user.username != target_tg_user.username:
                    user.username = target_tg_user.username
                if target_tg_user.full_name and user.full_name != target_tg_user.full_name:
                    user.full_name = target_tg_user.full_name

            await _ensure_chat_member(session, chat, user)
            return user, remaining_args

    # 2. По text_mention в entities (когда упомянули пользователя через Telegram UI)
    entities = getattr(message, "entities", None)
    if entities:
        for entity in entities:
            if entity.type == "text_mention" and entity.user:
                tg_user = entity.user
                query = select(User).where(User.telegram_id == tg_user.id)
                user = await session.scalar(query)
                if not user:
                    user = User(
                        telegram_id=tg_user.id,
                        username=tg_user.username,
                        full_name=tg_user.full_name or f"User {tg_user.id}",
                        role_level=PositionLevel.CITIZEN.value,
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

                await _ensure_chat_member(session, chat, user)
                if remaining_args:
                    return user, remaining_args[1:]
                return user, []

    # 3. По аргументам
    if not remaining_args:
        return None, []

    raw_first_arg = remaining_args[0].strip()
    first_arg = raw_first_arg.strip(" ,:;()[]<>")

    # @username
    if first_arg.startswith("@") or raw_first_arg.startswith("@"):
        username = first_arg.lstrip("@").lower()
        query = select(User).where(User.username.ilike(username))
        user = await session.scalar(query)
        if user:
            await _ensure_chat_member(session, chat, user)
            return user, remaining_args[1:]

        # Если пользователь не найден в БД, проверяем администраторов чата
        if bot and chat and getattr(chat, "type", "") in ("group", "supergroup"):
            try:
                admins = await chat.get_administrators()
                for adm in admins:
                    if adm.user and adm.user.username and adm.user.username.lower() == username:
                        tg_user = adm.user
                        user = User(
                            telegram_id=tg_user.id,
                            username=tg_user.username,
                            full_name=tg_user.full_name or f"User {tg_user.id}",
                            role_level=PositionLevel.CITIZEN.value,
                            balance=5000,
                            is_enemy=False,
                        )
                        session.add(user)
                        await session.flush()
                        await _ensure_chat_member(session, chat, user)
                        return user, remaining_args[1:]
            except Exception:
                pass

    # telegram id
    if first_arg.isdigit():
        tg_id = int(first_arg)
        query = select(User).where(User.telegram_id == tg_id)
        user = await session.scalar(query)
        if not user:
            # Создаем на лету, пытаясь получить данные через Bot API
            uname = None
            fname = f"ID {tg_id}"
            if bot and chat:
                try:
                    member = await bot.get_chat_member(chat.id, tg_id)
                    if member and member.user:
                        uname = member.user.username
                        fname = member.user.full_name or fname
                except Exception:
                    pass
            user = User(
                telegram_id=tg_id,
                username=uname,
                full_name=fname,
                role_level=PositionLevel.CITIZEN.value,
                balance=5000,
                is_enemy=False,
            )
            session.add(user)
            await session.flush()

        await _ensure_chat_member(session, chat, user)
        return user, remaining_args[1:]

    # minecraft nick или поиск по username без @
    query = select(User).where(User.minecraft_nick.ilike(first_arg))
    user = await session.scalar(query)
    if user:
        await _ensure_chat_member(session, chat, user)
        return user, remaining_args[1:]

    query_by_username = select(User).where(User.username.ilike(first_arg))
    user = await session.scalar(query_by_username)
    if user:
        await _ensure_chat_member(session, chat, user)
        return user, remaining_args[1:]

    return None, remaining_args
