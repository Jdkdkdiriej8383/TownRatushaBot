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
    2. Из первого аргумента (@username, telegram_id, minecraft_nick)
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
                full_name=target_tg_user.full_name,
            )
            session.add(user)
            await session.flush()
        return user, remaining_args

    # 2. По аргументу
    if not remaining_args:
        return None, []

    first_arg = remaining_args[0].strip()

    # @username
    if first_arg.startswith("@"):
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
        if user:
            return user, remaining_args[1:]

    # minecraft nick
    query = select(User).where(User.minecraft_nick.ilike(first_arg))
    user = await session.scalar(query)
    if user:
        return user, remaining_args[1:]

    return None, remaining_args
