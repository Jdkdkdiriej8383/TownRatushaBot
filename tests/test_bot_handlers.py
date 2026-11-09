from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, User as TgUser, Chat
from bot.handlers.laws import cmd_law, cmd_law_edit
from bot.handlers.justice import cmd_fine, cmd_amnesty
from bot.handlers.passport import cmd_passport, cmd_set_nick
from bot.handlers.common import cmd_summon_all
from bot.handlers.regulators_admin import (
    cmd_toggle_anticaps,
    cmd_toggle_mediaspam,
    cmd_toggle_antilink,
)
from bot.commands import setup_bot_commands, BOT_COMMANDS
from db.models import Fine
from core.enums import PositionLevel, FineStatus


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


@pytest.mark.asyncio
async def test_cmd_summon_all_admin(db_session, sample_users):
    """Тест команды /созвать (/all) Администрацией города."""
    admin = sample_users["admin"]

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1001234567

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = admin.telegram_id
    tg_user.mention_html.return_value = f'<a href="tg://user?id={admin.telegram_id}">{admin.full_name}</a>'

    bot_mock = MagicMock()
    bot_mock.pin_chat_message = AsyncMock()

    message = MagicMock(spec=Message)
    message.chat = chat
    message.from_user = tg_user
    message.bot = bot_mock
    message.text = "/созвать Срочное собрание на ратушной площади"
    sent_msg = MagicMock()
    sent_msg.message_id = 999
    message.answer = AsyncMock(return_value=sent_msg)

    await cmd_summon_all(message, db_session, db_user=admin)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "ОБЩИЙ СБОР ЖИТЕЛЕЙ ГОРОДА!" in reply
    assert "Срочное собрание на ратушной площади" in reply


@pytest.mark.asyncio
async def test_cmd_summon_all_citizen_forbidden(db_session, sample_users):
    """Тест команды /all обычным жителем — отказ в доступе."""
    citizen = sample_users["citizen"]

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1001234567
    chat.get_member = AsyncMock(return_value=MagicMock(status="member"))

    tg_user = MagicMock(spec=TgUser)
    tg_user.id = citizen.telegram_id

    message = MagicMock(spec=Message)
    message.chat = chat
    message.from_user = tg_user
    message.text = "/all"
    message.answer = AsyncMock()

    await cmd_summon_all(message, db_session, db_user=citizen)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "только Администрация" in reply


@pytest.mark.asyncio
async def test_cmd_set_nick_admin_forced(db_session, sample_users):
    """Тест принудительного назначения ника жителю Администратором."""
    admin = sample_users["admin"]
    citizen = sample_users["citizen"]

    message = MagicMock(spec=Message)
    message.text = f"/ник @{citizen.username} Steve_AdminAssigned"
    message.reply_to_message = None
    message.answer = AsyncMock()

    await cmd_set_nick(message, db_session, db_user=admin)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "Администрация принудительно привязала ник" in reply
    assert citizen.minecraft_nick == "Steve_AdminAssigned"


@pytest.mark.asyncio
async def test_cmd_set_nick_citizen_forbidden_for_others(db_session, sample_users):
    """Тест попытки обычного жителя изменить чужой никнейм."""
    citizen = sample_users["citizen"]
    assistant = sample_users["assistant"]

    message = MagicMock(spec=Message)
    message.text = f"/ник @{assistant.username} HackNick"
    message.reply_to_message = None
    message.answer = AsyncMock()

    await cmd_set_nick(message, db_session, db_user=citizen)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "только Администрация города" in reply


@pytest.mark.asyncio
async def test_cmd_law_edit_higher_admin(db_session, sample_users):
    """Тест редактирования закона Высшей Администрацией (уровень 5)."""
    senior_admin = sample_users["senior_admin"]  # уровень 5

    message = MagicMock(spec=Message)
    message.text = "/закон_ред 1.1 Все граждане равны перед Законом и обязаны соблюдать его."
    message.answer = AsyncMock()

    await cmd_law_edit(message, db_session, db_user=senior_admin)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "успешно изменена" in reply
    assert "Все граждане равны перед Законом" in reply


@pytest.mark.asyncio
async def test_cmd_law_edit_assistant_denied(db_session, sample_users):
    """Тест попытки редактирования закона помощником (уровень 1) — отказ."""
    assistant = sample_users["assistant"]  # уровень 1

    message = MagicMock(spec=Message)
    message.text = "/закон_ред 1.1 Попытка взлома законов"
    message.answer = AsyncMock()

    await cmd_law_edit(message, db_session, db_user=assistant)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "недостаточно прав" in reply.lower() or "только" in reply.lower()


