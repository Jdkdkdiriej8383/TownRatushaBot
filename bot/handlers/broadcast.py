import asyncio
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from core.enums import PositionLevel
from core.hierarchy_service import HierarchyService
from config import settings

logger = logging.getLogger("townbot.broadcast")
router = Router(name="broadcast_router")


@router.message(Command("bc", "broadcast", "рассылка"))
async def cmd_broadcast(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /bc <сообщение> (или /broadcast, /рассылка)
    Отправляет рассылку всем зарегистрированным пользователям бота.
    Доступно исключительно Владельцу города и Высшей Администрации (Ранг 4+).
    """
    is_owner = (
        HierarchyService.is_owner(db_user)
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
        or db_user.government_rank >= 4
        or db_user.role_level >= PositionLevel.SENIOR_ADMINISTRATION.value
    )
    if not is_owner:
        await message.reply("🚫 <b>Отказано:</b> Запуск глобальной рассылки разрешен только Владельцу города и Высшей Администрации!")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "📢 <b>ГЛОБАЛЬНАЯ РАССЫЛКА (/bc)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Использование: <code>/bc [текст сообщения]</code>\n\n"
            "<i>Пример:</i>\n"
            "<code>/bc 📢 Внимание жителям! Сегодня в 19:00 состоится общегородское собрание в Ратуше.</code>\n\n"
            "💡 <i>Поддерживается HTML-разметка. Сообщение будет доставлено всем гражданам в ЛС бота.</i>"
        )
        return

    broadcast_text = parts[1].strip()

    status_msg = await message.answer("⏳ <i>Подготовка базы получателей для рассылки...</i>")

    # Получаем всех уникальных пользователей из базы
    users_query = select(User.telegram_id).where(User.telegram_id > 0).distinct()
    user_ids = (await session.scalars(users_query)).all()
    total_users = len(user_ids)

    if total_users == 0:
        await status_msg.edit_text("❌ В базе данных не найдено ни одного пользователя для рассылки.")
        return

    formatted_card = (
        f"📢 <b>ОФИЦИАЛЬНОЕ ОПОВЕЩЕНИЕ ГОРОДА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{broadcast_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛 <i>Отправлено Администрацией Города</i>"
    )

    await status_msg.edit_text(f"🚀 <i>Запуск рассылки для {total_users} граждан...</i>")

    delivered_count = 0
    blocked_count = 0
    failed_count = 0

    for i, target_id in enumerate(user_ids, 1):
        try:
            await message.bot.send_message(
                chat_id=target_id,
                text=formatted_card,
            )
            delivered_count += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.bot.send_message(chat_id=target_id, text=formatted_card)
                delivered_count += 1
            except Exception:
                failed_count += 1
        except TelegramForbiddenError:
            blocked_count += 1
        except TelegramBadRequest:
            failed_count += 1
        except Exception as e:
            logger.debug(f"Broadcast failed for {target_id}: {e}")
            failed_count += 1

        # Небольшая пауза для соблюдения лимитов Telegram (30 сообщений/сек)
        if i % 25 == 0:
            await asyncio.sleep(0.5)

    result_text = (
        f"📢 <b>РАССЫЛКА УСПЕШНО ЗАВЕРШЕНА!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• 👥 <b>Всего получателей в базе:</b> {total_users}\n"
        f"• ✅ <b>Успешно доставлено:</b> {delivered_count}\n"
        f"• 🚫 <b>Заблокировали бота / ЛС закрыто:</b> {blocked_count}\n"
        f"• ⚠️ <b>Ошибки доставки:</b> {failed_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(result_text)
