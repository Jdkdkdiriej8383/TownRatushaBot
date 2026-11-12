import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from db.models.chat_settings import ChatSettings
from db.models.chat_member import ChatMember
from core.enums import PositionLevel, GovernmentRole
from bot.handlers.network import cmd_network
from bot.handlers.broadcast import cmd_broadcast
from bot.handlers.common import cmd_summon_all
from bot.handlers.tickets import cmd_ticket_panel
from bot.handlers.court import cmd_appeal


@pytest.mark.asyncio
async def test_cmd_network_create_and_join(db_session: AsyncSession):
    """Тест создания сетки чатов и подключения другого чата."""
    owner = User(
        telegram_id=1965081517,
        username="DivniDed",
        full_name="Овнер Города",
        role_level=PositionLevel.OWNER.value,
        custom_title="Мэр",
    )
    db_session.add(owner)
    await db_session.commit()

    # Чат 1: Создание сетки
    msg1 = MagicMock()
    msg1.chat.id = -100111
    msg1.chat.type = "supergroup"
    msg1.chat.title = "Чат Ратуши #1"
    msg1.from_user.id = owner.telegram_id
    msg1.text = "/сетка создать Федерация Севера"
    msg1.answer = AsyncMock()
    msg1.reply = AsyncMock()
    msg1.chat.get_member = AsyncMock(return_value=MagicMock(status="creator"))

    await cmd_network(message=msg1, session=db_session, db_user=owner)
    msg1.answer.assert_called_once()
    reply_text = msg1.answer.call_args[0][0]
    assert "УСПЕШНО СОЗДАНА" in reply_text
    assert "NET-" in reply_text

    # Получаем сгенерированный код сети
    cs1 = await db_session.scalar(select(ChatSettings).where(ChatSettings.chat_id == -100111))
    assert cs1 is not None
    assert cs1.network_id.startswith("NET-")
    net_code = cs1.network_id

    # Чат 2: Подключение к сетке
    msg2 = MagicMock()
    msg2.chat.id = -100222
    msg2.chat.type = "supergroup"
    msg2.chat.title = "Чат Ратуши #2"
    msg2.from_user.id = owner.telegram_id
    msg2.text = f"/сетка подключить {net_code}"
    msg2.answer = AsyncMock()
    msg2.reply = AsyncMock()
    msg2.chat.get_member = AsyncMock(return_value=MagicMock(status="creator"))

    await cmd_network(message=msg2, session=db_session, db_user=owner)
    msg2.answer.assert_called_once()
    assert "ОБЪЕДИНЕНА В СЕТКУ" in msg2.answer.call_args[0][0]

    cs2 = await db_session.scalar(select(ChatSettings).where(ChatSettings.chat_id == -100222))
    assert cs2.network_id == net_code


@pytest.mark.asyncio
async def test_cmd_summon_all_hidden_mentions(db_session: AsyncSession):
    """Тест скрытого пинга /all строго для участников текущего чата."""
    owner = User(
        telegram_id=1965081517,
        username="DivniDed",
        full_name="Овнер Города",
        role_level=PositionLevel.OWNER.value,
        custom_title="Мэр",
    )
    user_in_chat = User(
        telegram_id=111111,
        username="user_in_chat",
        full_name="Житель Этого Чата",
        role_level=PositionLevel.CITIZEN.value,
    )
    user_in_other_chat = User(
        telegram_id=222222,
        username="user_in_other_chat",
        full_name="Житель Другого Чата",
        role_level=PositionLevel.CITIZEN.value,
    )
    db_session.add_all([owner, user_in_chat, user_in_other_chat])
    await db_session.commit()

    # Фиксируем принадлежность к -100555 только для user_in_chat
    cm = ChatMember(
        chat_id=-100555,
        user_id=user_in_chat.id,
        telegram_id=user_in_chat.telegram_id,
        is_active=True,
    )
    db_session.add(cm)
    await db_session.commit()

    msg = MagicMock()
    msg.chat.id = -100555
    msg.chat.type = "supergroup"
    msg.from_user.id = owner.telegram_id
    msg.from_user.mention_html = MagicMock(return_value="<b>Овнер</b>")
    msg.text = "/all Срочное голосование"
    msg.answer = AsyncMock(return_value=MagicMock(message_id=999))
    msg.chat.get_administrators = AsyncMock(return_value=[])
    msg.bot.pin_chat_message = AsyncMock()

    await cmd_summon_all(message=msg, session=db_session, db_user=owner)

    msg.answer.assert_called_once()
    call_text = msg.answer.call_args[0][0]

    # Скрытый пинг содержит <a href="tg://user?id=111111">&#8288;</a>
    assert f'tg://user?id=111111' in call_text
    # Не содержит пользователя из другого чата
    assert f'tg://user?id=222222' not in call_text
    # Нет текстового юзернейма наружу
    assert "@user_in_chat" not in call_text


@pytest.mark.asyncio
async def test_cmd_broadcast_bc(db_session: AsyncSession):
    """Тест команды /bc рассылки."""
    owner = User(
        telegram_id=1965081517,
        username="DivniDed",
        full_name="Овнер Города",
        role_level=PositionLevel.OWNER.value,
        custom_title="Мэр",
    )
    u1 = User(telegram_id=3001, full_name="User 1")
    u2 = User(telegram_id=3002, full_name="User 2")
    db_session.add_all([owner, u1, u2])
    await db_session.commit()

    msg = MagicMock()
    msg.chat.type = "private"
    msg.from_user.id = owner.telegram_id
    msg.text = "/bc Важное обновление Ратуши!"
    status_mock = MagicMock()
    status_mock.edit_text = AsyncMock()
    msg.answer = AsyncMock(return_value=status_mock)
    msg.bot.send_message = AsyncMock()

    await cmd_broadcast(message=msg, session=db_session, db_user=owner)

    # Должен отправить сообщения пользователям
    assert msg.bot.send_message.call_count >= 2
    status_mock.edit_text.assert_called()
    last_status = status_mock.edit_text.call_args[0][0]
    assert "РАССЫЛКА УСПЕШНО ЗАВЕРШЕНА" in last_status


@pytest.mark.asyncio
async def test_cmd_ticket_panel_in_group(db_session: AsyncSession):
    """Проверка доступности /ticket_panel в группе без юрисдикционных блокировок."""
    warden = User(
        telegram_id=4001,
        username="warden_ivan",
        full_name="Иван Блюститель",
        role_level=PositionLevel.CHAT_WARDEN.value,
        custom_title="Блюститель",
    )
    db_session.add(warden)
    await db_session.commit()

    msg = MagicMock()
    msg.chat.id = -100888
    msg.chat.type = "supergroup"
    msg.message_thread_id = None
    msg.from_user.id = warden.telegram_id
    msg.text = "/ticket_panel@TestTownRatushaBot"
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()

    await cmd_ticket_panel(message=msg, session=db_session, db_user=warden)
    msg.answer.assert_called_once()
    assert "ГОСУДАРСТВЕННАЯ ПРИЕМНАЯ" in msg.answer.call_args[0][0]
