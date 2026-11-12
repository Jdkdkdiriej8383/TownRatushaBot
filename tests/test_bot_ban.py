import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Message, CallbackQuery

from db.models import User, ChatSettings, ChatMember
from core.enums import PositionLevel
from config import settings
from bot.handlers.moderation import cmd_bot_ban, cmd_unbot_ban
from bot.middlewares.user_sync import UserSyncMiddleware
from bot.handlers.common import on_chat_member_update, on_new_chat_members
from bot.utils import BOT_BAN_USER_NOTICE


@pytest.mark.asyncio
async def test_cmd_bot_ban_permission_check(db_session: AsyncSession):
    """Проверяет, что обычный администратор не может выдать бан в боте (только Овнер)."""
    admin = User(
        telegram_id=88888,
        username="some_admin",
        full_name="Обычный Админ",
        role_level=PositionLevel.ADMINISTRATION.value,
    )
    target = User(
        telegram_id=99999,
        username="target_user",
        full_name="Цель",
        role_level=PositionLevel.CITIZEN.value,
    )
    db_session.add_all([admin, target])
    await db_session.commit()

    msg = MagicMock()
    msg.chat.id = -100111
    msg.chat.type = "supergroup"
    msg.text = "/банбот @target_user спам"
    msg.reply = AsyncMock()

    await cmd_bot_ban(msg, db_session, admin)

    msg.reply.assert_called_once()
    assert "Отказано в доступе" in msg.reply.call_args[0][0]
    assert "@DivniDed" in msg.reply.call_args[0][0]

    # Пользователь не забанен
    refreshed_target = await db_session.scalar(select(User).where(User.telegram_id == 99999))
    assert refreshed_target.is_bot_banned is False


@pytest.mark.asyncio
async def test_cmd_bot_ban_success_and_broadcast_ban(db_session: AsyncSession):
    """
    Проверяет успешное выполнение /банбот Владельцем бота:
    1. Установка флага is_bot_banned в БД.
    2. Бан во всех зарегистрированных группах.
    3. Отправка персонального уведомления с контактом @DivniDed.
    4. Отчет Овнеру.
    """
    owner = User(
        telegram_id=settings.OWNER_ID,
        username=settings.OWNER_USERNAME,
        full_name="Создатель",
        role_level=PositionLevel.OWNER.value,
    )
    target = User(
        telegram_id=777123,
        username="malicious_user",
        full_name="Злостный Нарушитель",
        role_level=PositionLevel.CITIZEN.value,
    )
    # Две группы в БД
    g1 = ChatSettings(chat_id=-100111)
    g2 = ChatSettings(chat_id=-100222)
    db_session.add_all([owner, target, g1, g2])
    await db_session.commit()

    msg = MagicMock()
    msg.chat.id = -100111
    msg.chat.type = "supergroup"
    msg.text = "/банбот @malicious_user Реклама и спам"
    msg.reply = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.ban_chat_member = AsyncMock()
    msg.bot.send_message = AsyncMock()

    await cmd_bot_ban(msg, db_session, owner)

    # 1. Проверяем БД
    refreshed_target = await db_session.scalar(select(User).where(User.telegram_id == 777123))
    assert refreshed_target.is_bot_banned is True
    assert refreshed_target.bot_ban_reason == "Реклама и спам"
    assert refreshed_target.bot_banned_at is not None

    # 2. Проверяем баны в группах (-100111 и -100222)
    banned_chat_ids = [call.kwargs.get("chat_id") for call in msg.bot.ban_chat_member.call_args_list]
    assert -100111 in banned_chat_ids
    assert -100222 in banned_chat_ids

    # 3. Проверяем отправку личного сообщения нарушителю
    pm_calls = [call for call in msg.bot.send_message.call_args_list if call.kwargs.get("chat_id") == 777123]
    assert len(pm_calls) == 1
    pm_call = pm_calls[0]
    assert "@DivniDed" in pm_call.kwargs.get("text")
    assert "ДОСТУП К БОТУ ЗАБЛОКИРОВАН" in pm_call.kwargs.get("text")

    # 4. Проверяем ответ Владельцу
    msg.reply.assert_called_once()
    reply_text = msg.reply.call_args[0][0]
    assert "ГЛОБАЛЬНЫЙ БАН В БОТЕ" in reply_text
    assert "malicious_user" in reply_text


@pytest.mark.asyncio
async def test_cmd_unbot_ban_success(db_session: AsyncSession):
    """Проверяет снятие глобального бана через /разбанбот."""
    owner = User(
        telegram_id=settings.OWNER_ID,
        username=settings.OWNER_USERNAME,
        full_name="Создатель",
        role_level=PositionLevel.OWNER.value,
    )
    banned_target = User(
        telegram_id=777456,
        username="forgiven_user",
        full_name="Помилованный",
        role_level=PositionLevel.CITIZEN.value,
        is_bot_banned=True,
        bot_ban_reason="Старая блокировка",
    )
    g1 = ChatSettings(chat_id=-100333)
    db_session.add_all([owner, banned_target, g1])
    await db_session.commit()

    msg = MagicMock()
    msg.chat.id = -100333
    msg.chat.type = "supergroup"
    msg.text = "/разбанбот @forgiven_user Амнистия"
    msg.reply = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.unban_chat_member = AsyncMock()
    msg.bot.send_message = AsyncMock()

    await cmd_unbot_ban(msg, db_session, owner)

    # 1. Проверяем БД
    refreshed = await db_session.scalar(select(User).where(User.telegram_id == 777456))
    assert refreshed.is_bot_banned is False
    assert refreshed.bot_ban_reason is None

    # 2. Проверяем разбан в группе
    msg.bot.unban_chat_member.assert_called_once_with(chat_id=-100333, user_id=777456, only_if_banned=True)

    # 3. Проверяем уведомление в ЛС
    pm_calls = [call for call in msg.bot.send_message.call_args_list if call.kwargs.get("chat_id") == 777456]
    assert len(pm_calls) == 1
    assert "БЛОКИРОВКА В БОТЕ СНЯТА" in pm_calls[0].kwargs.get("text")


