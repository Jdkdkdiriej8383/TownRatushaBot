import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from core.fine_service import FineService
from core.auction_service import AuctionService, _to_utc
from core.enums import AuctionStatus
from db.models import Auction
from config import settings

logger = logging.getLogger(__name__)


async def check_overdue_fines_job(session_maker: async_sessionmaker[AsyncSession], bot: Bot):
    """
    Фоновый воркер:
    Проверяет неоплаченные штрафы со сроком > 48 часов.
    Удваивает сумму (x2), переводит в розыск и отправляет депешу в чат.
    """
    try:
        async with session_maker() as session:
            overdue_items = await FineService.process_overdue_fines(session)
            if not overdue_items:
                return

            logger.info("Обработано %s просроченных штрафов (>48ч).", len(overdue_items))

            chat_id = settings.MAIN_CHAT_ID
            for fine, user in overdue_items:
                alert_text = (
                    f"🚨 <b>ВНИМАНИЕ: СРОК ОПЛАТЫ ШТРАФА ИСТЕК (п. 3.12)!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Гражданин: <b>{user.full_name}</b> (@{user.username or '—'})\n"
                    f"Тикет штрафа: № {fine.id} (ст. {fine.law_article})\n"
                    f"Сумма штрафа <b>УДВОЕНА (x2)</b> и составляет: <code>{fine.amount:,}</code> валюты!\n\n"
                    f"🚨 <b>ГРАЖДАНИН ОБЪЯВЛЕН В ОБЩЕГОРОДСКОЙ РОЗЫСК!</b>\n"
                    f"Блюстителям порядка предписано задержать неплательщика до полного погашения долга.\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )

                if chat_id:
                    try:
                        await bot.send_message(chat_id=chat_id, text=alert_text)
                    except Exception as e:
                        logger.error("Не удалось отправить депешу о розыске в чат %s: %s", chat_id, e)

    except Exception as e:
        logger.exception("Ошибка в фоновом воркере проверки штрафов: %s", e)


async def check_expired_auctions_job(session_maker: async_sessionmaker[AsyncSession], bot: Bot):
    """
    Фоновый воркер:
    Проверяет активные аукционы, время которых истекло.
    Завершает торги, распределяет средства в Государственную казну и обновляет карточку лота.
    """
    try:
        async with session_maker() as session:
            now = datetime.now(timezone.utc)
            query = select(Auction).where(Auction.status == AuctionStatus.ACTIVE.value)
            result = await session.execute(query)
            active_auctions = list(result.scalars().all())
            expired_auctions = [
                auc for auc in active_auctions
                if (end_utc := _to_utc(auc.end_time)) and end_utc <= now
            ]

            for auc in expired_auctions:
                closed_auc = await AuctionService.finalize_auction(session, auc.id)
                if not closed_auc:
                    continue

                card_text = AuctionService.format_card_text(closed_auc)
                keyboard = AuctionService.build_card_keyboard(closed_auc)

                if closed_auc.message_id and closed_auc.chat_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=closed_auc.chat_id,
                            message_id=closed_auc.message_id,
                            text=card_text,
                            reply_markup=keyboard
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.exception("Ошибка в фоновом воркере проверки аукционов: %s", e)


async def start_scheduler_loop(session_maker: async_sessionmaker[AsyncSession], bot: Bot, interval_seconds: int = 60):
    """Бесконечный цикл периодической проверки штрафов и аукционов."""
    logger.info("Фоновый планировщик проверки штрафов и аукционов запущен (интервал %s сек).", interval_seconds)
    while True:
        await check_overdue_fines_job(session_maker, bot)
        await check_expired_auctions_job(session_maker, bot)
        await asyncio.sleep(interval_seconds)