@pytest.mark.asyncio
async def test_cmd_regulators_toggle(db_session, sample_users):
    """Тест включения и отключения регуляторов чата (/антикапс, /спам, /ссылки)."""
    admin = sample_users["admin"]
    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -1005555

    # 1. Антикапс выкл
    msg_caps = MagicMock(spec=Message)
    msg_caps.chat = chat
    msg_caps.text = "/антикапс выкл"
    msg_caps.answer = AsyncMock()
    await cmd_toggle_anticaps(msg_caps, db_session, db_user=admin)
    assert "ОТКЛЮЧЕН" in msg_caps.answer.call_args[0][0]

    # 2. Медиа-спам вкл
    msg_spam = MagicMock(spec=Message)
    msg_spam.chat = chat
    msg_spam.text = "/спам вкл"
    msg_spam.answer = AsyncMock()
    await cmd_toggle_mediaspam(msg_spam, db_session, db_user=admin)
    assert "ВКЛЮЧЕН" in msg_spam.answer.call_args[0][0]

    # 3. Ссылки выкл
    msg_link = MagicMock(spec=Message)
    msg_link.chat = chat
    msg_link.text = "/ссылки выкл"
    msg_link.answer = AsyncMock()
    await cmd_toggle_antilink(msg_link, db_session, db_user=admin)
    assert "ОТКЛЮЧЕН" in msg_link.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_setup_bot_commands_menu():
    """Тест установки меню команд Telegram."""
    bot_mock = MagicMock()
    bot_mock.set_my_commands = AsyncMock()

    await setup_bot_commands(bot_mock)

    bot_mock.set_my_commands.assert_called_once()
    commands_passed = bot_mock.set_my_commands.call_args[0][0]
    assert len(commands_passed) == len(BOT_COMMANDS)
    command_names = [c.command for c in commands_passed]
    assert "all" in command_names
    assert "nick" in command_names
    assert "laws" in command_names
    assert "regulators" in command_names
    assert "amnesty" in command_names


@pytest.mark.asyncio
async def test_cmd_amnesty_individual(db_session, sample_users):
    """Тест команды /амнистия для конкретного нарушителя."""
    admin = sample_users["admin"]
    enemy = sample_users["enemy"]

    # Даем нарушителю предупреждения, статус розыска и активный штраф
    enemy.warns_count = 3
    enemy.is_wanted = True
    fine = Fine(
        user_id=enemy.id,
        target_telegram_id=enemy.telegram_id,
        issuer_id=admin.id,
        issuer_telegram_id=admin.telegram_id,
        law_article="2.1",
        amount=15000,
        original_amount=15000,
        reason="Оскорбление",
        status=FineStatus.ACTIVE.value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db_session.add(fine)
    await db_session.commit()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100777
    chat.restrict = AsyncMock()
    chat.unban = AsyncMock()

    message = MagicMock(spec=Message)
    message.chat = chat
    message.text = f"/амнистия @{enemy.username} Чистосердечное раскаяние"
    message.reply_to_message = None
    message.answer = AsyncMock()
    message.bot = None

    await cmd_amnesty(message, db_session, db_user=admin)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "АКТ ГОРОДСКОЙ АМНИСТИИ" in reply
    assert enemy.full_name in reply

    # Проверяем, что все снято
    assert enemy.warns_count == 0
    assert enemy.is_wanted is False
    assert enemy.is_enemy is False
    assert enemy.role_level == PositionLevel.CITIZEN.value
    assert fine.status == FineStatus.CANCELLED.value
    chat.restrict.assert_called_once()
    chat.unban.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_amnesty_all(db_session, sample_users):
    """Тест всеобщей городской амнистии (/амнистия все)."""
    admin = sample_users["admin"]
    citizen = sample_users["citizen"]

    citizen.warns_count = 2
    citizen.is_wanted = True
    await db_session.commit()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100777

    message = MagicMock(spec=Message)
    message.chat = chat
    message.text = "/амнистия все В честь дня основания города"
    message.answer = AsyncMock()
    message.bot = None

    await cmd_amnesty(message, db_session, db_user=admin)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "ОБЩАЯ ГОРОДСКАЯ АМНИСТИЯ ОБЪЯВЛЕНА!" in reply
    assert citizen.warns_count == 0
    assert citizen.is_wanted is False


@pytest.mark.asyncio
async def test_cmd_amnesty_citizen_forbidden(db_session, sample_users):
    """Тест попытки объявить амнистию обычным жителем — отказ."""
    citizen = sample_users["citizen"]
    enemy = sample_users["enemy"]

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100777
    chat.get_member = AsyncMock(return_value=MagicMock(status="member"))

    message = MagicMock(spec=Message)
    message.chat = chat
    message.from_user = MagicMock(id=citizen.telegram_id)
    message.text = f"/амнистия @{enemy.username}"
    message.reply_to_message = None
    message.answer = AsyncMock()

    await cmd_amnesty(message, db_session, db_user=citizen)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "только Администрация" in reply
