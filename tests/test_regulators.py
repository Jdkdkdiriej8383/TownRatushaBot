import pytest
from db.models import User
from core.regulators import RegulatorService
from core.enums import PositionLevel
from core.exceptions import (
    SubordinationViolationError,
    RegulatorLimitExceededError,
    SelfPunishmentError,
    EnemyOfTownError,
)
from config import settings


@pytest.mark.asyncio
async def test_subordination_hierarchy(db_session, sample_users):
    """Тест субординации: наказывать можно ТОЛЬКО тех, кто строго ниже по должности."""
    assistant = sample_users["assistant"]      # Уровень 1
    citizen = sample_users["citizen"]          # Уровень 0
    chat_warden = sample_users["chat_warden"]  # Уровень 2

    # 1. Помощник (1) наказывать Гражданина (0) - РАЗРЕШЕНО
    RegulatorService.check_subordination(issuer=assistant, target=citizen)

    # 2. Помощник (1) наказывать Блюстителя чата (2) - ЗАПРЕЩЕНО
    with pytest.raises(SubordinationViolationError):
        RegulatorService.check_subordination(issuer=assistant, target=chat_warden)

    # 3. Наказывать равного по должности - ЗАПРЕЩЕНО
    assistant_2 = User(
        telegram_id=9999,
        username="another_assistant",
        full_name="Второй Помощник",
        role_level=PositionLevel.ASSISTANT.value,
    )
    with pytest.raises(SubordinationViolationError):
        RegulatorService.check_subordination(issuer=assistant, target=assistant_2)


@pytest.mark.asyncio
async def test_self_punishment_forbidden(sample_users):
    """Блюститель не может наказывать самого себя."""
    admin = sample_users["admin"]
    with pytest.raises(SelfPunishmentError):
        RegulatorService.check_subordination(issuer=admin, target=admin)


@pytest.mark.asyncio
async def test_mute_regulator_limits(db_session, sample_users):
    """
    Проверка регулятора лимитов мута:
    Помощник (уровень 1) имеет лимит 7200 сек (2 часа).
    """
    assistant = sample_users["assistant"]
    citizen = sample_users["citizen"]

    # В пределах 2 часов (7200 сек) - успешно
    reg = await RegulatorService.validate_mute(db_session, assistant, citizen, duration_seconds=7200)
    assert reg.role_level == PositionLevel.ASSISTANT.value

    # Свыше 2 часов (7201 сек) - исключение
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_mute(db_session, assistant, citizen, duration_seconds=7201)


@pytest.mark.asyncio
async def test_fine_regulator_limits(db_session, sample_users):
    """
    Проверка регулятора штрафов:
    Блюститель чата (уровень 2) может штрафовать до 50 000 и ТОЛЬКО по разделу II.
    """
    chat_warden = sample_users["chat_warden"]
    citizen = sample_users["citizen"]

    # В пределах 50 000 по разделу II - успешно
    await RegulatorService.validate_fine(
        db_session, chat_warden, citizen, amount=50000, is_chat_section=True
    )

    # Превышение суммы штрафа (50 001) - ошибка
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_fine(
            db_session, chat_warden, citizen, amount=50001, is_chat_section=True
        )

    # Попытка выписать штраф вне Раздела II (чат) - ошибка
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_fine(
            db_session, chat_warden, citizen, amount=10000, is_chat_section=False
        )


@pytest.mark.asyncio
async def test_ban_rights(db_session, sample_users):
    """
    Проверка права на изгнание (бан):
    Помощник и Блюститель чата не имеют права бана (can_ban=False).
    Старший блюститель (уровень 3) имеет право бана.
    """
    assistant = sample_users["assistant"]
    chat_warden = sample_users["chat_warden"]
    senior_warden = sample_users["senior_warden"]
    citizen = sample_users["citizen"]

    # Помощник пытается забанить -> отказ
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_ban(db_session, assistant, citizen)

    # Блюститель чата пытается забанить -> отказ
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_ban(db_session, chat_warden, citizen)

    # Старший блюститель банит гражданина -> успешно
    reg = await RegulatorService.validate_ban(db_session, senior_warden, citizen, duration_seconds=86400)
    assert reg.can_ban is True


@pytest.mark.asyncio
async def test_edit_laws_rights(db_session, sample_users):
    """
    Право на изменение статей Закона имеют Администрация (4), Высшая администрация (5) и Владелец.
    """
    senior_warden = sample_users["senior_warden"]
    admin = sample_users["admin"]
    senior_admin = sample_users["senior_admin"]

    # Старший блюститель (3) пытается редактировать -> отказ
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_edit_laws(db_session, senior_warden)

    # Администрация (4) -> разрешено
    reg4 = await RegulatorService.validate_edit_laws(db_session, admin)
    assert reg4.can_edit_laws is True

    # Высшая администрация (5) -> разрешено
    reg5 = await RegulatorService.validate_edit_laws(db_session, senior_admin)
    assert reg5.can_edit_laws is True

    # Владелец города (DivniDed / OWNER_ID) -> разрешено
    owner_user = User(
        telegram_id=settings.OWNER_ID,
        username=settings.OWNER_USERNAME,
        full_name="Основатель",
        role_level=0,
    )
    reg_owner = await RegulatorService.validate_edit_laws(db_session, owner_user)
    assert reg_owner.can_edit_laws is True


@pytest.mark.asyncio
async def test_appointment_limits(db_session, sample_users):
    """
    Проверка прав назначения должностей:
    Старший блюститель (can_appoint_level=1) может назначить Помощника (1),
    но не может назначить Блюстителя чата (2).
    """
    senior_warden = sample_users["senior_warden"]
    citizen = sample_users["citizen"]

    # Назначение на Помощника (1) - разрешено
    await RegulatorService.validate_appointment(
        db_session, issuer=senior_warden, target=citizen, new_level=1
    )

    # Назначение на Блюстителя чата (2) - отказ (выше лимита назначения)
    with pytest.raises(RegulatorLimitExceededError):
        await RegulatorService.validate_appointment(
            db_session, issuer=senior_warden, target=citizen, new_level=2
        )


@pytest.mark.asyncio
async def test_enemy_of_town_rights(db_session, sample_users):
    """Враг города поражен во всех правах."""
    enemy = sample_users["enemy"]
    citizen = sample_users["citizen"]

    with pytest.raises(EnemyOfTownError):
        RegulatorService.check_subordination(issuer=enemy, target=citizen)
