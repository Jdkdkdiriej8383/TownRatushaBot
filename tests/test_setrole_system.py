import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Message, User as TgUser, Chat, CallbackQuery
from db.models.user import User
from core.enums import PositionLevel, GovernmentRole, resolve_role_alias
from core.hierarchy_service import HierarchyService
from bot.handlers.admin import (
    cmd_setrole,
    cb_setrole_select,
    cmd_demote,
    build_role_keyboard,
    SETROLE_DEFINITIONS,
    ROLE_CODE_MAP,
)
from bot.utils import extract_target_user


def test_resolve_role_alias():
    """Проверка всестороннего разрешения должностей и рангов."""
    # 1. Цифровые ранги
    assert resolve_role_alias("4") == (5, GovernmentRole.MAYOR.value)
    assert resolve_role_alias("3") == (4, GovernmentRole.MINISTER.value)
    assert resolve_role_alias("2") == (2, GovernmentRole.WARDEN.value)
    assert resolve_role_alias("1") == (1, GovernmentRole.ASSISTANT.value)
    assert resolve_role_alias("0") == (0, GovernmentRole.CITIZEN.value)

    # 2. Ранги с префиксами
    assert resolve_role_alias("ранг 3") == (4, GovernmentRole.MINISTER.value)
    assert resolve_role_alias("уровень: 2") == (2, GovernmentRole.WARDEN.value)
    assert resolve_role_alias("ранг 4") == (5, GovernmentRole.MAYOR.value)
    assert resolve_role_alias("rank 1") == (1, GovernmentRole.ASSISTANT.value)

    # 3. Точные названия и формы
    assert resolve_role_alias("мэр") == (5, GovernmentRole.MAYOR.value)
    assert resolve_role_alias("премьер-министр") == (5, GovernmentRole.PRIME_MINISTER.value)
    assert resolve_role_alias("конституционный судья") == (5, GovernmentRole.CHIEF_JUSTICE.value)
    assert resolve_role_alias("заместитель мэра") == (4, GovernmentRole.DEPUTY_MAYOR.value)
    assert resolve_role_alias("министр") == (4, GovernmentRole.MINISTER.value)
    assert resolve_role_alias("судья") == (4, GovernmentRole.JUDGE.value)
    assert resolve_role_alias("блюститель") == (2, GovernmentRole.WARDEN.value)
    assert resolve_role_alias("помощник") == (1, GovernmentRole.ASSISTANT.value)
    assert resolve_role_alias("гражданин") == (0, GovernmentRole.CITIZEN.value)

    # 4. Сокращения и сленг
    assert resolve_role_alias("зам") == (4, GovernmentRole.DEPUTY_MAYOR.value)
    assert resolve_role_alias("вице") == (4, GovernmentRole.DEPUTY_MAYOR.value)
    assert resolve_role_alias("пм") == (5, GovernmentRole.PRIME_MINISTER.value)
    assert resolve_role_alias("премьер") == (5, GovernmentRole.PRIME_MINISTER.value)
    assert resolve_role_alias("ксуд") == (5, GovernmentRole.CHIEF_JUSTICE.value)
    assert resolve_role_alias("модер") == (2, GovernmentRole.WARDEN.value)
    assert resolve_role_alias("хелпер") == (1, GovernmentRole.ASSISTANT.value)
    assert resolve_role_alias("саппорт") == (1, GovernmentRole.ASSISTANT.value)
    assert resolve_role_alias("админ") == (4, "Администрация")
    assert resolve_role_alias("снять") == (0, GovernmentRole.CITIZEN.value)

    # 5. Английские названия
    assert resolve_role_alias("mayor") == (5, GovernmentRole.MAYOR.value)
    assert resolve_role_alias("deputy") == (4, GovernmentRole.DEPUTY_MAYOR.value)
    assert resolve_role_alias("minister") == (4, GovernmentRole.MINISTER.value)
    assert resolve_role_alias("judge") == (4, GovernmentRole.JUDGE.value)
    assert resolve_role_alias("warden") == (2, GovernmentRole.WARDEN.value)
    assert resolve_role_alias("helper") == (1, GovernmentRole.ASSISTANT.value)
    assert resolve_role_alias("citizen") == (0, GovernmentRole.CITIZEN.value)


