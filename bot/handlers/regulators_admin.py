import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Regulator, ChatSettings, User
from core.enums import PositionLevel
from core.regulators import format_duration
from config import settings

logger = logging.getLogger("townbot.regulators_admin")

router = Router(name="regulators_admin_router")


async def _has_admin_rights(message: Message, db_user: User) -> bool:
    """
    Проверяет права на настройку защит чата:
    1. Владелец города (settings.OWNER_ID / settings.OWNER_USERNAME)
    2. Администрация города по ролевой системе (роль >= 4 или Высшая адм)
    3. Создатель или Администратор текущей супергруппы в Telegram
    """
    if (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    ):
        return True

    if message.chat.type in ("group", "supergroup") and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                return True
        except Exception as e:
            logger.debug("Ошибка при проверке прав get_chat_member: %s", e)

    return False


def _parse_toggle_arg(text: str, current_value: bool) -> tuple[bool, str]:
    """Разбирает аргументы включения/выключения регулятора."""
    tokens = (text or "").strip().split()
    if len(tokens) > 1:
        arg = tokens[1].lower()
        if arg in ("вкл", "1", "on", "true", "да", "enable", "enabled", "включить", "активировать"):
            return True, "включен"
        elif arg in ("выкл", "0", "off", "false", "нет", "disable", "disabled", "выключить", "деактивировать"):
            return False, "отключен"

    # При вызове без параметров — инвертируем текущее состояние
    new_val = not current_value
    return new_val, ("включен" if new_val else "отключен")


async def _get_or_create_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    """Безопасно загружает или создает объект настроек чата."""
    chat_settings = await session.scalar(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    if not chat_settings:
        chat_settings = ChatSettings(chat_id=chat_id)
        session.add(chat_settings)
        await session.flush()
    return chat_settings


@router.message(Command("регуляторы", "регулятор", "regulators", "regulator"))
@router.message(F.text.lower().in_(["регуляторы", "регулятор", "regulators", "regulator"]))
async def cmd_view_regulators(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /регуляторы — сводка регуляторов полномочий всех должностей (0-5)
    и текущее состояние защит чата.
    """
    # 1. Загружаем все регуляторы
    regulators_query = select(Regulator).order_by(Regulator.role_level)
    regulators = (await session.scalars(regulators_query)).all()

    # 2. Загружаем настройки текущего чата
    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)

    status_icon = lambda val: "🟢 Включен" if val else "🔴 Отключен"

    lines = [
        "⚙️ <b>КОНФИГУРАЦИЯ СИСТЕМЫ «РЕГУЛЯТОРОВ»</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🛡 <b>Защитные регуляторы чата:</b>",
        f"• Анти-капс (>70%): {status_icon(chat_settings.anti_caps_enabled)}",
        f"• Анти-спам (медиа-спам): {status_icon(chat_settings.media_spam_enabled)}",
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
    lines.append(
        "<i>Управление защитами (для Администрации):</i>\n"
        "• <code>/антикапс вкл/выкл</code> — фильтр КАПСа\n"
        "• <code>/спам вкл/выкл</code> (или <code>/медиаспам</code>) — фильтр медиа-спама\n"
        "• <code>/ссылки вкл/выкл</code> (или <code>/антиссылки</code>) — фильтр ссылок"
    )

    await message.answer("\n".join(lines))


@router.message(Command("антикапс", "anticaps", "капс", "caps"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("антикапс", "anticaps", "капс", "caps", "/антикапс", "/anticaps", "/капс", "/caps"))))
async def cmd_toggle_anticaps(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора анти-капса."""
    if not await _has_admin_rights(message, db_user):
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)
    val, state_word = _parse_toggle_arg(message.text or "", chat_settings.anti_caps_enabled)
    chat_settings.anti_caps_enabled = val

    await session.commit()
    badge = "🟢 <b>ВКЛЮЧЕН</b>" if val else "🔴 <b>ОТКЛЮЧЕН</b>"
    await message.answer(
        f"⚙️ Регулятор анти-капса успешно <b>{state_word}</b> ({badge}) для этого чата.\n"
        f"<i>(Сообщения с капсом более 70% автоматически фильтруются).</i>"
    )


@router.message(Command("спам", "антиспам", "медиаспам", "spam", "antispam", "mediaspam"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("спам", "антиспам", "медиаспам", "spam", "antispam", "mediaspam", "/спам", "/антиспам", "/медиаспам", "/spam", "/antispam", "/mediaspam"))))
async def cmd_toggle_mediaspam(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора медиа-спама."""
    if not await _has_admin_rights(message, db_user):
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)
    val, state_word = _parse_toggle_arg(message.text or "", chat_settings.media_spam_enabled)
    chat_settings.media_spam_enabled = val

    await session.commit()
    badge = "🟢 <b>ВКЛЮЧЕН</b>" if val else "🔴 <b>ОТКЛЮЧЕН</b>"
    await message.answer(
        f"⚙️ Регулятор медиа-спама (>3 подряд) успешно <b>{state_word}</b> ({badge}) для этого чата.\n"
        f"<i>(Отправка более {chat_settings.media_spam_threshold} стикеров/ГС подряд блокируется).</i>"
    )


@router.message(Command("ссылки", "ссылка", "антиссылки", "антиссылка", "антилинк", "links", "link", "antilinks", "antilink"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("ссылки", "ссылка", "антиссылки", "антиссылка", "антилинк", "links", "link", "antilinks", "antilink", "/ссылки", "/ссылка", "/антиссылки", "/антиссылка", "/антилинк", "/links", "/link", "/antilinks", "/antilink"))))
async def cmd_toggle_antilink(message: Message, session: AsyncSession, db_user: User):
    """Включение/выключение регулятора ссылок и несанкционированной рекламы."""
    if not await _has_admin_rights(message, db_user):
        await message.answer("🚫 Настройка регуляторов доступна только Администрации города!")
        return

    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)
    val, state_word = _parse_toggle_arg(message.text or "", chat_settings.anti_link_enabled)
    chat_settings.anti_link_enabled = val

    await session.commit()
    badge = "🟢 <b>ВКЛЮЧЕН</b>" if val else "🔴 <b>ОТКЛЮЧЕН</b>"
    await message.answer(
        f"⚙️ Регулятор ссылок и несанкционированной рекламы успешно <b>{state_word}</b> ({badge}) для этого чата.\n"
        f"<i>(Сообщения со сторонними URL-адресами автоматически удаляются с предупреждением/мутом).</i>"
    )
