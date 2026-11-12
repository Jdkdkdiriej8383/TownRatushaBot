import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, ChatSettings, Auction, Fine
from core.enums import PositionLevel, GovernmentRole, AuctionStatus, FineStatus
from core.auction_service import AuctionService
from core.fine_service import FineService
from bot.handlers.treasury import cmd_treasury, cmd_balance, cmd_salary, cmd_transfer_money
from bot.handlers.auction import cmd_list_auctions, cmd_auction_router, cb_auction_bid, cb_auction_refresh, cb_auction_close


@pytest.mark.asyncio
async def test_cmd_treasury_and_balance(db_session: AsyncSession):
    """Тест команд /казна и /баланс."""
    owner = User(
        telegram_id=1965081517,
        username="DivniDed",
        full_name="Мэр Города",
        role_level=PositionLevel.OWNER.value,
        custom_title="Мэр",
        balance=15000,
    )
    db_session.add(owner)

    chat_settings = ChatSettings(
        chat_id=-100555,
        treasury_balance=250000,
        total_fines_collected=50000,
        total_salaries_paid=30000,
    )
    db_session.add(chat_settings)
    await db_session.commit()

    # 1. Проверяем /казна
    msg_treasury = MagicMock()
    msg_treasury.chat.id = -100555
    msg_treasury.chat.type = "supergroup"
    msg_treasury.from_user.id = owner.telegram_id
    msg_treasury.text = "/казна"
    msg_treasury.reply = AsyncMock()

    await cmd_treasury(message=msg_treasury, session=db_session, db_user=owner)
    msg_treasury.reply.assert_called_once()
    reply_text = msg_treasury.reply.call_args[0][0]
    assert "250,000" in reply_text
    assert "50,000" in reply_text
    assert "30,000" in reply_text
    assert "ГОСУДАРСТВЕННАЯ КАЗНА ГОРОДА" in reply_text

    # 2. Проверяем /баланс своего счета
    msg_balance = MagicMock()
    msg_balance.chat.id = -100555
    msg_balance.chat.type = "supergroup"
    msg_balance.from_user.id = owner.telegram_id
    msg_balance.reply_to_message = None
    msg_balance.entities = []
    msg_balance.text = "/баланс"
    msg_balance.reply = AsyncMock()

    await cmd_balance(message=msg_balance, session=db_session, db_user=owner)
    msg_balance.reply.assert_called_once()
    bal_text = msg_balance.reply.call_args[0][0]
    assert "15,000" in bal_text
    assert "Мэр Города" in bal_text


@pytest.mark.asyncio
async def test_cmd_salary_and_transfer(db_session: AsyncSession):
    """Тест выплаты жалования /зарплата из казны и перевода /перевод между гражданами."""
    admin = User(
        telegram_id=111111,
        username="MayorAdmin",
        full_name="Премьер-министр",
        role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
        custom_title="Премьер-министр",
        balance=10000,
    )
    worker = User(
        telegram_id=222222,
        username="GoodWorker",
        full_name="Блюститель Боб",
        role_level=PositionLevel.CHAT_WARDEN.value,
        custom_title="Блюститель",
        balance=2000,
    )
    citizen = User(
        telegram_id=333333,
        username="SimpleCitizen",
        full_name="Житель Джон",
        role_level=PositionLevel.CITIZEN.value,
        balance=1000,
    )
    db_session.add_all([admin, worker, citizen])

    chat_settings = ChatSettings(
        chat_id=-100777,
        treasury_balance=100000,
        total_salaries_paid=0,
    )
    db_session.add(chat_settings)
    await db_session.commit()

    # 1. Выплата зарплаты сотруднику из казны: /зарплата @GoodWorker 15000 За дежурство
    msg_salary = MagicMock()
    msg_salary.chat.id = -100777
    msg_salary.chat.type = "supergroup"
    msg_salary.from_user.id = admin.telegram_id
    msg_salary.reply_to_message = None
    msg_salary.entities = []
    msg_salary.text = "/зарплата @GoodWorker 15000 За безупречное ночное дежурство"
    msg_salary.reply = AsyncMock()
    msg_salary.bot = MagicMock()
    msg_salary.bot.send_message = AsyncMock()

    await cmd_salary(message=msg_salary, session=db_session, db_user=admin)
    msg_salary.reply.assert_called_once()
    salary_reply = msg_salary.reply.call_args[0][0]
    assert "УКАЗ О ПРЕМИРОВАНИИ" in salary_reply
    assert "+15,000" in salary_reply

    # Проверяем изменения в БД:
    await db_session.refresh(chat_settings)
    await db_session.refresh(worker)
    assert chat_settings.treasury_balance == 85000  # 100 000 - 15 000
    assert chat_settings.total_salaries_paid == 15000
    assert worker.balance == 17000  # 2 000 + 15 000

    # 2. Перевод между жителями: worker переводит 5000 citizen
    msg_transfer = MagicMock()
    msg_transfer.chat.id = -100777
    msg_transfer.chat.type = "supergroup"
    msg_transfer.from_user.id = worker.telegram_id
    msg_transfer.reply_to_message = None
    msg_transfer.entities = []
    msg_transfer.text = "/перевод @SimpleCitizen 5000 Возврат долга за кирку"
    msg_transfer.reply = AsyncMock()
    msg_transfer.bot = MagicMock()
    msg_transfer.bot.send_message = AsyncMock()

    await cmd_transfer_money(message=msg_transfer, session=db_session, db_user=worker)
    msg_transfer.reply.assert_called_once()
    transfer_reply = msg_transfer.reply.call_args[0][0]
    assert "ПЕРЕВОД УСПЕШНО ВЫПОЛНЕН" in transfer_reply
    assert "5,000" in transfer_reply

    await db_session.refresh(worker)
    await db_session.refresh(citizen)
    assert worker.balance == 12000  # 17 000 - 5 000
    assert citizen.balance == 6000   # 1 000 + 5 000


