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
from bot.filters.topic import TopicCommandFilter
from bot.filters.role import RoleFilter, MinRankFilter

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


@router.message(Command("ticket_panel", "приемная"), TopicCommandFilter(["tickets", "admin"]))
async def cmd_ticket_panel(message: Message, session: AsyncSession, db_user: User):
    """Отправляет панель приемной граждан для закрепления в TICKETS_TOPIC_ID."""
    if not db_user.is_warden_or_higher and not db_user.is_middle_admin:
        await message.reply("❌ Создавать панель приемной могут только сотрудники администрации!")
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
    await callback.message.answer(
        text,
        reply_markup=get_ticket_category_keyboard(),
    )
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
        # Если группа не форум или нет прав, используем текущий тред или ветку
        thread_id = getattr(callback.message, "message_thread_id", None)
        if thread_id:
            await TicketService.bind_forum_topic(session, ticket.id, thread_id)

    # 2. Отправляем карточку тикета в созданную тему
    card = (
        f"🏛️ <b>ГОСУДАРСТВЕННОЕ ОБРАЩЕНИЕ #{ticket.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Заявитель:</b> @{db_user.username or '—'} (ID: <code>{db_user.telegram_id}</code>)\n"
        f"• <b>Инстанция:</b> {cat_title}\n"
        f"• <b>Целевое ведомство:</b> <i>{ticket.target_role}</i>\n"
        f"• <b>Статус:</b> 🟡 <i>Ожидает рассмотрения</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Уполномоченные лица уведомлены. Заявитель, подробно опишите суть вашей проблемы или вопроса в этом топике."
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
    """
    if not db_user.is_staff:
        await message.reply("❌ Закрывать обращения могут только сотрудники администрации!")
        return

    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply("⚠️ Команда /close должна вызываться внутри топика обращения!")
        return

    ticket = await TicketService.get_ticket_by_thread(session, thread_id)
    if not ticket:
        await message.reply("❌ В этом топике нет активного обращения!")
        return

    parts = (message.text or "").split(maxsplit=1)
    verdict = parts[1].strip() if len(parts) > 1 else "Вопрос решен / Обращение рассмотрено"

    try:
        await TicketService.close_ticket(session, ticket.id, db_user, verdict)
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

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


@router.callback_query(F.data.startswith("ticket_close_btn:"))
async def cb_ticket_close_btn(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Закрытие тикета по кнопке внутри карточки."""
    if not db_user.is_staff:
        await callback.answer("❌ Закрывать обращения могут только сотрудники администрации!", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[1])
    try:
        ticket = await TicketService.close_ticket(
            session=session,
            ticket_id=ticket_id,
            staff_user=db_user,
            verdict="Вопрос решен через быстрое закрытие",
        )
    except TownBaseException as e:
        await callback.answer(e.message, show_alert=True)
        return

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
