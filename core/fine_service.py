from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Fine, User, ChatSettings
from core.enums import FineStatus
from config import settings


class FineService:
    """
    Сервис городского казначейства и судебных приставов.
    Контролирует тикеты штрафов, таймер 48 часов (п. 3.12 Законов),
    автоматическое удвоение и объявление нарушителей в розыск.
    """

    @staticmethod
    async def create_fine(
        session: AsyncSession,
        target_user: User,
        issuer_user: User,
        law_article: str,
        amount: int,
        reason: str
    ) -> Fine:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=settings.FINE_EXPIRATION_HOURS)

        fine = Fine(
            user_id=target_user.id,
            target_telegram_id=target_user.telegram_id,
            issuer_id=issuer_user.id,
            issuer_telegram_id=issuer_user.telegram_id,
            law_article=law_article,
            amount=amount,
            original_amount=amount,
            is_doubled=False,
            reason=reason,
            status=FineStatus.ACTIVE.value,
            issued_at=now,
            expires_at=expires_at,
        )
        session.add(fine)
        await session.commit()
        return fine

    @staticmethod
    async def pay_fine(session: AsyncSession, fine_id: int, chat_id: int | None = None) -> Fine | None:
        query = select(Fine).where(Fine.id == fine_id)
        fine = await session.scalar(query)
        if not fine:
            return None

        fine.status = FineStatus.PAID.value
        fine.paid_at = datetime.now(timezone.utc)

        # Проверяем, есть ли еще просроченные штрафы у гражданина, и списываем баланс
        user_query = select(User).where(User.id == fine.user_id)
        user = await session.scalar(user_query)
        if user:
            if hasattr(user, "balance") and user.balance is not None:
                user.balance = max(0, user.balance - fine.amount)
            active_overdue = await session.scalar(
                select(Fine).where(
                    Fine.user_id == user.id,
                    Fine.status == FineStatus.OVERDUE.value
                )
            )
            if not active_overdue:
                user.is_wanted = False

        # Пополняем Государственную казну чата
        effective_chat_id = chat_id or settings.MAIN_CHAT_ID
        if effective_chat_id:
            chat_settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == effective_chat_id))
            if not chat_settings:
                chat_settings = ChatSettings(chat_id=effective_chat_id)
                session.add(chat_settings)
            chat_settings.treasury_balance = (chat_settings.treasury_balance or 0) + fine.amount
            chat_settings.total_fines_collected = (chat_settings.total_fines_collected or 0) + fine.amount

        await session.commit()
        return fine

    @staticmethod
    async def process_overdue_fines(session: AsyncSession) -> List[Tuple[Fine, User]]:
        """
        Фоновый обработчик просроченных штрафов:
        Если прошло >48 часов с момента выписки:
        1. Сумма удваивается (x2).
        2. Статус меняется на 'overdue'.
        3. Нарушитель объявляется в общегородской розыск (is_wanted = True).
        """
        now = datetime.now(timezone.utc)
        query = (
            select(Fine, User)
            .join(User, Fine.user_id == User.id)
            .where(
                Fine.status == FineStatus.ACTIVE.value,
                Fine.expires_at <= now
            )
        )
        result = await session.execute(query)
        overdue_items = result.all()

        processed = []
        for fine, user in overdue_items:
            fine.status = FineStatus.OVERDUE.value
            fine.is_doubled = True
            fine.amount = int(fine.amount * settings.FINE_DOUBLE_MULTIPLIER)
            user.is_wanted = True
            processed.append((fine, user))

        if processed:
            await session.commit()

        return processed

    @staticmethod
    def format_fine_ticket(fine: Fine, user_name: str, issuer_name: str) -> str:
        """Форматирует официальный тикет штрафа."""
        exp_time = fine.expires_at.strftime("%d.%m.%Y %H:%M UTC")
        return (
            f"📜 <b>ОФИЦИАЛЬНЫЙ ТИКЕТ ШТРАФА №{fine.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Нарушитель:</b> {user_name}\n"
            f"👮 <b>Блюститель:</b> {issuer_name}\n"
            f"⚖️ <b>Статья закона:</b> № {fine.law_article}\n"
            f"💰 <b>Сумма к оплате:</b> <code>{fine.amount:,}</code> валюты\n"
            f"📝 <b>Причина:</b> {fine.reason}\n"
            f"⏳ <b>Срок на уплату:</b> до {exp_time} (48 часов)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <i>Внимание (п. 3.12): по истечении 48 часов сумма автоматически удваивается, "
            f"а неплательщик объявляется в общегородской розыск!</i>"
        )
