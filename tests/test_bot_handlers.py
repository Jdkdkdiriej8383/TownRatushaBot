import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, User as TgUser, Chat
from bot.handlers.laws import cmd_law
from bot.handlers.justice import cmd_fine
from bot.handlers.passport import cmd_passport, cmd_set_position
from core.enums import PositionLevel


@pytest.mark.asyncio
async def test_cmd_law_card(db_session):
    """Тест выполнения команды /закон 2.1"""
    message = MagicMock(spec=Message)
    message.text = "/закон 2.1"
    message.answer = AsyncMock()

    await cmd_law(message, db_session)

    message.answer.assert_called_once()
    reply_text = message.answer.call_args[0][0]
    assert "Статья 2.1. Оскорбление руководства" in reply_text
    assert "ГОРОДСКОЙ СВОД ЗАКОНОВ" in reply_text


@pytest.mark.asyncio
async def test_cmd_passport_view(db_session, sample_users):
    """Тест выполнения команды /паспорт"""
    citizen = sample_users["citizen"]

    message = MagicMock(spec=Message)
    message.text = "/паспорт"
    message.reply_to_message = None
    message.answer = AsyncMock()

    await cmd_passport(message, db_session, db_user=citizen)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "ПАСПОРТ ГРАЖДАНИНА ГОРОДА" in reply
    assert citizen.full_name in reply
    assert "Ivan_Crafter" in reply
    assert "Гражданин" in reply


@pytest.mark.asyncio
async def test_cmd_fine_subordination_violation(db_session, sample_users):
    """Тест команды /штраф: попытка оштрафовать равного или старшего по должности."""
    assistant = sample_users["assistant"]  # уровень 1
    chat_warden = sample_users["chat_warden"]  # уровень 2

    message = MagicMock(spec=Message)
    message.text = f"/штраф {chat_warden.telegram_id} 2.1 1000 тест"
    message.reply_to_message = None
    message.answer = AsyncMock()

    await cmd_fine(message, db_session, db_user=assistant)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "Нарушение субординации" in reply
