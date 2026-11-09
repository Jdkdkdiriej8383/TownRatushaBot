import re
import time
import logging
from typing import Callable, Dict, Any, Awaitable
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import Message, ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import ChatSettings, User
from core.enums import PositionLevel
from config import settings

logger = logging.getLogger("townbot.chat_regulator")

# In-memory трекер для медиа-спама (user_id -> list of timestamps)
_media_tracker: Dict[int, list[float]] = defaultdict(list)

# Регулярное выражение для поиска ссылок
URL_REGEX = re.compile(
    r"(https?://\S+|t\.me/\S+|telegram\.me/\S+|discord\.gg/\S+|vk\.com/\S+|[a-zA-Z0-9-]+\.(?:com|ru|org|net|io|me|xyz|top|gg|site|online)/?\S*)",
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

        # Боты не модерируются
        if event.from_user and getattr(event.from_user, "is_bot", False) is True:
            return await handler(event, data)

        db_user: User | None = data.get("db_user")
        session: AsyncSession | None = data.get("session")

        # Проверка статуса владельца и администрации
        is_owner = False
        if db_user:
            is_owner = (
                db_user.telegram_id == settings.OWNER_ID
                or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
            )
        elif event.from_user:
            is_owner = (
                event.from_user.id == settings.OWNER_ID
                or (event.from_user.username and event.from_user.username.lower() == settings.OWNER_USERNAME.lower())
            )

        is_staff = is_owner or bool(db_user and db_user.role_level >= PositionLevel.ASSISTANT.value)

        # Загружаем настройки регуляторов для чата
        chat_settings = None
        if session:
            try:
                settings_query = select(ChatSettings).where(ChatSettings.chat_id == event.chat.id)
                chat_settings = await session.scalar(settings_query)
                if not chat_settings:
                    chat_settings = ChatSettings(chat_id=event.chat.id)
                    session.add(chat_settings)
                    await session.flush()
            except Exception as e:
                logger.warning("Ошибка при загрузке ChatSettings: %s", e)
                try:
                    await session.rollback()
                except Exception:
                    pass

        if not chat_settings:
            chat_settings = ChatSettings(chat_id=event.chat.id)

        user_id = event.from_user.id if event.from_user else 0
        mention = event.from_user.mention_html() if event.from_user else "Участник"
        now = time.time()

        async def safe_delete():
            try:
                await event.delete()
            except Exception as e:
                logger.debug("Не удалось удалить сообщение: %s", e)

        async def safe_mute(seconds: int):
            if is_staff:
                return  # Персонал и Владелец не подвергаются муту
            try:
                until = int(now + seconds)
                await event.bot.restrict_chat_member(
                    chat_id=event.chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception as e:
                logger.debug("Не удалось замутить участника: %s", e)

        # 1. Проверка на медиа-спам (стикеры, ГС, видеосообщения/кружки, фото, видео)
        is_media = bool(event.sticker or event.voice or event.video_note or event.photo or event.video or event.animation)
        if is_media and chat_settings.media_spam_enabled:
            tracker = _media_tracker[user_id]
            # Очищаем события старше 15 секунд
            tracker = [t for t in tracker if now - t < 15]
            tracker.append(now)
            _media_tracker[user_id] = tracker

            if len(tracker) > chat_settings.media_spam_threshold:
                await safe_delete()
                await safe_mute(chat_settings.auto_mute_seconds)
                try:
                    await event.answer(
                        f"🛑 <b>Регулятор медиа-спама!</b>\n"
                        f"{mention} временно ограничен в речи на 30 мин "
                        f"за отправку более {chat_settings.media_spam_threshold} медиа подряд (Статья 2.3)."
                    )
                except Exception:
                    pass
                return

        text = event.text or event.caption or ""
        is_command = text.startswith("/") or text.lower().strip() in (
            "паспорт", "мой паспорт", "профиль", "стат", "стата",
            "помощь", "хелп", "help", "команды", "законы", "правила",
            "регуляторы", "регулятор", "созвать", "созвать всех"
        )

        # 2. Проверка анти-капса (>70% заглавных букв при длине от 6)
        if text and chat_settings.anti_caps_enabled and not is_command:
            letters = [c for c in text if c.isalpha()]
            if len(letters) >= chat_settings.anti_caps_min_chars:
                upper_count = sum(1 for c in letters if c.isupper())
                ratio = upper_count / len(letters)
                if ratio >= chat_settings.anti_caps_threshold:
                    await safe_delete()
                    if db_user and not is_staff:
                        db_user.warns_count += 1
                        if session:
                            try:
                                await session.commit()
                            except Exception:
                                pass
                    try:
                        await event.answer(
                            f"⚠️ <b>Регулятор капса:</b> {mention}, "
                            f"не кричите в чате! Сообщение удалено по Статье 2.2 Свода Законов."
                        )
                    except Exception:
                        pass
                    return

        # 3. Проверка несанкционированных ссылок
        if text and chat_settings.anti_link_enabled and not text.startswith("/"):
            found_urls = []
            entities = list(getattr(event, "entities", None) or []) + list(getattr(event, "caption_entities", None) or [])
            for ent in entities:
                ent_type = getattr(ent, "type", "")
                if ent_type == "url":
                    offset = getattr(ent, "offset", 0)
                    length = getattr(ent, "length", 0)
                    found_urls.append(text[offset:offset + length])
                elif ent_type == "text_link" and getattr(ent, "url", None):
                    found_urls.append(ent.url)

            for match in URL_REGEX.finditer(text):
                found_urls.append(match.group(0))

            disallowed = False
            for u in found_urls:
                u_low = u.lower()
                if "teletype.in/@townratushabot" in u_low or settings.RULES_URL.lower() in u_low:
                    continue
                disallowed = True
                break

            if disallowed:
                await safe_delete()
                await safe_mute(chat_settings.auto_mute_seconds)
                try:
                    await event.answer(
                        f"🚫 <b>Регулятор рекламы:</b> {mention}, "
                        f"публикация сторонних ссылок запрещена (Статья 2.4 Свода Законов)."
                    )
                except Exception:
                    pass
                return

        return await handler(event, data)
