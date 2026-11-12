import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import MessageEntity, User as AiogramUser

from db.models import User, ChatMember
from core.enums import PositionLevel
from bot.middlewares.user_sync import UserSyncMiddleware
from bot.utils import extract_target_user
from bot.handlers.common import on_chat_member_update, on_new_chat_members, cmd_sync_chat_users


@pytest.mark.asyncio
async def test_user_sync_middleware_captures_regular_chat_messages(db_session: AsyncSession):
    """
    Проверяет, что UserSyncMiddleware сохраняет обычного участника чата
    (который ни разу не писал команды боту, а просто написал сообщение)
    и связывает его с группой через ChatMember.
    """
    middleware = UserSyncMiddleware()

    msg = MagicMock()
    msg.from_user.id = 999111
    msg.from_user.username = "ordinary_resident"
    msg.from_user.full_name = "Обычный Житель"
    msg.from_user.is_bot = False
    msg.chat.id = -100777
    msg.chat.type = "supergroup"
    msg.reply_to_message = None
    msg.new_chat_members = None

    handler_called = False

    async def mock_handler(event, data):
        nonlocal handler_called
        handler_called = True
        return "handled"

    data = {"session": db_session}
    res = await middleware(mock_handler, msg, data)

    assert res == "handled"
    assert handler_called is True
    assert "db_user" in data
    assert data["db_user"].telegram_id == 999111

    # Проверяем наличие в БД User
    user = await db_session.scalar(select(User).where(User.telegram_id == 999111))
    assert user is not None
    assert user.username == "ordinary_resident"
    assert user.balance == 5000

    # Проверяем наличие ChatMember
    cm = await db_session.scalar(
        select(ChatMember).where(
            ChatMember.chat_id == -100777,
            ChatMember.telegram_id == 999111
        )
    )
    assert cm is not None
    assert cm.is_active is True


@pytest.mark.asyncio
async def test_user_sync_middleware_syncs_replied_and_forwarded_user(db_session: AsyncSession):
    """
    Проверяет, что при ответе на чужое сообщение или пересылке,
    автор исходного сообщения тоже автоматически заносится в БД.
    """
    middleware = UserSyncMiddleware()

    msg = MagicMock()
    msg.from_user.id = 111
    msg.from_user.username = "sender_user"
    msg.from_user.full_name = "Отправитель"
    msg.from_user.is_bot = False
    msg.chat.id = -100777
    msg.chat.type = "supergroup"
    msg.new_chat_members = None

    # Reply to another user who never touched the bot
    replied_user = MagicMock()
    replied_user.id = 222
    replied_user.username = "target_silent_user"
    replied_user.full_name = "Молчун"
    replied_user.is_bot = False

    msg.reply_to_message.from_user = replied_user
    msg.reply_to_message.forward_from = None

    async def mock_handler(event, data):
        return "ok"

    data = {"session": db_session}
    await middleware(mock_handler, msg, data)

    # Оба пользователя должны быть в БД
    u1 = await db_session.scalar(select(User).where(User.telegram_id == 111))
    u2 = await db_session.scalar(select(User).where(User.telegram_id == 222))
    assert u1 is not None
    assert u2 is not None
    assert u2.username == "target_silent_user"

    # Оба должны быть в ChatMember
    cm2 = await db_session.scalar(
        select(ChatMember).where(
            ChatMember.chat_id == -100777,
            ChatMember.telegram_id == 222
        )
    )
    assert cm2 is not None


@pytest.mark.asyncio
async def test_extract_target_user_by_reply_registers_new_user(db_session: AsyncSession):
    """
    Проверяет, что extract_target_user автоматически регистрирует пользователя
    при ответе на его сообщение, даже если его раньше не было в БД.
    """
    msg = MagicMock()
    msg.chat.id = -100888
    msg.chat.type = "supergroup"

    # Ответ на сообщение пользователя 333
    target_tg = MagicMock()
    target_tg.id = 333
    target_tg.username = "new_replied_citizen"
    target_tg.full_name = "Новый Гражданин"
    target_tg.is_bot = False

    msg.reply_to_message = MagicMock()
    msg.reply_to_message.from_user = target_tg
    msg.reply_to_message.forward_from = None
    msg.text = "/варн 1.1 нарушение"
    msg.entities = None

    target, remaining_args = await extract_target_user(msg, db_session, ["1.1", "нарушение"])

    assert target is not None
    assert target.telegram_id == 333
    assert target.username == "new_replied_citizen"
    assert remaining_args == ["1.1", "нарушение"]

    # Проверяем в БД
    saved_u = await db_session.scalar(select(User).where(User.telegram_id == 333))
    assert saved_u is not None
    saved_cm = await db_session.scalar(
        select(ChatMember).where(
            ChatMember.chat_id == -100888,
            ChatMember.telegram_id == 333
        )
    )
    assert saved_cm is not None


@pytest.mark.asyncio
async def test_extract_target_user_by_text_mention(db_session: AsyncSession):
    """
    Проверяет захват пользователя через кликабельное текстовое упоминание (text_mention),
    даже если у пользователя нет @username и он никогда не писал боту.
    """
    target_tg = AiogramUser(
        id=444,
        is_bot=False,
        first_name="Человек",
        last_name="Без Юзернейма"
    )

    entity = MessageEntity(
        type="text_mention",
        offset=6,
        length=21,
        user=target_tg
    )

    msg = MagicMock()
    msg.chat.id = -100888
    msg.chat.type = "supergroup"
    msg.reply_to_message = None
    msg.text = "/штраф [Человек Без Юзернейма] 500 хулиганство"
    msg.entities = [entity]

    target, remaining_args = await extract_target_user(
        msg,
        db_session,
        ["[Человек", "Без", "Юзернейма]", "500", "хулиганство"]
    )

    assert target is not None
    assert target.telegram_id == 444
    assert "Человек" in target.full_name


