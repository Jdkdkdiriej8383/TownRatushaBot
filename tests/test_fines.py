import pytest
from datetime import datetime, timedelta, timezone
from core.fine_service import FineService
from core.enums import FineStatus


@pytest.mark.asyncio
async def test_fine_lifecycle_and_48h_overdue(db_session, sample_users):
    """
    Тест жизненного цикла штрафа:
    1. Выписка тикета на 48 часов.
    2. Просрочка >48ч -> авто-удвоение (x2), статус 'overdue' и розыск (is_wanted=True).
    3. Оплата штрафа -> статус 'paid', снятие статуса розыска.
    """
    citizen = sample_users["citizen"]
    chat_warden = sample_users["chat_warden"]

    # 1. Выставляем штраф на 15 000 валюты
    fine = await FineService.create_fine(
        session=db_session,
        target_user=citizen,
        issuer_user=chat_warden,
        law_article="2.1",
        amount=15000,
        reason="Оскорбление жителей в чате"
    )

    assert fine.id is not None
    assert fine.amount == 15000
    assert fine.status == FineStatus.ACTIVE.value
    assert fine.is_doubled is False
    assert citizen.is_wanted is False

    # 2. Имитируем истечение 48 часов
    fine.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()

    # Запускаем фоновый обработчик просрочек
    overdue_list = await FineService.process_overdue_fines(db_session)
    assert len(overdue_list) == 1

    processed_fine, updated_user = overdue_list[0]
    assert processed_fine.id == fine.id
    assert processed_fine.status == FineStatus.OVERDUE.value
    assert processed_fine.amount == 30000  # 15000 * 2 = 30000 (x2)
    assert processed_fine.is_doubled is True
    assert updated_user.is_wanted is True  # Гражданин объявлен в розыск!

    # 3. Гражданин оплачивает удвоенный штраф
    paid_fine = await FineService.pay_fine(db_session, fine.id)
    assert paid_fine.status == FineStatus.PAID.value
    assert paid_fine.paid_at is not None
    assert citizen.is_wanted is False  # Розыск снят после оплаты
