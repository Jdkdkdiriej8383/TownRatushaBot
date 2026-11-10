import asyncio
import logging
from typing import Optional
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
from db.models.chat_settings import ChatSettings
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


async def _get_or_create_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    """Безопасно загружает или создает объект настроек чата."""
    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=chat_id)
        session.add(chat_settings)
        await session.flush()
    return chat_settings


def render_report_settings_text(chat_settings: ChatSettings, topic_name: str) -> str:
    dest_map = {
        "both": "⚡ В оба канала (Личные сообщения + Топик)",
        "pm": "📬 Только в Личные сообщения (ЛС)",
        "topic": "📌 Только в топик форума",
    }
    dest_str = dest_map.get(chat_settings.reports_destination, "⚡ В оба канала")
    anon_str = "🟢 Включена (ник скрыт)" if chat_settings.reports_anonymous else "⚪ Отключена (ник виден)"

    return (
        "⚙️ <b>НАСТРОЙКИ СИСТЕМЫ ЖАЛОБ (REPORTS)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Маршрутизация:</b> {dest_str}\n"
        f"• <b>Анонимность заявителя:</b> {anon_str}\n"
        f"• <b>Топик для жалоб:</b> «{topic_name}»\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Сотрудники модерации (от Блюстителя и выше) должны начать диалог "
        "с ботом в ЛС (/start), чтобы получать карточки жалоб персонально!</i>"
    )


def get_report_settings_keyboard(chat_settings: ChatSettings) -> InlineKeyboardMarkup:
    cur_dest = chat_settings.reports_destination or "both"
    anon_status = "ВЫКЛ ⚪" if not chat_settings.reports_anonymous else "ВКЛ 🟢"

    b_both = f"{'✅ ' if cur_dest == 'both' else ''}⚡ ЛС + Топик"
    b_pm = f"{'✅ ' if cur_dest == 'pm' else ''}📬 Только ЛС"
    b_topic = f"{'✅ ' if cur_dest == 'topic' else ''}📌 Только Топик"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=b_both, callback_data="rep_set:dest:both"),
                InlineKeyboardButton(text=b_pm, callback_data="rep_set:dest:pm"),
                InlineKeyboardButton(text=b_topic, callback_data="rep_set:dest:topic"),
            ],
            [
                InlineKeyboardButton(text=f"🥷 Анонимность: {anon_status}", callback_data="rep_set:toggle_anon"),
            ],
            [
                InlineKeyboardButton(text="🎯 Назначить эту ветку топиком жалоб", callback_data="rep_set:bind_topic"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="rep_set:refresh"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="rep_set:close"),
            ],
        ]
    )


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


@router.message(Command("report_settings", "reportsettings", "reports_settings", "настройки_репортов", "настройка_репортов", "настройки_жалоб", "настройка_жалоб", "настройки"))
@router.message(F.text.lower().in_(["/report_settings", "/настройки_репортов", "/настройки_жалоб", "настройки репортов", "настройки жалоб", "!настройки"]))
async def cmd_report_settings(message: Message, session: AsyncSession, db_user: User):
    """
    Панель управления системой жалоб:
    - Выбор маршрутизации (ЛС / Топик / Оба)
    - Переключение анонимности заявителя
    - Привязка текущего топика
    Доступно Администрации (Ранг 3+), Овнеру города и Администраторам чата в Telegram.
    """
    target_chat_id = message.chat.id
    if message.chat.type == "private":
        target_chat_id = settings.MAIN_CHAT_ID or message.chat.id

    is_admin = False
    if (
        db_user.government_rank >= 3
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    ):
        is_admin = True
    elif message.chat.type in ("group", "supergroup") and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Доступ к настройкам жалоб открыт только для Администрации (Ранг 3+) и Овнера!")
        return

    chat_settings = await _get_or_create_chat_settings(session, target_chat_id)

    topic_id = chat_settings.reports_topic_id
    if topic_id is None:
        topic_id = await TopicService.get_topic_thread_id(
            session=session, chat_id=target_chat_id, topic_type=TopicType.REPORTS.value
        )
    topic_name = await TopicService.get_topic_name(session, target_chat_id, topic_id) if topic_id else "Не привязан (fallback)"

    text = render_report_settings_text(chat_settings, topic_name)
    kb = get_report_settings_keyboard(chat_settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("rep_set:"))
