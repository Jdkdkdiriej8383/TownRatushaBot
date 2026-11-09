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
from config import settings

router = Router(name="passport_router")


@router.message(Command("паспорт", "passport"))
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
        f"📋 <b>Служебных выговоров:</b> {getattr(user, 'reprimands_count', 0)}/3\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Паспорт зарегистрирован в Городской Ратуше.</i>"
    )
    await message.answer(passport_text)


@router.message(Command("ник", "nick"))
async def cmd_set_nick(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /ник [minecraft_ник] — привязка игрового никнейма в паспорте.
    Администрация города (уровни 4-5) и Владелец могут принудительно привязать ник:
    /ник @юзер [minecraft_ник] или ответом на сообщение /ник [minecraft_ник].
    """
    raw_args = message.text.split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    # Если указан целевой пользователь (через @юзер или reply) и это не сам отправитель
    if target_user and target_user.id != db_user.id:
        if not is_admin:
            await message.answer("🚫 Принудительно привязывать ники другим жителям может только Администрация города!")
            return

        if not remaining_args:
            await message.answer(
                "Использование для Администрации:\n"
                "• <code>/ник @юзер [Minecraft_Ник]</code>\n"
                "• Ответом на сообщение: <code>/ник [Minecraft_Ник]</code>"
            )
            return

        new_nick = remaining_args[0].strip()
        existing = await session.scalar(
            select(User).where(User.minecraft_nick.ilike(new_nick), User.id != target_user.id)
        )
        if existing:
            await message.answer(f"⚠️ Ник <code>{new_nick}</code> уже привязан к другому паспорту ({existing.full_name})!")
            return

        target_user.minecraft_nick = new_nick
        await session.commit()
        await message.answer(
            f"✅ <b>Администрация принудительно привязала ник!</b>\n"
            f"Гражданину <b>{target_user.full_name}</b> установлен Minecraft-ник: <code>{new_nick}</code>."
        )
        return

    # Обычная привязка своего ника пользователем
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: <code>/ник [Ваш_Minecraft_Ник]</code>\n"
            "Пример: <code>/ник Steve_Builder</code>\n\n"
            "<i>(Для Администрации: <code>/ник @юзер [Minecraft_Ник]</code>)</i>"
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


@router.message(Command("отпуск", "vacation"))
async def cmd_vacation(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /отпуск [дней] — оформление статуса отпуска по п. 3.25 Городского Свода Законов.
    Максимум 30 дней.
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: <code>/отпуск [кол-во дней от 1 до 30]</code>\n"
            "Пример: <code>/отпуск 14</code>\n\n"
            "<i>Согласно ст. 3.25, статус отпуска защищает имущество жителя от изъятия при длительном оффлайне.</i>"
        )
        return

    try:
        days = int(args[1].strip())
        if days < 1 or days > 30:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Срок отпуска должен быть числом от 1 до 30 дней!")
        return

    now = datetime.now(timezone.utc)
    db_user.on_vacation = True
    db_user.vacation_until = now + timedelta(days=days)
    await session.commit()

    until_str = db_user.vacation_until.strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"🌴 <b>ОТПУСК ОФОРМЛЕН (Статья 3.25)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Гражданин: <b>{db_user.full_name}</b>\n"
        f"Срок отпуска: <b>{days} дн.</b> (до {until_str} UTC)\n"
        f"Статус: <i>Ваш участок и имущество находятся под защитой закона на время отсутствия.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


@router.message(Command("должность", "position"))
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
            "5: Высшая администрация"
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
