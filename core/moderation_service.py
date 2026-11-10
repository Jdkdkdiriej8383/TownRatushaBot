import re
import logging
from datetime import datetime, timezone
from typing import Optional
from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from db.models.punishment import Punishment
from core.enums import PunishmentType, PositionLevel, TopicType
from core.hierarchy_service import HierarchyService
from core.topic_service import TopicService
from core.exceptions import TownBaseException

logger = logging.getLogger("townbot.moderation")

# 3 варна = авто-мут на 24 часа, 5 варнов = авто-бан
WARNS_MUTE_THRESHOLD = 3
WARNS_BAN_THRESHOLD = 5
WARNS_MUTE_DURATION = 86400  # 24 часа в секундах


def parse_duration(time_str: str) -> Optional[int]:
    """Парсит строку вида '15m', '1h', '2d', '30s', '24ч', '2д' в секунды."""
    if not time_str:
        return None
    time_str = time_str.strip().lower()
    units = {
        "s": 1, "с": 1, "sec": 1, "сек": 1,
        "m": 60, "м": 60, "min": 60, "мин": 60,
        "h": 3600, "ч": 3600, "час": 3600,
        "d": 86400, "д": 86400, "день": 86400, "дн": 86400,
    }
    match = re.match(r"^(\d+)([a-zA-Zа-яА-Я]+)?$", time_str)
    if not match:
        return None
    val = int(match.group(1))
    unit = match.group(2)
    if not unit:
        return val * 60  # по умолчанию считаем в минутах
    mult = units.get(unit)
    if mult:
        return val * mult
    return None


