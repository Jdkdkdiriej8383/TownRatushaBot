import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from core.enums import PositionLevel, GovernmentRole, ROLE_ALIASES, resolve_role_alias, TopicType
from core.hierarchy_service import HierarchyService
from core.topic_service import TopicService, TOPIC_TYPE_TITLES
from core.moderation_service import ModerationService
from core.exceptions import TownBaseException
from bot.utils import extract_target_user
from bot.filters.topic import TopicCommandFilter

logger = logging.getLogger("townbot.admin")
router = Router(name="admin_router")

SETROLE_DEFINITIONS: list[tuple[str, str, int, str]] = [
    # (label, code, role_level, title)
    ("👑 Мэр (Ранг 4)", "mayor", PositionLevel.SENIOR_ADMINISTRATION.value, GovernmentRole.MAYOR.value),
    ("🏛️ Премьер (Ранг 4)", "pm", PositionLevel.SENIOR_ADMINISTRATION.value, GovernmentRole.PRIME_MINISTER.value),
    ("⚖️ Конст. судья (Ранг 4)", "cjudge", PositionLevel.SENIOR_ADMINISTRATION.value, GovernmentRole.CHIEF_JUSTICE.value),
    ("🏛️ Зам. мэра (Ранг 3)", "deputy", PositionLevel.ADMINISTRATION.value, GovernmentRole.DEPUTY_MAYOR.value),
    ("💼 Министр (Ранг 3)", "min", PositionLevel.ADMINISTRATION.value, GovernmentRole.MINISTER.value),
    ("⚖️ Судья (Ранг 3)", "judge", PositionLevel.ADMINISTRATION.value, GovernmentRole.JUDGE.value),
    ("🛡️ Блюститель (Ранг 2)", "warden", PositionLevel.CHAT_WARDEN.value, GovernmentRole.WARDEN.value),
    ("🔰 Помощник (Ранг 1)", "help", PositionLevel.ASSISTANT.value, GovernmentRole.ASSISTANT.value),
    ("👤 Снять в Граждане (Ранг 0)", "cit", PositionLevel.CITIZEN.value, GovernmentRole.CITIZEN.value),
]

ROLE_CODE_MAP: dict[str, tuple[int, str]] = {
    code: (level, title) for _, code, level, title in SETROLE_DEFINITIONS
}


def build_role_keyboard(initiator: User, target: User) -> InlineKeyboardMarkup:
    """Генерирует инлайн-клавиатуру только с теми должностями, которые инициатор имеет право назначить."""
    builder = InlineKeyboardBuilder()

    for label, code, level, title in SETROLE_DEFINITIONS:
        can_appoint, _ = HierarchyService.can_appoint_role(
            initiator=initiator,
            target=target,
            target_level=level,
            target_title=title,
        )
        if can_appoint:
            builder.button(
                text=label,
                callback_data=f"setrole:{target.telegram_id}:{code}"
            )

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"setrole:{target.telegram_id}:cancel"))
    return builder.as_markup()


