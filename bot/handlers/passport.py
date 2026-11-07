from datetime import datetime, timedelta, timezone
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Fine
from core.enums import PositionLevel, FineStatus
from core.regulators import RegulatorService
from core.exceptions import TownBaseException
from bot.utils import extract_target_user

router = Router(name="passport_router")


@router.message(Command("паспорт"))
async def cmd_passport(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /паспорт — электронный паспорт гражданина города.
    Отображает: Minecraft-ник, Должность, статус отпуска (п. 3.25),
    историю штрафов и статус розыска.
    """
    raw_args = message.text.split()[1:]
    target_user, _ = await extract_target_user(message, session, raw_args)

    user = target_user or db_user

    # Подсчет активных штрафов
    fines_query = select(Fine).where(
        Fine.user_id == user.id,
        Fine.status.in_([FineStatus.ACTIVE.value, FineStatus.OVERDUE.value])
    )
    active_fines = (await session.scalars(fines_query)).all()
    total_debt = sum(f.amount for f in active_fines)

    # Статус отпуска
    now = datetime.now(timezone.utc)
    if user.on_vacation and user.vacation_until:
        if user.vacation_until > now:
            vacation_info = f"🌴 В отпуске до {user.vacation_until.strftime('%d.%m.%Y %H:%M')}"
        else:
            user.on_vacation = False
            user.vacation_until = None
            await session.commit()
            vacation_info = "💼 На службе (отпуск завершен)"
    else:
        vacation_info = "💼 На службе (активен)"

    status_badge = ""
    if user.is_enemy:
        status_badge = "\n☠️ <b>ВРАГ ГОРОДА (ПОРАЖЕНИЕ В ПРАВАХ)</b>\n"
    elif user.is_wanted:
        status_badge = "\n🚨 <b>ОБЪЯВЛЕН В ОБЩЕГОРОДСКОЙ РОЗЫСК</b>\n"

    passport_text = (
        f"🏛 <b>ПАСПОРТ ГРАЖДАНИНА ГОРОДА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_badge}"
        f"👤 <b>Имя жителя:</b> {user.full_name}\n"
        f"🎮 <b>Minecraft Nick:</b> <code>{user.minecraft_nick or 'Не зарегистрирован (введите /ник)'}</code>\n"
        f"🎖 <b>Должность:</b> <b>{user.position_title}</b> (Уровень {user.role_level})\n"
        f"🏖 <b>Статус отпуска (п. 3.25):</b> {vacation_info}\n"
        f"💰 <b>Задолженность по штрафам:</b> <code>{total_debt:,}</code> валюты\n"
        f"⚠️ <b>Предупреждений:</b> {user.warns_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Паспорт зарегистрирован в Городской Ратуше.</i>"
    )
    await message.answer(passport_text)


@router.message(Command("ник"))
async def cmd_set_nick(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /ник [minecraft_ник] — привязка игрового никнейма в паспорте.
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: <code>/ник [Ваш_Minecraft_Ник]</code>\n"
            "Пример: <code>/ник Steve_Builder</code>"
        )
        return

    new_nick = args[1].strip()

    # Проверка на занятость ника
    existing = await session.scalar(
        select(User).where(User.minecraft_nick.ilike(new_nick), User.id != db_user.id)
    )
    if existing:
        await message.answer(f"⚠️ Ник <code>{new_nick}</code> уже привязан к другому паспорту!")
        return

    db_user.minecraft_nick = new_nick
    await session.commit()

    await message.answer(
        f"✅ В ваш паспорт успешно внесен Minecraft-ник: <code>{new_nick}</code>!\n"
        f"Теперь городские службы идентифицируют вас в игре."
    )


@router.message(Command("отпуск"))
async def cmd_vacation(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /отпуск [дней] — оформление статуса официального отпуска (п. 3.25).
    Защищает постройки гражданина от сноса за неактивность.
    """
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "Использование: <code>/отпуск [число_дней (от 1 до 30)]</code>\n"
            "Пример: <code>/отпуск 14</code>"
        )
        return

    days = int(args[1])
    if days < 1 or days > 30:
        await message.answer("⚠️ Согласно ст. 3.25 срок отпуска может составлять от 1 до 30 дней.")
        return

    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days)

    db_user.on_vacation = True
    db_user.vacation_until = until
    await session.commit()

    await message.answer(
        f"🌴 <b>ОТПУСК ОФОРМЛЕН (ст. 3.25 Законов)</b>\n\n"
        f"Срок: <b>{days} дней</b> (до {until.strftime('%d.%m.%Y %H:%M UTC')})\n"
        f"Ваше городское имущество и недвижимость защищены от сноса и отчуждения!"
    )


@router.message(Command("должность"))
async def cmd_set_position(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /должность @юзер [0-5]
    Повышение/понижение жителя в должности.
    Строгая проверка прав назначающего и субординации.
    """
    raw_args = message.text.split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user or not remaining_args:
        await message.answer(
            "Использование: <code>/должность @юзер [0-5]</code>\n"
            "<b>Иерархия должностей:</b>\n"
            "0: Гражданин\n"
            "1: Помощник\n"
            "2: Блюститель чата\n"
            "3: Старший блюститель\n"
            "4: Администрация\n"
            "5: Старшая администрация"
        )
        return

    new_level_str = remaining_args[0].strip()
    try:
        new_level = int(new_level_str)
        if new_level < 0 or new_level > 5:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Уровень должности должен быть числом от 0 до 5!")
        return

    try:
        # Проверяем полномочия через сервис Регуляторов
        regulator = await RegulatorService.validate_appointment(
            session=session,
            issuer=db_user,
            target=target_user,
            new_level=new_level
        )

        old_title = target_user.position_title
        target_user.role_level = new_level
        new_title = PositionLevel.get_title(new_level)
        await session.commit()

        action = "повышен" if new_level > target_user.role_level else "переведен"

        await message.answer(
            f"🎖 <b>ПРИКАЗ О НАЗНАЧЕНИИ НА ДОЛЖНОСТЬ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Гражданин: <b>{target_user.full_name}</b> (@{target_user.username or '—'})\n"
            f"Прежняя должность: {old_title}\n"
            f"Новая должность: <b>{new_title}</b> (Уровень {new_level})\n"
            f"Издал приказ: {db_user.full_name} ({db_user.position_title})\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

    except TownBaseException as e:
        await message.answer(e.message)
