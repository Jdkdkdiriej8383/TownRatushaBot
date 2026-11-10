import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from core.enums import PositionLevel, GovernmentRole, TopicType
from core.report_service import ReportService
from core.moderation_service import ModerationService
from core.topic_service import TopicService
from core.hierarchy_service import HierarchyService
from core.exceptions import TownBaseException
from bot.filters.topic import auto_delete_messages
from config import settings

logger = logging.getLogger("townbot.reports")
router = Router(name="reports_router")


def get_report_inline_keyboard(report_id: int) -> InlineKeyboardMarkup:
    """Создает кнопки управления жалобой для сотрудников модерации."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✋ Взять в работу", callback_data=f"rep_claim:{report_id}"),
            ],
            [
                InlineKeyboardButton(text="🔇 Мут 15м", callback_data=f"rep_mute:{report_id}:900"),
                InlineKeyboardButton(text="🔇 1ч", callback_data=f"rep_mute:{report_id}:3600"),
                InlineKeyboardButton(text="🔇 24ч", callback_data=f"rep_mute:{report_id}:86400"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Выдать варн", callback_data=f"rep_warn:{report_id}"),
                InlineKeyboardButton(text="🔨 Бан (изгнание)", callback_data=f"rep_ban:{report_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Ложный вызов", callback_data=f"rep_false:{report_id}"),
            ],
        ]
    )


@router.message(Command("report", "репорт", "жалоба"))
@router.message(F.text.startswith("!жб") | F.text.startswith("!report"))
async def cmd_report(message: Message, session: AsyncSession, db_user: User):
    """
    Подача жалобы гражданином на сообщение нарушителя.
    Удаляет исходную команду, чтобы нарушитель не увидел факт доноса,
    и конфиденциально направляет карточку инцидента должностям от Блюстителя и выше
    (Блюстители, Министры, Зам. мэра, Мэр, Судьи, Конст. судья, Премьер-министр).
    """
    # 1. Сразу удаляем сообщение с командой заявителя (полная конфиденциальность)
    try:
        await message.delete()
    except Exception:
        pass

    if not message.reply_to_message:
        # Уведомляем заявителя во временном исчезающем сообщении
        hint = await message.answer(
            "⚠️ Чтобы подать жалобу, ответьте командой <code>/report [причина]</code> (или <code>!жб [причина]</code>) "
            "на сообщение нарушителя!"
        )
        asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=5.0))
        return

    violator_tg_user = message.reply_to_message.from_user
    if not violator_tg_user or violator_tg_user.is_bot:
        return

    # Получаем/регистрируем нарушителя в БД
    violator_res = await session.scalar(select(User).where(User.telegram_id == violator_tg_user.id))
    if not violator_res:
        violator_res = User(
            telegram_id=violator_tg_user.id,
            username=violator_tg_user.username,
            full_name=violator_tg_user.full_name,
            role_level=PositionLevel.CITIZEN.value,
        )
        session.add(violator_res)
        await session.commit()
        await session.refresh(violator_res)

    # Парсим причину
    text_content = message.text or ""
    parts = text_content.split(maxsplit=1)
    reason = parts[1].strip() if len(parts) > 1 else "Нарушение порядка"

    current_thread_id = getattr(message, "message_thread_id", None)
    incident_topic_name = await TopicService.get_topic_name(session, message.chat.id, current_thread_id)

    reported_text = message.reply_to_message.text or message.reply_to_message.caption or "[Медиа-контент / стикер]"

    try:
        report = await ReportService.create_report(
            session=session,
            reporter=db_user,
            violator=violator_res,
            incident_topic_id=current_thread_id,
            incident_topic_name=incident_topic_name,
            message_id=message.reply_to_message.message_id,
            message_text=reported_text,
            reason=reason,
            chat_id=message.chat.id,
        )
    except TownBaseException as e:
        hint = await message.answer(e.message)
        asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=5.0))
        return

    # Карточка жалобы строго для должностных лиц (от Блюстителя и выше)
    card = (
        f"🚨 <b>ЖАЛОБА #{report.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Заявитель:</b> @{db_user.username or '—'} (ID: <code>{db_user.telegram_id}</code>)\n"
        f"• <b>Нарушитель:</b> @{violator_res.username or '—'} (ID: <code>{violator_res.telegram_id}</code>)\n"
        f"• <b>Должность нарушителя:</b> {violator_res.position_title} (Ранг {violator_res.government_rank})\n"
        f"• <b>Тема инцидента:</b> «{incident_topic_name}»\n"
        f"• <b>Причина:</b> <b>{reason}</b>\n"
        f"• <b>Текст сообщения:</b> <i>«{reported_text[:400]}»</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👮 <i>Ожидает рассмотрения дежурным Блюстителем или Администрацией.</i>"
    )

    # 1. В чате нарушителя и группы пишем только тихое исчезающее подтверждение заявителю
    confidential_hint = await message.answer(
        "🔒 <b>Жалоба принята конфиденциально!</b>\n"
        "Информация передана дежурным Блюстителям и Администрации города."
    )
    asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [confidential_hint.message_id], delay=5.0))

    # 2. Находим всех сотрудников от Ранга 2 (Блюститель) и выше (Блюстители, Министры, Зам. мэра, Мэр, Судьи, Конст. судья, Премьер-министр) + Овнера
    staff_query = select(User).where(
        (User.role_level >= PositionLevel.CHAT_WARDEN.value) |
        (User.telegram_id == settings.OWNER_ID)
    )
    staff_members = (await session.scalars(staff_query)).all()

    # 3. Отправляем интерактивную карточку в ЛИЧНЫЕ СООБЩЕНИЯ каждому сотруднику
    keyboard = get_report_inline_keyboard(report.id)
    for staff in staff_members:
        try:
            await message.bot.send_message(
                chat_id=staff.telegram_id,
                text=card,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.debug("Не удалось отправить карточку жалобы в ЛС сотруднику %s: %s", staff.telegram_id, e)

    # 4. Если настроен отдельный закрытый топик модерации (не совпадающий с общим чатом и темой инцидента)
    reports_thread_id = await TopicService.get_topic_thread_id(
        session=session, chat_id=message.chat.id, topic_type=TopicType.REPORTS.value
    )
    if reports_thread_id is not None and reports_thread_id != current_thread_id and reports_thread_id != settings.COMMUNITY_TOPIC_ID:
        try:
            sent_card = await message.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=reports_thread_id,
                text=card,
                reply_markup=keyboard,
            )
            report.card_message_id = sent_card.message_id
            await session.commit()
        except Exception as e:
            logger.warning("Не удалось отправить жалобу в топик модерации (%s): %s", reports_thread_id, e)


@router.callback_query(F.data.startswith("rep_claim:"))
async def cb_report_claim(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Закрепляет жалобу за дежурным сотрудником модерации (от Блюстителя и выше)."""
    if not db_user or db_user.government_rank < 2:
        await callback.answer(
            "🚫 Рассматривать жалобы могут только должности от Блюстителя и выше (Блюститель, Министр, Судья, Мэр)!",
            show_alert=True,
        )
        return

    report_id = int(callback.data.split(":")[1])
    try:
        report = await ReportService.claim_report(session, report_id, db_user)
        await callback.answer("Вы приняли жалобу в работу!", show_alert=False)

        if callback.message:
            claimer_name = f"@{db_user.username}" if db_user.username else db_user.full_name
            new_text = (
                f"{callback.message.html_text}\n\n"
                f"✋ <b>В работе у:</b> {db_user.position_title} {claimer_name}"
            )
            await callback.message.edit_text(
                new_text,
                reply_markup=get_report_inline_keyboard(report.id),
            )
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)


