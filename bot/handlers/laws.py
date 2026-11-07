from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.laws_service import LawService
from core.regulators import RegulatorService
from core.exceptions import TownBaseException

router = Router(name="laws_router")


@router.message(Command("закон"))
async def cmd_law(message: Message, session: AsyncSession):
    """
    Команда /закон [номер] — выдает карточку статьи Городского Свода Законов
    с точной диспозицией и регламентом наказания.
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📖 <b>ГОРОДСКОЙ СВОД ЗАКОНОВ</b>\n\n"
            "Чтобы ознакомиться со статьей, используйте:\n"
            "<code>/закон [номер_статьи]</code> (например, <code>/закон 2.1</code> или <code>/закон 3.12</code>)\n\n"
            "<b>Разделы Свода Законов:</b>\n"
            "• <b>Раздел I.</b> Общие положения (1.1 - 1.4)\n"
            "• <b>Раздел II.</b> Чат Telegram (2.1 - 2.12)\n"
            "• <b>Раздел III.</b> Внутриигровые законы (3.1 - 3.28)\n"
            "• <b>Раздел IV.</b> Служба и работа (4.1 - 4.4)\n\n"
            "<i>Для полного списка всех статей введите:</i> <code>/законы</code>"
        )
        return

    article_number = args[1].strip()
    try:
        law = await LawService.get_law(session, article_number)
        card = LawService.format_law_card(law)
        await message.answer(card)
    except TownBaseException as e:
        await message.answer(e.message)


@router.message(Command("законы"))
async def cmd_laws_list(message: Message, session: AsyncSession):
    """Список всех статей Городского Свода Законов."""
    laws = await LawService.get_all_laws(session)
    if not laws:
        await message.answer("В реестре пока нет зарегистрированных законов.")
        return

    sections: dict[str, list] = {}
    for law in laws:
        sections.setdefault(law.section, []).append(law)

    text_parts = ["🏛 <b>РЕЕСТР ГОРОДСКОГО СВОДА ЗАКОНОВ</b>\n"]
    for sec_name, sec_laws in sections.items():
        text_parts.append(f"\n<b>{sec_name}:</b>")
        for law in sec_laws:
            text_parts.append(f"• <b>ст. {law.article_number}</b> — {law.title}")

    text_parts.append("\n<i>Для детального регламента введите: <code>/закон [номер]</code></i>")
    await message.answer("\n".join(text_parts))


@router.message(Command("закон_ред"))
async def cmd_law_edit(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /закон_ред [номер] [новый_текст]
    Редактирование статьи закона. Доступно только Администрации (уровни 4-5).
    """
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "Использование: <code>/закон_ред [номер_статьи] [новый текст статьи]</code>\n"
            "<i>Пример: <code>/закон_ред 2.2 Запрещен капс более 70% и флуд.</code></i>"
        )
        return

    article_number = args[1].strip()
    new_text = args[2].strip()

    try:
        # Проверка прав через сервис Регуляторов
        await RegulatorService.validate_edit_laws(session, db_user)

        law = await LawService.update_law_text(
            session=session,
            article_number=article_number,
            new_description=new_text,
            editor=db_user
        )

        await message.answer(
            f"✅ <b>Статья № {law.article_number} успешно изменена!</b>\n\n"
            f"<b>Редактор:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"<b>Новая редакция:</b>\n{law.description}"
        )
    except TownBaseException as e:
        await message.answer(e.message)
