import pytest
from core.laws_service import LawService
from core.enums import LawSection, PunishmentType
from core.exceptions import LawNotFoundError


@pytest.mark.asyncio
async def test_laws_registry_and_sections(db_session):
    """Проверка доступности разделов и статей Городского Свода Законов."""
    laws = await LawService.get_all_laws(db_session)
    assert len(laws) >= 15

    # Проверка статьи 1.1 (Раздел I)
    law_1_1 = await LawService.get_law(db_session, "1.1")
    assert law_1_1.article_number == "1.1"
    assert law_1_1.section == LawSection.SECTION_1.value

    # Проверка статьи 2.1 (Раздел II. Чат)
    law_2_1 = await LawService.get_law(db_session, "2.1")
    assert law_2_1.article_number == "2.1"
    assert law_2_1.section == LawSection.SECTION_2.value

    # Проверка статьи 3.12 (Раздел III. Регламент уплаты штрафов 48ч)
    law_3_12 = await LawService.get_law(db_session, "3.12")
    assert law_3_12.article_number == "3.12"

    # Несуществующая статья
    with pytest.raises(LawNotFoundError):
        await LawService.get_law(db_session, "99.99")


@pytest.mark.asyncio
async def test_update_law_text(db_session, sample_users):
    """Тест обновления текста статьи закона."""
    admin = sample_users["admin"]
    new_desc = "Категорически запрещен любой капс свыше 50% и флуд смайлами."

    updated_law = await LawService.update_law_text(
        session=db_session,
        article_number="2.2",
        new_description=new_desc,
        editor=admin
    )

    assert updated_law.article_number == "2.2"
    assert updated_law.description == new_desc
    assert updated_law.last_edited_by_tg_id == admin.telegram_id


@pytest.mark.asyncio
async def test_log_punishment(db_session, sample_users):
    """Тест фиксации в протоколе городского суда."""
    citizen = sample_users["citizen"]
    assistant = sample_users["assistant"]

    punishment = await LawService.log_punishment(
        session=db_session,
        target_user=citizen,
        issuer_user=assistant,
        punishment_type=PunishmentType.MUTE,
        law_article="2.3",
        duration_seconds=3600,
        reason="Медиа-спам в чате"
    )

    assert punishment.id is not None
    assert punishment.target_telegram_id == citizen.telegram_id
    assert punishment.issuer_telegram_id == assistant.telegram_id
    assert punishment.punishment_type == PunishmentType.MUTE.value
