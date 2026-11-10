from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.ticket import Ticket
from db.models.user import User
from core.enums import TicketStatus, TicketCategory
from core.exceptions import TownBaseException

CATEGORY_DEFAULT_ROLES: dict[str, str] = {
    TicketCategory.MAYOR.value: "Мэрия / Кабинет Министров",
    TicketCategory.COURT.value: "Судья",
    TicketCategory.STAFF_COMPLAINT.value: "Администрация",
    TicketCategory.GENERAL.value: "Помощник",
}


class TicketService:
    """Сервис управления государственными обращениями (тикетами) граждан."""

    @classmethod
    async def create_ticket(
        cls,
        session: AsyncSession,
        creator: User,
        category: str,
        initial_text: Optional[str] = None,
    ) -> Ticket:
        """Создает новое обращение гражданина в БД."""
        target_role = CATEGORY_DEFAULT_ROLES.get(category, "Администрация")
        ticket = Ticket(
            creator_id=creator.id,
            creator_telegram_id=creator.telegram_id,
            category=category,
            target_role=target_role,
            status=TicketStatus.OPEN.value,
            initial_text=initial_text,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return ticket

    @classmethod
    async def bind_forum_topic(
        cls, session: AsyncSession, ticket_id: int, thread_id: int
    ) -> Ticket:
        """Привязывает созданный топик форума Telegram к записи тикета."""
        ticket = await cls.get_ticket(session, ticket_id)
        if not ticket:
            raise TownBaseException(f"Тикет #{ticket_id} не найден!")

        ticket.topic_thread_id = thread_id
        await session.commit()
        await session.refresh(ticket)
        return ticket

    @classmethod
    async def get_ticket(cls, session: AsyncSession, ticket_id: int) -> Optional[Ticket]:
        query = select(Ticket).where(Ticket.id == ticket_id)
        return await session.scalar(query)

    @classmethod
    async def get_ticket_by_thread(
        cls, session: AsyncSession, thread_id: int
    ) -> Optional[Ticket]:
        query = select(Ticket).where(Ticket.topic_thread_id == thread_id)
        return await session.scalar(query)

    @classmethod
    async def claim_ticket(
        cls, session: AsyncSession, ticket_id: int, staff_user: User
    ) -> Ticket:
        """Берет обращение в работу уполномоченным сотрудником."""
        ticket = await cls.get_ticket(session, ticket_id)
        if not ticket:
            raise TownBaseException(f"Тикет #{ticket_id} не найден!")

        if ticket.status == TicketStatus.CLOSED.value:
            raise TownBaseException("Это обращение уже закрыто!")

        ticket.status = TicketStatus.IN_PROGRESS.value
        ticket.claimed_by_id = staff_user.id
        await session.commit()
        await session.refresh(ticket)
        return ticket

    @classmethod
    async def transfer_ticket(
        cls, session: AsyncSession, ticket_id: int, new_role: str, staff_user: User
    ) -> Ticket:
        """Перенаправляет обращение в другое ведомство/инстанцию."""
        ticket = await cls.get_ticket(session, ticket_id)
        if not ticket:
            raise TownBaseException(f"Тикет #{ticket_id} не найден!")

        if ticket.status == TicketStatus.CLOSED.value:
            raise TownBaseException("Нельзя перенаправить уже закрытое обращение!")

        ticket.target_role = new_role.strip()
        ticket.status = TicketStatus.OPEN.value
        ticket.claimed_by_id = None  # Сбрасываем исполнителя для новой инстанции
        await session.commit()
        await session.refresh(ticket)
        return ticket

    @classmethod
    async def close_ticket(
        cls, session: AsyncSession, ticket_id: int, staff_user: User, verdict: str
    ) -> Ticket:
        """
        Закрывает обращение с фиксацией итогового вердикта.
        Начисляет сотруднику служебную заслугу (closed_tickets_count += 1).
        """
        ticket = await cls.get_ticket(session, ticket_id)
        if not ticket:
            raise TownBaseException(f"Тикет #{ticket_id} не найден!")

        if ticket.status == TicketStatus.CLOSED.value:
            raise TownBaseException("Это обращение уже закрыто!")

        ticket.status = TicketStatus.CLOSED.value
        ticket.verdict = verdict.strip() or "Обращение рассмотрено и закрыто"
        ticket.claimed_by_id = staff_user.id
        ticket.closed_at = datetime.now(timezone.utc)

        # Начисляем заслугу сотруднику
        staff_user.closed_tickets_count = (staff_user.closed_tickets_count or 0) + 1

        await session.commit()
        await session.refresh(ticket)
        return ticket
