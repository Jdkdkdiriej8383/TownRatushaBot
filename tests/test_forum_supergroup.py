import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User
from db.models.report import Report
from db.models.ticket import Ticket
from db.models.topic_config import TopicConfig
from core.enums import PositionLevel, GovernmentRole, TicketCategory, TicketStatus, TopicType
from core.hierarchy_service import HierarchyService
from core.topic_service import TopicService
from core.report_service import ReportService
from core.ticket_service import TicketService
from core.moderation_service import ModerationService, parse_duration
from core.exceptions import TownBaseException


@pytest.fixture
async def gov_users(db_session: AsyncSession):
    """Набор пользователей государственной администрации разного ранга."""
    users = {
        "citizen": User(
            telegram_id=2000,
            username="citizen_vasya",
            full_name="Василий Гражданин",
            role_level=PositionLevel.CITIZEN.value,
            custom_title=GovernmentRole.CITIZEN.value,
        ),
        "helper": User(
            telegram_id=2001,
            username="helper_kolya",
            full_name="Николай Помощник",
            role_level=PositionLevel.ASSISTANT.value,
            custom_title=GovernmentRole.ASSISTANT.value,
        ),
        "warden": User(
            telegram_id=2002,
            username="warden_sasha",
            full_name="Александр Блюститель",
            role_level=PositionLevel.CHAT_WARDEN.value,
            custom_title=GovernmentRole.WARDEN.value,
        ),
        "judge": User(
            telegram_id=2003,
            username="judge_elena",
            full_name="Елена Судья",
            role_level=PositionLevel.ADMINISTRATION.value,
            custom_title=GovernmentRole.JUDGE.value,
        ),
        "minister": User(
            telegram_id=2004,
            username="minister_boris",
            full_name="Борис Министр",
            role_level=PositionLevel.ADMINISTRATION.value,
            custom_title=GovernmentRole.MINISTER.value,
        ),
        "deputy_mayor": User(
            telegram_id=2005,
            username="deputy_oleg",
            full_name="Олег Вице-Мэр",
            role_level=PositionLevel.ADMINISTRATION.value,
            custom_title=GovernmentRole.DEPUTY_MAYOR.value,
        ),
        "chief_justice": User(
            telegram_id=2006,
            username="chief_justice_lev",
            full_name="Лев Конституционный Судья",
            role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
            custom_title=GovernmentRole.CHIEF_JUSTICE.value,
        ),
        "prime_minister": User(
            telegram_id=2007,
            username="pm_mikhail",
            full_name="Михаил Премьер",
            role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
            custom_title=GovernmentRole.PRIME_MINISTER.value,
        ),
        "mayor": User(
            telegram_id=2008,
            username="mayor_vladimir",
            full_name="Владимир Мэр",
            role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
            custom_title=GovernmentRole.MAYOR.value,
        ),
    }
    for u in users.values():
        db_session.add(u)
    await db_session.commit()
    return users


@pytest.mark.asyncio
async def test_seniority_and_rbac(gov_users):
    """Проверка правила старшинства (Ранг_Инициатора > Ранг_Цели) и судебной неприкосновенности."""
    citizen = gov_users["citizen"]
    helper = gov_users["helper"]
    warden = gov_users["warden"]
    judge = gov_users["judge"]
    minister = gov_users["minister"]
    chief_justice = gov_users["chief_justice"]
    mayor = gov_users["mayor"]

    # 1. Младший не может наказать старшего
    with pytest.raises(TownBaseException, match="Нарушение субординации"):
        HierarchyService.validate_seniority(initiator=helper, target=warden, action_name="варн")

    # 2. Равный не может наказать равного (Министр vs Судья - оба Ранг 3)
    with pytest.raises(TownBaseException, match="Нарушение субординации"):
        HierarchyService.validate_seniority(initiator=minister, target=judge, action_name="мут")

    # 3. Нельзя наказывать самого себя
    with pytest.raises(TownBaseException, match="к самому себе"):
        HierarchyService.validate_seniority(initiator=warden, target=warden, action_name="мут")

    # 4. Старший может наказать младшего
    HierarchyService.validate_seniority(initiator=minister, target=warden, action_name="выговор")
    HierarchyService.validate_seniority(initiator=warden, target=citizen, action_name="варн")

    # 4. Конституционный судья обладает полной судебной неприкосновенностью
    with pytest.raises(TownBaseException, match="Конституционный судья"):
        HierarchyService.validate_seniority(initiator=mayor, target=chief_justice, action_name="бан")