@pytest.mark.asyncio
async def test_fine_payment_deposits_to_treasury(db_session: AsyncSession):
    """Тест оплаты штрафа: списание средств у жителя и пополнение казны."""
    officer = User(
        telegram_id=444444,
        username="Officer",
        full_name="Офицер Смит",
        role_level=PositionLevel.CHAT_WARDEN.value,
    )
    violator = User(
        telegram_id=555555,
        username="Violator",
        full_name="Нарушитель Сэм",
        role_level=PositionLevel.CITIZEN.value,
        balance=25000,
    )
    db_session.add_all([officer, violator])

    chat_settings = ChatSettings(
        chat_id=-100888,
        treasury_balance=50000,
        total_fines_collected=0,
    )
    db_session.add(chat_settings)
    await db_session.commit()

    # Выписываем штраф
    fine = await FineService.create_fine(
        session=db_session,
        target_user=violator,
        issuer_user=officer,
        law_article="2.5",
        amount=10000,
        reason="Капс и спам",
    )
    assert fine.status == FineStatus.ACTIVE.value

    # Оплачиваем штраф через сервис с указанием чата
    paid_fine = await FineService.pay_fine(session=db_session, fine_id=fine.id, chat_id=-100888)
    assert paid_fine is not None
    assert paid_fine.status == FineStatus.PAID.value

    await db_session.refresh(violator)
    await db_session.refresh(chat_settings)
    assert violator.balance == 15000  # 25 000 - 10 000
    assert chat_settings.treasury_balance == 60000  # 50 000 + 10 000
    assert chat_settings.total_fines_collected == 10000


@pytest.mark.asyncio
async def test_auction_service_lifecycle(db_session: AsyncSession):
    """Тест сервиса аукционов: создание, ставки, анти-снайп и завершение торгов."""
    warden = User(
        telegram_id=666666,
        username="WardenTom",
        full_name="Блюститель Том",
        role_level=PositionLevel.CHAT_WARDEN.value,
    )
    bidder1 = User(
        telegram_id=777777,
        username="BidderAlice",
        full_name="Алиса",
        role_level=PositionLevel.CITIZEN.value,
        balance=50000,
    )
    bidder2 = User(
        telegram_id=888888,
        username="BidderBob",
        full_name="Боб",
        role_level=PositionLevel.CITIZEN.value,
        balance=40000,
    )
    db_session.add_all([warden, bidder1, bidder2])

    chat_settings = ChatSettings(
        chat_id=-100999,
        treasury_balance=100000,
        total_fines_collected=0,
    )
    db_session.add(chat_settings)
    await db_session.commit()

    # 1. Создание аукциона
    auction = await AuctionService.create_auction(
        session=db_session,
        chat_id=-100999,
        initiator=warden,
        title="Конфискованный Незеритовый Сет",
        start_price=10000,
        duration_minutes=30,
    )
    assert auction.id is not None
    assert auction.status == AuctionStatus.ACTIVE.value
    assert auction.current_price == 10000
    assert auction.bids_count == 0

    # 2. Ставка 1: Алиса повышает на 1000 -> 11000
    success, msg, auc = await AuctionService.place_bid(
        session=db_session,
        auction_id=auction.id,
        bidder=bidder1,
        increment=1000,
    )
    assert success is True
    assert auc.current_price == 11000
    assert auc.current_winner_id == bidder1.id
    assert auc.bids_count == 1

    # Алиса пробует перебить саму себя -> отказ
    success_self, msg_self, _ = await AuctionService.place_bid(
        session=db_session,
        auction_id=auction.id,
        bidder=bidder1,
        increment=1000,
    )
    assert success_self is False
    assert "уже удерживаете" in msg_self

    # 3. Ставка 2: Боб повышает на 5000 -> 16000
    # Проверим анти-снайпинг: ставим время до конца < 60 сек
    auc.end_time = datetime.now(timezone.utc) + timedelta(seconds=30)
    await db_session.commit()

    success_bob, msg_bob, auc = await AuctionService.place_bid(
        session=db_session,
        auction_id=auction.id,
        bidder=bidder2,
        increment=5000,
    )
    assert success_bob is True
    assert auc.current_price == 16000
    assert auc.current_winner_id == bidder2.id
    assert auc.bids_count == 2
    # Время должно быть продлено (анти-снайпинг > 60 секунд)
    now = datetime.now(timezone.utc)
    end_utc = AuctionService.to_utc(auc.end_time)
    assert (end_utc - now).total_seconds() > 60

    # 4. Завершение аукциона
    closed_auc = await AuctionService.finalize_auction(session=db_session, auction_id=auction.id)
    assert closed_auc.status == AuctionStatus.COMPLETED.value
    assert closed_auc.closed_at is not None

    # Проверяем финансовые проводки:
    await db_session.refresh(bidder2)
    await db_session.refresh(chat_settings)
    assert bidder2.balance == 24000  # 40 000 - 16 000
    assert chat_settings.treasury_balance == 116000  # 100 000 + 16 000
    assert chat_settings.total_fines_collected == 16000

    # 5. Проверка форматирования карточки завершенного аукциона
    card_text = AuctionService.format_card_text(closed_auc)
    assert "ЗАВЕРШЕН" in card_text
    assert "16,000" in card_text
    assert "Боб" in card_text


