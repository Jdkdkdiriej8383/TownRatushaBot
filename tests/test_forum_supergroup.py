import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
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
