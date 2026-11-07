import asyncio
import logging
from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from core.fine_service import FineService
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


async def start_scheduler_loop(session_maker: async_sessionmaker[AsyncSession], bot: Bot, interval_seconds: int = 60):
    """Бесконечный цикл периодической проверки штрафов."""
    logger.info("Фоновый планировщик проверки штрафов запущен (интервал %s сек).", interval_seconds)
    while True:
        await check_overdue_fines_job(session_maker, bot)
        await asyncio.sleep(interval_seconds)
