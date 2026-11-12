import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from db.models import ChatSettings, ChatMember
from config import settings
from core.enums import PositionLevel, TopicType
from core.hierarchy_service import HierarchyService
from core.moderation_service import ModerationService, parse_duration
from core.topic_service import TopicService
from core.exceptions import TownBaseException
from bot.utils import extract_target_user, BOT_BAN_USER_NOTICE
from bot.filters.topic import TopicCommandFilter, auto_delete_messages
from bot.filters.role import MinRankFilter

logger = logging.getLogger("townbot.moderation")
router = Router(name="moderation_router")


@router.message(Command("warn", "варн", "предупреждение"), TopicCommandFilter(["reports", "admin", "court", "tickets"]))
async def cmd_warn(message: Message, session: AsyncSession, db_user: User):
    """
    Выдача предупреждения нарушителю (/warn [причина] в ответ на сообщение,
    или /warn @юзер [причина]).
    """
    if db_user.government_rank < 1:
        await message.reply("🚫 Выдавать предупреждения могут только сотрудники от Ранга 1 (Помощник)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/warn [причина]</code> ответом на сообщение нарушителя\n"
            "или: <code>/warn @username [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Нарушение регламента"

    try:
        warns, auto_muted, auto_banned, extra, punishment = await ModerationService.apply_warn(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"⚠️ <b>ВЫНЕСЕНО ПРЕДУПРЕЖДЕНИЕ ({warns}/5)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Нарушитель:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Модератор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
        f"{extra}"
    )
    await message.answer(reply_text)

    # Протокол в тему аудита
    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"ВАРН ({warns}/5)",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("unwarn", "анварн", "снять_варн"), TopicCommandFilter(["reports", "admin", "court"]))
