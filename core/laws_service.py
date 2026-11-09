from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Law, User, Punishment
from core.enums import LawSection, PunishmentType
from core.exceptions import LawNotFoundError
from core.regulators import format_duration


class LawService:
    """Сервис взаимодействия с Городским Сводом Законов."""

    @staticmethod
    async def get_law(session: AsyncSession, article_number: str) -> Law:
        clean_article = article_number.strip().lstrip("№").strip()
        query = select(Law).where(Law.article_number == clean_article)
        law = await session.scalar(query)
        if not law:
            raise LawNotFoundError(clean_article)
        return law

    @staticmethod
    async def get_all_laws(session: AsyncSession) -> List[Law]:
        query = select(Law).order_by(Law.article_number)
        result = await session.scalars(query)
        return list(result.all())

    @staticmethod
    async def update_law_text(
        session: AsyncSession,
        article_number: str,
        new_description: str,
        editor: User
    ) -> Law:
        law = await LawService.get_law(session, article_number)
        law.description = new_description
        law.last_edited_by_tg_id = editor.telegram_id
        law.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return law

    @staticmethod
    def format_law_card(law: Law) -> str:
        """Форматирует карточку закона в стиле судебного вестника города."""
        card = (
            f"🏛 <b>ГОРОДСКОЙ СВОД ЗАКОНОВ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Статья {law.article_number}. {law.title}</b>\n"
            f"<i>Раздел: {law.section}</i>\n\n"
            f"<b>Диспозиция:</b>\n{law.description}\n\n"
            f"⚖️ <b>Санкция и регламент:</b>\n{law.sanction_text}\n"
        )
        defaults = []
        if law.default_mute_seconds:
            defaults.append(f"• Мут по умолчанию: <code>{format_duration(law.default_mute_seconds)}</code>")
        if law.default_fine_amount:
            defaults.append(f"• Штраф по умолчанию: <code>{law.default_fine_amount:,}</code>")
        if law.is_ban_applicable:
            defaults.append("• Предусмотрено <b>изгнание (бан)</b>")

        if defaults:
            card += "\n<b>Параметры применения:</b>\n" + "\n".join(defaults)

        card += "\n━━━━━━━━━━━━━━━━━━━━"
        return card

    @staticmethod
    async def log_punishment(
        session: AsyncSession,
        target_user: User,
        issuer_user: User,
        punishment_type: PunishmentType | str,
        law_article: Optional[str],
        duration_seconds: Optional[int],
        reason: str
    ) -> Punishment:
        punishment = Punishment(
            user_id=target_user.id,
            target_telegram_id=target_user.telegram_id,
            issuer_id=issuer_user.id,
            issuer_telegram_id=issuer_user.telegram_id,
            punishment_type=punishment_type.value if hasattr(punishment_type, "value") else str(punishment_type),
            law_article=law_article,
            duration_seconds=duration_seconds,
            reason=reason,
        )
        session.add(punishment)
        await session.commit()
        return punishment