@pytest.mark.asyncio
async def test_appointments_rbac(gov_users):
    """Проверка полномочий назначения на государственные должности."""
    citizen = gov_users["citizen"]
    helper = gov_users["helper"]
    deputy_mayor = gov_users["deputy_mayor"]
    prime_minister = gov_users["prime_minister"]
    mayor = gov_users["mayor"]

    # Мэр может назначать любые ранги 0-4
    can_m, _ = HierarchyService.can_appoint_role(
        initiator=mayor, target=citizen, target_level=PositionLevel.ADMINISTRATION.value, target_title="Министр"
    )
    assert can_m is True

    # Премьер-министр может назначать министров (ранг 3), но не Мэра или Главного Судью (ранг 4)
    can_pm, _ = HierarchyService.can_appoint_role(
        initiator=prime_minister, target=citizen, target_level=PositionLevel.ADMINISTRATION.value, target_title="Министр"
    )
    assert can_pm is True

    can_pm_top, msg = HierarchyService.can_appoint_role(
        initiator=prime_minister, target=citizen, target_level=PositionLevel.SENIOR_ADMINISTRATION.value, target_title="Мэр"
    )
    assert can_pm_top is False
    assert "не может назначать" in msg

    # Заместитель мэра назначает только блюстителей и помощников (ранги 1-2)
    can_dep_w, _ = HierarchyService.can_appoint_role(
        initiator=deputy_mayor, target=citizen, target_level=PositionLevel.CHAT_WARDEN.value, target_title="Блюститель"
    )
    assert can_dep_w is True

    can_dep_m, _ = HierarchyService.can_appoint_role(
        initiator=deputy_mayor, target=citizen, target_level=PositionLevel.ADMINISTRATION.value, target_title="Министр"
    )
    assert can_dep_m is False

    # Помощник (ранг 1) вообще не может назначать
    can_help, _ = HierarchyService.can_appoint_role(
        initiator=helper, target=citizen, target_level=PositionLevel.CHAT_WARDEN.value, target_title="Блюститель"
    )
    assert can_help is False


@pytest.mark.asyncio
async def test_topic_jurisdiction_validation(db_session: AsyncSession):
    """Проверка работы Forum Topics Filter и определения юрисдикции тем."""
    chat_id = -1001234567890

    # Настраиваем топики в БД
    await TopicService.set_topic_mapping(
        db_session, chat_id=chat_id, topic_type=TopicType.COMMUNITY.value, thread_id=101, topic_name="Флудилка"
    )
    await TopicService.set_topic_mapping(
        db_session, chat_id=chat_id, topic_type=TopicType.REPORTS.value, thread_id=102, topic_name="Модерация"
    )
    await TopicService.set_topic_mapping(
        db_session, chat_id=chat_id, topic_type=TopicType.COURT.value, thread_id=103, topic_name="Зал Суда"
    )

    # 1. Команда модерации в разрешенной теме (102) -> Успех
    allowed, cur_name, _ = await TopicService.validate_jurisdiction(
        db_session, chat_id=chat_id, current_thread_id=102, allowed_types=[TopicType.REPORTS.value, TopicType.ADMIN.value]
    )
    assert allowed is True
    assert cur_name == "Модерация"

    # 2. Команда модерации во Флудилке (101) -> Ошибка юрисдикции
    allowed, cur_name, target_name = await TopicService.validate_jurisdiction(
        db_session, chat_id=chat_id, current_thread_id=101, allowed_types=[TopicType.REPORTS.value, TopicType.ADMIN.value]
    )
    assert allowed is False
    assert cur_name == "Флудилка"
    assert "Жалобы / Модерация" in target_name


