import logging
from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.topic_config import TopicConfig
from config import settings
from core.enums import TopicType

logger = logging.getLogger("townbot.topics")

# Стандартные названия типов тем для понятного вывода гражданам
TOPIC_TYPE_TITLES: dict[str, str] = {
    TopicType.COMMUNITY.value: "Общий чат / Флудилка",
    TopicType.REPORTS.value: "Жалобы / Модерация",
    TopicType.TICKETS.value: "Приемная граждан",
    TopicType.COURT.value: "Зал Суда / Апелляции",
    TopicType.ADMIN.value: "Штаб / Кабинет администрации",
    TopicType.DECREES.value: "Государственные указы и законы",
    TopicType.LOGS.value: "Служебный аудит и логи",
}


class TopicService:
    """Сервис управления и валидации форумных тем супергруппы."""

    @classmethod
    async def get_topic_thread_id(
        cls, session: AsyncSession, chat_id: int, topic_type: str
    ) -> Optional[int]:
        """
        Возвращает thread_id (message_thread_id) для указанного типа темы.
        Сначала ищет в БД (TopicConfig), затем проверяет fallback из settings (config.py).
        """
        query = select(TopicConfig).where(
            TopicConfig.chat_id == chat_id,
            TopicConfig.topic_type == topic_type,
        )
        conf = await session.scalar(query)
        if conf and conf.thread_id:
            return conf.thread_id

        # Fallback на настройки .env / config
        fallback_map = {
            TopicType.COMMUNITY.value: settings.COMMUNITY_TOPIC_ID,
            TopicType.REPORTS.value: settings.REPORTS_TOPIC_ID,
            TopicType.TICKETS.value: settings.TICKETS_TOPIC_ID,
            TopicType.COURT.value: settings.COURT_TOPIC_ID,
            TopicType.ADMIN.value: settings.ADMIN_TOPIC_ID,
            TopicType.DECREES.value: settings.DECREES_TOPIC_ID,
            TopicType.LOGS.value: settings.LOG_TOPIC_ID,
        }
        return fallback_map.get(topic_type)

    @classmethod
    async def get_topic_name(
        cls, session: AsyncSession, chat_id: int, thread_id: Optional[int]
    ) -> str:
        """Возвращает человекопонятное название темы по ее thread_id."""
        if not thread_id:
            return "Основной чат"

        query = select(TopicConfig).where(
            TopicConfig.chat_id == chat_id,
            TopicConfig.thread_id == thread_id,
        )
        conf = await session.scalar(query)
        if conf and conf.topic_name:
            return conf.topic_name

        # Проверка fallback соответствий
        if thread_id == settings.COMMUNITY_TOPIC_ID:
            return "Общий чат"
        if thread_id == settings.REPORTS_TOPIC_ID:
            return "Жалобы"
        if thread_id == settings.TICKETS_TOPIC_ID:
            return "Приемная граждан"
        if thread_id == settings.COURT_TOPIC_ID:
            return "Зал Суда"
        if thread_id == settings.ADMIN_TOPIC_ID:
            return "Штаб администрации"
        if thread_id == settings.DECREES_TOPIC_ID:
            return "Указы и законы"
        if thread_id == settings.LOG_TOPIC_ID:
            return "Аудит и логи"

        return f"Тема #{thread_id}"

    @classmethod
    async def set_topic_mapping(
        cls,
        session: AsyncSession,
        chat_id: int,
        topic_type: str,
        thread_id: int,
        topic_name: str,
    ) -> TopicConfig:
        """Привязывает thread_id к указанному функциональному типу темы."""
        query = select(TopicConfig).where(
            TopicConfig.chat_id == chat_id,
            TopicConfig.topic_type == topic_type,
        )
        conf = await session.scalar(query)
        if not conf:
            conf = TopicConfig(
                chat_id=chat_id,
                topic_type=topic_type,
                thread_id=thread_id,
                topic_name=topic_name,
            )
            session.add(conf)
        else:
            conf.thread_id = thread_id
            conf.topic_name = topic_name

        await session.commit()
        await session.refresh(conf)
        logger.info(
            "Топик '%s' (%s) для чата %s привязан к thread_id=%s",
            topic_name,
            topic_type,
            chat_id,
            thread_id,
        )
        return conf

    @classmethod
    async def validate_jurisdiction(
        cls,
        session: AsyncSession,
        chat_id: int,
        current_thread_id: Optional[int],
        allowed_types: List[str],
    ) -> Tuple[bool, str, str]:
        """
        Проверяет юрисдикцию команды.
        Возвращает кортеж: (is_allowed, current_topic_name, target_topic_name).
        """
        current_topic_name = await cls.get_topic_name(session, chat_id, current_thread_id)

        target_names = [TOPIC_TYPE_TITLES.get(t, t) for t in allowed_types]
        target_display = " / ".join(target_names)

        # Если темы в чате не настроены вообще — разрешаем выполнение
        all_configs_query = select(TopicConfig).where(TopicConfig.chat_id == chat_id)
        existing_configs = (await session.scalars(all_configs_query)).all()
        has_any_topic_configured = bool(
            existing_configs
            or settings.COMMUNITY_TOPIC_ID
            or settings.REPORTS_TOPIC_ID
            or settings.TICKETS_TOPIC_ID
            or settings.COURT_TOPIC_ID
            or settings.ADMIN_TOPIC_ID
        )

        if not has_any_topic_configured:
            return True, current_topic_name, target_display

        # Проверяем, совпадает ли current_thread_id с хотя бы одной разрешенной темой
        for t_type in allowed_types:
            allowed_thread_id = await cls.get_topic_thread_id(session, chat_id, t_type)
            if allowed_thread_id is not None and current_thread_id == allowed_thread_id:
                return True, current_topic_name, target_display

        return False, current_topic_name, target_display
