import re
import time
from typing import Callable, Dict, Any, Awaitable
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import Message, ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import ChatSettings, User
from core.enums import PositionLevel

# In-memory трекер для медиа-спама (user_id -> list of timestamps)
_media_tracker: Dict[int, list[float]] = defaultdict(list)

# Регулярное выражение для поиска ссылок
URL_REGEX = re.compile(
    r"(https?://\S+|t\.me/\S+|discord\.gg/\S+|vk\.com/\S+)",
    re.IGNORECASE
)


class ChatRegulatorMiddleware(BaseMiddleware):
    """
    Middleware защитных регуляторов чата:
    1. Анти-капс (>70% заглавных букв)
    2. Медиа-спам (>3 ГС / кружков / стикеров подряд)
    3. Защита от ссылок и несанкционированной рекламы
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # Применяется только к сообщениям в группах и супергруппах
        if not isinstance(event, Message) or event.chat.type not in ("group", "supergroup"):
            return await handler(event, data)

        db_user: User | None = data.get("db_user")
        session: AsyncSession = data.get("session")

        # Блюстители (уровень 1 и выше) освобождаются от спам-фильтра
        if db_user and db_user.role_level >= PositionLevel.ASSISTANT.value:
            return await handler(event, data)

        # Загружаем настройки регуляторов для чата
        if session:
            settings_query = select(ChatSettings).where(ChatSettings.chat_id == event.chat.id)
            chat_settings = await session.scalar(settings_query)
            if not chat_settings:
                chat_settings = ChatSettings(chat_id=event.chat.id)
                session.add(chat_settings)
                await session.flush()
        else:
            chat_settings = ChatSettings(chat_id=event.chat.id)

        user_id = event.from_user.id
        now = time.time()

        # 1. Проверка на медиа-спам (стикеры, ГС, видеосообщения/кружки)
        is_media = bool(event.sticker or event.voice or event.video_note)
        if is_media and chat_settings.media_spam_enabled:
            tracker = _media_tracker[user_id]
            # Очищаем события старше 15 секунд
            tracker = [t for t in tracker if now - t < 15]
            tracker.append(now)
            _media_tracker[user_id] = tracker

            if len(tracker) > chat_settings.media_spam_threshold:
                try:
                    await event.delete()
                    await event.bot.restrict_chat_member(
                        chat_id=event.chat.id,
                        user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=int(now + chat_settings.auto_mute_seconds)
                    )
                    await event.answer(
                        f"🛑 <b>Регулятор медиа-спама!</b>\n"
                        f"Гражданин {event.from_user.mention_html()} временно ограничен в речи на 30 мин "
                        f"за отправку более {chat_settings.media_spam_threshold} медиа подряд (Статья 2.3)."
                    )
                    return
                except Exception:
                    pass

        # 2. Проверка анти-капса
        text = event.text or event.caption or ""
        if text and chat_settings.anti_caps_enabled and not text.startswith("/"):
            letters = [c for c in text if c.isalpha()]
            if len(letters) >= chat_settings.anti_caps_min_chars:
                upper_count = sum(1 for c in letters if c.isupper())
                ratio = upper_count / len(letters)
                if ratio >= chat_settings.anti_caps_threshold:
                    try:
                        await event.delete()
                        await event.answer(
                            f"⚠️ <b>Регулятор капса:</b> {event.from_user.mention_html()}, "
                            f"не кричите в чате! Сообщение удалено по Статье 2.2 Свода Законов."
                        )
                        return
                    except Exception:
                        pass

        # 3. Проверка несанкционированных ссылок
        if text and chat_settings.anti_link_enabled:
            if URL_REGEX.search(text):
                try:
                    await event.delete()
                    await event.answer(
                        f"🚫 <b>Регулятор рекламы:</b> {event.from_user.mention_html()}, "
                        f"публикация сторонних ссылок запрещена (Статья 2.4 Свода Законов)."
                    )
                    return
                except Exception:
                    pass

        return await handler(event, data)
