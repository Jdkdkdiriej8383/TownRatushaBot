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
from db.models.ticket import Ticket
from core.enums import TicketCategory, TicketStatus, PositionLevel, TopicType
from core.ticket_service import TicketService
from core.topic_service import TopicService
from core.hierarchy_service import HierarchyService
from core.exceptions import TownBaseException
from bot.filters.topic import TopicCommandFilter, auto_delete_messages
from bot.filters.role import RoleFilter, MinRankFilter
from config import settings

logger = logging.getLogger("townbot.tickets")
router = Router(name="tickets_router")

CATEGORY_NAMES = {
    TicketCategory.MAYOR.value: "🏛️ В Мэрию / Кабинет Министров",
    TicketCategory.COURT.value: "⚖️ В Конституционный Суд / Суд",
    TicketCategory.STAFF_COMPLAINT.value: "🛡️ Жалоба на Блюстителя / Помощника",
    TicketCategory.GENERAL.value: "❓ Общий вопрос / Помощь по серверу",
}


def get_ticket_reception_keyboard() -> InlineKeyboardMarkup:
    """Кнопка для закрепленного сообщения в теме приемной."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Обратиться в государственные органы",
                    callback_data="ticket_create_start",
                )
            ]
        ]
    )


def get_ticket_category_keyboard() -> InlineKeyboardMarkup:
    """Выбор инстанции для обращения."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏛️ В Мэрию / Кабинет Министров",
                    callback_data=f"ticket_cat:{TicketCategory.MAYOR.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚖️ В Конституционный Суд / Суд",
                    callback_data=f"ticket_cat:{TicketCategory.COURT.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛡️ Жалоба на Блюстителя / Помощника",
                    callback_data=f"ticket_cat:{TicketCategory.STAFF_COMPLAINT.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Общий вопрос / Помощь по серверу",
                    callback_data=f"ticket_cat:{TicketCategory.GENERAL.value}",
                )
            ],
        ]
    )


def get_ticket_action_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления внутри топика тикета."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✋ Принять обращение",
                    callback_data=f"ticket_claim:{ticket_id}",
                ),
                InlineKeyboardButton(
                    text="🔒 Закрыть",
                    callback_data=f"ticket_close_btn:{ticket_id}",
                ),
            ]
        ]
    )


@router.message(Command("ticket_panel", "приемная", "тикеты", "панель_тикетов", "панель_приемной"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "/ticket_panel", "ticket_panel", "/приемная", "приемная",
    "/тикеты", "тикеты", "/панель_тикетов", "панель_тикетов",
    "/панель_приемной", "панель_приемной", "!ticket_panel", "!приемная"
))))
async def cmd_ticket_panel(message: Message, session: AsyncSession, db_user: User):
    """Отправляет панель приемной граждан в чат."""
    is_staff = (
        db_user.government_rank >= 2
        or db_user.is_warden_or_higher
        or db_user.is_middle_admin
        or HierarchyService.is_owner(db_user)
        or db_user.telegram_id == settings.OWNER_ID
    )
    if not is_staff and message.from_user and message.chat.type in ("group", "supergroup"):
        try:
            m = await message.chat.get_member(message.from_user.id)
            if getattr(m, "status", "") in ("creator", "administrator"):
                is_staff = True
        except Exception:
            pass

    if not is_staff:
        await message.reply("❌ Создавать панель приемной могут только сотрудники администрации или администраторы чата!")
        return

    text = (
        "🏛️ <b>ГОСУДАРСТВЕННАЯ ПРИЕМНАЯ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Здесь каждый гражданин может официально обратиться к государственным органам власти города.\n\n"
        "• Обращения рассматриваются уполномоченными должностными лицами.\n"
        "• Для каждого обращения создается отдельная ветка (топик).\n\n"
        "Нажмите кнопку ниже, чтобы подать обращение:"
    )
    await message.answer(text, reply_markup=get_ticket_reception_keyboard())