@router.callback_query(F.data.startswith("rep_mute:"))
async def cb_report_mute(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Выдача мута нарушителю через карточку жалобы (доступно от Блюстителя)."""
    if not db_user or db_user.government_rank < 2:
        await callback.answer(
            "🚫 Налагать наказания по жалобам могут только должности от Блюстителя и выше!",
            show_alert=True,
        )
        return

    parts = callback.data.split(":")
    report_id = int(parts[1])
    duration = int(parts[2])

    report = await ReportService.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена!", show_alert=True)
        return

    violator = await session.scalar(select(User).where(User.id == report.violator_id))
    if not violator:
        await callback.answer("Нарушитель не найден!", show_alert=True)
        return

    target_chat_id = report.chat_id or settings.MAIN_CHAT_ID or callback.message.chat.id

    try:
        p_log = await ModerationService.apply_mute(
            session=session,
            bot=callback.bot,
            chat_id=target_chat_id,
            issuer=db_user,
            target=violator,
            duration_seconds=duration,
            reason=f"По жалобе #{report.id}: {report.reason}",
        )
        hours = duration // 3600 if duration >= 3600 else duration // 60
        unit = "ч." if duration >= 3600 else "мин."

        await ModerationService.send_audit_log(
            bot=callback.bot,
            session=session,
            chat_id=target_chat_id,
            target=violator,
            issuer=db_user,
            action_title=f"МУТ ({hours} {unit})",
            reason=f"По жалобе #{report.id}: {report.reason}",
            duration_str=f"{hours} {unit}",
            punishment_id=p_log.id,
        )

        await ReportService.resolve_report(
            session=session,
            report_id=report_id,
            staff_user=db_user,
            resolution=f"Выдан мут на {hours} {unit} сотрудником {db_user.position_title}",
        )

        await callback.answer(f"✅ Нарушитель замучен на {hours} {unit}!", show_alert=True)
        if callback.message:
            res_text = (
                f"{callback.message.html_text}\n\n"
                f"✅ <b>РЕШЕНИЕ:</b> Выдан мут на {hours} {unit}\n"
                f"👮 <b>Исполнитель:</b> {db_user.position_title} @{db_user.username or db_user.full_name}"
            )
            await callback.message.edit_text(res_text, reply_markup=None)
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)


@router.callback_query(F.data.startswith("rep_warn:"))
async def cb_report_warn(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Выдача варна нарушителю через карточку жалобы (доступно от Блюстителя)."""
    if not db_user or db_user.government_rank < 2:
        await callback.answer(
            "🚫 Выдавать варны по жалобам могут только должности от Блюстителя и выше!",
            show_alert=True,
        )
        return

    report_id = int(callback.data.split(":")[1])
    report = await ReportService.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена!", show_alert=True)
        return

    violator = await session.scalar(select(User).where(User.id == report.violator_id))
    if not violator:
        await callback.answer("Нарушитель не найден!", show_alert=True)
        return

    target_chat_id = report.chat_id or settings.MAIN_CHAT_ID or callback.message.chat.id

    try:
        warns, auto_muted, auto_banned, extra, p_log = await ModerationService.apply_warn(
            session=session,
            bot=callback.bot,
            chat_id=target_chat_id,
            issuer=db_user,
            target=violator,
            reason=f"По жалобе #{report.id}: {report.reason}",
        )

        await ModerationService.send_audit_log(
            bot=callback.bot,
            session=session,
            chat_id=target_chat_id,
            target=violator,
            issuer=db_user,
            action_title=f"ВАРН ({warns}/5)",
            reason=f"По жалобе #{report.id}: {report.reason}",
            punishment_id=p_log.id,
        )

        await ReportService.resolve_report(
            session=session,
            report_id=report_id,
            staff_user=db_user,
            resolution=f"Выдан варн ({warns}/5) сотрудником {db_user.position_title}",
        )

        await callback.answer(f"⚠️ Предупреждение вынесено ({warns}/5)!", show_alert=True)
        if callback.message:
            res_text = (
                f"{callback.message.html_text}\n\n"
                f"⚠️ <b>РЕШЕНИЕ:</b> Вынесено предупреждение ({warns}/5){extra}\n"
                f"👮 <b>Исполнитель:</b> {db_user.position_title} @{db_user.username or db_user.full_name}"
            )
            await callback.message.edit_text(res_text, reply_markup=None)
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)


