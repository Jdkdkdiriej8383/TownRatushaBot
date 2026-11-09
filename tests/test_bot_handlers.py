from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, User as TgUser, Chat
from bot.handlers.laws import cmd_law, cmd_laws_list, cmd_law_edit
from bot.handlers.justice import (
    cmd_fine,
    cmd_amnesty,
    cmd_reprimand,
    cmd_unreprimand,
    cmd_promote_admin,
    cmd_demote_admin,
)
from bot.handlers.passport import cmd_passport, cmd_set_nick
from bot.handlers.common import cmd_summon_all, cmd_sync_menu
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
async def test_cmd_laws_list_summary(db_session):
    """Тест выполнения команды /законы: вывод канонической навигационной карточки."""
    message = MagicMock(spec=Message)
    message.text = "/законы"
    message.answer = AsyncMock()

    await cmd_laws_list(message, db_session)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "📖 <b>ГОРОДСКОЙ СВОД ЗАКОНОВ</b>" in reply
    assert "Чтобы ознакомиться со статьей, используйте:" in reply
    assert "/закон [номер_статьи]" in reply
    assert "/закон 2.1" in reply
    assert "/закон 3.12" in reply
    assert "Разделы Свода Законов:" in reply
    assert "• Раздел I. Общие положения (1.1 - 1.4)" in reply
    assert "• Раздел II. Чат Telegram (2.1 - 2.12)" in reply
    assert "• Раздел III. Внутриигровые законы (3.1 - 3.28)" in reply
    assert "• Раздел IV. Служба и работа (4.1 - 4.4)" in reply
    assert "Для полного списка всех статей введите: /законы" in reply
    assert "https://teletype.in/@townratushabot/Rules" in reply



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
    """Тест установки меню команд Telegram во всех областях и локалях."""
    bot_mock = MagicMock()
    bot_mock.set_my_commands = AsyncMock()
    bot_mock.delete_my_commands = AsyncMock()

    count = await setup_bot_commands(bot_mock)

    assert count == len(BOT_COMMANDS)
    assert bot_mock.delete_my_commands.called
    assert bot_mock.set_my_commands.call_count >= 4
    commands_passed = bot_mock.set_my_commands.call_args_list[0][0][0]
    assert len(commands_passed) == len(BOT_COMMANDS)
    command_names = [c.command for c in commands_passed]
    assert "all" in command_names
    assert "nick" in command_names
    assert "laws" in command_names
    assert "regulators" in command_names
    assert "amnesty" in command_names
    assert "reprimand" in command_names
    assert "unreprimand" in command_names
    assert "promote" in command_names
    assert "demote" in command_names
    assert "sync_menu" in command_names


@pytest.mark.asyncio
async def test_cmd_sync_menu_admin(sample_users):
    """Тест команды /обновить_меню администратором города."""
    admin = sample_users["admin"]

    bot_mock = MagicMock()
    bot_mock.set_my_commands = AsyncMock()
    bot_mock.delete_my_commands = AsyncMock()

    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()

    message = MagicMock(spec=Message)
    message.text = "/обновить_меню"
    message.bot = bot_mock
    message.answer = AsyncMock(return_value=status_msg)

    await cmd_sync_menu(message, db_user=admin)

    message.answer.assert_called_once()
    status_msg.edit_text.assert_called_once()
    reply = status_msg.edit_text.call_args[0][0]
    assert "МЕНЮ КОМАНД TELEGRAM УСПЕШНО ОБНОВЛЕНО" in reply
    assert f"{len(BOT_COMMANDS)}" in reply



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


@pytest.mark.asyncio
async def test_cmd_reprimand_progression_and_auto_dismissal(db_session, sample_users):
    """
    Тест системы выговоров /выговор:
    1-й выговор -> счетчик 1/3
    2-й выговор -> счетчик 2/3
    3-й выговор -> автоматическое отстранение от должности (роль 0),
                  обнуление счетчика выговоров,
                  снятие Telegram-прав администратора в супергруппе.
    """
    admin = sample_users["admin"]
    warden = sample_users["chat_warden"]
    assert warden.role_level == PositionLevel.CHAT_WARDEN.value
    assert warden.reprimands_count == 0

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100555
    chat.promote = AsyncMock()

    # 1. Первый выговор
    msg1 = MagicMock(spec=Message)
    msg1.chat = chat
    msg1.from_user = MagicMock(id=admin.telegram_id)
    msg1.text = f"/выговор @{warden.username} Опоздание на дежурство"
    msg1.reply_to_message = None
    msg1.answer = AsyncMock()
    msg1.bot = None

    await cmd_reprimand(msg1, db_session, db_user=admin)
    msg1.answer.assert_called_once()
    assert "1 / 3" in msg1.answer.call_args[0][0]
    assert warden.reprimands_count == 1
    assert warden.role_level == PositionLevel.CHAT_WARDEN.value

    # 2. Второй выговор
    msg2 = MagicMock(spec=Message)
    msg2.chat = chat
    msg2.from_user = MagicMock(id=admin.telegram_id)
    msg2.text = f"/выговор @{warden.username} Невыполнение распоряжения"
    msg2.reply_to_message = None
    msg2.answer = AsyncMock()
    msg2.bot = None

    await cmd_reprimand(msg2, db_session, db_user=admin)
    msg2.answer.assert_called_once()
    assert "2 / 3" in msg2.answer.call_args[0][0]
    assert warden.reprimands_count == 2
    assert warden.role_level == PositionLevel.CHAT_WARDEN.value

    # 3. Третий выговор -> Отстранение от должности
    msg3 = MagicMock(spec=Message)
    msg3.chat = chat
    msg3.from_user = MagicMock(id=admin.telegram_id)
    msg3.text = f"/выговор @{warden.username} Грубое нарушение устава"
    msg3.reply_to_message = None
    msg3.answer = AsyncMock()
    msg3.bot = None

    await cmd_reprimand(msg3, db_session, db_user=admin)
    msg3.answer.assert_called_once()
    reply3 = msg3.answer.call_args[0][0]
    assert "СЛУЖЕБНОЕ ОТСТРАНЕНИЕ ОТ ДОЛЖНОСТИ" in reply3
    assert "3/3" in reply3
    assert warden.role_level == PositionLevel.CITIZEN.value
    assert warden.reprimands_count == 0
    chat.promote.assert_called_once_with(
        user_id=warden.telegram_id,
        can_manage_chat=False,
        can_change_info=False,
        can_delete_messages=False,
        can_invite_users=False,
        can_restrict_members=False,
        can_pin_messages=False,
        can_promote_members=False,
        can_manage_video_chats=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
    )


