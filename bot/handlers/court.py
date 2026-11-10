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
from db.models.ticket import Ticket
from db.models.punishment import Punishment
from core.enums import TicketCategory, TicketStatus, PositionLevel, PunishmentType, TopicType
from core.ticket_service import TicketService
from core.moderation_service import ModerationService
from core.topic_service import TopicService
from core.hierarchy_service import HierarchyService
from core.exceptions import TownBaseException
from bot.filters.topic import TopicCommandFilter
from bot.filters.role import MinRankFilter
from config import settings

logger = logging.getLogger("townbot.court")
router = Router(name="court_router")


def get_appeal_inline_keyboard(appeal_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления судебной апелляцией для Судей."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🕊️ Оправдать (снять санкции)",
                    callback_data=f"court_verdict:{appeal_id}:pardon",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📉 Смягчить (-1 варн / размут)",
                    callback_data=f"court_verdict:{appeal_id}:mitigate",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔨 Отклонить (оставить в силе)",
                    callback_data=f"court_verdict:{appeal_id}:reject",
                ),
            ],
        ]
    )


@router.message(Command("appeal", "апелляция", "иск"))
async def cmd_appeal(message: Message, session: AsyncSession, db_user: User):
    """
    Подача апелляции или судебного иска гражданином (/appeal [текст] или /апелляция [текст]).
    Доступно как в темах форума, так и в личных сообщениях с ботом (для изгнанных).
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "⚖️ <b>Подача судебной апелляции в Зал Суда:</b>\n"
            "Использование: <code>/appeal [опишите причину несогласия с наказанием или суть иска]</code>\n\n"
            "<i>Пример: <code>/appeal Был ошибочно замучен, прошу пересмотреть дело.</code></i>"
        )
        return

    appeal_text = parts[1].strip()

    # Создаем обращение категории COURT
    ticket = await TicketService.create_ticket(
        session=session,
        creator=db_user,
        category=TicketCategory.COURT.value,
        initial_text=appeal_text,
    )
    ticket.target_role = "Конституционный Суд / Суд"
    await session.commit()

    banned_status = "🚨 В изгнании (Бан)" if db_user.is_enemy else "✅ Гражданин"
    warns_status = f"{db_user.warns_count or 0}/5"

    card = (
        f"⚖️ <b>СУДЕБНАЯ АПЕЛЛЯЦИЯ #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Заявитель / Истец:</b> @{db_user.username or '—'} (ID: <code>{db_user.telegram_id}</code>)\n"
        f"• <b>Статус заявителя:</b> {banned_status} | Варны: <b>{warns_status}</b>\n"
        f"• <b>Суть обращения:</b>\n<i>«{appeal_text}»</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <i>Дело открыто. Ожидает рассмотрения Судьей или Конституционным судьей.</i>"
    )

    keyboard = get_appeal_inline_keyboard(ticket.id)

    # 1. Отвечаем заявителю подтверждением о принятии иска
    applicant_reply = (
        f"⚖️ <b>СУДЕБНАЯ АПЕЛЛЯЦИЯ #{ticket.id} ЗАРЕГИСТРИРОВАНА!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Суть иска:</b> <i>«{appeal_text[:300]}»</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <i>Дело передано на рассмотрение Судейской коллегии города. "
        f"О вынесенном вердикте вы будете уведомлены персонально.</i>"
    )
    await message.answer(applicant_reply)

    # 2. Определяем чат и топик суда
    target_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else settings.MAIN_CHAT_ID
    court_thread_id = None
    if target_chat_id:
        court_thread_id = await TopicService.get_topic_thread_id(
            session=session, chat_id=target_chat_id, topic_type=TopicType.COURT.value
        )
        if court_thread_id is None:
            court_thread_id = await TopicService.get_topic_thread_id(
                session=session, chat_id=target_chat_id, topic_type=TopicType.ADMIN.value
            )

    # 3. Публикуем интерактивную карточку в топик Зала Суда / чат
    if target_chat_id:
        current_thread_id = getattr(message, "message_thread_id", None)
        send_thread = court_thread_id if court_thread_id is not None else current_thread_id
        try:
            await message.bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=send_thread,
                text=card,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("Не удалось отправить карточку апелляции в топик суда %s: %s", send_thread, e)

    # 4. Направляем карточку в ЛС судьям (Ранг 3+) и Овнеру
    judges_query = select(User).where(
        (User.role_level >= PositionLevel.ADMINISTRATION.value) |
        (User.telegram_id == settings.OWNER_ID)
    )
    judges = (await session.scalars(judges_query)).all()
    for judge in judges:
        try:
            await message.bot.send_message(
                chat_id=judge.telegram_id,
                text=card,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.debug("Не удалось отправить карточку апелляции в ЛС судье %s: %s", judge.telegram_id, e)


@router.message(Command("verdict", "вердикт"), TopicCommandFilter(["court", "admin"]))
async def cmd_verdict(message: Message, session: AsyncSession, db_user: User):
    """
    Вынесение официального судебного вердикта:
    /verdict <id_дела> <оправдать/отклонить/смягчить> [обоснование]
    Доступно Судье, Конституционному Судье или Мэру (Ранг 3+).
    """
    if db_user.government_rank < 3:
        await message.reply("🚫 Выносить судебные вердикты могут только судьи и высшая администрация (Ранг 3+)!")
        return

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await message.reply(
            "⚠️ Использование: <code>/verdict &lt;id_дела&gt; &lt;оправдать|отклонить|смягчить&gt; [обоснование]</code>"
        )
        return

    if not parts[1].isdigit():
        await message.reply("⚠️ Номер дела должен быть числом! Пример: <code>/verdict 1 оправдать Невиновен</code>")
        return

    appeal_id = int(parts[1])
    action = parts[2].lower()
    reason = parts[3].strip() if len(parts) > 3 else "По решению Суда"

    ticket = await TicketService.get_ticket(session, appeal_id)
    if not ticket:
        await message.reply(f"❌ Судебное дело #{appeal_id} не найдено!")
        return

    if ticket.status == TicketStatus.CLOSED.value:
        await message.reply(f"⚠️ Судебное дело #{appeal_id} уже закрыто вердиктом: {ticket.verdict}")
        return

    target_user = await session.scalar(select(User).where(User.id == ticket.creator_id))
    if not target_user:
        await message.reply("❌ Заявитель не найден в базе данных!")
        return

    outcome_text = ""
    if action in ["оправдать", "pardon", "амнистия"]:
        # Снимаем бан и все варны
        if target_user.is_enemy:
            await ModerationService.apply_unban(
                session=session,
                bot=message.bot,
                chat_id=message.chat.id,
                issuer=db_user,
                target=target_user,
                reason=f"Судебное оправдание по делу #{appeal_id}: {reason}",
            )
        target_user.warns_count = 0
        await session.commit()
        outcome_text = "🕊️ <b>ПОЛНОЕ ОПРАВДАНИЕ:</b> Все предупреждения аннулированы, бан снят."

    elif action in ["смягчить", "mitigate"]:
        # Снимаем 1 варн или размучиваем
        if target_user.warns_count and target_user.warns_count > 0:
            target_user.warns_count -= 1
        await ModerationService.apply_unmute(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=f"Судебное смягчение по делу #{appeal_id}: {reason}",
        )
        await session.commit()
        outcome_text = f"📉 <b>СМЯГЧЕНИЕ НАКАЗАНИЯ:</b> Снято 1 предупреждение (осталось {target_user.warns_count}/5), мут снят."

    elif action in ["отклонить", "reject"]:
        outcome_text = "🔨 <b>ОТКЛОНЕНО:</b> Наказание признано законным и оставлено в силе."
    else:
        await message.reply("⚠️ Неизвестный вердикт! Допустимо: <code>оправдать</code>, <code>отклонить</code>, <code>смягчить</code>.")
        return

    # Закрываем тикет дела
    full_verdict = f"{outcome_text} Обоснование: {reason}"
    await TicketService.close_ticket(
        session=session,
        ticket_id=ticket.id,
        staff_user=db_user,
        verdict=full_verdict,
    )

    verdict_card = (
        f"🏛️ <b>ОФИЦИАЛЬНОЕ ПОСТАНОВЛЕНИЕ СУДА #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Дело:</b> Апелляция гражданина @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Судья:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Постановление:</b>\n{outcome_text}\n"
        f"• <b>Обоснование:</b> <i>{reason}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ <i>Решение вступило в законную силу и обжалованию не подлежит.</i>"
    )
    await message.answer(verdict_card)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"СУДЕБНЫЙ ВЕРДИКТ #{ticket.id}",
        reason=reason,
    )


@router.callback_query(F.data.startswith("court_verdict:"))
async def cb_court_verdict(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Вынесение вердикта судьей по инлайн-кнопкам под карточкой апелляции."""
    if db_user.government_rank < 3:
        await callback.answer("🚫 Выносить вердикты могут только судьи (Ранг 3+)!", show_alert=True)
        return

    parts = callback.data.split(":")
    appeal_id = int(parts[1])
    action = parts[2]

    ticket = await TicketService.get_ticket(session, appeal_id)
    if not ticket or ticket.status == TicketStatus.CLOSED.value:
        await callback.answer("Дело уже рассмотрено или не найдено!", show_alert=True)
        return

    target_user = await session.scalar(select(User).where(User.id == ticket.creator_id))
    if not target_user:
        await callback.answer("Заявитель не найден в базе данных!", show_alert=True)
        return

    outcome_text = ""
    if action == "pardon":
        if target_user.is_enemy:
            await ModerationService.apply_unban(
                session=session,
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                issuer=db_user,
                target=target_user,
                reason=f"Судебное оправдание по делу #{appeal_id}",
            )
        target_user.warns_count = 0
        await session.commit()
        outcome_text = "🕊️ Оправдан. Наказания и варны аннулированы."

    elif action == "mitigate":
        if target_user.warns_count and target_user.warns_count > 0:
            target_user.warns_count -= 1
        await ModerationService.apply_unmute(
            session=session,
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=f"Судебное смягчение по делу #{appeal_id}",
        )
        await session.commit()
        outcome_text = f"📉 Наказание смягчено. Варны: {target_user.warns_count}/5, мут снят."

    elif action == "reject":
        outcome_text = "🔨 Апелляция отклонена. Наказание оставлено в силе."

    await TicketService.close_ticket(
        session=session,
        ticket_id=ticket.id,
        staff_user=db_user,
        verdict=outcome_text,
    )

    # Уведомляем заявителя в ЛС
    try:
        verdict_pm = (
            f"⚖️ <b>ВЫНЕСЕН СУДЕБНЫЙ ВЕРДИКТ ПО ДЕЛУ #{ticket.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Решение:</b> {outcome_text}\n"
            f"• <b>Судья:</b> {db_user.position_title} @{db_user.username or db_user.full_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Решение суда вступает в силу немедленно.</i>"
        )
        await callback.bot.send_message(chat_id=target_user.telegram_id, text=verdict_pm)
    except Exception as e:
        logger.warning("Не удалось уведомить заявителя в ЛС: %s", e)

    await callback.answer("Вердикт успешно вынесен!")
    if callback.message:
        updated_card = (
            f"{callback.message.html_text}\n\n"
            f"⚖️ <b>СУДЕБНЫЙ ВЕРДИКТ:</b>\n"
            f"• <b>Решение:</b> {outcome_text}\n"
            f"• <b>Судья:</b> {db_user.position_title} @{db_user.username or db_user.full_name}"
        )
        await callback.message.edit_text(updated_card, reply_markup=None)


@router.message(Command("court", "суд"), TopicCommandFilter(["court", "admin"]))
async def cmd_court_info(message: Message, session: AsyncSession, db_user: User):
    """Справка о судебной системе и правилах подачи апелляций."""
    info_text = (
        "⚖️ <b>ЗАЛ ГОСУДАРСТВЕННОГО СУДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Суд является независимой ветвью государственной власти города.\n\n"
        "<b>Полномочия судей:</b>\n"
        "• Рассмотрение апелляций на баны и варны модераторов\n"
        "• Разрешение гражданских споров и конфликтов\n"
        "• Санкционирование высшей меры наказания (изгнание)\n\n"
        "<b>Команды судебного производства:</b>\n"
        "• <code>/appeal [текст]</code> — подать апелляцию или судебный иск\n"
        "• <code>/verdict &lt;id&gt; &lt;оправдать|отклонить|смягчить&gt;</code> — вынести вердикт (для Судей)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📖 <i>Все решения Суда основываются на Городском Своде Законов.</i>"
    )
    await message.answer(info_text)
