import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, Chat, User as TgUser
from bot.middlewares.chat_regulator import ChatRegulatorMiddleware, _media_tracker
from db.models import ChatSettings, User
from core.enums import PositionLevel
from config import settings


@pytest.mark.asyncio
async def test_chat_regulator_caps_triggers(db_session, sample_users):
    """Тест перехвата сообщения с капсом (>70%)."""
    citizen = sample_users["citizen"]
    middleware = ChatRegulatorMiddleware()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1009999

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = citizen.telegram_id
    tg_user.is_bot = False
    tg_user.mention_html.return_value = citizen.full_name

    event = MagicMock(spec=Message)
    event.chat = chat
    event.from_user = tg_user
    event.text = "ВСЕМ ПРИВЕТ КАК ДЕЛА В ГОРОДЕ ЭТО КАПС"
    event.caption = None
    event.sticker = None
    event.voice = None
    event.video_note = None
    event.photo = None
    event.video = None
    event.animation = None
    event.entities = []
    event.delete = AsyncMock()
    event.answer = AsyncMock()

    handler = AsyncMock()
    data = {"db_user": citizen, "session": db_session}

    # Включаем антикапс в настройках чата
    chat_settings = ChatSettings(chat_id=chat.id, anti_caps_enabled=True)
    db_session.add(chat_settings)
    await db_session.commit()

    await middleware(handler, event, data)

    # Сообщение должно быть удалено, вынесено предупреждение, handler НЕ вызван
    event.delete.assert_called_once()
    event.answer.assert_called_once()
    assert "Регулятор капса" in event.answer.call_args[0][0]
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_chat_regulator_caps_disabled(db_session, sample_users):
    """Тест пропуска сообщения с капсом, если регулятор выключен."""
    citizen = sample_users["citizen"]
    middleware = ChatRegulatorMiddleware()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1009998

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = citizen.telegram_id
    tg_user.is_bot = False

    event = MagicMock(spec=Message)
    event.chat = chat
    event.from_user = tg_user
    event.text = "ВСЕМ ПРИВЕТ КАК ДЕЛА"
    event.caption = None
    event.sticker = None
    event.voice = None
    event.video_note = None
    event.photo = None
    event.video = None
    event.animation = None
    event.entities = []
    event.delete = AsyncMock()
    event.answer = AsyncMock()

    handler = AsyncMock()
    data = {"db_user": citizen, "session": db_session}

    # Отключаем антикапс в настройках чата
    chat_settings = ChatSettings(chat_id=chat.id, anti_caps_enabled=False)
    db_session.add(chat_settings)
    await db_session.commit()

    await middleware(handler, event, data)

    # Handler должен быть вызван
    handler.assert_called_once_with(event, data)
    event.delete.assert_not_called()


@pytest.mark.asyncio
async def test_chat_regulator_anti_link(db_session, sample_users):
    """Тест блокировки сторонних ссылок."""
    citizen = sample_users["citizen"]
    middleware = ChatRegulatorMiddleware()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1009997

    bot_mock = MagicMock()
    bot_mock.restrict_chat_member = AsyncMock()

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = citizen.telegram_id
    tg_user.is_bot = False
    tg_user.mention_html.return_value = citizen.full_name

    event = MagicMock(spec=Message)
    event.chat = chat
    event.from_user = tg_user
    event.bot = bot_mock
    event.text = "Смотрите классный сервер https://unknown-minecraft-server.xyz/join"
    event.caption = None
    event.sticker = None
    event.voice = None
    event.video_note = None
    event.photo = None
    event.video = None
    event.animation = None
    event.entities = []
    event.delete = AsyncMock()
    event.answer = AsyncMock()

    handler = AsyncMock()
    data = {"db_user": citizen, "session": db_session}

    chat_settings = ChatSettings(chat_id=chat.id, anti_link_enabled=True)
    db_session.add(chat_settings)
    await db_session.commit()

    await middleware(handler, event, data)

    event.delete.assert_called_once()
    event.answer.assert_called_once()
    assert "Регулятор рекламы" in event.answer.call_args[0][0]
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_chat_regulator_rules_link_allowed(db_session, sample_users):
    """Тест разрешения официальной ссылки на законы города (Teletype)."""
    citizen = sample_users["citizen"]
    middleware = ChatRegulatorMiddleware()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1009996

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = citizen.telegram_id
    tg_user.is_bot = False

    event = MagicMock(spec=Message)
    event.chat = chat
    event.from_user = tg_user
    event.text = f"Ознакомьтесь с правилами: {settings.RULES_URL}"
    event.caption = None
    event.sticker = None
    event.voice = None
    event.video_note = None
    event.photo = None
    event.video = None
    event.animation = None
    event.entities = []
    event.delete = AsyncMock()

    handler = AsyncMock()
    data = {"db_user": citizen, "session": db_session}

    chat_settings = ChatSettings(chat_id=chat.id, anti_link_enabled=True)
    db_session.add(chat_settings)
    await db_session.commit()

    await middleware(handler, event, data)

    # Официальная ссылка разрешена, сообщение передано в handler
    handler.assert_called_once_with(event, data)
    event.delete.assert_not_called()


@pytest.mark.asyncio
async def test_chat_regulator_media_spam(db_session, sample_users):
    """Тест регулятора медиа-спама (>3 подряд)."""
    citizen = sample_users["citizen"]
    middleware = ChatRegulatorMiddleware()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1009995

    bot_mock = MagicMock()
    bot_mock.restrict_chat_member = AsyncMock()

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = 555888
    tg_user.is_bot = False
    tg_user.mention_html.return_value = "Спамер"

    # Очищаем трекер
    _media_tracker[555888].clear()

    handler = AsyncMock()
    data = {"db_user": citizen, "session": db_session}

    chat_settings = ChatSettings(chat_id=chat.id, media_spam_enabled=True, media_spam_threshold=3)
    db_session.add(chat_settings)
    await db_session.commit()

    # Отправляем 3 стикера (допустимо)
    for _ in range(3):
        msg = MagicMock(spec=Message)
        msg.chat = chat
        msg.from_user = tg_user
        msg.bot = bot_mock
        msg.text = None
        msg.caption = None
        msg.sticker = MagicMock()
        msg.voice = None
        msg.video_note = None
        msg.photo = None
        msg.video = None
        msg.animation = None
        msg.entities = []
        msg.delete = AsyncMock()
        msg.answer = AsyncMock()
        await middleware(handler, msg, data)

    assert handler.call_count == 3

    # 4-й стикер должен вызвать срабатывание регулятора медиа-спама
    msg4 = MagicMock(spec=Message)
    msg4.chat = chat
    msg4.from_user = tg_user
    msg4.bot = bot_mock
    msg4.text = None
    msg4.caption = None
    msg4.sticker = MagicMock()
    msg4.voice = None
    msg4.video_note = None
    msg4.photo = None
    msg4.video = None
    msg4.animation = None
    msg4.entities = []
    msg4.delete = AsyncMock()
    msg4.answer = AsyncMock()

    await middleware(handler, msg4, data)

    msg4.delete.assert_called_once()
    msg4.answer.assert_called_once()
    assert "Регулятор медиа-спама" in msg4.answer.call_args[0][0]
    # handler не должен быть вызван для 4-го сообщения
    assert handler.call_count == 3
