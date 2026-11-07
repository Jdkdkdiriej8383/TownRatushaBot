from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.rp_service import RPService
from core.exceptions import TownBaseException
from bot.utils import extract_target_user

router = Router(name="rp_actions_router")

# Фильтры для текстовых триггеров РП команд
RP_COMMANDS = {
    "отдать честь": "salute",
    "честь": "salute",
    "/честь": "salute",
    "арестовать": "arrest",
    "/арестовать": "arrest",
    "досмотреть": "frisk",
    "обыск": "frisk",
    "/досмотреть": "frisk",
    "пожать руку": "shake",
    "/пожать_руку": "shake",
    "выдать повестку": "subpoena",
    "повестка": "subpoena",
    "/повестка": "subpoena",
}


@router.message(F.text.lower().func(lambda t: any(t.startswith(cmd) for cmd in RP_COMMANDS.keys())))
async def handle_rp_actions(message: Message, session: AsyncSession, db_user: User):
    """
    Обработчик ролевых команд с учетом субординации:
    'отдать честь', 'арестовать', 'досмотреть', 'пожать руку', 'выдать повестку'.
    """
    text_lower = message.text.lower().strip()
    matched_action = None

    for cmd_text, action_name in RP_COMMANDS.items():
        if text_lower.startswith(cmd_text):
            matched_action = action_name
            break

    if not matched_action:
        return

    raw_args = message.text.split()[1:]
    target_user, _ = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            f"ℹ️ Укажите гражданина через @юзер или ответьте на его сообщение:\n"
            f"Пример: <code>отдать честь @юзер</code>"
        )
        return

    if db_user.id == target_user.id:
        await message.answer("🤷 Нельзя применить данное RP-действие к самому себе!")
        return

    try:
        if matched_action == "salute":
            resp = RPService.salute(actor=db_user, target=target_user)
        elif matched_action == "arrest":
            resp = RPService.arrest(actor=db_user, target=target_user)
        elif matched_action == "frisk":
            resp = RPService.frisk(actor=db_user, target=target_user)
        elif matched_action == "shake":
            resp = RPService.shake_hands(actor=db_user, target=target_user)
        elif matched_action == "subpoena":
            resp = RPService.issue_subpoena(actor=db_user, target=target_user)
        else:
            return

        await message.answer(resp)

    except TownBaseException as e:
        await message.answer(e.message)