@pytest.mark.asyncio
async def test_build_role_keyboard(db_session: AsyncSession):
    """Проверка генерации инлайн-клавиатуры под ранг инициатора."""
    mayor = User(telegram_id=9001, username="mayor", full_name="Мэр", role_level=5, custom_title=GovernmentRole.MAYOR.value)
    deputy = User(telegram_id=9002, username="deputy", full_name="Зам", role_level=4, custom_title=GovernmentRole.DEPUTY_MAYOR.value)
    target = User(telegram_id=9003, username="target", full_name="Цель", role_level=0, custom_title=GovernmentRole.CITIZEN.value)
    db_session.add_all([mayor, deputy, target])
    await db_session.commit()

    # Мэр видит все должности
    kb_mayor = build_role_keyboard(mayor, target)
    button_texts_mayor = [btn.text for row in kb_mayor.inline_keyboard for btn in row]
    assert any("Мэр" in t for t in button_texts_mayor)
    assert any("Министр" in t for t in button_texts_mayor)
    assert any("Блюститель" in t for t in button_texts_mayor)
    assert any("Отмена" in t for t in button_texts_mayor)

    # Заместитель мэра видит только ранги 0-2 (Блюститель, Помощник, Снять)
    kb_deputy = build_role_keyboard(deputy, target)
    button_texts_deputy = [btn.text for row in kb_deputy.inline_keyboard for btn in row]
    assert not any("Мэр" in t for t in button_texts_deputy)
    assert not any("Министр" in t for t in button_texts_deputy)
    assert any("Блюститель" in t for t in button_texts_deputy)
    assert any("Помощник" in t for t in button_texts_deputy)


@pytest.mark.asyncio
async def test_cmd_setrole_text_and_numbers(db_session: AsyncSession):
    """Назначение роли через текст и через числовые ранги."""
    mayor = User(telegram_id=9101, username="big_mayor", full_name="Мэр Города", role_level=5, custom_title=GovernmentRole.MAYOR.value)
    citizen = User(telegram_id=9102, username="ordinary_ivan", full_name="Иван Обычный", role_level=0, custom_title=GovernmentRole.CITIZEN.value)
    db_session.add_all([mayor, citizen])
    await db_session.commit()

    # 1. Мэр назначает Министра по тексту
    msg = MagicMock(spec=Message)
    msg.text = "/setrole @ordinary_ivan Министр"
    msg.chat = MagicMock(spec=Chat, id=-1003980887141)
    msg.reply_to_message = None
    msg.entities = []
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.send_message = AsyncMock()

    await cmd_setrole(message=msg, session=db_session, db_user=mayor)
    await db_session.refresh(citizen)
    assert citizen.role_level == PositionLevel.ADMINISTRATION.value
    assert citizen.custom_title == GovernmentRole.MINISTER.value
    msg.answer.assert_called_once()
    assert "ГОСУДАРСТВЕННОЕ НАЗНАЧЕНИЕ" in msg.answer.call_args[0][0]

    # 2. Мэр назначает Блюстителя через цифру "2"
    msg2 = MagicMock(spec=Message)
    msg2.text = "/роль @ordinary_ivan 2"
    msg2.chat = MagicMock(spec=Chat, id=-1003980887141)
    msg2.reply_to_message = None
    msg2.entities = []
    msg2.reply = AsyncMock()
    msg2.answer = AsyncMock()
    msg2.bot = MagicMock()
    msg2.bot.send_message = AsyncMock()

    await cmd_setrole(message=msg2, session=db_session, db_user=mayor)
    await db_session.refresh(citizen)
    assert citizen.role_level == PositionLevel.CHAT_WARDEN.value
    assert citizen.custom_title == GovernmentRole.WARDEN.value