class ModerationService:
    """Сервис исполнения наказаний, субординации и прогрессии варнов."""

    @classmethod
    async def log_punishment(
        cls,
        session: AsyncSession,
        target_user: User,
        issuer_user: User,
        punishment_type: PunishmentType | str,
        reason: str,
        duration_seconds: Optional[int] = None,
        law_article: Optional[str] = None,
    ) -> Punishment:
        """Сохраняет запись о взыскании в судебно-следственный протокол."""
        p_type = punishment_type.value if hasattr(punishment_type, "value") else str(punishment_type)
        punishment = Punishment(
            user_id=target_user.id,
            target_telegram_id=target_user.telegram_id,
            issuer_id=issuer_user.id,
            issuer_telegram_id=issuer_user.telegram_id,
            punishment_type=p_type,
            duration_seconds=duration_seconds,
            law_article=law_article,
            reason=reason,
        )
        session.add(punishment)
        await session.commit()
        await session.refresh(punishment)
        return punishment

    @classmethod
    async def apply_warn(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        reason: str,
    ) -> tuple[int, bool, bool, str, Punishment]:
        """
        Выдает предупреждение (варн) с проверкой субординации и авто-эскалацией.
        Возвращает: (warns_count, auto_muted, auto_banned, result_message, punishment).
        """
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="предупреждение")

        target.warns_count = (target.warns_count or 0) + 1
        current_warns = target.warns_count

        auto_muted = False
        auto_banned = False
        extra_note = ""

        # Фиксируем варн в протоколе
        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.WARN,
            reason=reason,
        )

        # 5 варнов -> Авто-бан (изгнание) с правом на апелляцию в Суд
        if current_warns >= WARNS_BAN_THRESHOLD:
            auto_banned = True
            target.is_enemy = True
            target.enemy_reason = f"Лимит предупреждений исчерпан (5/5): {reason}"
            if bot and chat_id:
                try:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=target.telegram_id)
                except Exception as e:
                    logger.warning("Не удалось забанить в Telegram: %s", e)

            await cls.log_punishment(
                session=session,
                target_user=target,
                issuer_user=issuer,
                punishment_type=PunishmentType.BAN,
                reason=f"Автоматический бан за 5/5 предупреждений: {reason}",
            )
            extra_note = "\n🚨 <b>Достигнут лимит варнов (5/5)!</b> Нарушитель изгнан из города. Апелляция возможна в Зале Суда (/appeal)."

        # 3 варна -> Авто-мут на 24 часа
        elif current_warns == WARNS_MUTE_THRESHOLD:
            auto_muted = True
            until_dt = datetime.fromtimestamp(
                int(datetime.now(timezone.utc).timestamp()) + WARNS_MUTE_DURATION,
                tz=timezone.utc,
            )
            if bot and chat_id:
                try:
                    await bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=target.telegram_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until_dt,
                    )
                except Exception as e:
                    logger.warning("Не удалось замутить в Telegram: %s", e)

            await cls.log_punishment(
                session=session,
                target_user=target,
                issuer_user=issuer,
                punishment_type=PunishmentType.MUTE,
                duration_seconds=WARNS_MUTE_DURATION,
                reason=f"Автоматический мут на 24ч за 3/5 предупреждений: {reason}",
            )
            extra_note = "\n⚠️ <b>3-е предупреждение!</b> Включен автоматический мут на 24 часа."

        await session.commit()
        return current_warns, auto_muted, auto_banned, extra_note, punishment

    @classmethod
    async def remove_warn(
        cls, session: AsyncSession, issuer: User, target: User, reason: str
    ) -> tuple[int, Punishment]:
        """Снимает одно предупреждение с нарушителя."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="снятие варна")

        current_warns = target.warns_count or 0
        if current_warns <= 0:
            raise TownBaseException(f"У пользователя {target.full_name} нет активных предупреждений (0/5).")

        target.warns_count = current_warns - 1

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.UNWARN,
            reason=reason,
        )
        await session.commit()
        return target.warns_count, punishment

    @classmethod
    async def apply_mute(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        duration_seconds: int,
        reason: str,
    ) -> Punishment:
        """Применяет временное ограничение отправки сообщений (мут)."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="мут")

        max_allowed = HierarchyService.get_max_mute_seconds(issuer)
        if duration_seconds > max_allowed:
            raise TownBaseException(
                f"🚫 Ваша должность ({issuer.position_title}) позволяет выдавать мут максимум на "
                f"{max_allowed // 3600} ч. Запрошено: {duration_seconds // 3600} ч."
            )

        until_dt = datetime.fromtimestamp(
            int(datetime.now(timezone.utc).timestamp()) + duration_seconds,
            tz=timezone.utc,
        )

        if bot and chat_id:
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target.telegram_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_dt,
                )
            except Exception as e:
                logger.warning("Ошибка Telegram при муте: %s", e)

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.MUTE,
            duration_seconds=duration_seconds,
            reason=reason,
        )
        await session.commit()
        return punishment

    @classmethod
    async def apply_unmute(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        reason: str,
    ) -> Punishment:
        """Снимает мут в Telegram и восстанавливает права отправки сообщений."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="размут")

        if bot and chat_id:
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target.telegram_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
            except Exception as e:
                logger.warning("Ошибка Telegram при размуте: %s", e)

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.UNMUTE,
            reason=reason,
        )
        await session.commit()
        return punishment

    @classmethod
    async def apply_kick(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        reason: str,
    ) -> Punishment:
        """Исключает участника из чата без постоянной блокировки (кик)."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="кик")

        if bot and chat_id:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=target.telegram_id)
                await bot.unban_chat_member(chat_id=chat_id, user_id=target.telegram_id)
            except Exception as e:
                logger.warning("Ошибка Telegram при кике: %s", e)

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.KICK,
            reason=reason,
        )
        await session.commit()
        return punishment

    @classmethod
    async def apply_ban(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        reason: str,
    ) -> Punishment:
        """Применяет бан (изгнание). Доступно только Администрации от Ранга 3 и Овнеру."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="бан")

        if not HierarchyService.can_ban(issuer):
            raise TownBaseException(
                "🚫 <b>Блюстители не могут банить без санкции Судьи или Министра!</b>\n"
                "Запросите судебную санкцию на изгнание в Зале Суда (/court)."
            )

        target.is_enemy = True
        target.enemy_reason = reason
        target.role_level = PositionLevel.ENEMY.value

        if bot and chat_id:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=target.telegram_id)
            except Exception as e:
                logger.warning("Ошибка Telegram при бане: %s", e)

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.BAN,
            reason=reason,
        )
        await session.commit()
        return punishment

    @classmethod
    async def apply_unban(
        cls,
        session: AsyncSession,
        bot: Optional[Bot],
        chat_id: int,
        issuer: User,
        target: User,
        reason: str,
    ) -> Punishment:
        """Снимает бан в Telegram и восстанавливает гражданство."""
        HierarchyService.validate_seniority(initiator=issuer, target=target, action_name="разбан")

        target.is_enemy = False
        target.enemy_reason = None
        if target.role_level == PositionLevel.ENEMY.value:
            target.role_level = PositionLevel.CITIZEN.value

        if bot and chat_id:
            try:
                await bot.unban_chat_member(chat_id=chat_id, user_id=target.telegram_id, only_if_banned=True)
            except Exception as e:
                logger.warning("Ошибка Telegram при разбане: %s", e)

        punishment = await cls.log_punishment(
            session=session,
            target_user=target,
            issuer_user=issuer,
            punishment_type=PunishmentType.UNBAN,
            reason=reason,
        )
        await session.commit()
        return punishment

    @classmethod
    async def send_audit_log(
        cls,
        bot: Bot,
        session: AsyncSession,
        chat_id: int,
        target: User,
        issuer: User,
        action_title: str,
        reason: str,
        duration_str: Optional[str] = None,
        punishment_id: Optional[int] = None,
    ) -> None:
        """Отправляет карточку протокола наказания в тему LOG_TOPIC_ID."""
        log_thread_id = await TopicService.get_topic_thread_id(session, chat_id, TopicType.LOGS.value)
        pid_text = f" #{punishment_id}" if punishment_id else ""
        dur_text = f"\n• <b>Срок действия:</b> {duration_str}" if duration_str else ""
        card = (
            f"🛡️ <b>ПРОТОКОЛ НАКАЗАНИЯ{pid_text}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Нарушитель:</b> @{target.username or '—'} (ID: <code>{target.telegram_id}</code>)\n"
            f"• <b>Модератор:</b> @{issuer.username or '—'} (Ранг {issuer.government_rank}, {issuer.position_title})\n"
            f"• <b>Тип наказания:</b> <b>{action_title}</b>\n"
            f"• <b>Причина:</b> <i>{reason}</i>"
            f"{dur_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=log_thread_id,
                text=card,
            )
        except Exception as e:
            logger.warning("Не удалось отправить протокол наказания в тему аудита: %s", e)
