from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Regulator, ChatSettings, User
from core.enums import PositionLevel
from core.regulators import format_duration

router = Router(name="regulators_admin_router")


@router.message(Command("регуляторы"))
async def cmd_view_regulators(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /регуляторы — сводка регуляторов полномочий всех должностей (0-5)
    и текущее состояние защит чата.
    """
    # 1. Загружаем все регуляторы
    regulators_query = select(Regulator).order_by(Regulator.role_level)
    regulators = (await session.scalars(regulators_query)).all()

    # 2. Загружаем настройки текущего чата
    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == message.chat.id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=message.chat.id)
        session.add(chat_settings)
        await session.flush()

    status_icon = lambda val: "🟢 Включен" if val else "🔴 Отключен"

    lines = [
        "⚙️ <b>КОНФИГУРАЦИЯ СИСТЕМЫ «РЕГУЛЯТОРОВ»</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🛡 <b>Защитные регуляторы чата:</b>",
        f"• Анти-капс (>70%): {status_icon(chat_settings.anti_caps_enabled)}",
        f"• Медиа-спам (>3 подряд): {status_icon(chat_settings.media_spam_enabled)}",
        f"• Защита от рекламы/ссылок: {status_icon(chat_settings.anti_link_enabled)}",
        "",
        "📊 <b>Лимиты полномочий по должностям:</b>",
    ]

    for reg in regulators:
        mute_info = format_duration(reg.max_mute_time) if reg.max_mute_time > 0 else "запрещено"
        fine_info = f"до {reg.max_fine_amount:,}" if reg.max_fine_amount > 0 else "запрещено"
        ban_info = "Да" if reg.can_ban else "Нет"
        laws_info = "Да" if reg.can_edit_laws else "Нет"

        lines.append(
            f"🎖 <b>[{reg.role_level}] {reg.title}:</b>\n"
            f"   • Мут: <code>{mute_info}</code> | Штраф: <code>{fine_info}</code>\n"
            f"   • Бан: <code>{ban_info}</code> | Правка законов: <code>{laws_info}</code>"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Переключение защит (для Администрации): <code>/антикапс вкл/выкл</code>, <code>/медиаспам вкл/выкл</code>, <code>/антиссылки вкл/выкл</code></i>")

    await message.answer("\n".join(lines))


@router.message(Command("антикапс"))
async def cmd_toggle_anticaps(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора анти-капса."""
    if db_user.role_level < PositionLevel.ADMINISTRATION.value:
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == message.chat.id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=message.chat.id)
        session.add(chat_settings)

    args = message.text.split()
    if len(args) > 1:
        val = args[1].lower() in ("вкл", "1", "on", "true", "да")
        chat_settings.anti_caps_enabled = val
    else:
        chat_settings.anti_caps_enabled = not chat_settings.anti_caps_enabled

    await session.commit()
    state = "включен" if chat_settings.anti_caps_enabled else "отключен"
    await message.answer(f"⚙️ Регулятор анти-капса успешно <b>{state}</b> для этого чата.")


@router.message(Command("медиаспам"))
async def cmd_toggle_mediaspam(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора медиа-спама."""
    if db_user.role_level < PositionLevel.ADMINISTRATION.value:
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == message.chat.id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=message.chat.id)
        session.add(chat_settings)

    args = message.text.split()
    if len(args) > 1:
        val = args[1].lower() in ("вкл", "1", "on", "true", "да")
        chat_settings.media_spam_enabled = val
    else:
        chat_settings.media_spam_enabled = not chat_settings.media_spam_enabled

    await session.commit()
    state = "включен" if chat_settings.media_spam_enabled else "отключен"
    await message.answer(f"⚙️ Регулятор медиа-спама (>3 подряд) успешно <b>{state}</b> для этого чата.")


@router.message(Command("антиссылки"))
async def cmd_toggle_antilink(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора ссылок и рекламы."""
    if db_user.role_level < PositionLevel.ADMINISTRATION.value:
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == message.chat.id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=message.chat.id)
        session.add(chat_settings)

    args = message.text.split()
    if len(args) > 1:
        val = args[1].lower() in ("вкл", "1", "on", "true", "да")
        chat_settings.anti_link_enabled = val
    else:
        chat_settings.anti_link_enabled = not chat_settings.anti_link_enabled

    await session.commit()
    state = "включен" if chat_settings.anti_link_enabled else "отключен"
    await message.answer(f"⚙️ Регулятор ссылок и несанкционированной рекламы успешно <b>{state}</b> для этого чата.")