@pytest.mark.asyncio
async def test_auction_handlers_and_callbacks(db_session: AsyncSession):
    """Тест обработчиков команд и кнопок аукционов."""
    warden = User(
        telegram_id=999001,
        username="WardenMike",
        full_name="Блюститель Майк",
        role_level=PositionLevel.CHAT_WARDEN.value,
        balance=10000,
    )
    buyer = User(
        telegram_id=999002,
        username="RichBuyer",
        full_name="Богатый Покупатель",
        role_level=PositionLevel.CITIZEN.value,
        balance=50000,
    )
    db_session.add_all([warden, buyer])
    await db_session.commit()

    # 1. Команда создания аукциона: /аукцион создать Алмазная броня 5000 15
    msg_create = MagicMock()
    msg_create.chat.id = -100444
    msg_create.chat.type = "supergroup"
    msg_create.from_user.id = warden.telegram_id
    msg_create.message_thread_id = None
    msg_create.text = "/аукцион создать Алмазная броня 5000 15"
    sent_card = MagicMock()
    sent_card.message_id = 12345
    msg_create.answer = AsyncMock(return_value=sent_card)
    msg_create.reply = AsyncMock()

    await cmd_auction_router(message=msg_create, session=db_session, db_user=warden)
    msg_create.answer.assert_called_once()
    created_card_text = msg_create.answer.call_args[0][0]
    assert "ГОСУДАРСТВЕННЫЙ АУКЦИОН КОНФИСКАТА" in created_card_text
    assert "Алмазная броня" in created_card_text

    # Получаем созданный аукцион
    auction = await db_session.scalar(select(Auction).where(Auction.chat_id == -100444))
    assert auction is not None
    assert auction.current_price == 5000

    # 2. Проверка команды /аукционы
    msg_list = MagicMock()
    msg_list.chat.id = -100444
    msg_list.chat.type = "supergroup"
    msg_list.from_user.id = buyer.telegram_id
    msg_list.text = "/аукционы"
    msg_list.reply = AsyncMock()

    await cmd_list_auctions(message=msg_list, session=db_session, db_user=buyer)
    msg_list.reply.assert_called_once()
    list_text = msg_list.reply.call_args[0][0]
    assert "Алмазная броня" in list_text
    assert "5,000" in list_text

    # 3. Нажатие кнопки ставки: auc_bid:<id>:1000
    cb_bid = MagicMock()
    cb_bid.data = f"auc_bid:{auction.id}:1000"
    cb_bid.message = MagicMock()
    cb_bid.message.edit_text = AsyncMock()
    cb_bid.answer = AsyncMock()

    await cb_auction_bid(callback=cb_bid, session=db_session, db_user=buyer)
    cb_bid.answer.assert_called_once()
    cb_bid.message.edit_text.assert_called_once()

    await db_session.refresh(auction)
    assert auction.current_price == 6000  # 5000 + 1000
    assert auction.current_winner_id == buyer.id

    # 4. Нажатие кнопки обновления: auc_refresh:<id>
    cb_ref = MagicMock()
    cb_ref.data = f"auc_refresh:{auction.id}"
    cb_ref.message = MagicMock()
    cb_ref.message.edit_text = AsyncMock()
    cb_ref.answer = AsyncMock()

    await cb_auction_refresh(callback=cb_ref, session=db_session, db_user=buyer)
    cb_ref.answer.assert_called_once()

    # 5. Досрочное завершение аукциона организатором: auc_close:<id>
    cb_close = MagicMock()
    cb_close.data = f"auc_close:{auction.id}"
    cb_close.message = MagicMock()
    cb_close.message.edit_text = AsyncMock()
    cb_close.answer = AsyncMock()

    await cb_auction_close(callback=cb_close, session=db_session, db_user=warden)
    cb_close.answer.assert_called_once()
    cb_close.message.edit_text.assert_called_once()

    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.COMPLETED.value
    await db_session.refresh(buyer)
    assert buyer.balance == 44000  # 50000 - 6000