@pytest.mark.asyncio
async def test_extract_target_user_by_telegram_id_with_bot_api(db_session: AsyncSession):
    """
    Проверяет извлечение пользователя по числовому Telegram ID:
    если в БД его нет, запрашивает Telegram Bot API (get_chat_member) и регистрирует.
    """
    msg = MagicMock()
    msg.chat.id = -100888
    msg.chat.type = "supergroup"
    msg.reply_to_message = None
    msg.text = "/досье 555666"
    msg.entities = None

    member_mock = MagicMock()
    member_mock.user.id = 555666
    member_mock.user.username = "fetched_by_id"
    member_mock.user.full_name = "Пользователь По ID"

    msg.bot = MagicMock()
    msg.bot.get_chat_member = AsyncMock(return_value=member_mock)

    target, remaining_args = await extract_target_user(msg, db_session, ["555666"])

    assert target is not None
    assert target.telegram_id == 555666
    assert target.username == "fetched_by_id"
    msg.bot.get_chat_member.assert_awaited_once_with(-100888, 555666)

    # Проверяем сохранение в БД
    saved_u = await db_session.scalar(select(User).where(User.telegram_id == 555666))
    assert saved_u is not None


@pytest.mark.asyncio
async def test_extract_target_user_by_admin_username_scan(db_session: AsyncSession):
    """
    Проверяет поиск администратора по @username через get_administrators(),
    если администратор еще ни разу не писал боту и его нет в БД.
    """
    msg = MagicMock()
    msg.chat.id = -100888
    msg.chat.type = "supergroup"
    msg.reply_to_message = None
    msg.text = "/должность @cool_admin 4"
    msg.entities = None

    admin_tg = MagicMock()
    admin_tg.user.id = 777888
    admin_tg.user.username = "cool_admin"
    admin_tg.user.full_name = "Крутой Админ"

    msg.chat.get_administrators = AsyncMock(return_value=[admin_tg])
    msg.bot = MagicMock()

    target, remaining_args = await extract_target_user(msg, db_session, ["@cool_admin", "4"])

    assert target is not None
    assert target.telegram_id == 777888
    assert target.username == "cool_admin"
    assert remaining_args == ["4"]


@pytest.mark.asyncio
async def test_chat_member_updated_and_new_members_handlers(db_session: AsyncSession):
    """
    Тестирует обработчики входа в чат:
    on_chat_member_update и on_new_chat_members.
    """
    # 1. on_chat_member_update
    event = MagicMock()
    event.chat.id = -100999
    event.chat.type = "supergroup"
    event.new_chat_member = MagicMock()
    event.new_chat_member.user.id = 888111
    event.new_chat_member.user.username = "joined_user"
    event.new_chat_member.user.full_name = "Присоединившийся"
    event.new_chat_member.user.is_bot = False
    event.new_chat_member.status = "member"

    await on_chat_member_update(event, db_session)

    u1 = await db_session.scalar(select(User).where(User.telegram_id == 888111))
    assert u1 is not None
    cm1 = await db_session.scalar(select(ChatMember).where(ChatMember.telegram_id == 888111))
    assert cm1 is not None
    assert cm1.is_active is True

    # 2. on_new_chat_members service message
    msg = MagicMock()
    msg.chat.id = -100999
    msg.chat.type = "supergroup"

    new_user = MagicMock()
    new_user.id = 888222
    new_user.username = "service_joined_user"
    new_user.full_name = "Сервисный Участник"
    new_user.is_bot = False

    msg.new_chat_members = [new_user]
    msg.reply = AsyncMock()

    await on_new_chat_members(msg, db_session)

    u2 = await db_session.scalar(select(User).where(User.telegram_id == 888222))
    assert u2 is not None
    cm2 = await db_session.scalar(select(ChatMember).where(ChatMember.telegram_id == 888222))
    assert cm2 is not None


@pytest.mark.asyncio
async def test_cmd_sync_users_scans_administrators(db_session: AsyncSession):
    """
    Тестирует команду /sync_users (/скан_чата).
    """
    admin_caller = User(
        telegram_id=123456,
        username="admin_user",
        full_name="Админ",
        role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
    )
    db_session.add(admin_caller)
    await db_session.commit()

    status_msg_mock = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -100555
    msg.chat.type = "supergroup"
    msg.from_user.id = 123456
    msg.reply = AsyncMock(return_value=status_msg_mock)

    # Админы в чате
    adm1 = MagicMock()
    adm1.user.id = 123456
    adm1.user.username = "admin_user"
    adm1.user.full_name = "Админ"
    adm1.user.is_bot = False

    adm2 = MagicMock()
    adm2.user.id = 654321
    adm2.user.username = "silent_deputy"
    adm2.user.full_name = "Тихий Зам"
    adm2.user.is_bot = False

    msg.chat.get_administrators = AsyncMock(return_value=[adm1, adm2])

    await cmd_sync_chat_users(msg, db_session, admin_caller)

    msg.reply.assert_called_once()
    status_msg_mock.edit_text.assert_called_once()
    reply_text = status_msg_mock.edit_text.call_args[0][0]
    assert "СИНХРОНИЗАЦИЯ ЧАТА" in reply_text
    assert "Администраторов обнаружено: <b>2</b>" in reply_text

    # Проверяем, что silent_deputy теперь в User и ChatMember
    deputy = await db_session.scalar(select(User).where(User.telegram_id == 654321))
    assert deputy is not None
    assert deputy.username == "silent_deputy"

    cm = await db_session.scalar(select(ChatMember).where(ChatMember.telegram_id == 654321))
    assert cm is not None
    assert cm.is_active is True