@router.callback_query(F.data.startswith("rep_ban:"))
async def cb_report_ban(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Выдача бана (изгнания) через карточку жалобы (Ранг 3+: Администрация, Судьи, Мэр)."""
    if not db_user or db_user.government_rank < 2:
        await callback.answer("🚫 Недостаточно полномочий!", show_alert=True)
        return

    report_id = int(callback.data.split(":")[1])
    report = await ReportService.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена!", show_alert=True)
        return

    violator = await session.scalar(select(User).where(User.id == report.violator_id))
    if not violator:
        await callback.answer("Нарушитель не найден!", show_alert=True)
        return

    # Проверка: Блюстители (Ранг 2) не могут банить без санкции Судьи или Министра
    if not HierarchyService.can_ban(db_user):
        await callback.answer(
            "🚫 Блюстители не могут банить без санкции Судьи или Министра!\nЗапросите судебную санкцию в Зале Суда.",
            show_alert=True,
        )
        return

    target_chat_id = report.chat_id or settings.MAIN_CHAT_ID or callback.message.chat.id

    try:
        p_log = await ModerationService.apply_ban(
            session=session,
            bot=callback.bot,
            chat_id=target_chat_id,
            issuer=db_user,
            target=violator,
            reason=f"По жалобе #{report.id}: {report.reason}",
        )

        await ModerationService.send_audit_log(
            bot=callback.bot,
            session=session,
            chat_id=target_chat_id,
            target=violator,
            issuer=db_user,
            action_title="БАН (ИЗГНАНИЕ)",
            reason=f"По жалобе #{report.id}: {report.reason}",
            punishment_id=p_log.id,
        )

        await ReportService.resolve_report(
            session=session,
            report_id=report_id,
            staff_user=db_user,
            resolution=f"Бан (изгнание) вынесен сотрудником {db_user.position_title}",
        )

        await callback.answer("🔨 Нарушитель забанен и изгнан!", show_alert=True)
        if callback.message:
            res_text = (
                f"{callback.message.html_text}\n\n"
                f"🔨 <b>РЕШЕНИЕ:</b> Изгнание (бан) из города\n"
                f"🏛 <b>Постановил:</b> {db_user.position_title} @{db_user.username or db_user.full_name}"
            )
            await callback.message.edit_text(res_text, reply_markup=None)
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)


@router.callback_query(F.data.startswith("rep_false:"))
async def cb_report_false(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Отклонение жалобы как ложный вызов (доступно от Блюстителя и выше)."""
    if not db_user or db_user.government_rank < 2:
        await callback.answer(
            "🚫 Отклонять жалобы могут только должности от Блюстителя и выше!",
            show_alert=True,
        )
        return

    report_id = int(callback.data.split(":")[1])
    try:
        report, is_blocked = await ReportService.mark_false_report(session, report_id, db_user)
        msg_extra = " (Заявитель заблокирован на 24ч за 3 ложных вызова)" if is_blocked else ""
        await callback.answer(f"❌ Жалоба отклонена как ложный вызов!{msg_extra}", show_alert=True)

        if callback.message:
            res_text = (
                f"{callback.message.html_text}\n\n"
                f"❌ <b>РЕШЕНИЕ:</b> Отклонено как ложный вызов{msg_extra}\n"
                f"👮 <b>Рассмотрел:</b> {db_user.position_title} @{db_user.username or db_user.full_name}"
            )
            await callback.message.edit_text(res_text, reply_markup=None)
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)
