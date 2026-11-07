from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Law
from core.enums import PositionLevel
from core.laws_service import LawService
from core.regulators import RegulatorService
from core.exceptions import TownBaseException
from api.client import PollBotClient
from api.schemas import ReferendumType
from bot.utils import extract_target_user

router = Router(name="referendum_router")
poll_client = PollBotClient()


@router.message(Command("референдум"))
async def cmd_referendum(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /референдум [номер_статьи] [новый_текст_поправки]
    Выносит законопроект на всеобщее голосование горожан через Cross-bot API (Poll Bot).
    Доступно Старшей администрации.
    """
    if db_user.role_level < PositionLevel.ADMINISTRATION.value:
        await message.answer("🚫 Инициировать общегородской референдум может только Администрация города!")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "🏛 <b>ОБЩЕГОРОДСКОЙ РЕФЕРЕНДУМ</b>\n\n"
            "Использование:\n"
            "<code>/референдум [номер_статьи] [предлагаемый текст поправки]</code>\n\n"
            "<i>Пример: <code>/референдум 2.3 Запрещен медиа-спам более 5 сообщений подряд.</code></i>\n"
            "После вызова запрос будет передан боту опросов для запуска голосования."
        )
        return

    article_number = args[1].strip()
    proposed_text = args[2].strip()

    try:
        law = await LawService.get_law(session, article_number)

        poll_question = (
            f"🗳 РЕФЕРЕНДУМ: Принять поправку к Статье {law.article_number} ({law.title})?"
        )
        poll_options = [
            "✅ ЗА (Принять поправку)",
            "❌ ПРОТИВ (Оставить как есть)"
        ]

        # Отправляем задачу во второй бот опросов
        success = await poll_client.create_poll(
            question=poll_question,
            options=poll_options,
            referendum_type=ReferendumType.LAW_AMENDMENT,
            article_number=law.article_number,
            proposed_text=proposed_text,
            duration_hours=24
        )

        status_msg = (
            "✅ <b>Запрос передан боту опросов!</b> Голосование запущено в чате."
            if success else
            "⚠️ <i>Связь с сервером опросов временно недоступна, зафиксировано в протоколе Ратуши.</i>"
        )

        await message.answer(
            f"🗳 <b>ОБЩЕГОРОДСКОЙ РЕФЕРЕНДУМ ОБЪЯВЛЕН!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📜 <b>Статья:</b> № {law.article_number} — {law.title}\n"
            f"✍️ <b>Инициатор:</b> {db_user.full_name} ({db_user.position_title})\n\n"
            f"<b>Предлагаемый текст:</b>\n{proposed_text}\n\n"
            f"⏳ Срок голосования: 24 часа.\n"
            f"{status_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Право голоса имеют исключительно Граждане города. Враги города исключены.</i>"
        )

    except TownBaseException as e:
        await message.answer(e.message)


@router.message(Command("присяжные"))
async def cmd_jury_trial(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /присяжные @юзер [номер_статьи] [суть_обвинения]
    Вынесение спорного обвинения на публичный суд присяжных заседателей.
    """
    if db_user.role_level < PositionLevel.SENIOR_WARDEN.value:
        await message.answer("🚫 Созывать суд присяжных может только Старший блюститель или Администрация!")
        return

    raw_args = message.text.split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user or len(remaining_args) < 2:
        await message.answer(
            "Использование: <code>/присяжные @юзер [номер_статьи] [суть обвинения]</code>\n"
            "Пример: <code>/присяжные @ivan 3.1 Подозрение в тайном подкопе под склад казны</code>"
        )
        return

    article_number = remaining_args[0].strip()
    accusation = " ".join(remaining_args[1:]).strip()

    try:
        law = await LawService.get_law(session, article_number)

        poll_question = (
            f"⚖️ СУД ПРИСЯЖНЫХ: Виновен ли гражданин {target_user.full_name} по ст. {law.article_number}?"
        )
        poll_options = [
            "🔴 ВИНОВЕН (Наложить санкцию)",
            "🟢 НЕВИНОВЕН (Оправдать)"
        ]

        success = await poll_client.create_poll(
            question=poll_question,
            options=poll_options,
            referendum_type=ReferendumType.JURY_TRIAL,
            article_number=law.article_number,
            target_user_id=target_user.telegram_id,
            duration_hours=12
        )

        await message.answer(
            f"⚖️ <b>СОЗВАН ГОРОДСКОЙ СУД ПРИСЯЖНЫХ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Подсудимый:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
            f"👮 <b>Гособвинитель:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"📜 <b>Статья обвинения:</b> № {law.article_number} ({law.title})\n"
            f"📝 <b>Суть обвинения:</b> {accusation}\n\n"
            f"🗳 Горожане призываются исполнить гражданский долг и вынести вердикт в опросе!\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

    except TownBaseException as e:
        await message.answer(e.message)