@router.callback_query(F.data == "ticket_create_start")
async def cb_ticket_create_start(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Показывает заявителю выбор инстанции."""
    text = (
        "🏛️ <b>ВЫБОР ГОСУДАРСТВЕННОЙ ИНСТАНЦИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Пожалуйста, выберите орган или должностное лицо, которому адресовано обращение:"
    )
    prompt_msg = await callback.message.answer(
        text,
        reply_markup=get_ticket_category_keyboard(),
    )
    asyncio.create_task(auto_delete_messages(callback.bot, callback.message.chat.id, [prompt_msg.message_id], delay=45.0))
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_cat:"))
async def cb_ticket_category_selected(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Создает топик форума и регистрирует обращение в БД."""
    category = callback.data.split(":", 1)[1]
    cat_title = CATEGORY_NAMES.get(category, category)

    chat_id = callback.message.chat.id

    # 1. Создаем тикет в БД
    ticket = await TicketService.create_ticket(
        session=session,
        creator=db_user,
        category=category,
    )

    topic_name = f"Тикет #{ticket.id} | @{db_user.username or db_user.telegram_id}"
    if len(topic_name) > 120:
        topic_name = topic_name[:120]

    thread_id = None
    try:
        forum_topic = await callback.bot.create_forum_topic(
            chat_id=chat_id,
            name=topic_name,
        )
        thread_id = forum_topic.message_thread_id
        await TicketService.bind_forum_topic(session, ticket.id, thread_id)
    except Exception as e:
        logger.warning(f"Failed to create forum topic for ticket #{ticket.id}: {e}")
        thread_id = getattr(callback.message, "message_thread_id", None)
        if thread_id:
            await TicketService.bind_forum_topic(session, ticket.id, thread_id)

    # Определение дежурных сотрудников для уведомления
    if category == TicketCategory.COURT.value:
        q = select(User).where(User.custom_title.in_(["Судья", "Конституционный судья"]))
    elif category == TicketCategory.MAYOR.value:
        q = select(User).where(User.custom_title.in_(["Мэр", "Премьер-министр", "Заместитель мэра"]))
    elif category == TicketCategory.STAFF_COMPLAINT.value:
        q = select(User).where(User.role_level >= PositionLevel.ADMINISTRATION.value)
    else:
        q = select(User).where(User.role_level >= PositionLevel.ASSISTANT.value)

    staff_members = (await session.scalars(q)).all()
    pings_list = [f"@{u.username}" for u in staff_members if u.username]
    staff_notice = " ".join(pings_list[:5]) if pings_list else "дежурные сотрудники ведомства"

    # Формируем ссылку на топик
    clean_chat_id = str(chat_id).replace("-100", "")
    chat_username = callback.message.chat.username
    if chat_username and thread_id:
        topic_link = f"https://t.me/{chat_username}/{thread_id}"
    elif thread_id:
        topic_link = f"https://t.me/c/{clean_chat_id}/{thread_id}"
    else:
        topic_link = ""

    # 2. Отправляем карточку тикета в созданную тему
    card = (
        f"🏛️ <b>ГОСУДАРСТВЕННОЕ ОБРАЩЕНИЕ #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Заявитель:</b> @{db_user.username or '—'} (ID: <code>{db_user.telegram_id}</code>)\n"
        f"• <b>Инстанция:</b> {cat_title}\n"
        f"• <b>Целевое ведомство:</b> <i>{ticket.target_role}</i>\n"
        f"• <b>Статус:</b> 🟡 <i>Ожидает рассмотрения</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 <b>Уведомление:</b> {staff_notice}\n\n"
        f"Заявитель (@{db_user.username or 'гражданин'}), подробно опишите суть вашей проблемы или вопроса в этом топике."
    )

    try:
        await callback.bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=card,
            reply_markup=get_ticket_action_keyboard(ticket.id),
        )
    except Exception as e:
        logger.error(f"Failed to send ticket card to thread {thread_id}: {e}")

    await callback.answer(f"✅ Обращение #{ticket.id} открыто!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем подтверждение со ссылкой для быстрого перехода
    if topic_link:
        jump_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="👉 Перейти в тему обращения", url=topic_link)]]
        )
        confirm_msg = await callback.message.answer(
            f"✅ <b>Обращение #{ticket.id} создано!</b>\nПерейдите в созданную ветку форума:",
            reply_markup=jump_kb,
        )
        asyncio.create_task(auto_delete_messages(callback.bot, chat_id, [confirm_msg.message_id], delay=20.0))

        # Уведомляем заявителя в ЛС
        try:
            await callback.bot.send_message(
                chat_id=db_user.telegram_id,
                text=(
                    f"🏛 <b>Ваше обращение #{ticket.id} успешно открыто!</b>\n"
                    f"• <b>Инстанция:</b> {cat_title}\n"
                    f"• <b>Ветка форума:</b> {topic_name}"
                ),
                reply_markup=jump_kb,
            )
        except Exception:
            pass

        # Уведомляем дежурный персонал в ЛС
        for staff in staff_members:
            try:
                await callback.bot.send_message(
                    chat_id=staff.telegram_id,
                    text=(
                        f"📬 <b>Новое обращение #{ticket.id}</b>\n"
                        f"• <b>Заявитель:</b> @{db_user.username or '—'} ({db_user.full_name})\n"
                        f"• <b>Инстанция:</b> {cat_title}\n"
                        f"• <b>Ведомство:</b> <i>{ticket.target_role}</i>"
                    ),
                    reply_markup=jump_kb,
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("ticket_claim:"))
async def cb_ticket_claim(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Сотрудник принимает обращение по кнопке."""
    if not db_user.is_staff:
        await callback.answer("❌ Принимать обращения могут только сотрудники администрации!", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    try:
        ticket = await TicketService.claim_ticket(session, ticket_id, db_user)
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)
        return

    text = (
        f"✋ <b>ОБРАЩЕНИЕ ВЗЯТО В РАБОТУ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
        f"• <b>Статус:</b> 🟢 <i>В процессе рассмотрения</i>\n"
    )
    await callback.message.answer(text)
    await callback.answer("Вы приняли обращение в работу!")


@router.message(Command("claim", "принять"))
async def cmd_claim_ticket(message: Message, session: AsyncSession, db_user: User):
    """Команда /claim для взятия тикета в работу в текущем топике."""
    if not db_user.is_staff:
        await message.reply("❌ Принимать обращения могут только сотрудники администрации!")
        return

    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply("⚠️ Команда /claim должна вызываться внутри топика обращения!")
        return

    ticket = await TicketService.get_ticket_by_thread(session, thread_id)
    if not ticket:
        await message.reply("❌ В этом топике нет активного обращения!")
        return

    try:
        await TicketService.claim_ticket(session, ticket.id, db_user)
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    text = (
        f"✋ <b>ОБРАЩЕНИЕ #{ticket.id} ВЗЯТО В РАБОТУ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Ответственный сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
        f"• <b>Статус:</b> 🟢 <i>В процессе рассмотрения</i>"
    )
    await message.answer(text)


@router.message(Command("transfer", "передать"))
async def cmd_transfer_ticket(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /transfer <новая_инстанция>
    Перенаправляет тикет в другое ведомство.
    """
    if not db_user.is_staff:
        await message.reply("❌ Перенаправлять обращения могут только сотрудники администрации!")
        return

    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply("⚠️ Команда /transfer должна вызываться внутри топика обращения!")
        return

    ticket = await TicketService.get_ticket_by_thread(session, thread_id)
    if not ticket:
        await message.reply("❌ В этом топике нет активного обращения!")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ Укажите ведомство: <code>/transfer Суд / Мэрия / Помощники</code>")
        return

    new_role = parts[1].strip()
    try:
        await TicketService.transfer_ticket(session, ticket.id, new_role, db_user)
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    text = (
        f"🔄 <b>ОБРАЩЕНИЕ #{ticket.id} ПЕРЕНАПРАВЛЕНО</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Перенаправил:</b> @{db_user.username or db_user.full_name}\n"
        f"• <b>Новое ведомство:</b> 🏛️ <b>{new_role}</b>\n"
        f"• <b>Статус:</b> 🟡 <i>Ожидает нового ответственного</i>"
    )
    await message.answer(text, reply_markup=get_ticket_action_keyboard(ticket.id))


@router.message(Command("close", "закрыть"))
async def cmd_close_ticket(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /close [вердикт]
    Закрывает обращение, фиксирует вердикт, начисляет заслугу сотруднику и закрывает топик форума.
    Доступно как сотрудникам администрации, так и самому заявителю.
    """
    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply("⚠️ Команда /close должна вызываться внутри топика обращения!")
        return

    ticket = await TicketService.get_ticket_by_thread(session, thread_id)
    if not ticket:
        await message.reply("❌ В этом топике нет активного обращения!")
        return

    is_creator = (ticket.creator_id == db_user.id)
    if not db_user.is_staff and not is_creator:
        await message.reply("❌ Закрывать обращения могут только сотрудники администрации или сам заявитель!")
        return

    parts = (message.text or "").split(maxsplit=1)
    if is_creator and not db_user.is_staff:
        verdict = parts[1].strip() if len(parts) > 1 else "Отозвано заявителем / Вопрос решен"
    else:
        verdict = parts[1].strip() if len(parts) > 1 else "Вопрос решен / Обращение рассмотрено"

    try:
        await TicketService.close_ticket(session, ticket.id, db_user, verdict)
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    cat_name = CATEGORY_NAMES.get(ticket.category, ticket.category)
    verdict_text = (
        f"🏛️ <b>ОФИЦИАЛЬНЫЙ ВЕРДИКТ ПО ОБРАЩЕНИЮ #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
        f"• <b>Итоговое решение:</b> <i>{verdict}</i>\n"
        f"• <b>Заслуга:</b> +1 к закрытым обращениям (Всего: {db_user.closed_tickets_count})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <i>Обращение официально закрыто. Тема архивируется.</i>"
    )
    await message.answer(verdict_text)

    # Закрываем топик форума
    try:
        await message.bot.close_forum_topic(chat_id=message.chat.id, message_thread_id=thread_id)
    except Exception as e:
        logger.warning(f"Failed to close forum topic {thread_id}: {e}")

    # Отправка протокола в архив логов
    try:
        log_thread_id = await TopicService.get_topic_thread_id(session, message.chat.id, TopicType.LOGS.value)
        audit_card = (
            f"📁 <b>АРХИВ ОБРАЩЕНИЙ: ТИКЕТ #{ticket.id} ЗАКРЫТ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Заявитель:</b> ID <code>{ticket.creator_telegram_id}</code>\n"
            f"• <b>Инстанция:</b> {cat_name}\n"
            f"• <b>Исполнитель:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
            f"• <b>Итоговый вердикт:</b> <i>{verdict}</i>\n"
            f"• <b>Заслуга сотрудника:</b> {db_user.closed_tickets_count} закрытых тикетов\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        await message.bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=log_thread_id,
            text=audit_card,
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить лог закрытия тикета: {e}")

    # Уведомляем заявителя в ЛС о закрытии с вердиктом
    try:
        creator_user = await session.scalar(select(User).where(User.id == ticket.creator_id))
        if creator_user:
            await message.bot.send_message(
                chat_id=creator_user.telegram_id,
                text=(
                    f"🏛 <b>ВАШЕ ОБРАЩЕНИЕ #{ticket.id} ЗАКРЫТО</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Инстанция:</b> {cat_name}\n"
                    f"• <b>Сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
                    f"• <b>Итоговое решение:</b> <i>{verdict}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Спасибо за обращение в Государственные органы!"
                ),
            )
    except Exception as e:
        logger.debug(f"Не удалось отправить вердикт заявителю в ЛС: {e}")


@router.callback_query(F.data.startswith("ticket_close_btn:"))
async def cb_ticket_close_btn(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Закрытие тикета по кнопке внутри карточки."""
    ticket_id = int(callback.data.split(":")[1])
    ticket = await TicketService.get_ticket(session, ticket_id)
    if not ticket:
        await callback.answer("Обращение не найдено!", show_alert=True)
        return

    is_creator = (ticket.creator_id == db_user.id)
    if not db_user.is_staff and not is_creator:
        await callback.answer("❌ Закрывать обращения могут только сотрудники администрации или сам заявитель!", show_alert=True)
        return

    verdict_str = "Отозвано заявителем / Вопрос урегулирован" if is_creator and not db_user.is_staff else "Вопрос решен через быстрое закрытие"
    try:
        ticket = await TicketService.close_ticket(
            session=session,
            ticket_id=ticket_id,
            staff_user=db_user,
            verdict=verdict_str,
        )
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)
        return

    cat_name = CATEGORY_NAMES.get(ticket.category, ticket.category)
    verdict_text = (
        f"🏛️ <b>ОФИЦИАЛЬНЫЙ ВЕРДИКТ ПО ОБРАЩЕНИЮ #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
        f"• <b>Итоговое решение:</b> <i>Вопрос урегулирован</i>\n"
        f"• <b>Заслуга:</b> +1 к закрытым обращениям (Всего: {db_user.closed_tickets_count})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <i>Обращение официально закрыто.</i>"
    )
    await callback.message.answer(verdict_text)
    await callback.answer("Обращение закрыто!")

    thread_id = getattr(callback.message, "message_thread_id", None)
    if thread_id:
        try:
            await callback.bot.close_forum_topic(chat_id=callback.message.chat.id, message_thread_id=thread_id)
        except Exception:
            pass

    # Отправка протокола в архив логов
    try:
        log_thread_id = await TopicService.get_topic_thread_id(session, callback.message.chat.id, TopicType.LOGS.value)
        audit_card = (
            f"📁 <b>АРХИВ ОБРАЩЕНИЙ: ТИКЕТ #{ticket.id} ЗАКРЫТ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Заявитель:</b> ID <code>{ticket.creator_telegram_id}</code>\n"
            f"• <b>Инстанция:</b> {cat_name}\n"
            f"• <b>Исполнитель:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
            f"• <b>Итоговый вердикт:</b> <i>Быстрое закрытие (вопрос решен)</i>\n"
            f"• <b>Заслуга сотрудника:</b> {db_user.closed_tickets_count} закрытых тикетов\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        await callback.bot.send_message(
            chat_id=callback.message.chat.id,
            message_thread_id=log_thread_id,
            text=audit_card,
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить лог закрытия тикета: {e}")

    # Уведомляем заявителя в ЛС
    try:
        creator_user = await session.scalar(select(User).where(User.id == ticket.creator_id))
        if creator_user:
            await callback.bot.send_message(
                chat_id=creator_user.telegram_id,
                text=(
                    f"🏛 <b>ВАШЕ ОБРАЩЕНИЕ #{ticket.id} ЗАКРЫТО</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Инстанция:</b> {cat_name}\n"
                    f"• <b>Сотрудник:</b> @{db_user.username or db_user.full_name} ({db_user.position_title})\n"
                    f"• <b>Итоговое решение:</b> <i>Вопрос урегулирован</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Спасибо за обращение в Государственные органы!"
                ),
            )
    except Exception as e:
        logger.debug(f"Не удалось отправить вердикт заявителю в ЛС: {e}")


@router.message(F.message_thread_id.is_not(None))
async def guard_ticket_topic_messages(message: Message, session: AsyncSession, db_user: User):
    """
    Контроль доступа внутри форумных веток тикетов:
    В ветке тикета разрешено писать ТОЛЬКО заявителю и дежурным сотрудникам.
    Сообщения посторонних участников мгновенно удаляются.
    """
    # Пропускаем команды, чтобы они шли в соответствующие обработчики
    if (message.text or "").startswith("/"):
        return

    thread_id = message.message_thread_id
    ticket = await TicketService.get_ticket_by_thread(session, thread_id)
    if not ticket or ticket.status == TicketStatus.CLOSED.value:
        return

    # Разрешено: создателю тикета, сотрудникам от Ранга 1, и Овнеру
    is_creator = message.from_user and message.from_user.id == ticket.creator_telegram_id
    is_staff = db_user.is_staff or db_user.government_rank >= 1 or db_user.telegram_id == settings.OWNER_ID

    if not (is_creator or is_staff):
        try:
            await message.delete()
        except Exception:
            pass
        warn = await message.answer(
            f"⚠️ @{message.from_user.username or message.from_user.first_name}, "
            f"эта ветка является персональным обращением гражданина и доступна только заявителю и администрации!"
        )
        asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [warn.message_id], delay=5.0))
