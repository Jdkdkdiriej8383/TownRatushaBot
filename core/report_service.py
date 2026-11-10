from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.report import Report
from db.models.user import User
from core.enums import ReportStatus
from core.exceptions import TownBaseException

FALSE_REPORTS_THRESHOLD = 3
FALSE_REPORTS_BLOCK_HOURS = 24


class ReportService:
    """Сервис обработки жалоб (репортов) граждан."""

    @classmethod
    def is_reporter_blocked(cls, reporter: User) -> bool:
        """Проверяет, не заблокирована ли подача жалоб у заявителя за ложные вызовы."""
        if not reporter.reports_blocked_until:
            return False
        return datetime.now(timezone.utc) < reporter.reports_blocked_until

    @classmethod
    async def create_report(
        cls,
        session: AsyncSession,
        reporter: User,
        violator: User,
        incident_topic_id: Optional[int],
        incident_topic_name: str,
        message_id: Optional[int],
        message_text: Optional[str],
        reason: str,
    ) -> Report:
        """Создает новую запись жалобы в базе данных."""
        if cls.is_reporter_blocked(reporter):
            until_str = reporter.reports_blocked_until.strftime("%d.%m.%Y %H:%M")
            raise TownBaseException(
                f"🚫 <b>Подача жалоб временно заблокирована!</b>\n"
                f"Причина: превышен лимит ложных вызовов (3/3).\n"
                f"Блокировка действует до: <b>{until_str} UTC</b>."
            )

        if reporter.id == violator.id:
            raise TownBaseException("🤷 Нельзя подать жалобу на самого себя!")

        report = Report(
            reporter_id=reporter.id,
            reporter_telegram_id=reporter.telegram_id,
            violator_id=violator.id,
            violator_telegram_id=violator.telegram_id,
            incident_topic_id=incident_topic_id,
            incident_topic_name=incident_topic_name,
            message_id=message_id,
            message_text=message_text[:500] if message_text else None,
            reason=reason.strip() or "Нарушение регламента чата",
            status=ReportStatus.PENDING.value,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report

    @classmethod
    async def get_report(cls, session: AsyncSession, report_id: int) -> Optional[Report]:
        query = select(Report).where(Report.id == report_id)
        return await session.scalar(query)

    @classmethod
    async def claim_report(
        cls, session: AsyncSession, report_id: int, staff_user: User
    ) -> Report:
        """Закрепляет рассмотрение жалобы за сотрудником."""
        report = await cls.get_report(session, report_id)
        if not report:
            raise TownBaseException(f"Жалоба #{report_id} не найдена в реестре!")

        if report.status in (ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value, ReportStatus.FALSE_REPORT.value):
            raise TownBaseException("Эта жалоба уже была рассмотрена и закрыта!")

        report.status = ReportStatus.CLAIMED.value
        report.claimed_by_id = staff_user.id
        await session.commit()
        await session.refresh(report)
        return report

    @classmethod
    async def resolve_report(
        cls, session: AsyncSession, report_id: int, staff_user: User, resolution: str
    ) -> Report:
        """Фиксирует удовлетворение жалобы и примененную меру наказания."""
        report = await cls.get_report(session, report_id)
        if not report:
            raise TownBaseException(f"Жалоба #{report_id} не найдена!")

        report.status = ReportStatus.RESOLVED.value
        report.claimed_by_id = staff_user.id
        report.resolution_details = resolution
        report.resolved_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(report)
        return report

    @classmethod
    async def mark_false_report(
        cls, session: AsyncSession, report_id: int, staff_user: User
    ) -> tuple[Report, bool]:
        """
        Отклоняет жалобу как ложный вызов.
        Увеличивает счетчик ложных вызовов у заявителя.
        При достижении лимита блокирует подачу жалоб на 24 часа.
        Возвращает (report, is_blocked).
        """
        report = await cls.get_report(session, report_id)
        if not report:
            raise TownBaseException(f"Жалоба #{report_id} не найдена!")

        report.status = ReportStatus.FALSE_REPORT.value
        report.claimed_by_id = staff_user.id
        report.resolution_details = f"Отклонено как ложный вызов сотрудником {staff_user.position_title}"
        report.resolved_at = datetime.now(timezone.utc)

        # Обновляем заявителя
        reporter = await session.scalar(select(User).where(User.id == report.reporter_id))
        is_now_blocked = False
        if reporter:
            reporter.false_reports_count = (reporter.false_reports_count or 0) + 1
            if reporter.false_reports_count >= FALSE_REPORTS_THRESHOLD:
                reporter.reports_blocked_until = datetime.now(timezone.utc) + timedelta(hours=FALSE_REPORTS_BLOCK_HOURS)
                reporter.false_reports_count = 0  # Сбрасываем счетчик после наложения блокировки
                is_now_blocked = True

        await session.commit()
        await session.refresh(report)
        return report, is_now_blocked