@pytest.mark.asyncio
async def test_report_workflow_and_false_limit(db_session: AsyncSession, gov_users):
    """Проверка подачи репорта, взятия в работу и счетчика ложных вызовов."""
    citizen = gov_users["citizen"]
    violator = gov_users["helper"]
    warden = gov_users["warden"]

    # 1. Подача жалобы
    rep1 = await ReportService.create_report(
        session=db_session,
        reporter=citizen,
        violator=violator,
        incident_topic_id=101,
        incident_topic_name="Общий чат",
        message_id=555,
        message_text="Оскорбительное сообщение",
        reason="Спам и мат",
    )
    assert rep1.id is not None
    assert rep1.status == "pending"

    # 2. Блюститель берет в работу
    rep1_claimed = await ReportService.claim_report(db_session, rep1.id, warden)
    assert rep1_claimed.status == "claimed"
    assert rep1_claimed.claimed_by_id == warden.id

    # 3. Фиксация 3 ложных вызовов подряд блокирует гражданину репорты на 24ч
    await ReportService.mark_false_report(db_session, rep1.id, warden)
    assert citizen.false_reports_count == 1

    rep2 = await ReportService.create_report(
        session=db_session, reporter=citizen, violator=violator, incident_topic_id=101,
        incident_topic_name="Общий чат", message_id=556, message_text="test", reason="false"
    )
    await ReportService.mark_false_report(db_session, rep2.id, warden)
    assert citizen.false_reports_count == 2

    rep3 = await ReportService.create_report(
        session=db_session, reporter=citizen, violator=violator, incident_topic_id=101,
        incident_topic_name="Общий чат", message_id=557, message_text="test", reason="false"
    )
    _, is_blocked = await ReportService.mark_false_report(db_session, rep3.id, warden)
    assert is_blocked is True
    assert citizen.reports_blocked_until is not None

    # Попытка создать 4-й репорт вызывает исключение
    with pytest.raises(TownBaseException, match="заблокирована"):
        await ReportService.create_report(
            session=db_session, reporter=citizen, violator=violator, incident_topic_id=101,
            incident_topic_name="Общий чат", message_id=558, message_text="test", reason="blocked"
        )


@pytest.mark.asyncio
async def test_ticket_lifecycle_and_merits(db_session: AsyncSession, gov_users):
    """Проверка полного жизненного цикла тикета и начисления заслуг персоналу."""
    citizen = gov_users["citizen"]
    helper = gov_users["helper"]
    judge = gov_users["judge"]

    # 1. Создание тикета
    ticket = await TicketService.create_ticket(
        session=db_session,
        creator=citizen,
        category=TicketCategory.GENERAL.value,
        initial_text="Как получить участок в городе?",
    )
    assert ticket.status == TicketStatus.OPEN.value
    assert ticket.target_role == "Помощник"

    # 2. Привязка ветки форума
    await TicketService.bind_forum_topic(db_session, ticket.id, thread_id=777)
    found_by_thread = await TicketService.get_ticket_by_thread(db_session, thread_id=777)
    assert found_by_thread.id == ticket.id

    # 3. Помощник берет в работу
    await TicketService.claim_ticket(db_session, ticket.id, helper)
    assert ticket.status == TicketStatus.IN_PROGRESS.value
    assert ticket.claimed_by_id == helper.id

    # 4. Перенаправление в Суд
    await TicketService.transfer_ticket(db_session, ticket.id, "Судья", helper)
    assert ticket.target_role == "Судья"
    assert ticket.status == TicketStatus.OPEN.value
    assert ticket.claimed_by_id is None

    # 5. Судья закрывает обращение
    initial_merits = judge.closed_tickets_count or 0
    await TicketService.close_ticket(
        session=db_session, ticket_id=ticket.id, staff_user=judge, verdict="Консультация оказана"
    )
    assert ticket.status == TicketStatus.CLOSED.value
    assert ticket.verdict == "Консультация оказана"
    assert judge.closed_tickets_count == initial_merits + 1


