import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from core.enums import PositionLevel, GovernmentRole, ROLE_ALIASES, TopicType
from core.hierarchy_service import HierarchyService
from core.topic_service import TopicService, TOPIC_TYPE_TITLES
from core.moderation_service import ModerationService
from core.exceptions import TownBaseException
from bot.utils import extract_target_user
from bot.filters.topic import TopicCommandFilter

logger = logging.getLogger("townbot.admin")
router = Router(name="admin_router")


@router.message(Command("setrole", "роль", "должность"), TopicCommandFilter(["admin"]))
async def cmd_setrole(message: Message, session: AsyncSession, db_user: User):
    """
    Назначение государственной должности: /setrole <reply|id|@user> <должность>
    Строго соблюдается субординация: Ранг_Инициатора > Целевой_Ранг.
    """
    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/setrole @username &lt;должность&gt;</code>\n"
            "или ответом на сообщение: <code>/setrole &lt;должность&gt;</code>\n\n"
            "<b>Доступные должности:</b> Мэр, Премьер-министр, Конституционный судья, "
            "Заместитель мэра, Министр, Судья, Блюститель, Помощник, Гражданин."
        )
        return

    if not remaining_args:
        await message.reply(
            "⚠️ Укажите желаемую должность! Пример: <code>/setrole @username Министр</code>\n"
            "Доступные: Мэр, Премьер, Судья, Министр, Блюститель, Помощник, Гражданин."
        )
        return

    role_input = " ".join(remaining_args).strip().lower()
    role_info = ROLE_ALIASES.get(role_input)

    if not role_info:
        # Попробуем частичный поиск
        matched = None
        for alias, info in ROLE_ALIASES.items():
            if alias in role_input or role_input in alias:
                matched = info
                break
        if matched:
            role_info = matched
        else:
            await message.reply(
                f"❌ Неизвестная должность «{role_input}»!\n"
                f"Допустимо: <i>Мэр, Премьер-министр, Конституционный судья, Заместитель мэра, "
                f"Министр, Судья, Блюститель, Помощник, Гражданин</i>."
            )
            return

    target_level, target_title = role_info

    # Проверка права назначения через HierarchyService
    can_appoint, reason = HierarchyService.can_appoint_role(
        initiator=db_user,
        target=target_user,
        target_level=target_level,
        target_title=target_title,
    )
    if not can_appoint:
        await message.reply(f"🚫 <b>Отказано в назначении:</b> {reason}")
        return

    # Применяем новую должность
    target_user.role_level = target_level
    target_user.custom_title = target_title
    target_user.is_enemy = False  # Снимаем статус врага, если назначается должность
    await session.commit()
    await session.refresh(target_user)

    reply_text = (
        f"👑 <b>ГОСУДАРСТВЕННОЕ НАЗНАЧЕНИЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Гражданин:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Новая должность:</b> 🎖️ <b>{target_title}</b> (Ранг {target_user.government_rank})\n"
        f"• <b>Назначил:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 <i>Указ о назначении вступил в законную силу.</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"НАЗНАЧЕНИЕ: {target_title}",
        reason="Государственное распоряжение",
    )


@router.message(Command("demote", "разжаловать", "снять"), TopicCommandFilter(["admin"]))
async def cmd_demote(message: Message, session: AsyncSession, db_user: User):
    """Разжалование сотрудника в рядового Гражданина: /demote <reply|id|@user>"""
    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "⚠️ Использование: <code>/demote @username [причина]</code>\n"
            "или ответом на сообщение: <code>/demote [причина]</code>"
        )
        return

    try:
        HierarchyService.validate_seniority(initiator=db_user, target=target_user, action_name="разжалование")
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Служебное несоответствие"

    prev_title = target_user.custom_title or target_user.position_title
    target_user.role_level = PositionLevel.CITIZEN.value
    target_user.custom_title = None
    await session.commit()
    await session.refresh(target_user)

    reply_text = (
        f"📉 <b>РАЗЖАЛОВАНИЕ В ДОЛЖНОСТИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Сотрудник:</b> @{target_user.username or '—'} (<code>{target_user.telegram_id}</code>)\n"
        f"• <b>Прежняя должность:</b> {prev_title}\n"
        f"• <b>Текущий статус:</b> 👤 <b>Гражданин</b> (Ранг 0)\n"
        f"• <b>Инициатор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
        f"• <b>Причина:</b> <i>{reason}</i>"
    )
    await message.answer(reply_text)

    await ModerationService.send_audit_log(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title="РАЗЖАЛОВАНИЕ В ГРАЖДАНИНА",
        reason=reason,
    )