@pytest.mark.asyncio
async def test_cmd_setrole_interactive_keyboard(db_session: AsyncSession):
    """Вызов /setrole без аргумента роли открывает интерактивные кнопки."""
    mayor = User(telegram_id=9201, username="mayor2", full_name="Мэр 2", role_level=5, custom_title=GovernmentRole.MAYOR.value)
    target = User(telegram_id=9202, username="target2", full_name="Кандидат", role_level=0, custom_title=GovernmentRole.CITIZEN.value)
    db_session.add_all([mayor, target])
    await db_session.commit()

    msg = MagicMock(spec=Message)
    msg.text = "/setrole @target2"
    msg.chat = MagicMock(spec=Chat, id=-1003980887141)
    msg.reply_to_message = None
    msg.entities = []
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    msg.bot = MagicMock()

    await cmd_setrole(message=msg, session=db_session, db_user=mayor)

    msg.reply.assert_called_once()
    args, kwargs = msg.reply.call_args
    assert "Выберите новую государственную должность" in args[0]
    assert "reply_markup" in kwargs
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_cb_setrole_select(db_session: AsyncSession):
    """Нажатие кнопки в интерактивном меню назначает должность."""
    mayor = User(telegram_id=9301, username="mayor3", full_name="Мэр 3", role_level=5, custom_title=GovernmentRole.MAYOR.value)
    target = User(telegram_id=9302, username="target3", full_name="Кандидат 3", role_level=0, custom_title=GovernmentRole.CITIZEN.value)
    db_session.add_all([mayor, target])
    await db_session.commit()

    cb = MagicMock(spec=CallbackQuery)
    cb.data = f"setrole:{target.telegram_id}:judge"
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(spec=Chat, id=-1003980887141)
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()

    await cb_setrole_select(callback=cb, session=db_session, db_user=mayor)
    await db_session.refresh(target)

    assert target.role_level == PositionLevel.ADMINISTRATION.value
    assert target.custom_title == GovernmentRole.JUDGE.value
    cb.message.edit_text.assert_called_once()
    assert "ГОСУДАРСТВЕННОЕ НАЗНАЧЕНИЕ" in cb.message.edit_text.call_args[0][0]
    cb.answer.assert_called_once_with("✅ Должность успешно присвоена!")


@pytest.mark.asyncio
async def test_cmd_demote_and_subordination(db_session: AsyncSession):
    """Разжалование сотрудника и проверка субординации."""
    mayor = User(telegram_id=9401, username="mayor4", full_name="Мэр 4", role_level=5, custom_title=GovernmentRole.MAYOR.value)
    minister = User(telegram_id=9402, username="min4", full_name="Министр 4", role_level=4, custom_title=GovernmentRole.MINISTER.value)
    citizen = User(telegram_id=9403, username="cit4", full_name="Гражданин 4", role_level=0, custom_title=GovernmentRole.CITIZEN.value)
    db_session.add_all([mayor, minister, citizen])
    await db_session.commit()

    # 1. Гражданин пытается разжаловать министра -> отказ
    msg_fail = MagicMock(spec=Message)
    msg_fail.text = "/demote @min4"
    msg_fail.chat = MagicMock(spec=Chat, id=-1003980887141)
    msg_fail.reply_to_message = None
    msg_fail.entities = []
    msg_fail.reply = AsyncMock()
    msg_fail.answer = AsyncMock()
    msg_fail.bot = MagicMock()

    await cmd_demote(message=msg_fail, session=db_session, db_user=citizen)
    await db_session.refresh(minister)
    assert minister.role_level == PositionLevel.ADMINISTRATION.value
    msg_fail.reply.assert_called_once()
    assert "Нарушение субординации" in msg_fail.reply.call_args[0][0]

    # 2. Мэр разжалует министра -> успешно
    msg_ok = MagicMock(spec=Message)
    msg_ok.text = "/demote @min4 Потеря доверия"
    msg_ok.chat = MagicMock(spec=Chat, id=-1003980887141)
    msg_ok.reply_to_message = None
    msg_ok.entities = []
    msg_ok.reply = AsyncMock()
    msg_ok.answer = AsyncMock()
    msg_ok.bot = MagicMock()

    await cmd_demote(message=msg_ok, session=db_session, db_user=mayor)
    await db_session.refresh(minister)
    assert minister.role_level == PositionLevel.CITIZEN.value
    assert minister.custom_title is None
    msg_ok.answer.assert_called_once()
    assert "РАЗЖАЛОВАНИЕ В ДОЛЖНОСТИ" in msg_ok.answer.call_args[0][0]