@pytest.mark.asyncio
async def test_warns_progression_and_bans(db_session: AsyncSession, gov_users):
    """Проверка эскалации варнов: 3 варна -> авто-мут 24ч, 5 варнов -> авто-бан."""
    citizen = gov_users["citizen"]
    warden = gov_users["warden"]

    mock_bot = MagicMock()
    mock_bot.restrict_chat_member = AsyncMock()
    mock_bot.ban_chat_member = AsyncMock()

    # Варн 1
    w1, muted, banned, _, _ = await ModerationService.apply_warn(
        db_session, bot=mock_bot, chat_id=-100, issuer=warden, target=citizen, reason="Флуд 1"
    )
    assert w1 == 1 and not muted and not banned

    # Варн 2
    w2, muted, banned, _, _ = await ModerationService.apply_warn(
        db_session, bot=mock_bot, chat_id=-100, issuer=warden, target=citizen, reason="Флуд 2"
    )
    assert w2 == 2 and not muted and not banned

    # Варн 3 -> Авто-мут 24ч
    w3, muted, banned, extra, _ = await ModerationService.apply_warn(
        db_session, bot=mock_bot, chat_id=-100, issuer=warden, target=citizen, reason="Флуд 3"
    )
    assert w3 == 3 and muted is True and banned is False
    assert "автоматический мут" in extra.lower()

    # Варн 4
    w4, muted, banned, _, _ = await ModerationService.apply_warn(
        db_session, bot=mock_bot, chat_id=-100, issuer=warden, target=citizen, reason="Флуд 4"
    )
    assert w4 == 4 and not muted and not banned

    # Варн 5 -> Авто-бан (изгнание)
    w5, muted, banned, extra, _ = await ModerationService.apply_warn(
        db_session, bot=mock_bot, chat_id=-100, issuer=warden, target=citizen, reason="Флуд 5"
    )
    assert w5 == 5 and banned is True
    assert citizen.is_enemy is True
    assert "изгнан" in extra.lower()

    # Снятие варна
    new_count, _ = await ModerationService.remove_warn(
        session=db_session, issuer=warden, target=citizen, reason="Смягчение"
    )
    assert new_count == 4


@pytest.mark.asyncio
async def test_duration_parsing_and_mute_limits(db_session: AsyncSession, gov_users):
    """Проверка парсинга сроков и лимитов длительности мута по рангам."""
    assert parse_duration("15m") == 900
    assert parse_duration("1h") == 3600
    assert parse_duration("2d") == 172800
    assert parse_duration("30s") == 30
    assert parse_duration("24ч") == 86400

    helper = gov_users["helper"]
    warden = gov_users["warden"]
    citizen = gov_users["citizen"]

    # Помощник: лимит 2ч (7200 сек). Запрос 3ч (10800) должен быть отклонен
    with pytest.raises(TownBaseException, match="максимум на 2 ч"):
        await ModerationService.apply_mute(
            session=db_session,
            bot=None,
            chat_id=-100,
            issuer=helper,
            target=citizen,
            duration_seconds=10800,
            reason="Превышение лимита помощника",
        )

    # Блюститель: не может банить без санкции
    with pytest.raises(TownBaseException, match="Блюстители не могут банить"):
        await ModerationService.apply_ban(
            session=db_session,
            bot=None,
            chat_id=-100,
            issuer=warden,
            target=citizen,
            reason="Самоуправный бан",
        )


@pytest.mark.asyncio
async def test_confidential_report_staff_visibility(db_session: AsyncSession, gov_users):
    """Проверка, что в список получателей жалоб попадают ТОЛЬКО должности от Блюстителя и выше."""
    from sqlalchemy import select
    from config import settings

    staff_query = select(User).where(
        (User.role_level >= PositionLevel.CHAT_WARDEN.value) |
        (User.telegram_id == settings.OWNER_ID)
    )
    recipients = (await db_session.scalars(staff_query)).all()
    recipient_titles = {u.custom_title or u.position_title for u in recipients}

    # Должны входить: Блюститель, Судья, Министр, Вице-мэр, Конституционный судья, Премьер, Мэр
    assert "Блюститель" in recipient_titles
    assert "Судья" in recipient_titles
    assert "Министр" in recipient_titles
    assert "Мэр" in recipient_titles

    # НЕ должны входить: Гражданин, Помощник
    assert "Гражданин" not in recipient_titles
    assert "Помощник" not in recipient_titles


