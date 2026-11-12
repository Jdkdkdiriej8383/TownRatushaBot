import uuid
import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from db.models.chat_settings import ChatSettings
from core.enums import PositionLevel
from core.hierarchy_service import HierarchyService
from config import settings

logger = logging.getLogger("townbot.network")
router = Router(name="network_router")


async def _get_or_create_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    cs = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    if not cs:
        cs = ChatSettings(chat_id=chat_id)
        session.add(cs)
        await session.flush()
    return cs


def _is_admin(db_user: User, tg_member_status: Optional[str] = None) -> bool:
    if HierarchyService.is_owner(db_user):
        return True
    if db_user.government_rank >= 4 or db_user.role_level >= PositionLevel.SENIOR_ADMINISTRATION.value:
        return True
    if tg_member_status in ("creator", "administrator"):
        return True
    return False


@router.message(Command("network", "сетка", "сеть", "federation", "grid"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "/network", "network", "/сетка", "сетка", "/сеть", "сеть", "/federation", "federation", "/grid", "grid"
))))
async def cmd_network(message: Message, session: AsyncSession, db_user: User):
    """
    Управление сеткой чатов (Федерация / Мульти-чат):
    /сетка — статус текущего чата
    /сетка создать [Название] — создать новую сетку и сгенерировать код подключения
    /сетка подключить [КОД] — объединить текущий чат в существующую сетку
    /сетка отключить — отсоединить чат от сетки (режим автономии)
    /сетка инфо — список всех чатов, объединенных в текущую сетку
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚠️ Управление сеткой чатов доступно только в групповых чатах!")
        return

    # Проверка прав администратора
    tg_status = None
    if message.from_user:
        try:
            m = await message.chat.get_member(message.from_user.id)
            tg_status = getattr(m, "status", None)
        except Exception:
            pass

    if not _is_admin(db_user, tg_status):
        await message.reply("🚫 Управлять объединением чатов в сетку может только Высшая Администрация или Владелец группы!")
        return

    chat_settings = await _get_or_create_chat_settings(session, message.chat.id)
    args = (message.text or "").split()[1:]
    subcmd = args[0].lower() if args else ""

    if subcmd in ("создать", "create", "new"):
        name = " ".join(args[1:]).strip() if len(args) > 1 else f"Сетка {message.chat.title or 'Города'}"
        net_code = f"NET-{uuid.uuid4().hex[:6].upper()}"

        chat_settings.network_id = net_code
        chat_settings.network_name = name
        await session.commit()

        await message.answer(
            f"🌐 <b>СЕТКА ЧАТОВ «{name}» УСПЕШНО СОЗДАНА!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Главный узел:</b> {message.chat.title} (ID: <code>{message.chat.id}</code>)\n"
            f"• <b>Код подключения:</b> <code>{net_code}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Чтобы подключить другие группы к этой сетке, напишите в нужной группе команду:\n"
            f"<code>/сетка подключить {net_code}</code>\n\n"
            f"💡 <i>В объединенной сетке чаты синхронизируют общие списки и федеральные регламенты, "
            f"сохраняя при этом изолированные очереди тикетов и локальный контекст!</i>"
        )
        return

    if subcmd in ("подключить", "join", "connect", "link"):
        if len(args) < 2:
            await message.reply(
                "⚠️ <b>Укажите код сетки:</b>\n"
                "Пример: <code>/сетка подключить NET-XXXXXX</code>"
            )
            return

        target_code = args[1].strip().upper()
        # Ищем существующую сетку с таким кодом
        existing_net = await session.scalar(
            select(ChatSettings).where(ChatSettings.network_id == target_code)
        )
        if not existing_net:
            await message.reply(f"❌ Сетка с кодом <code>{target_code}</code> не найдена!")
            return

        chat_settings.network_id = target_code
        chat_settings.network_name = existing_net.network_name or "Объединенная сеть"
        await session.commit()

        await message.answer(
            f"✅ <b>ГРУППА УСПЕШНО ОБЪЕДИНЕНА В СЕТКУ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Сетка:</b> «{chat_settings.network_name}»\n"
            f"• <b>Код сети:</b> <code>{target_code}</code>\n"
            f"• <b>Текущий чат:</b> {message.chat.title}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 Теперь эта группа является полноправным узлом единой сетки чатов."
        )
        return

    if subcmd in ("отключить", "leave", "disconnect", "unlink"):
        if not chat_settings.network_id:
            await message.reply("ℹ️ Этот чат не состоит ни в одной сетке — он уже работает в режиме автономии.")
            return

        old_name = chat_settings.network_name or chat_settings.network_id
        chat_settings.network_id = None
        chat_settings.network_name = None
        await session.commit()

        await message.answer(
            f"🔌 <b>ГРУППА ОТКЛЮЧЕНА ОТ СЕТКИ «{old_name}»</b>\n"
            f"Чат переведен в режим полной изоляции и автономии."
        )
        return

    if subcmd in ("инфо", "info", "список", "list"):
        if not chat_settings.network_id:
            await message.answer("ℹ️ Этот чат является автономным и не подключен к сетке.")
            return

        all_in_net = (await session.scalars(
            select(ChatSettings).where(ChatSettings.network_id == chat_settings.network_id)
        )).all()

        text = (
            f"🌐 <b>ИНФОРМАЦИЯ О СЕТКЕ «{chat_settings.network_name}»</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Код сетки:</b> <code>{chat_settings.network_id}</code>\n"
            f"• <b>Всего объединенных чатов:</b> {len(all_in_net)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>Узлы сети:</b>\n"
        )
        for i, cs in enumerate(all_in_net, 1):
            cur_marker = " <i>(текущий)</i>" if cs.chat_id == message.chat.id else ""
            text += f"{i}. Чат ID: <code>{cs.chat_id}</code>{cur_marker}\n"

        await message.answer(text)
        return

    # По умолчанию — сводка статуса сетки
    if chat_settings.network_id:
        status_text = (
            f"🌐 <b>СЕТКА ЧАТОВ: «{chat_settings.network_name}»</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Статус группы:</b> 🟢 Подключена к единой сетке\n"
            f"• <b>Код сетки:</b> <code>{chat_settings.network_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Доступные команды:</b>\n"
            f"• <code>/сетка инфо</code> — список всех чатов в сети\n"
            f"• <code>/сетка отключить</code> — отключить группу от сети"
        )
    else:
        status_text = (
            f"🌐 <b>СЕТКА ЧАТОВ (ФЕДЕРАЦИЯ)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Статус группы:</b> ⚪ Автономный изолированный чат\n"
            f"• <b>Сетка:</b> не привязана (данные не выходят за пределы чата)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Как объединить группы в одну сетку:</b>\n"
            f"1. В главном чате напишите:\n"
            f"   <code>/сетка создать [Название]</code>\n"
            f"2. В других группах введите полученный код:\n"
            f"   <code>/сетка подключить [КОД]</code>"
        )

    await message.answer(status_text)