async def cmd_unwarn(message: Message, session: AsyncSession, db_user: User):
    """Снятие предупреждения (/unwarn [причина], доступно с Ранга 2 - Блюститель)."""
    if db_user.government_rank < 2:
        await message.reply("🚫 Снимать предупреждения могут только сотрудники от Ранга 2 (Блюститель)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/unwarn [причина]</code> в ответ на сообщение\n"
            "или: <code>/unwarn @username [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Снятие предупреждения / исправление"

    try:
        new_warns, punishment = await ModerationService.remove_warn(
            session=session,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"✅ <b>ПРЕДУПРЕЖДЕНИЕ СНЯТО ({new_warns}/5)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Гражданин:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Сотрудник:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"СНЯТИЕ ВАРНА ({new_warns}/5)",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("mute", "мут"), TopicCommandFilter(["reports", "admin", "court", "tickets"]))
async def cmd_mute(message: Message, session: AsyncSession, db_user: User):
    """
    Выдача временного мута: /mute [время] [причина]
    Ранг 1 (Помощник): до 2ч
    Ранг 2 (Блюститель): до 24ч
    Ранг 3+ (Администрация): бессрочно
    """
    if db_user.government_rank < 1:
        await message.reply("🚫 Выдавать мут могут только сотрудники от Ранга 1 (Помощник)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/mute [время: 15m/1h/2d] [причина]</code> в ответ на сообщение\n"
            "или: <code>/mute @username 1h [причина]</code>"
        )
        return

    if not remaining_args:
        await message.reply("⚠️ Укажите длительность мута! Пример: <code>/mute 15m Флуд</code> или <code>/mute 2h Спам</code>")
        return

    duration = parse_duration(remaining_args[0])
    if not duration or duration <= 0:
        await message.reply(
            "⚠️ Неверный формат времени! Допустимые форматы: <code>15m</code>, <code>2h</code>, <code>1d</code>."
        )
        return

    reason = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else "Нарушение порядка"

    try:
        punishment = await ModerationService.apply_mute(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            duration_seconds=duration,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    # Красивое отображение времени
    if duration >= 86400:
        dur_str = f"{duration // 86400} дн."
    elif duration >= 3600:
        dur_str = f"{duration // 3600} ч."
    else:
        dur_str = f"{duration // 60} мин."

    reply_text = (
        f"🔇 <b>ОГРАНИЧЕНИЕ ПЕРЕПИСКИ (МУТ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Нарушитель:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Модератор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Срок:</b> {dur_str}\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"МУТ ({dur_str})",
        reason=reason,
        duration_str=dur_str,
        punishment_id=punishment.id,
    )


@router.message(Command("unmute", "размут"))
async def cmd_unmute(message: Message, session: AsyncSession, db_user: User):
    """Досрочное снятие мута: /unmute [причина]"""
    if db_user.government_rank < 1:
        await message.reply("🚫 Снимать мут могут только сотрудники от Ранга 1 (Помощник)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/unmute [причина]</code> в ответ на сообщение\n"
            "или: <code>/unmute @username [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Досрочное снятие ограничения"

    try:
        punishment = await ModerationService.apply_unmute(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"🔊 <b>ПРАВА ПЕРЕПИСКИ ВОССТАНОВЛЕНЫ (РАЗМУТ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Гражданин:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Модератор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="РАЗМУТ",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("kick", "кик"), TopicCommandFilter(["reports", "admin", "court"]))
async def cmd_kick(message: Message, session: AsyncSession, db_user: User):
    """Исключение из чата без постоянного бана: /kick [причина] (доступно с Ранга 2)."""
    if db_user.government_rank < 2:
        await message.reply("🚫 Исключать участников могут только сотрудники от Ранга 2 (Блюститель)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/kick [причина]</code> в ответ на сообщение\n"
            "или: <code>/kick @username [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Исключение из чата"

    try:
        punishment = await ModerationService.apply_kick(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"🚪 <b>ИСКЛЮЧЕНИЕ ИЗ ЧАТА (КИК)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Исключен:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Модератор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="КИК",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("ban", "бан"), TopicCommandFilter(["reports", "admin", "court"]))
async def cmd_ban(message: Message, session: AsyncSession, db_user: User):
    """Перманентный бан / изгнание из полиса: /ban [причина] (только Ранг 3+)."""
    if db_user.government_rank < 3:
        await message.reply(
            "🚫 <b>Блюстители не могут банить без санкции Судьи или Министра!</b>\n"
            "Запросите судебную санкцию на изгнание в Зале Суда (/court)."
        )
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/ban [причина]</code> в ответ на сообщение\n"
            "или: <code>/ban @username [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Изгнание из города"

    try:
        punishment = await ModerationService.apply_ban(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"🔨 <b>ИЗГНАНИЕ ИЗ ГОРОДА (БАН)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Изгнанный:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Постановил:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>\n"
        f"⚖️ <i>Право на судебную апелляцию: /appeal в Зале Суда.</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="БАН (ИЗГНАНИЕ)",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("unban", "разбан"), TopicCommandFilter(["reports", "admin", "court"]))
async def cmd_unban(message: Message, session: AsyncSession, db_user: User):
    """Снятие бана и восстановление гражданства: /unban <tg_id|@username> [причина] (Ранг 3+)."""
    if db_user.government_rank < 3:
        await message.reply("🚫 Снимать бан могут только сотрудники администрации от Ранга 3!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply("⚠️ Использование: <code>/unban @username [причина]</code> или <code>/unban telegram_id</code>")
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Помилование / снятие бана"

    try:
        punishment = await ModerationService.apply_unban(
            session=session,
            bot=message.bot,
            chat_id=message.chat.id,
            issuer=db_user,
            target=target_user,
            reason=reason,
        )
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reply_text = (
        f"🕊️ <b>ПОМИЛОВАНИЕ / СНЯТИЕ БАНА (РАЗБАН)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Гражданин:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Постановил:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>\n"
        f"✅ Гражданские права восстановлены."
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="РАЗБАН",
        reason=reason,
        punishment_id=punishment.id,
    )


@router.message(Command("clear", "del", "очистить"))
async def cmd_clear_messages(message: Message, session: AsyncSession, db_user: User):
    """
    Очистка чата от спама: /clear <кол-во> или /del в ответ на сообщение.
    Доступно сотрудникам с Ранга 1 (Помощник).
    """
    if db_user.government_rank < 1:
        await message.reply("🚫 Очищать сообщения могут только сотрудники от Ранга 1 (Помощник)!")
        return

    # Если вызвана в ответ на сообщение — удаляем конкретное сообщение и команду
    if message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply(
            "⚠️ Использование: <code>/clear [количество от 1 до 100]</code>\n"
            "или ответьте командой <code>/del</code> на сообщение, которое нужно удалить."
        )
        return

    count = int(parts[1])
    if count < 1:
        count = 1
    if count > 100:
        count = 100

    deleted_count = 0
    current_id = message.message_id

    # Удаляем сообщения одно за другим
    for offset in range(count + 1):  # включая само сообщение команды
        mid = current_id - offset
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=mid)
            if offset > 0:
                deleted_count += 1
        except Exception:
            pass

    confirm = await message.answer(f"🗑️ Удалено {deleted_count} сообщений.")
    asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [confirm.message_id], delay=3.0))


@router.message(Command("botban", "bot_ban", "банбот", "бан_бот"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "botban", "/botban", "!botban",
    "банбот", "/банбот", "!банбот",
    "бан_бот", "/бан_бот", "!бан_бот",
))))
async def cmd_bot_ban(message: Message, session: AsyncSession, db_user: User):
    """
    Глобальный бан в боте (эксклюзивно для Владельца бота):
    /банбот <reply | @username | tg_id> [причина]
    1. Блокирует пользователя во всем боте.
    2. Банит пользователя во всех группах сетки чатов.
    3. Отправляет нарушителю уведомление об обращении к @DivniDed для разбана.
    4. Предотвращает любой вход нарушителя в другие группы бота.
    """
    if not HierarchyService.is_owner(db_user):
        await message.reply(
            "🚫 <b>Отказано в доступе!</b>\n"
            "Команда глобальной блокировки в боте доступна исключительно Создателю и Владельцу бота (@DivniDed)."
        )
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ <b>Использование:</b> <code>/банбот [причина]</code> в ответ на сообщение нарушителя\n"
            "или: <code>/банбот @username [причина]</code>\n"
            "или: <code>/банбот telegram_id [причина]</code>"
        )
        return

    if HierarchyService.is_owner(target_user):
        await message.reply("🤦 Нельзя забанить в боте Создателя города!")
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Решение Создателя бота"

    # Устанавливаем флаг блокировки
    target_user.is_bot_banned = True
    target_user.bot_ban_reason = reason
    target_user.bot_banned_at = datetime.now(timezone.utc)

    # Баним во всех известных группах бота
    groups_settings = (await session.scalars(select(ChatSettings.chat_id).where(ChatSettings.chat_id < 0))).all()
    groups_members = (await session.scalars(select(ChatMember.chat_id).where(ChatMember.chat_id < 0).distinct())).all()
    all_chat_ids = set(groups_settings).union(set(groups_members))
    if message.chat and message.chat.id < 0:
        all_chat_ids.add(message.chat.id)

    banned_groups_count = 0
    for cid in all_chat_ids:
        try:
            await message.bot.ban_chat_member(chat_id=cid, user_id=target_user.telegram_id)
            banned_groups_count += 1
        except Exception as be:
            logger.debug("Не удалось забанить %s в группе %s: %s", target_user.telegram_id, cid, be)

    # Деактивируем статус участника в базе
    cm_records = (await session.scalars(
        select(ChatMember).where(ChatMember.telegram_id == target_user.telegram_id)
    )).all()
    for cm in cm_records:
        cm.is_active = False

    await session.commit()

    # Отправляем красивое личное уведомление нарушителю
    user_notice = BOT_BAN_USER_NOTICE.format(reason=reason)
    try:
        await message.bot.send_message(
            chat_id=target_user.telegram_id,
            text=user_notice,
            parse_mode="HTML"
        )
    except Exception as ne:
        logger.debug("Не удалось отправить личное сообщение пользователю %s: %s", target_user.telegram_id, ne)

    # Отвечаем Владельцу
    target_name = f"@{target_user.username}" if target_user.username else (target_user.full_name or f"ID {target_user.telegram_id}")
    reply_text = (
        f"⛔ <b>ГЛОБАЛЬНЫЙ БАН В БОТЕ (BOT BAN)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Нарушитель:</b> {target_name} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Инициатор:</b> @{db_user.username or 'DivniDed'} (Владелец бота)\n"
        f"• <b>Причина:</b> <i>{reason}</i>\n"
        f"• <b>Исключен из групп:</b> <b>{banned_groups_count}</b> чат(ов)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 <i>Пользователь полностью заблокирован в системе бота. При входе в любой чат сетки он будет мгновенно забанен повторно.</i>"
    )
    await message.reply(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="ГЛОБАЛЬНЫЙ БАН В БОТЕ",
        reason=reason,
    )


@router.message(Command("unbotban", "unbot_ban", "разбанбот", "разбан_бот"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "unbotban", "/unbotban", "!unbotban",
    "разбанбот", "/разбанбот", "!разбанбот",
    "разбан_бот", "/разбан_бот", "!разбан_бот",
))))
async def cmd_unbot_ban(message: Message, session: AsyncSession, db_user: User):
    """
    Снятие глобального бана в боте (эксклюзивно для Владельца бота):
    /разбанбот <reply | @username | tg_id> [причина]
    """
    if not HierarchyService.is_owner(db_user):
        await message.reply(
            "🚫 <b>Отказано в доступе!</b>\n"
            "Команда разбана в боте доступна исключительно Создателю и Владельцу бота (@DivniDed)."
        )
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ <b>Использование:</b> <code>/разбанбот [причина]</code> в ответ на сообщение\n"
            "или: <code>/разбанбот @username [причина]</code>\n"
            "или: <code>/разбанбот telegram_id [причина]</code>"
        )
        return

    if not getattr(target_user, "is_bot_banned", False):
        await message.reply(f"ℹ️ Пользователь <code>{target_user.telegram_id}</code> не заблокирован в боте.")
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Решение Создателя бота"

    target_user.is_bot_banned = False
    target_user.bot_ban_reason = None
    target_user.bot_banned_at = None

    # Разбаниваем в группах, чтобы пользователь мог снова зайти
    groups_settings = (await session.scalars(select(ChatSettings.chat_id).where(ChatSettings.chat_id < 0))).all()
    groups_members = (await session.scalars(select(ChatMember.chat_id).where(ChatMember.chat_id < 0).distinct())).all()
    all_chat_ids = set(groups_settings).union(set(groups_members))
    if message.chat and message.chat.id < 0:
        all_chat_ids.add(message.chat.id)

    unbanned_count = 0
    for cid in all_chat_ids:
        try:
            await message.bot.unban_chat_member(chat_id=cid, user_id=target_user.telegram_id, only_if_banned=True)
            unbanned_count += 1
        except Exception:
            pass

    await session.commit()

    # Уведомляем пользователя
    try:
        await message.bot.send_message(
            chat_id=target_user.telegram_id,
            text=(
                "🕊️ <b>БЛОКИРОВКА В БОТЕ СНЯТА</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Создатель бота (@DivniDed) разблокировал ваш аккаунт в TownBot.\n"
                f"📝 <b>Причина:</b> <i>{reason}</i>\n\n"
                "Вам вновь открыт доступ ко всем сервисам и чатам города."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    target_name = f"@{target_user.username}" if target_user.username else (target_user.full_name or f"ID {target_user.telegram_id}")
    reply_text = (
        f"✅ <b>ГЛОБАЛЬНЫЙ РАЗБАН В БОТЕ (UNBOT BAN)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Пользователь:</b> {target_name} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Инициатор:</b> @{db_user.username or 'DivniDed'} (Владелец бота)\n"
        f"• <b>Причина:</b> <i>{reason}</i>\n"
        f"• <b>Разблокирован в группах:</b> <b>{unbanned_count}</b> чат(ов)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔓 <i>Глобальная блокировка аннулирована. Пользователь снова может взаимодействовать с ботом.</i>"
    )
    await message.reply(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="СНЯТИЕ БАНА В БОТЕ",
        reason=reason,
    )