@router.message(Command("setrole", "set_role", "роль", "должность", "назначить", "дать_роль", "role"))
@router.message(F.text.regexp(r"^!(?:setrole|set_role|роль|должность|назначить|дать_роль|role)(?:\s|$)"))
async def cmd_setrole(message: Message, session: AsyncSession, db_user: User):
    """
    Назначение государственной должности: /setrole <reply|id|@user> [должность]
    Если должность не указана, открывает интерактивные кнопки для назначения в 1 клик.
    Строго соблюдается субординация: Ранг_Инициатора > Целевой_Ранг.
    """
    # Проверка базовых административных полномочий инициатора
    is_admin = (
        HierarchyService.is_owner(db_user)
        or db_user.government_rank >= 3
        or db_user.custom_title == GovernmentRole.DEPUTY_MAYOR.value
    )
    if not is_admin:
        await message.reply("🚫 <b>Отказано:</b> Назначать на государственные должности разрешено только Администрации (Ранг 3+)!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        if raw_args and raw_args[0].startswith("@"):
            await message.reply(
                f"❌ Пользователь <b>{raw_args[0]}</b> не найден в базе данных бота.\n\n"
                "💡 <b>Как назначить:</b>\n"
                "1. Ответьте на любое сообщение кандидата командой <code>/роль</code>\n"
                "2. Или укажите числовой Telegram ID: <code>/setrole 123456789 [должность]</code>\n"
                "3. Или попросите кандидата написать сообщение в чат бота."
            )
            return

        await message.reply(
            "👑 <b>ГОСУДАРСТВЕННЫЕ НАЗНАЧЕНИЯ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>Самый удобный способ:</b>\n"
            "• Ответьте командой <code>/роль</code> на сообщение кандидата — бот откроет интерактивные кнопки!\n\n"
            "📝 <b>Текстовые форматы:</b>\n"
            "• <code>/setrole @username [должность]</code>\n"
            "• <code>/setrole [ID] [должность]</code>\n"
            "• <code>/роль [должность]</code> <i>(ответом на сообщение)</i>\n\n"
            "🎖️ <b>Ранги и должности:</b>\n"
            "• <b>Ранг 4:</b> Мэр, Премьер-министр, Конст. судья (или <code>4</code>)\n"
            "• <b>Ранг 3:</b> Заместитель мэра, Министр, Судья (или <code>3</code>)\n"
            "• <b>Ранг 2:</b> Блюститель (или <code>модер</code>, <code>2</code>)\n"
            "• <b>Ранг 1:</b> Помощник (или <code>хелпер</code>, <code>1</code>)\n"
            "• <b>Ранг 0:</b> Гражданин (или <code>снять</code>, <code>0</code>)"
        )
        return

    # Субординация по текущему рангу кандидата
    if not HierarchyService.is_owner(db_user) and db_user.government_rank <= target_user.government_rank:
        await message.reply(
            f"🚫 <b>Нарушение субординации!</b>\n"
            f"Вы ({db_user.position_title}, Ранг {db_user.government_rank}) не можете изменять должность "
            f"равного или старшего сотрудника (@{target_user.username or target_user.full_name}, {target_user.position_title})."
        )
        return

    # Если должность не указана текстом — показываем интерактивную клавиатуру
    if not remaining_args:
        kb = build_role_keyboard(initiator=db_user, target=target_user)
        uname = f"@{target_user.username}" if target_user.username else target_user.full_name
        current_title = target_user.custom_title or target_user.position_title
        await message.reply(
            f"👑 <b>ГОСУДАРСТВЕННОЕ НАЗНАЧЕНИЕ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Кандидат:</b> {uname} (ID: <code>{target_user.telegram_id}</code>)\n"
            f"• <b>Текущий статус:</b> {current_title} (Ранг {target_user.government_rank})\n"
            f"• <b>Инициатор:</b> @{db_user.username or '—'} ({db_user.position_title})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Выберите новую государственную должность одним нажатием:</i>",
            reply_markup=kb,
        )
        return

    # Если должность передана текстом — парсим и применяем
    role_input = " ".join(remaining_args).strip().lower()
    role_info = resolve_role_alias(role_input)

    if not role_info:
        await message.reply(
            f"❌ Неизвестная должность «{role_input}»!\n\n"
            f"💡 <b>Доступные варианты:</b>\n"
            f"• <b>Ранг 4:</b> Мэр, Премьер, Конст. судья (или <code>4</code>)\n"
            f"• <b>Ранг 3:</b> Зам. мэра, Министр, Судья (или <code>3</code>)\n"
            f"• <b>Ранг 2:</b> Блюститель (или <code>модер</code>, <code>2</code>)\n"
            f"• <b>Ранг 1:</b> Помощник (или <code>хелпер</code>, <code>1</code>)\n"
            f"• <b>Ранг 0:</b> Гражданин (или <code>0</code>, <code>снять</code>)\n\n"
            f"<i>Совет: отправьте <code>/роль</code> без текста, чтобы выбрать кнопкой.</i>"
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
    target_user.custom_title = target_title if target_level > 0 else None
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

    try:
        await message.bot.send_message(
            chat_id=target_user.telegram_id,
            text=(
                f"👑 <b>Вам присвоена государственная должность!</b>\n\n"
                f"🎖️ Должность: <b>{target_title}</b> (Ранг {target_user.government_rank})\n"
                f"🏛️ Приказ подписал: @{db_user.username or db_user.full_name} ({db_user.position_title})"
            )
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("setrole:"))
async def cb_setrole_select(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Обработка выбора должности через интерактивную инлайн-клавиатуру."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных", show_alert=True)
        return

    target_id = int(parts[1])
    role_code = parts[2]

    if role_code == "cancel":
        await callback.message.edit_text("❌ Назначение должности отменено.", reply_markup=None)
        await callback.answer("Отменено")
        return

    if role_code not in ROLE_CODE_MAP:
        await callback.answer("❌ Неизвестная должность", show_alert=True)
        return

    target_level, target_title = ROLE_CODE_MAP[role_code]

    target_user = await session.scalar(select(User).where(User.telegram_id == target_id))
    if not target_user:
        await callback.answer("❌ Кандидат не найден в базе данных", show_alert=True)
        return

    can_appoint, reason = HierarchyService.can_appoint_role(
        initiator=db_user,
        target=target_user,
        target_level=target_level,
        target_title=target_title,
    )
    if not can_appoint:
        await callback.answer(f"🚫 {reason}", show_alert=True)
        return

    # Применяем новую должность
    target_user.role_level = target_level
    target_user.custom_title = target_title if target_level > 0 else None
    target_user.is_enemy = False
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
    await callback.message.edit_text(reply_text, reply_markup=None)
    await callback.answer("✅ Должность успешно присвоена!")

    await ModerationService.send_audit_log(
        bot=callback.bot,
        session=session,
        chat_id=callback.message.chat.id,
        target=target_user,
        issuer=db_user,
        action_title=f"НАЗНАЧЕНИЕ: {target_title}",
        reason="Государственное распоряжение (через меню)",
    )

    try:
        await callback.bot.send_message(
            chat_id=target_user.telegram_id,
            text=(
                f"👑 <b>Вам присвоена государственная должность!</b>\n\n"
                f"🎖️ Должность: <b>{target_title}</b> (Ранг {target_user.government_rank})\n"
                f"🏛️ Приказ подписал: @{db_user.username or db_user.full_name} ({db_user.position_title})"
            )
        )
    except Exception:
        pass


@router.message(Command("demote", "разжаловать", "снять", "снять_роль", "демот"))
@router.message(F.text.regexp(r"^!(?:demote|разжаловать|снять|снять_роль|демот)(?:\s|$)"))
async def cmd_demote(message: Message, session: AsyncSession, db_user: User):
    """Разжалование сотрудника в рядового Гражданина: /demote <reply|id|@user> [причина]"""
    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        if raw_args and raw_args[0].startswith("@"):
            await message.reply(
                f"❌ Пользователь <b>{raw_args[0]}</b> не найден в базе данных.\n"
                "💡 Ответьте командой <code>/demote</code> на сообщение сотрудника или укажите его Telegram ID."
            )
            return

        await message.reply(
            "⚠️ <b>Использование:</b> <code>/demote @username [причина]</code>\n"
            "или ответом на сообщение: <code>/demote [причина]</code>\n"
            "<i>Синонимы:</i> <code>/разжаловать</code>, <code>/снять</code>"
        )
        return

    try:
        HierarchyService.validate_seniority(initiator=db_user, target=target_user, action_name="разжалование")
    except TownBaseException as e:
        await message.reply(f"❌ {e.message}")
        return

    if target_user.government_rank == 0 and not target_user.custom_title:
        await message.reply(f"ℹ️ @{target_user.username or target_user.full_name} уже является рядовым Гражданином.")
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
        f"• <b>Причина:</b> <i>{reason}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 <i>Сотрудник освобожден от занимаемой должности.</i>"
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


@router.message(Command("staff", "состав", "чиновники"))
@router.message(F.text.regexp(r"^!(?:staff|состав|чиновники)(?:\s|$)"))
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

    ranks_map: dict[int, list[User]] = {4: [], 3: [], 2: [], 1: []}
    for m in staff_members:
        rank = m.government_rank
        # Объединяем высшую администрацию (ранги 4 и 5) вместе без публичного выделения овнера
        effective_rank = 4 if rank >= 4 else rank
        if effective_rank in ranks_map:
            ranks_map[effective_rank].append(m)

    lines = [
        "🏛️ <b>ГОСУДАРСТВЕННЫЙ АППАРАТ</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    rank_headers = {
        4: "👑 <b>Ранг 4: Высшая администрация (Supreme Admins)</b>",
        3: "⚖️ <b>Ранг 3: Администрация (Middle Admins)</b>",
        2: "🛡️ <b>Ранг 2: Блюстители (Senior Moderators)</b>",
        1: "🔰 <b>Ранг 1: Помощники (Junior Moderators)</b>",
    }

    for rank in [4, 3, 2, 1]:
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