@pytest.mark.asyncio
async def test_user_sync_middleware_blocks_banned_user_in_pm(db_session: AsyncSession):
    """Проверяет, что забаненный в боте пользователь при попытке написать в ЛС получает сообщение о разбане через @DivniDed."""
    middleware = UserSyncMiddleware()

    banned_user = User(
        telegram_id=666111,
        username="blocked_pm",
        full_name="Забаненный",
        role_level=PositionLevel.CITIZEN.value,
        is_bot_banned=True,
        bot_ban_reason="Нарушение правил",
    )
    db_session.add(banned_user)
    await db_session.commit()

    msg = MagicMock()
    msg.from_user.id = 666111
    msg.from_user.username = "blocked_pm"
    msg.from_user.full_name = "Забаненный"
    msg.from_user.is_bot = False
    msg.chat.id = 666111
    msg.chat.type = "private"
    msg.reply_to_message = None
    msg.new_chat_members = None
    msg.answer = AsyncMock()

    handler_called = False

    async def mock_handler(event, data):
        nonlocal handler_called
        handler_called = True
        return "ok"

    data = {"session": db_session}
    res = await middleware(mock_handler, msg, data)

    assert res is None
    assert handler_called is False  # Обработчик не должен вызываться!
    msg.answer.assert_called_once()
    answer_text = msg.answer.call_args[0][0]
    assert "@DivniDed" in answer_text
    assert "ДОСТУП К БОТУ ЗАБЛОКИРОВАН" in answer_text


@pytest.mark.asyncio
async def test_user_sync_middleware_bans_and_deletes_banned_user_in_group(db_session: AsyncSession):
    """Проверяет, что забаненный в боте пользователь при отправке сообщения в группу моментально банится и его сообщение удаляется."""
    middleware = UserSyncMiddleware()

    banned_user = User(
        telegram_id=666222,
        username="blocked_group_sender",
        full_name="Забаненный Группа",
        role_level=PositionLevel.CITIZEN.value,
        is_bot_banned=True,
        bot_ban_reason="Злостный спам",
    )
    db_session.add(banned_user)
    await db_session.commit()

    bot_mock = MagicMock()
    bot_mock.ban_chat_member = AsyncMock()

    msg = MagicMock()
    msg.from_user.id = 666222
    msg.from_user.username = "blocked_group_sender"
    msg.from_user.full_name = "Забаненный Группа"
    msg.from_user.is_bot = False
    msg.chat.id = -100999
    msg.chat.type = "supergroup"
    msg.reply_to_message = None
    msg.new_chat_members = None
    msg.delete = AsyncMock()

    handler_called = False

    async def mock_handler(event, data):
        nonlocal handler_called
        handler_called = True
        return "ok"

    data = {"session": db_session, "bot": bot_mock}
    res = await middleware(mock_handler, msg, data)

    assert res is None
    assert handler_called is False
    bot_mock.ban_chat_member.assert_called_once_with(chat_id=-100999, user_id=666222)
    msg.delete.assert_called_once()


@pytest.mark.asyncio
async def test_auto_ban_on_join_in_new_group(db_session: AsyncSession):
    """Проверяет, что при заходе в группу, где нарушителя раньше не было, бот мгновенно его банит."""
    banned_user = User(
        telegram_id=666333,
        username="joining_banned_user",
        full_name="Забаненный Новичок",
        role_level=PositionLevel.CITIZEN.value,
        is_bot_banned=True,
        bot_ban_reason="Пермабан",
    )
    db_session.add(banned_user)
    await db_session.commit()

    # 1. Событие chat_member_updated
    event = MagicMock()
    event.chat.id = -100444
    event.chat.type = "supergroup"
    event.bot = MagicMock()
    event.bot.ban_chat_member = AsyncMock()
    event.new_chat_member = MagicMock()
    event.new_chat_member.user.id = 666333
    event.new_chat_member.user.username = "joining_banned_user"
    event.new_chat_member.user.full_name = "Забаненный Новичок"
    event.new_chat_member.user.is_bot = False
    event.new_chat_member.status = "member"

    await on_chat_member_update(event, db_session)
    event.bot.ban_chat_member.assert_called_once_with(chat_id=-100444, user_id=666333)

    # 2. Служебное сообщение new_chat_members
    msg = MagicMock()
    msg.chat.id = -100444
    msg.chat.type = "supergroup"
    msg.bot = MagicMock()
    msg.bot.ban_chat_member = AsyncMock()
    msg.delete = AsyncMock()

    new_tg = MagicMock()
    new_tg.id = 666333
    new_tg.username = "joining_banned_user"
    new_tg.full_name = "Забаненный Новичок"
    new_tg.is_bot = False

    msg.new_chat_members = [new_tg]

    await on_new_chat_members(msg, db_session)
    msg.bot.ban_chat_member.assert_called_once_with(chat_id=-100444, user_id=666333)
    msg.delete.assert_called_once()