@pytest.mark.asyncio
async def test_owner_rank_5_and_seniority(db_session: AsyncSession, gov_users):
    """Проверка, что Владелец города имеет Ранг 5 и превосходит Мэра (Ранг 4)."""
    from config import settings

    owner = User(
        telegram_id=settings.OWNER_ID,
        username=settings.OWNER_USERNAME,
        full_name="Создатель Ратуши",
        role_level=PositionLevel.OWNER.value,
    )
    db_session.add(owner)
    await db_session.commit()

    assert owner.government_rank == 5
    assert owner.position_title == "Высшая администрация"
    assert HierarchyService.is_owner(owner) is True

    # Старшинство над Мэром
    mayor = gov_users["mayor"]
    assert mayor.government_rank == 4
    # Владелец может наказывать мэра
    HierarchyService.validate_seniority(owner, mayor, "наказание")

    # Мэр НЕ может наказывать Владельца
    with pytest.raises(TownBaseException, match="Овнер города обладает абсолютным иммунитетом"):
        HierarchyService.validate_seniority(mayor, owner, "наказание")


@pytest.mark.asyncio
async def test_report_without_reply_handler(db_session: AsyncSession, gov_users):
    """Проверка подачи жалобы без ответа на сообщение: /report @username [причина]."""
    from bot.handlers.reports import cmd_report
    from db.models.chat_settings import ChatSettings

    citizen = gov_users["citizen"]
    warden = gov_users["warden"]

    chat_settings = ChatSettings(chat_id=-100123, reports_destination="both")
    db_session.add(chat_settings)
    await db_session.commit()

    # Имитируем сообщение /report @warden_sasha Оскорбления в чате
    mock_msg = MagicMock()
    mock_msg.chat.id = -100123
    mock_msg.text = "/report @warden_sasha Оскорбления в чате"
    mock_msg.reply_to_message = None
    mock_msg.message_thread_id = 999
    mock_msg.delete = AsyncMock()
    mock_msg.answer = AsyncMock(return_value=MagicMock(message_id=555))
    mock_msg.bot = MagicMock()
    mock_msg.bot.send_message = AsyncMock(return_value=MagicMock(message_id=777))
    mock_msg.entities = None

    await cmd_report(message=mock_msg, session=db_session, db_user=citizen)

    # Проверяем, что исходная команда удалена
    mock_msg.delete.assert_called_once()

    # Проверяем, что репорт создан в БД
    rep_query = select(Report).where(Report.violator_id == warden.id)
    created_rep = await db_session.scalar(rep_query)
    assert created_rep is not None
    assert created_rep.reason == "Оскорбления в чате"
    assert created_rep.reporter_id == citizen.id
    assert created_rep.message_id is None
    assert "вне контекста" in created_rep.message_text


@pytest.mark.asyncio
async def test_report_settings_and_anonymity_toggle(db_session: AsyncSession, gov_users):
    """Проверка работы меню настроек жалоб и переключения анонимности/маршрутизации."""
    from bot.handlers.reports import cmd_report_settings, cb_report_settings
    from db.models.chat_settings import ChatSettings

    mayor = gov_users["mayor"]
    chat_settings = ChatSettings(chat_id=-100999, reports_destination="both", reports_anonymous=False)
    db_session.add(chat_settings)
    await db_session.commit()

    # 1. Открытие /report_settings Мэром
    mock_msg = MagicMock()
    mock_msg.chat.id = -100999
    mock_msg.chat.type = "supergroup"
    mock_msg.from_user.id = mayor.telegram_id
    mock_msg.answer = AsyncMock()

    await cmd_report_settings(message=mock_msg, session=db_session, db_user=mayor)
    mock_msg.answer.assert_called_once()
    assert "НАСТРОЙКИ СИСТЕМЫ ЖАЛОБ" in mock_msg.answer.call_args[0][0]

    # 2. Callback переключения анонимности
    mock_cb = MagicMock()
    mock_cb.data = "rep_set:toggle_anon"
    mock_cb.message.chat.id = -100999
    mock_cb.message.message_thread_id = 12
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.answer = AsyncMock()

    await cb_report_settings(callback=mock_cb, session=db_session, db_user=mayor)
    await db_session.refresh(chat_settings)
    assert chat_settings.reports_anonymous is True

    # 3. Callback переключения маршрутизации на "topic"
    mock_cb.data = "rep_set:dest:topic"
    await cb_report_settings(callback=mock_cb, session=db_session, db_user=mayor)
    await db_session.refresh(chat_settings)
    assert chat_settings.reports_destination == "topic"