@router.message(Command("staff", "состав", "чиновники"), TopicCommandFilter(["admin", "community", "reports", "tickets", "court"]))
async def cmd_staff(message: Message, session: AsyncSession, db_user: User):
    """Список действующего государственного аппарата и модерации по рангам."""
    query = (
        select(User)
        .where(User.role_level >= PositionLevel.ASSISTANT.value)
        .order_by(User.role_level.desc(), User.id.asc())
    )
    staff_members = (await session.scalars(query)).all()

    if not staff_members:
        await message.answer("ℹ️ Действующий состав администрации пока не назначен.")
        return

    ranks_map: dict[int, list[User]] = {5: [], 4: [], 3: [], 2: [], 1: []}
    for m in staff_members:
        rank = m.government_rank
        if rank in ranks_map:
            ranks_map[rank].append(m)

    lines = [
        "🏛️ <b>ГОСУДАРСТВЕННЫЙ АППАРАТ</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    rank_headers = {
        5: "👑 <b>Ранг 5: Создатель и Владелец города (Founder)</b>",
        4: "🏛 <b>Ранг 4: Высшая администрация (Supreme Admins)</b>",
        3: "⚖️ <b>Ранг 3: Администрация (Middle Admins)</b>",
        2: "🛡️ <b>Ранг 2: Блюстители (Senior Moderators)</b>",
        1: "🔰 <b>Ранг 1: Помощники (Junior Moderators)</b>",
    }

    for rank in [5, 4, 3, 2, 1]:
        members = ranks_map[rank]
        if not members:
            continue
        lines.append(rank_headers[rank])
        for u in members:
            uname = f"@{u.username}" if u.username else u.full_name
            title = u.custom_title or u.position_title
            merits = f" [Обращений: {u.closed_tickets_count}]" if u.closed_tickets_count else ""
            lines.append(f"• {uname} — <b>{title}</b>{merits}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"👥 Всего должностных лиц на службе: <b>{len(staff_members)}</b>\n")
    lines.append("💡 <i>Сотрудники должны открыть диалог с ботом в ЛС (/start), чтобы получать карточки жалоб персонально.</i>")

    await message.answer("\n".join(lines))


@router.message(Command("decree", "указ"))
async def cmd_decree(message: Message, session: AsyncSession, db_user: User):
    """
    Издание системного государственного указа (только Мэр, Премьер-министр или Овнер).
    Публикуется с особым форматированием и автоматически закрепляется (пин) в DECREES_TOPIC_ID.
    """
    is_mayor = db_user.custom_title == GovernmentRole.MAYOR.value
    is_pm = db_user.custom_title == GovernmentRole.PRIME_MINISTER.value
    is_owner = HierarchyService.is_owner(db_user)

    if not (is_mayor or is_pm or is_owner):
        await message.reply(
            "🚫 <b>Право издания государственных указов</b> принадлежит исключительно "
            "Мэру и Премьер-министру города!"
        )
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "📜 <b>Издание государственного указа:</b>\n"
            "Использование: <code>/decree [полный текст указа или регламента]</code>"
        )
        return

    decree_text = parts[1].strip()

    decree_card = (
        "📜 <b>ГОСУДАРСТВЕННЫЙ УКАЗ ПРАВИТЕЛЬСТВА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "В соответствии с исключительными полномочиями Высшей исполнительной власти города:\n\n"
        f"{decree_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Подписал:</b> {db_user.position_title} @{db_user.username or db_user.full_name}\n"
        "📅 <i>Указ вступает в законную силу немедленно с момента обнародования.</i>"
    )

    # Определяем топик для указов
    decrees_thread_id = await TopicService.get_topic_thread_id(
        session=session, chat_id=message.chat.id, topic_type=TopicType.DECREES.value
    )

    target_chat_id = message.chat.id
    target_thread_id = decrees_thread_id or getattr(message, "message_thread_id", None)

    try:
        sent_decree = await message.bot.send_message(
            chat_id=target_chat_id,
            message_thread_id=target_thread_id,
            text=decree_card,
        )
        # Автоматически закрепляем (пин)
        try:
            await message.bot.pin_chat_message(
                chat_id=target_chat_id,
                message_id=sent_decree.message_id,
                disable_notification=False,
            )
        except Exception as e:
            logger.warning("Не удалось закрепить указ: %s", e)

        await message.reply("✅ Указ успешно опубликован и закреплен в официальном ведомстве!")
    except Exception as e:
        logger.error("Ошибка при публикации указа: %s", e)
        await message.reply(f"❌ Ошибка публикации указа: {e}")


@router.message(Command("settopic", "топик"))
async def cmd_settopic(message: Message, session: AsyncSession, db_user: User):
    """
    Привязка текущей форумной темы к функционалу бота:
    /settopic <community|reports|tickets|court|admin|decrees|logs>
    Доступно Мэру и Владельцу.
    """
    is_mayor = db_user.custom_title == GovernmentRole.MAYOR.value or db_user.is_supreme_admin
    is_owner = HierarchyService.is_owner(db_user)

    if not (is_mayor or is_owner):
        await message.reply("🚫 Настраивать привязку тем форума могут только Мэр и Владелец!")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        valid_types = ", ".join(f"<code>{t.value}</code>" for t in TopicType)
        await message.reply(
            f"⚠️ Использование: <code>/settopic &lt;тип_темы&gt;</code>\n\n"
            f"<b>Допустимые типы:</b>\n{valid_types}"
        )
        return

    topic_type_str = parts[1].strip().lower()
    valid_values = [t.value for t in TopicType]
    if topic_type_str not in valid_values:
        await message.reply(f"❌ Неверный тип темы! Допустимо: {', '.join(valid_values)}")
        return

    current_thread_id = getattr(message, "message_thread_id", None)
    type_title = TOPIC_TYPE_TITLES.get(topic_type_str, topic_type_str)

    await TopicService.set_topic_mapping(
        session=session,
        chat_id=message.chat.id,
        topic_type=topic_type_str,
        thread_id=current_thread_id or 0,
        topic_name=type_title,
    )

    await message.reply(
        f"✅ <b>Тема успешно привязана!</b>\n"
        f"• <b>Тип:</b> {type_title} (<code>{topic_type_str}</code>)\n"
        f"• <b>Thread ID:</b> <code>{current_thread_id}</code>"
    )