@pytest.mark.asyncio
async def test_cmd_reprimand_subordination(db_session, sample_users):
    """Тест субординации при выговорах: нельзя выносить равному или старшему."""
    assistant = sample_users["assistant"]  # уровень 1
    warden = sample_users["chat_warden"]    # уровень 2

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100555
    chat.get_member = AsyncMock(return_value=MagicMock(status="member"))

    # Помощник (ур 1) пытается объявить выговор блюстителю (ур 2)
    msg = MagicMock(spec=Message)
    msg.chat = chat
    msg.from_user = MagicMock(id=assistant.telegram_id)
    msg.text = f"/выговор @{warden.username} Превышение полномочий"
    msg.reply_to_message = None
    msg.answer = AsyncMock()

    await cmd_reprimand(msg, db_session, db_user=assistant)
    msg.answer.assert_called_once()
    assert "только Администрация" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_unreprimand(db_session, sample_users):
    """Тест команды /снять_выговор: уменьшает счетчик выговоров на 1."""
    admin = sample_users["admin"]
    warden = sample_users["chat_warden"]
    warden.reprimands_count = 2
    await db_session.commit()

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100555

    msg = MagicMock(spec=Message)
    msg.chat = chat
    msg.from_user = MagicMock(id=admin.telegram_id)
    msg.text = f"/снять_выговор @{warden.username} Примерное поведение"
    msg.reply_to_message = None
    msg.answer = AsyncMock()

    await cmd_unreprimand(msg, db_session, db_user=admin)
    msg.answer.assert_called_once()
    reply = msg.answer.call_args[0][0]
    assert "СЛУЖЕБНЫЙ ВЫГОВОР АННУЛИРОВАН" in reply
    assert "1 / 3" in reply
    assert warden.reprimands_count == 1


@pytest.mark.asyncio
async def test_cmd_promote_and_demote_admin(db_session, sample_users):
    """Тест команд /выдать_адм и /снять_адм для управления правами в чате."""
    admin = sample_users["admin"]
    warden = sample_users["chat_warden"]

    chat = MagicMock(spec=Chat)
    chat.type = "supergroup"
    chat.id = -100555
    chat.promote = AsyncMock()
    chat.set_administrator_custom_title = AsyncMock()

    # 1. /выдать_адм
    msg_prom = MagicMock(spec=Message)
    msg_prom.chat = chat
    msg_prom.from_user = MagicMock(id=admin.telegram_id)
    msg_prom.text = f"/выдать_адм @{warden.username} Капитан"
    msg_prom.reply_to_message = None
    msg_prom.answer = AsyncMock()
    msg_prom.bot = None

    await cmd_promote_admin(msg_prom, db_session, db_user=admin)
    msg_prom.answer.assert_called_once()
    assert "НАЗНАЧЕНИЕ АДМИНИСТРАТОРА ЧАТА" in msg_prom.answer.call_args[0][0]
    chat.promote.assert_called_once()
    assert chat.promote.call_args[1]["can_manage_chat"] is True
    chat.set_administrator_custom_title.assert_called_once_with(
        user_id=warden.telegram_id,
        custom_title="Капитан",
    )

    # 2. /снять_адм
    chat.promote.reset_mock()
    msg_dem = MagicMock(spec=Message)
    msg_dem.chat = chat
    msg_dem.from_user = MagicMock(id=admin.telegram_id)
    msg_dem.text = f"/снять_адм @{warden.username} Ротация кадров"
    msg_dem.reply_to_message = None
    msg_dem.answer = AsyncMock()
    msg_dem.bot = None

    await cmd_demote_admin(msg_dem, db_session, db_user=admin)
    msg_dem.answer.assert_called_once()
    assert "ОТЗЫВ ПРАВ АДМИНИСТРАТОРА ЧАТА" in msg_dem.answer.call_args[0][0]
    chat.promote.assert_called_once()
    assert chat.promote.call_args[1]["can_manage_chat"] is False