@pytest.mark.asyncio
async def test_report_delivery_fallback_when_pm_fails(db_session: AsyncSession, gov_users):
    """Проверка гарантированной доставки: если ЛС админов недоступны, жалоба падает в топик/чат."""
    from bot.handlers.reports import cmd_report
    from db.models.chat_settings import ChatSettings

    citizen = gov_users["citizen"]
    warden = gov_users["warden"]

    chat_settings = ChatSettings(chat_id=-100888, reports_destination="pm")
    db_session.add(chat_settings)
    await db_session.commit()

    mock_msg = MagicMock()
    mock_msg.chat.id = -100888
    mock_msg.text = "/report @warden_sasha Спам"
    mock_msg.reply_to_message = None
    mock_msg.message_thread_id = 42
    mock_msg.delete = AsyncMock()
    mock_msg.answer = AsyncMock(return_value=MagicMock(message_id=111))
    mock_msg.entities = None

    # Имитируем ошибку отправки в ЛС (Forbidden: bot can't initiate conversation)
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=[Exception("TelegramForbiddenError"), MagicMock(message_id=888)])
    mock_msg.bot = mock_bot

    await cmd_report(message=mock_msg, session=db_session, db_user=citizen)

    # Проверяем, что fallback вызвал отправку в топик/чат
    assert mock_bot.send_message.call_count >= 2
    last_call = mock_bot.send_message.call_args_list[-1]
    assert "ЖАЛОБА #" in last_call.kwargs.get("text", "")


@pytest.mark.asyncio
async def test_cmd_punish_flexible(db_session: AsyncSession, gov_users):
    """Проверка работы обновленной команды /наказать с кастомным сроком и статьей."""
    from bot.handlers.justice import cmd_punish

    mayor = gov_users["mayor"]
    citizen = gov_users["citizen"]

    mock_msg = MagicMock()
    mock_msg.chat.id = -100555
    mock_msg.text = "/наказать @citizen_vasya 1h Нарушение порядка"
    mock_msg.reply_to_message = None
    mock_msg.message_thread_id = None
    mock_msg.chat.restrict = AsyncMock()
    mock_msg.answer = AsyncMock()
    mock_msg.bot = MagicMock()
    mock_msg.bot.send_message = AsyncMock()

    await cmd_punish(message=mock_msg, session=db_session, db_user=mayor)
    mock_msg.answer.assert_called_once()
    assert "СУДЕБНЫЙ ПРИГОВОР ВСТУПИЛ В СИЛУ" in mock_msg.answer.call_args[0][0]
    assert citizen.warns_count >= 1


