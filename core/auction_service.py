import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Auction, User, ChatSettings
from core.enums import AuctionStatus

logger = logging.getLogger("townbot.auctions")


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Приводит datetime к timezone-aware UTC для совместимости с SQLite и PostgreSQL."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

_to_utc = to_utc


class AuctionService:
    to_utc = staticmethod(to_utc)
    """
    Сервис конфискационных аукционов города.
    Управляет созданием лотов, проверкой ставок, автопродлением (анти-снайпинг)
    и финальным распределением средств в Государственную казну.
    """

    @staticmethod
    async def create_auction(
        session: AsyncSession,
        chat_id: int,
        initiator: User,
        title: str,
        start_price: int,
        duration_minutes: int = 30,
        thread_id: Optional[int] = None,
        description: Optional[str] = None
    ) -> Auction:
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(minutes=duration_minutes)

        auction = Auction(
            chat_id=chat_id,
            thread_id=thread_id,
            title=title,
            description=description,
            initiator_id=initiator.id,
            initiator_telegram_id=initiator.telegram_id,
            start_price=start_price,
            current_price=start_price,
            min_step=500,
            status=AuctionStatus.ACTIVE.value,
            bids_count=0,
            end_time=end_time,
            created_at=now,
        )
        session.add(auction)
        await session.commit()
        await session.refresh(auction)
        return auction

    @staticmethod
    async def place_bid(
        session: AsyncSession,
        auction_id: int,
        bidder: User,
        increment: int
    ) -> Tuple[bool, str, Optional[Auction]]:
        auction = await session.scalar(select(Auction).where(Auction.id == auction_id))
        if not auction:
            return False, "Аукцион не найден!", None

        now = datetime.now(timezone.utc)
        end_time_utc = _to_utc(auction.end_time)
        if auction.status != AuctionStatus.ACTIVE.value or (end_time_utc and end_time_utc <= now):
            await AuctionService.finalize_auction(session, auction_id)
            return False, "Торги по данному лоту уже завершены!", auction

        if auction.current_winner_id == bidder.id:
            return False, "Вы уже удерживаете наивысшую ставку на этом лоте!", auction

        new_price = auction.current_price + increment
        bidder_balance = getattr(bidder, "balance", 5000) or 0
        if bidder_balance < new_price:
            return False, (
                f"Недостаточно средств на счете!\n"
                f"Ваш баланс: {bidder_balance:,} ₽\n"
                f"Требуется для ставки: {new_price:,} ₽"
            ), auction

        # Анти-снайпинг: если ставка сделана менее чем за 60 секунд до конца, продлеваем на 2 минуты
        remaining = (end_time_utc - now).total_seconds() if end_time_utc else 0
        if remaining < 60:
            auction.end_time = now + timedelta(minutes=2)

        auction.current_price = new_price
        auction.current_winner_id = bidder.id
        auction.current_winner_telegram_id = bidder.telegram_id
        auction.current_winner_name = bidder.full_name
        auction.bids_count = (auction.bids_count or 0) + 1

        await session.commit()
        await session.refresh(auction)
        return True, f"Ваша ставка {new_price:,} ₽ успешно принята!", auction

    @staticmethod
    async def finalize_auction(session: AsyncSession, auction_id: int) -> Optional[Auction]:
        auction = await session.scalar(select(Auction).where(Auction.id == auction_id))
        if not auction:
            return None

        if auction.status != AuctionStatus.ACTIVE.value:
            return auction

        now = datetime.now(timezone.utc)
        auction.closed_at = now

        if auction.current_winner_id:
            # Есть победитель
            auction.status = AuctionStatus.COMPLETED.value
            winner = await session.scalar(select(User).where(User.id == auction.current_winner_id))
            if winner:
                winner.balance = max(0, (getattr(winner, "balance", 5000) or 0) - auction.current_price)

            # Средства зачисляются в Государственную казну чата
            chat_settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == auction.chat_id))
            if not chat_settings:
                chat_settings = ChatSettings(chat_id=auction.chat_id)
                session.add(chat_settings)
            chat_settings.treasury_balance = (chat_settings.treasury_balance or 0) + auction.current_price
            chat_settings.total_fines_collected = (chat_settings.total_fines_collected or 0) + auction.current_price
        else:
            # Ставок не было
            auction.status = AuctionStatus.CANCELLED.value

        await session.commit()
        await session.refresh(auction)
        return auction

    @staticmethod
    async def get_active_auctions(session: AsyncSession, chat_id: Optional[int] = None) -> List[Auction]:
        query = select(Auction).where(Auction.status == AuctionStatus.ACTIVE.value)
        if chat_id:
            query = query.where(Auction.chat_id == chat_id)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def format_card_text(auction: Auction) -> str:
        now = datetime.now(timezone.utc)
        if auction.status == AuctionStatus.COMPLETED.value:
            winner_text = auction.current_winner_name or f"ID {auction.current_winner_telegram_id}"
            return (
                f"🏛️ <b>ГОСУДАРСТВЕННЫЙ АУКЦИОН КОНФИСКАТА #{auction.id} [ЗАВЕРШЕН]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Лот:</b> <b>{auction.title}</b>\n"
                f"💰 <b>Финальная цена выкупа:</b> <code>{auction.current_price:,}</code> ₽\n"
                f"🏆 <b>Победитель торгов:</b> {winner_text}\n"
                f"📈 <b>Всего ставок:</b> {auction.bids_count}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏦 <i>Сумма {auction.current_price:,} ₽ списана со счета победителя "
                f"и зачислена в Государственную казну города.</i>"
            )
        elif auction.status == AuctionStatus.CANCELLED.value:
            return (
                f"🏛️ <b>ГОСУДАРСТВЕННЫЙ АУКЦИОН КОНФИСКАТА #{auction.id} [ОТМЕНЕН]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Лот:</b> <b>{auction.title}</b>\n"
                f"💰 <b>Стартовая цена:</b> <code>{auction.start_price:,}</code> ₽\n"
                f"📈 <b>Ставок не поступило.</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <i>Лот снят с торгов и возвращен на склад конфиската Мэрии.</i>"
            )

        # Активный аукцион
        end_time_utc = _to_utc(auction.end_time)
        diff = (end_time_utc - now) if end_time_utc else timedelta(0)
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            time_left_str = "⏳ Время истекло (завершение...)"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            if hours > 0:
                time_left_str = f"⏳ {hours} ч. {minutes} мин."
            else:
                time_left_str = f"⏳ {minutes} мин. {seconds} сек."

        winner_str = auction.current_winner_name if auction.current_winner_id else "Ставок пока нет"
        return (
            f"🏛️ <b>ГОСУДАРСТВЕННЫЙ АУКЦИОН КОНФИСКАТА #{auction.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Конфискованный лот:</b> <b>{auction.title}</b>\n"
            f"💰 <b>Текущая ставка:</b> <code>{auction.current_price:,}</code> ₽\n"
            f"👤 <b>Лидер торгов:</b> {winner_str}\n"
            f"📈 <b>Количество ставок:</b> {auction.bids_count}\n"
            f"⏳ <b>До окончания:</b> {time_left_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 <i>Все средства от продажи лота поступают в Государственную казну города. "
            f"За 60 сек. до конца любая ставка продлевает торги на +2 минуты (анти-снайпинг).</i>"
        )

    @staticmethod
    def build_card_keyboard(auction: Auction) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        if auction.status != AuctionStatus.ACTIVE.value:
            builder.button(text="🔒 Торги завершены", callback_data=f"auc_closed:{auction.id}")
            return builder.as_markup()

        builder.button(text="➕ 500 ₽", callback_data=f"auc_bid:{auction.id}:500")
        builder.button(text="➕ 1 000 ₽", callback_data=f"auc_bid:{auction.id}:1000")
        builder.button(text="➕ 5 000 ₽", callback_data=f"auc_bid:{auction.id}:5000")
        builder.adjust(3)

        builder.row(
            InlineKeyboardButton(text="🔄 Обновить таймер", callback_data=f"auc_refresh:{auction.id}"),
            InlineKeyboardButton(text="🏁 Завершить", callback_data=f"auc_close:{auction.id}")
        )
        return builder.as_markup()
