from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Regulator
from core.enums import PositionLevel
from core.exceptions import (
    SubordinationViolationError,
    RegulatorLimitExceededError,
    EnemyOfTownError,
    SelfPunishmentError,
)


def format_duration(seconds: int) -> str:
    """Форматирует секунды в человекочитаемый вид."""
    if seconds <= 0:
        return "бессрочно / мгновенно"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0:
        parts.append(f"{minutes} мин.")
    if secs > 0 and not parts:
        parts.append(f"{secs} сек.")
    return " ".join(parts) if parts else f"{seconds} сек."


class RegulatorService:
    """
    Сервис контроля полномочий и субординации.
    Гарантирует строгое исполнение Городского Свода Законов
    и защищает иерархию властей от самоуправства.
    """

    @staticmethod
    async def get_regulator(session: AsyncSession, role_level: int) -> Regulator:
        query = select(Regulator).where(Regulator.role_level == role_level)
        reg = await session.scalar(query)
        if not reg:
            # Fallback на дефолтные безопасные ограничения
            return Regulator(
                role_level=role_level,
                title=PositionLevel.get_title(role_level),
                max_mute_time=0,
                max_fine_amount=0,
                can_ban=False,
                can_edit_laws=False,
                can_appoint_level=-1,
                can_create_referendum=False,
            )
        return reg

    @classmethod
    def check_subordination(cls, issuer: User, target: User) -> None:
        """
        Проверка субординации:
        Блюститель может наказывать ТОЛЬКО пользователей с должностью СТРОГО ниже своей!
        """
        if issuer.telegram_id == target.telegram_id:
            raise SelfPunishmentError()

        if issuer.is_enemy:
            raise EnemyOfTownError(reason="Поражение в правах. Враг города не имеет полномочий.")

        # Уровень цели
        target_effective_level = PositionLevel.ENEMY.value if target.is_enemy else target.role_level

        # Если должность блюстителя не строго выше должности цели
        if issuer.role_level <= target_effective_level:
            raise SubordinationViolationError(
                issuer_title=issuer.position_title,
                target_title=target.position_title
            )

    @classmethod
    async def validate_mute(
        cls,
        session: AsyncSession,
        issuer: User,
        target: User,
        duration_seconds: int
    ) -> Regulator:
        cls.check_subordination(issuer, target)
        regulator = await cls.get_regulator(session, issuer.role_level)

        if regulator.max_mute_time <= 0:
            raise RegulatorLimitExceededError(
                f"🚫 Ваша должность <b>«{regulator.title}»</b> не наделена правом ограничивать речь граждан (выдавать мут)."
            )

        if duration_seconds > regulator.max_mute_time:
            raise RegulatorLimitExceededError(
                f"🚫 <b>Превышение лимита полномочий!</b>\n\n"
                f"Должность: <b>{regulator.title}</b>\n"
                f"Максимальный допустимый мут: <b>{format_duration(regulator.max_mute_time)}</b>\n"
                f"Запрошено: <b>{format_duration(duration_seconds)}</b>."
            )

        return regulator

    @classmethod
    async def validate_fine(
        cls,
        session: AsyncSession,
        issuer: User,
        target: User,
        amount: int,
        is_chat_section: bool = False
    ) -> Regulator:
        cls.check_subordination(issuer, target)
        regulator = await cls.get_regulator(session, issuer.role_level)

        if regulator.max_fine_amount <= 0:
            raise RegulatorLimitExceededError(
                f"🚫 Ваша должность <b>«{regulator.title}»</b> не наделена правом выписывать денежные штрафы."
            )

        # Особый регламент для уровня 2 (Блюститель чата): штрафы только по разделу II
        if issuer.role_level == PositionLevel.CHAT_WARDEN.value and not is_chat_section:
            raise RegulatorLimitExceededError(
                f"🚫 Должность <b>«{regulator.title}»</b> имеет право выписывать штрафы "
                f"<b>исключительно по статьям Раздела II (Чат Telegram)</b>!"
            )

        if amount > regulator.max_fine_amount:
            raise RegulatorLimitExceededError(
                f"🚫 <b>Превышение лимита штрафа!</b>\n\n"
                f"Должность: <b>{regulator.title}</b>\n"
                f"Максимальный допустимый штраф: <b>{regulator.max_fine_amount:,} валюты</b>\n"
                f"Запрошено: <b>{amount:,} валюты</b>."
            )

        return regulator

    @classmethod
    async def validate_ban(
        cls,
        session: AsyncSession,
        issuer: User,
        target: User,
        duration_seconds: int = 0
    ) -> Regulator:
        cls.check_subordination(issuer, target)
        regulator = await cls.get_regulator(session, issuer.role_level)

        if not regulator.can_ban:
            raise RegulatorLimitExceededError(
                f"🚫 Ваша должность <b>«{regulator.title}»</b> не наделена правом изгнания (бана) граждан."
            )

        if regulator.max_ban_time > 0 and (duration_seconds == 0 or duration_seconds > regulator.max_ban_time):
            raise RegulatorLimitExceededError(
                f"🚫 <b>Превышение срока изгнания!</b>\n\n"
                f"Должность: <b>{regulator.title}</b>\n"
                f"Максимальный срок бана: <b>{format_duration(regulator.max_ban_time)}</b>."
            )

        return regulator

    @classmethod
    async def validate_edit_laws(cls, session: AsyncSession, issuer: User) -> Regulator:
        if issuer.is_enemy:
            raise EnemyOfTownError()

        regulator = await cls.get_regulator(session, issuer.role_level)
        if not regulator.can_edit_laws:
            raise RegulatorLimitExceededError(
                f"🚫 Редактирование Городского Свода Законов разрешено "
                f"только Администрации и Старшей администрации (уровни 4-5). "
                f"Ваша должность: <b>«{regulator.title}»</b>."
            )
        return regulator

    @classmethod
    async def validate_appointment(
        cls,
        session: AsyncSession,
        issuer: User,
        target: User,
        new_level: int
    ) -> Regulator:
        if issuer.telegram_id == target.telegram_id:
            raise SelfPunishmentError()

        if issuer.is_enemy:
            raise EnemyOfTownError()

        regulator = await cls.get_regulator(session, issuer.role_level)

        if regulator.can_appoint_level < 0:
            raise RegulatorLimitExceededError(
                f"🚫 Должность <b>«{regulator.title}»</b> не имеет полномочий по назначению и снятию с должностей."
            )

        # Нельзя менять должность тому, кто выше или равен по должности
        if issuer.role_level <= target.role_level and issuer.role_level < PositionLevel.SENIOR_ADMINISTRATION.value:
            raise SubordinationViolationError(issuer.position_title, target.position_title)

        # Нельзя назначить должность выше своего разрешенного лимита назначения
        if new_level > regulator.can_appoint_level:
            raise RegulatorLimitExceededError(
                f"🚫 Вы не можете назначить должность уровня {new_level} (<b>{PositionLevel.get_title(new_level)}</b>).\n"
                f"Ваш максимальный уровень назначения: <b>{PositionLevel.get_title(regulator.can_appoint_level)}</b> ({regulator.can_appoint_level})."
            )

        # Нельзя назначить должность выше своей собственной
        if new_level >= issuer.role_level and issuer.role_level < PositionLevel.SENIOR_ADMINISTRATION.value:
            raise RegulatorLimitExceededError(
                "🚫 Вы не можете назначить жителя на должность, равную или превышающую вашу собственную!"
            )

        return regulator
