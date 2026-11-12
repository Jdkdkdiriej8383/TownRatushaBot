import logging
import re
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import Auction, User
from core.enums import AuctionStatus, PositionLevel
from core.hierarchy_service import HierarchyService
from core.auction_service import AuctionService, _to_utc
from core.topic_service import TopicService

logger = logging.getLogger("townbot.handlers.auction")
router = Router(name="auction_router")


@router.message(Command("аукционы", "auctions", "лоты", "торги"))
@router.message(F.text.func(lambda t: bool(t and (
    t.lower().split()[0].split("@")[0] in (
        "аукционы", "/аукционы", "!аукционы",
        "auctions", "/auctions", "!auctions",
        "лоты", "/лоты", "!лоты",
        "торги", "/торги", "!торги"
    )
))))
async def cmd_list_auctions(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /аукционы — Показывает список текущих открытых аукционов конфиската.
    """
    chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else settings.MAIN_CHAT_ID
    active_auctions = await AuctionService.get_active_auctions(session, chat_id=chat_id)

    if not active_auctions:
        await message.reply(
            "📦 <b>АКТИВНЫЕ АУКЦИОНЫ КОНФИСКАТА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "В данный момент открытых торгов нет.\n\n"
            "💡 <i>Выставить имущество на торги:</i>\n"
            "<code>/аукцион создать [название лота] [старт_цена] [минуты]</code>"
        )
        return

    now = datetime.now(timezone.utc)
    lines = [
        "🏛️ <b>АКТИВНЫЕ АУКЦИОНЫ ГОРОДА</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for auc in active_auctions:
        end_utc = _to_utc(auc.end_time)
        diff = (end_utc - now) if end_utc else timedelta(0)
        secs = max(0, int(diff.total_seconds()))
        mins = secs // 60
        leader = auc.current_winner_name or "Ставок нет"
        lines.append(
            f"🔹 <b>#{auc.id}</b>: <b>{auc.title}</b>\n"
            f"   💰 Цена: <code>{auc.current_price:,}</code> ₽ | 👤 Лидер: {leader} | ⏳ Осталось: {mins} мин."
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Сделайте ставку на карточке аукциона выше или откройте:</i> <code>/аукцион инфо [номер]</code>")

    await message.reply("\n".join(lines))


@router.message(Command("аукцион", "auction", "лот", "создать_аукцион", "new_auction"))
@router.message(F.text.func(lambda t: bool(t and (
    t.lower().split()[0].split("@")[0] in (
        "аукцион", "/аукцион", "!аукцион",
        "auction", "/auction", "!auction",
        "лот", "/лот", "!лот",
        "создать_аукцион", "/создать_аукцион", "!создать_аукцион"
    )
))))
async def cmd_auction_router(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /аукцион:
    - /аукцион создать <название лота> <старт_цена> [минуты]
    - /аукцион завершить <id>
    - /аукцион инфо <id>
    """
    if db_user.is_enemy:
        await message.reply("🚫 <b>Отказано:</b> Врагам города заблокирован доступ к аукционам!")
        return

    args = (message.text or "").split()[1:]
    if not args:
        await message.reply(
            "🏛️ <b>ГОСУДАРСТВЕННЫЙ АУКЦИОН КОНФИСКАТА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Доступные команды:\n"
            "• <code>/аукционы</code> — Список активных лотов\n"
            "• <code>/аукцион создать [название] [цена] [минуты]</code> — Создать торги\n"
            "• <code>/аукцион завершить [ID]</code> — Досрочно закрыть аукцион\n"
            "• <code>/аукцион инфо [ID]</code> — Просмотр карточки лота\n\n"
            "💡 <i>Пример:</i> <code>/аукцион создать Алмазная броня 5000 30</code>"
        )
        return

    subcmd = args[0].lower()

    # 1. Создание аукциона
    if subcmd in ("создать", "create", "new", "добавить", "add") or (args and args[-1].isdigit() and len(args) >= 2 and subcmd not in ("завершить", "close", "инфо", "info")):
        clean_args = args[1:] if subcmd in ("создать", "create", "new", "добавить", "add") else args
        if len(clean_args) < 2:
            await message.reply("⚠️ Использование: <code>/аукцион создать [название лота] [старт_цена] [длительность_мин]</code>\nПример: <code>/аукцион создать Незерит 5000 30</code>")
            return

        # Парсим аргументы: последний может быть длительностью в минутах, предпоследний — цена
        duration = 30
        price = 0
        title_parts = []

        if len(clean_args) >= 3 and clean_args[-1].isdigit() and clean_args[-2].isdigit():
            duration = int(clean_args[-1])
            price = int(clean_args[-2])
            title_parts = clean_args[:-2]
        elif clean_args[-1].isdigit():
            price = int(clean_args[-1])
            title_parts = clean_args[:-1]
        else:
            await message.reply("⚠️ Укажите корректную стартовую цену числом!\nПример: <code>/аукцион создать Элитры 10000 30</code>")
            return

        title = " ".join(title_parts).strip()
        if not title:
            await message.reply("⚠️ Укажите название конфискованного лота!")
            return

        if price <= 0:
            await message.reply("⚠️ Стартовая цена должна быть больше 0 ₽!")
            return

        if duration < 1:
            duration = 1
        elif duration > 1440:  # максимум 24 часа
            duration = 1440

        target_chat_id = message.chat.id
        if message.chat.type not in ("group", "supergroup") and settings.MAIN_CHAT_ID:
            target_chat_id = settings.MAIN_CHAT_ID
        if not target_chat_id or target_chat_id == 0:
            target_chat_id = message.chat.id

        raw_thread_id = getattr(message, "message_thread_id", None)
        thread_id = raw_thread_id if isinstance(raw_thread_id, int) else None

        auction = await AuctionService.create_auction(
            session=session,
            chat_id=target_chat_id,
            initiator=db_user,
            title=title,
            start_price=price,
            duration_minutes=duration,
            thread_id=thread_id,
        )

        card_text = AuctionService.format_card_text(auction)
        keyboard = AuctionService.build_card_keyboard(auction)

        try:
            if thread_id:
                sent_msg = await message.answer(
                    card_text,
                    reply_markup=keyboard,
                    message_thread_id=thread_id
                )
            else:
                sent_msg = await message.answer(
                    card_text,
                    reply_markup=keyboard
                )
        except Exception:
            sent_msg = await message.reply(
                card_text,
                reply_markup=keyboard
            )

        auction.message_id = sent_msg.message_id
        await session.commit()
        return

    # 2. Досрочное завершение аукциона
    elif subcmd in ("завершить", "close", "end", "stop"):
        if len(args) < 2 or not args[1].isdigit():
            await message.reply("⚠️ Укажите номер аукциона для завершения!\nПример: <code>/аукцион завершить 1</code>")
            return

        auc_id = int(args[1])
        auction = await session.scalar(select(Auction).where(Auction.id == auc_id))
        if not auction:
            await message.reply("❌ Аукцион с таким номером не найден.")
            return

        is_admin = (
            HierarchyService.is_owner(db_user)
            or db_user.government_rank >= 3
            or db_user.id == auction.initiator_id
        )
        if not is_admin:
            await message.reply("🚫 Завершить аукцион может только организатор торгов или Администрация (Ранг 3+)!")
            return

        if auction.status != AuctionStatus.ACTIVE.value:
            await message.reply(f"ℹ️ Аукцион #{auc_id} уже был закрыт ранее.")
            return

        auction = await AuctionService.finalize_auction(session, auc_id)
        card_text = AuctionService.format_card_text(auction)
        keyboard = AuctionService.build_card_keyboard(auction)

        await message.reply(card_text, reply_markup=keyboard)
        return

    # 3. Инфо по лоту
    elif subcmd in ("инфо", "info", "view", "показать"):
        if len(args) < 2 or not args[1].isdigit():
            await message.reply("⚠️ Укажите номер аукциона!\nПример: <code>/аукцион инфо 1</code>")
            return

        auc_id = int(args[1])
        auction = await session.scalar(select(Auction).where(Auction.id == auc_id))
        if not auction:
            await message.reply("❌ Аукцион с таким номером не найден.")
            return

        now = datetime.now(timezone.utc)
        end_time_utc = _to_utc(auction.end_time)
        if auction.status == AuctionStatus.ACTIVE.value and end_time_utc and end_time_utc <= now:
            auction = await AuctionService.finalize_auction(session, auc_id)

        card_text = AuctionService.format_card_text(auction)
        keyboard = AuctionService.build_card_keyboard(auction)
        await message.reply(card_text, reply_markup=keyboard)
        return

    else:
        await message.reply("⚠️ Неизвестная подкоманда. Используйте <code>/аукцион</code> или <code>/аукционы</code>.")


@router.callback_query(F.data.startswith("auc_bid:"))
async def cb_auction_bid(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Обработчик нажатия кнопок ставок: auc_bid:<id>:<increment>"""
    parts = callback.data.split(":")
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Ошибка формата ставки.", show_alert=True)
        return

    auc_id = int(parts[1])
    increment = int(parts[2])

    success, reply_msg, auction = await AuctionService.place_bid(
        session=session,
        auction_id=auc_id,
        bidder=db_user,
        increment=increment
    )

    if not success:
        await callback.answer(reply_msg, show_alert=True)
        # Если статус изменился, обновляем карточку
        if auction and callback.message:
            try:
                card_text = AuctionService.format_card_text(auction)
                keyboard = AuctionService.build_card_keyboard(auction)
                await callback.message.edit_text(card_text, reply_markup=keyboard)
            except Exception:
                pass
        return

    await callback.answer(reply_msg, show_alert=False)

    if callback.message and auction:
        try:
            card_text = AuctionService.format_card_text(auction)
            keyboard = AuctionService.build_card_keyboard(auction)
            await callback.message.edit_text(card_text, reply_markup=keyboard)
        except Exception as e:
            logger.debug("Не удалось обновить карточку аукциона: %s", e)


@router.callback_query(F.data.startswith("auc_refresh:"))
async def cb_auction_refresh(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Обработчик обновления карточки/таймера: auc_refresh:<id>"""
    parts = callback.data.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer()
        return

    auc_id = int(parts[1])
    auction = await session.scalar(select(Auction).where(Auction.id == auc_id))
    if not auction:
        await callback.answer("Аукцион не найден.", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    end_time_utc = _to_utc(auction.end_time)
    if auction.status == AuctionStatus.ACTIVE.value and end_time_utc and end_time_utc <= now:
        auction = await AuctionService.finalize_auction(session, auc_id)

    if callback.message and auction:
        try:
            card_text = AuctionService.format_card_text(auction)
            keyboard = AuctionService.build_card_keyboard(auction)
            await callback.message.edit_text(card_text, reply_markup=keyboard)
        except Exception:
            pass

    await callback.answer("🔄 Информация актуализирована!")


@router.callback_query(F.data.startswith("auc_close:"))
async def cb_auction_close(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Обработчик досрочного закрытия с кнопки: auc_close:<id>"""
    parts = callback.data.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer()
        return

    auc_id = int(parts[1])
    auction = await session.scalar(select(Auction).where(Auction.id == auc_id))
    if not auction:
        await callback.answer("Аукцион не найден.", show_alert=True)
        return

    is_admin = (
        HierarchyService.is_owner(db_user)
        or db_user.government_rank >= 3
        or db_user.id == auction.initiator_id
    )
    if not is_admin:
        await callback.answer("Завершить торги может только организатор или Администрация (Ранг 3+)!", show_alert=True)
        return

    auction = await AuctionService.finalize_auction(session, auc_id)
    if callback.message and auction:
        try:
            card_text = AuctionService.format_card_text(auction)
            keyboard = AuctionService.build_card_keyboard(auction)
            await callback.message.edit_text(card_text, reply_markup=keyboard)
        except Exception:
            pass

    await callback.answer("🏁 Аукцион завершен!", show_alert=True)


@router.callback_query(F.data.startswith("auc_closed:"))
async def cb_auction_already_closed(callback: CallbackQuery):
    await callback.answer("🔒 Торги по данному лоту уже завершены.", show_alert=True)
