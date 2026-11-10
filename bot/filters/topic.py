import asyncio
import logging
from typing import List, Union, Optional
from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from core.topic_service import TopicService
from core.hierarchy_service import HierarchyService
from core.enums import PositionLevel

logger = logging.getLogger("townbot.filters.topic")


async def auto_delete_messages(bot, chat_id: int, message_ids: List[int], delay: float = 6.0) -> None:
    """Удаляет указанные сообщения через delay секунд, не захламляя форумные темы."""
    await asyncio.sleep(delay)
    for mid in message_ids:
        if not mid:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


class TopicCommandFilter(BaseFilter):
    """
    Фильтр юрисдикции тем форума (Forum Topics Filter).
    Проверяет, разрешена ли команда в текущей теме (message_thread_id).

    Если вызвана в неразрешенной теме:
    - Отправляет сообщение об ошибке юрисдикции.
    - Автоматически удаляет исходную команду и предупреждение бота через 6 секунд.
    - Возвращает False.

    Ранг 4 (Высшая администрация) и Владелец обладают юрисдикционным иммунитетом.
    В личных сообщениях с ботом фильтр автоматически пропускает команду.
    """

    def __init__(
        self,
        allowed_topics: Union[List[str], str],
        immunity_min_level: int = PositionLevel.SENIOR_ADMINISTRATION.value,
    ):
        if isinstance(allowed_topics, str):
            self.allowed_topics = [allowed_topics]
        else:
            self.allowed_topics = list(allowed_topics)
        self.immunity_min_level = immunity_min_level

    async def __call__(
        self, message: Message, session: AsyncSession, db_user: Optional[User] = None
    ) -> bool:
        # В личных сообщениях с ботом ограничения тем форума не действуют
        if message.chat.type == "private":
            return True

        # Юрисдикционный иммунитет для Владельца и Высшей администрации (Ранг 4)
        if db_user:
            if HierarchyService.is_owner(db_user):
                return True
            if db_user.role_level >= self.immunity_min_level:
                return True

        current_thread_id = getattr(message, "message_thread_id", None)
        chat_id = message.chat.id

        # Проверка юрисдикции через сервис
        is_allowed, current_name, target_name = await TopicService.validate_jurisdiction(
            session=session,
            chat_id=chat_id,
            current_thread_id=current_thread_id,
            allowed_types=self.allowed_topics,
        )

        if is_allowed:
            return True

        # Ошибка юрисдикции
        cmd_text = (message.text or "").split()[0] if message.text else "Команда"

        warning_text = (
            f"⚠️ <b>Ошибка юрисдикции!</b>\n"
            f"Команда <code>{cmd_text}</code> не может быть выполнена в теме «{current_name}».\n"
            f"Пожалуйста, перейдите в тему: «<b>{target_name}</b>»."
        )

        try:
            warning_msg = await message.answer(
                warning_text,
                message_thread_id=current_thread_id,
            )
            # Запускаем автоудаление обоих сообщений через 6 секунд
            to_delete = [message.message_id, warning_msg.message_id]
            asyncio.create_task(
                auto_delete_messages(
                    bot=message.bot,
                    chat_id=chat_id,
                    message_ids=to_delete,
                    delay=6.0,
                )
            )
        except Exception as e:
            logger.debug("Не удалось отправить/удалить предупреждение юрисдикции: %s", e)

        return False