@pytest.mark.asyncio
async def test_cmd_appeal_and_verdict(db_session: AsyncSession, gov_users):
    """Проверка подачи судебной апелляции и вынесения вердикта."""
    from bot.handlers.court import cmd_appeal, cb_court_verdict

    citizen = gov_users["citizen"]
    judge = gov_users["judge"]

    # 1. Гражданин подает /appeal
    mock_msg = MagicMock()
    mock_msg.chat.id = -100444
    mock_msg.chat.type = "supergroup"
    mock_msg.text = "/appeal Был наказан по ошибке, прошу разобраться"
    mock_msg.message_thread_id = 15
    mock_msg.answer = AsyncMock()
    mock_msg.bot = MagicMock()
    mock_msg.bot.send_message = AsyncMock()

    await cmd_appeal(message=mock_msg, session=db_session, db_user=citizen)
    mock_msg.answer.assert_called_once()
    assert "СУДЕБНАЯ АПЕЛЛЯЦИЯ" in mock_msg.answer.call_args[0][0]

    # Находим созданный тикет
    t_query = select(Ticket).where(Ticket.creator_id == citizen.id)
    ticket = await db_session.scalar(t_query)
    assert ticket is not None

    # 2. Судья оправдывает по кнопке
    mock_cb = MagicMock()
    mock_cb.data = f"court_verdict:{ticket.id}:pardon"
    mock_cb.message.chat.id = -100444
    mock_cb.message.html_text = "Карточка апелляции"
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.answer = AsyncMock()
    mock_cb.bot = MagicMock()
    mock_cb.bot.send_message = AsyncMock()

    await cb_court_verdict(callback=mock_cb, session=db_session, db_user=judge)
    await db_session.refresh(ticket)
    assert ticket.status == TicketStatus.CLOSED.value
    assert "Оправдан" in ticket.verdict


@pytest.mark.asyncio
async def test_user_sync_middleware_for_callback_query(db_session: AsyncSession):
    """Проверка, что UserSyncMiddleware обрабатывает CallbackQuery и инжектирует db_user."""
    from bot.middlewares.user_sync import UserSyncMiddleware
    from aiogram.types import CallbackQuery, User as TgUser

    middleware = UserSyncMiddleware()
    tg_user = TgUser(id=999888777, is_bot=False, first_name="Test", username="callback_tester")
    mock_cb = MagicMock(spec=CallbackQuery)
    mock_cb.from_user = tg_user

    data = {"session": db_session, "event_from_user": tg_user}
    called = False

    async def dummy_handler(event, handler_data):
        nonlocal called
        called = True
        assert "db_user" in handler_data
        assert handler_data["db_user"].telegram_id == 999888777
        return "success"

    res = await middleware(dummy_handler, mock_cb, data)
    assert called is True
    assert res == "success"


@pytest.mark.asyncio
async def test_cb_report_settings_in_pm_and_close(db_session: AsyncSession, gov_users):
    """Проверка работы меню настроек жалоб при кликах в ЛС и корректного закрытия."""
    from bot.handlers.reports import cb_report_settings
    from db.models.chat_settings import ChatSettings

    mayor = gov_users["mayor"]
    chat_settings = ChatSettings(chat_id=-100111222, reports_destination="both", reports_anonymous=False)
    db_session.add(chat_settings)
    await db_session.commit()

    # Клик в ЛС (chat.type == 'private')
    mock_cb = MagicMock()
    mock_cb.data = "rep_set:dest:pm"
    mock_cb.message.chat.id = mayor.telegram_id
    mock_cb.message.chat.type = "private"
    mock_cb.from_user.id = mayor.telegram_id
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.answer = AsyncMock()

    await cb_report_settings(callback=mock_cb, session=db_session, db_user=mayor)
    await db_session.refresh(chat_settings)
    assert chat_settings.reports_destination == "pm"
    mock_cb.answer.assert_called_once()

    # Закрытие настроек
    mock_cb.reset_mock()
    mock_cb.data = "rep_set:close"
    mock_cb.message.delete = AsyncMock()
    await cb_report_settings(callback=mock_cb, session=db_session, db_user=mayor)
    mock_cb.answer.assert_called_once()
    mock_cb.message.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cb_court_verdict_pardon_lifts_mute_and_unbans(db_session: AsyncSession, gov_users):
    """Проверка, что судебное оправдание снимает и статус врага (бан), и мут в Telegram."""
    from bot.handlers.court import cb_court_verdict
    from core.ticket_service import TicketService
    from core.enums import TicketCategory

    judge = gov_users["judge"]
    citizen = gov_users["citizen"]
    citizen.is_enemy = True
    citizen.warns_count = 5
    await db_session.commit()

    ticket = await TicketService.create_ticket(
        session=db_session,
        creator=citizen,
        category=TicketCategory.COURT.value,
        initial_text="Прошу снять бан и мут",
    )

    mock_cb = MagicMock()
    mock_cb.data = f"court_verdict:{ticket.id}:pardon"
    mock_cb.message.chat.id = -100333
    mock_cb.message.chat.type = "supergroup"
    mock_cb.from_user.id = judge.telegram_id
    mock_cb.message.html_text = "Дело #{ticket.id}"
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.answer = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.unban_chat_member = AsyncMock()
    mock_bot.restrict_chat_member = AsyncMock()
    mock_bot.send_message = AsyncMock()
    mock_cb.bot = mock_bot

    await cb_court_verdict(callback=mock_cb, session=db_session, db_user=judge)
    await db_session.refresh(citizen)
    await db_session.refresh(ticket)

    assert citizen.is_enemy is False
    assert citizen.warns_count == 0
    assert ticket.status == TicketStatus.CLOSED.value
    mock_bot.unban_chat_member.assert_called_once()
    mock_bot.restrict_chat_member.assert_called()
    mock_cb.answer.assert_called_once_with("Вердикт успешно вынесен!")


