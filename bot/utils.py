import re
from typing import Optional, Tuple
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User


async def extract_target_user(
    message: Message,
    session: AsyncSession,
    args: list[str] | None = None
) -> Tuple[Optional[User], list[str]]:
    """
    Извлекает целевого пользователя:
    1. Из ответа на сообщение (reply_to_message)
    2. Из entities сообщения (text_mention)
    3. Из первого аргумента (@username, telegram_id, minecraft_nick)
    Возвращает (User | None, оставшиеся аргументы).
    """
    remaining_args = list(args) if args else []

    # 1. По реплаю
    if message.reply_to_message and message.reply_to_message.from_user:
        target_tg_user = message.reply_to_message.from_user
        query = select(User).where(User.telegram_id == target_tg_user.id)
        user = await session.scalar(query)
        if not user:
            # Создаем на лету
            user = User(
                telegram_id=target_tg_user.id,
                username=target_tg_user.username,
                full_name=target_tg_user.full_name or f"User {target_tg_user.id}",
            )
            session.add(user)
            await session.flush()
        else:
            if target_tg_user.username and user.username != target_tg_user.username:
                user.username = target_tg_user.username
            if target_tg_user.full_name and user.full_name != target_tg_user.full_name:
                user.full_name = target_tg_user.full_name
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
                    )
                    session.add(user)
                    await session.flush()
                else:
                    if tg_user.username and user.username != tg_user.username:
                        user.username = tg_user.username
                    if tg_user.full_name and user.full_name != tg_user.full_name:
                        user.full_name = tg_user.full_name

                # Если первый аргумент содержит упоминание, убираем его из оставшихся аргументов
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
            return user, remaining_args[1:]

    # telegram id
    if first_arg.isdigit():
        tg_id = int(first_arg)
        query = select(User).where(User.telegram_id == tg_id)
        user = await session.scalar(query)
        if not user:
            # Создаем на лету, пытаясь получить данные через Bot API
            uname = None
            fname = f"ID {tg_id}"
            if message.bot and message.chat:
                try:
                    member = await message.bot.get_chat_member(message.chat.id, tg_id)
                    if member and member.user:
                        uname = member.user.username
                        fname = member.user.full_name or fname
                except Exception:
                    pass
            user = User(
                telegram_id=tg_id,
                username=uname,
                full_name=fname,
            )
            session.add(user)
            await session.flush()
        return user, remaining_args[1:]

    # minecraft nick или поиск по username без @
    query = select(User).where(User.minecraft_nick.ilike(first_arg))
    user = await session.scalar(query)
    if user:
        return user, remaining_args[1:]

    query_by_username = select(User).where(User.username.ilike(first_arg))
    user = await session.scalar(query_by_username)
    if user:
        return user, remaining_args[1:]

    return None, remaining_args