async def cb_report_settings(callback: CallbackQuery, session: AsyncSession, db_user: User):
    is_admin = False
    if (
        db_user.government_rank >= 3
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    ):
        is_admin = True
    elif callback.message and callback.message.chat.type in ("group", "supergroup"):
        try:
            member = await callback.message.chat.get_member(callback.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await callback.answer("🚫 У вас нет прав для изменения настроек жалоб!", show_alert=True)
        return

    chat_settings = await _get_or_create_chat_settings(session, callback.message.chat.id)
    action = callback.data.split(":")[1]

    if action == "dest":
        dest_val = callback.data.split(":")[2]
        chat_settings.reports_destination = dest_val
        await session.commit()
        await callback.answer(f"Маршрутизация изменена на: {dest_val}")

    elif action == "toggle_anon":
        chat_settings.reports_anonymous = not chat_settings.reports_anonymous
        await session.commit()
        state_str = "включена" if chat_settings.reports_anonymous else "отключена"
        await callback.answer(f"Анонимность заявителя {state_str}")

    elif action == "bind_topic":
        thread_id = getattr(callback.message, "message_thread_id", None)
        if thread_id:
            chat_settings.reports_topic_id = thread_id
            await TopicService.set_topic_mapping(
                session=session,
                chat_id=callback.message.chat.id,
                topic_type=TopicType.REPORTS.value,
                thread_id=thread_id,
                topic_name=f"Тема #{thread_id}",
            )
            await session.commit()
            await callback.answer("✅ Текущая ветка форума назначена топиком жалоб!", show_alert=True)
        else:
            chat_settings.reports_topic_id = None
            await session.commit()
            await callback.answer("⚠️ Вы в общем чате. Перейдите в нужную тему форума для привязки.", show_alert=True)

    elif action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    elif action == "refresh":
        await callback.answer("Обновлено")

    topic_id = chat_settings.reports_topic_id
    if topic_id is None:
        topic_id = await TopicService.get_topic_thread_id(
            session=session, chat_id=callback.message.chat.id, topic_type=TopicType.REPORTS.value
        )
    topic_name = await TopicService.get_topic_name(session, callback.message.chat.id, topic_id) if topic_id else "Не привязан (fallback)"

    text = render_report_settings_text(chat_settings, topic_name)
    kb = get_report_settings_keyboard(chat_settings)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.message(Command("report", "репорт", "жалоба"))
@router.message(F.text.startswith("!жб") | F.text.startswith("!report"))
async def cmd_report(message: Message, session: AsyncSession, db_user: User):
    """
    Подача жалобы гражданином:
    1. Ответом на сообщение: /report [причина] (или !жб [причина])
    2. По username или ID: /report @username [причина] или /report [id] [причина]
    Удаляет исходную команду, чтобы нарушитель не увидел факт доноса,
    и конфиденциально направляет карточку инцидента должностям от Блюстителя и выше.
    """
    # 1. Сразу удаляем сообщение с командой заявителя (полная конфиденциальность)
    try:
        await message.delete()
    except Exception:
        pass

    raw_text = message.text or ""
    tokens = raw_text.strip().split()

    violator_res: Optional[User] = None
    reported_text: Optional[str] = None
    message_id: Optional[int] = None
    reason: str = "Нарушение порядка"

    if message.reply_to_message:
        violator_tg_user = message.reply_to_message.from_user
        if not violator_tg_user or violator_tg_user.is_bot:
            hint = await message.answer("⚠️ Нельзя подать жалобу на бота или системное сообщение!")
            asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=5.0))
            return

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

        parts = raw_text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            reason = parts[1].strip()

        message_id = message.reply_to_message.message_id
        reported_text = message.reply_to_message.text or message.reply_to_message.caption or "[Медиа-контент / стикер]"

    else:
        # Без реплая: /report @username [причина] или /report [tg_id] [причина]
        if len(tokens) < 2:
            hint = await message.answer(
                "⚠️ <b>Укажите нарушителя для подачи жалобы:</b>\n"
                "• <b>Ответом:</b> ответьте на сообщение нарушителя командой <code>/report [причина]</code>\n"
                "• <b>По тегу:</b> <code>/report @username [причина]</code>\n"
                "• <b>По ID:</b> <code>/report [telegram_id] [причина]</code>\n\n"
                "<i>Команда и подсказка удаляются автоматически для обеспечения вашей безопасности.</i>"
            )
            asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=7.0))
            return

        target_token = tokens[1].strip()
        reason = " ".join(tokens[2:]).strip() if len(tokens) > 2 else "Нарушение порядка"
        reported_text = "[Жалоба на поведение пользователя вне контекста конкретного сообщения]"
        message_id = None

        # Проверяем text_mention из entities
        if message.entities:
            for ent in message.entities:
                if ent.type == "text_mention" and ent.user:
                    u_ent = ent.user
                    violator_res = await session.scalar(select(User).where(User.telegram_id == u_ent.id))
                    if not violator_res:
                        violator_res = User(
                            telegram_id=u_ent.id,
                            username=u_ent.username,
                            full_name=u_ent.full_name,
                            role_level=PositionLevel.CITIZEN.value,
                        )
                        session.add(violator_res)
                        await session.commit()
                        await session.refresh(violator_res)
                    break

        if not violator_res and target_token.isdigit():
            tg_id = int(target_token)
            violator_res = await session.scalar(select(User).where(User.telegram_id == tg_id))
            if not violator_res:
                violator_res = User(
                    telegram_id=tg_id,
                    username=None,
                    full_name=f"Гражданин {tg_id}",
                    role_level=PositionLevel.CITIZEN.value,
                )
                session.add(violator_res)
                await session.commit()
                await session.refresh(violator_res)

        if not violator_res and target_token.startswith("@"):
            uname = target_token.lstrip("@").lower()
            violator_res = await session.scalar(select(User).where(User.username.ilike(uname)))

        if not violator_res:
            violator_res = await session.scalar(
                select(User).where(
                    User.username.ilike(target_token) | User.minecraft_nick.ilike(target_token)
                )
            )

        if not violator_res:
            hint = await message.answer(
                f"⚠️ Пользователь <b>{target_token}</b> не найден в базе данных чата!\n"
                f"Ответьте на его сообщение командой <code>/report [причина]</code> "
                f"или укажите его числовой Telegram ID."
            )
            asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=7.0))
            return

    if violator_res.telegram_id == db_user.telegram_id or violator_res.id == db_user.id:
        hint = await message.answer("🤷 Нельзя подать жалобу на самого себя!")
        asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=5.0))
        return

    current_thread_id = getattr(message, "message_thread_id", None)
    incident_topic_name = await TopicService.get_topic_name(session, message.chat.id, current_thread_id)

    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)

    try:
        report = await ReportService.create_report(
            session=session,
            reporter=db_user,
            violator=violator_res,
            incident_topic_id=current_thread_id,
            incident_topic_name=incident_topic_name,
            message_id=message_id,
            message_text=reported_text,
            reason=reason,
            chat_id=message.chat.id,
        )
    except TownBaseException as e:
        hint = await message.answer(e.message)
        asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [hint.message_id], delay=5.0))
        return

    # Проверяем настройку анонимности
    if chat_settings.reports_anonymous:
        reporter_display = f"🥷 <i>Анонимный гражданин (Ранг {db_user.government_rank})</i>"
    else:
        reporter_display = f"@{db_user.username or '—'} (ID: <code>{db_user.telegram_id}</code>)"

    # Карточка жалобы строго для должностных лиц (от Блюстителя и выше)
    card = (
        f"🚨 <b>ЖАЛОБА #{report.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Заявитель:</b> {reporter_display}\n"
        f"• <b>Нарушитель:</b> @{violator_res.username or '—'} (ID: <code>{violator_res.telegram_id}</code>)\n"
        f"• <b>Должность нарушителя:</b> {violator_res.position_title} (Ранг {violator_res.government_rank})\n"
        f"• <b>Тема инцидента:</b> «{incident_topic_name}»\n"
        f"• <b>Причина:</b> <b>{reason}</b>\n"
        f"• <b>Текст сообщения:</b> <i>«{reported_text[:400]}»</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👮 <i>Ожидает рассмотрения дежурным Блюстителем или Администрацией.</i>"
    )

    # 1. В чате группы пишем только тихое исчезающее подтверждение заявителю
    confidential_hint = await message.answer(
        "🔒 <b>Жалоба принята конфиденциально!</b>\n"
        "Информация передана дежурным Блюстителям и Администрации города."
    )
    asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [confidential_hint.message_id], delay=5.0))

    dest = chat_settings.reports_destination or "both"
    send_to_pm = dest in ("pm", "both")
    send_to_topic = dest in ("topic", "both")

    keyboard = get_report_inline_keyboard(report.id)
    pm_delivered_count = 0

    # 2. Отправка в ЛИЧНЫЕ СООБЩЕНИЯ (Владелец, сотрудники БД, администраторы чата Telegram)
    if send_to_pm:
        staff_ids = set()
        # Владелец всегда
        if settings.OWNER_ID:
            staff_ids.add(settings.OWNER_ID)

        # Все сотрудники из базы данных (от Помощника и выше)
        staff_query = select(User.telegram_id).where(
            (User.role_level >= PositionLevel.ASSISTANT.value) |
            (User.telegram_id == settings.OWNER_ID)
        )
        db_staff_ids = (await session.scalars(staff_query)).all()
        staff_ids.update(db_staff_ids)

        # Администраторы текущего чата в Telegram
        if message.chat.type in ("group", "supergroup"):
            try:
                chat_admins = await message.chat.get_administrators()
                for a in chat_admins:
                    if not a.user.is_bot:
                        staff_ids.add(a.user.id)
            except Exception as e:
                logger.debug("Не удалось получить список администраторов Telegram: %s", e)

        for target_id in staff_ids:
            try:
                await message.bot.send_message(
                    chat_id=target_id,
                    text=card,
                    reply_markup=keyboard,
                )
                pm_delivered_count += 1
            except Exception as e:
                logger.warning("Не удалось отправить карточку жалобы в ЛС сотруднику/админу %s: %s", target_id, e)

    # 3. Отправка в ТОПИК ФОРУМА
    reports_thread_id = None
    if chat_settings.reports_topic_id:
        reports_thread_id = chat_settings.reports_topic_id
    else:
        reports_thread_id = await TopicService.get_topic_thread_id(
            session=session, chat_id=message.chat.id, topic_type=TopicType.REPORTS.value
        )
        if reports_thread_id is None:
            reports_thread_id = await TopicService.get_topic_thread_id(
                session=session, chat_id=message.chat.id, topic_type=TopicType.ADMIN.value
            )

    # Если топик жалоб не привязан, используем текущую ветку форума / чат
    target_send_thread = reports_thread_id if reports_thread_id is not None else current_thread_id

    # В группу/топик отправляем, если включен режим 'both' или 'topic', либо если в ЛС не удалось доставить
    if send_to_topic or pm_delivered_count == 0 or reports_thread_id is not None:
        topic_card = card
        if pm_delivered_count == 0:
            topic_card += (
                "\n\n💡 <i>Дежурным сотрудникам: чтобы получать жалобы персонально в ЛС, "
                "начните диалог с ботом (/start в ЛС)!</i>"
            )
        try:
            sent_card = await message.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=target_send_thread,
                text=topic_card,
                reply_markup=keyboard,
            )
            report.card_message_id = sent_card.message_id
            await session.commit()
        except Exception as e:
            logger.warning("Не удалось отправить жалобу в топик форума (%s): %s", target_send_thread, e)


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