@pytest.mark.asyncio
async def test_cmd_amnesty_in_pm_unmutes_in_supergroup(db_session: AsyncSession, gov_users):
    """Проверка, что /амнистия, вызванная в ЛС бота, снимает мут и бан в целевой супергруппе."""
    from bot.handlers.justice import cmd_amnesty
    from db.models.chat_settings import ChatSettings

    mayor = gov_users["mayor"]
    citizen = gov_users["citizen"]
    citizen.warns_count = 3
    citizen.is_wanted = True
    chat_settings = ChatSettings(chat_id=-100987654)
    db_session.add(chat_settings)
    await db_session.commit()

    mock_msg = MagicMock()
    mock_msg.chat.id = mayor.telegram_id
    mock_msg.chat.type = "private"
    mock_msg.from_user.id = mayor.telegram_id
    mock_msg.text = f"/амнистия @{citizen.username} Личное помилование Мэра"
    mock_msg.reply_to_message = None
    mock_msg.answer = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.restrict_chat_member = AsyncMock()
    mock_bot.unban_chat_member = AsyncMock()
    mock_msg.bot = mock_bot

    await cmd_amnesty(message=mock_msg, session=db_session, db_user=mayor)
    await db_session.refresh(citizen)

    assert citizen.warns_count == 0
    assert citizen.is_wanted is False
    mock_msg.answer.assert_called_once()
    assert "АКТ ГОРОДСКОЙ АМНИСТИИ" in mock_msg.answer.call_args[0][0]
    # Должен быть вызван restrict_chat_member для супергруппы (-100987654)
    mock_bot.restrict_chat_member.assert_called_once()
    call_kwargs = mock_bot.restrict_chat_member.call_args.kwargs
    assert call_kwargs["chat_id"] == -100987654
    assert call_kwargs["user_id"] == citizen.telegram_id


@pytest.mark.asyncio
async def test_cmd_unmute_in_general_chat(db_session: AsyncSession, gov_users):
    """Проверка работы /unmute в общем чате без юрисдикционной блокировки."""
    from bot.handlers.moderation import cmd_unmute

    warden = gov_users["warden"]
    citizen = gov_users["citizen"]

    mock_msg = MagicMock()
    mock_msg.chat.id = -100555
    mock_msg.chat.type = "supergroup"
    mock_msg.message_thread_id = None
    mock_msg.text = f"/unmute @{citizen.username} Осознал вину"
    mock_msg.reply_to_message = None
    mock_msg.answer = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.restrict_chat_member = AsyncMock()
    mock_bot.send_message = AsyncMock()
    mock_msg.bot = mock_bot

    await cmd_unmute(message=mock_msg, session=db_session, db_user=warden)
    mock_msg.answer.assert_called_once()
    assert "ПРАВА ПЕРЕПИСКИ ВОССТАНОВЛЕНЫ (РАЗМУТ)" in mock_msg.answer.call_args[0][0]
    mock_bot.restrict_chat_member.assert_called()


