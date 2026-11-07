import time
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Law, Punishment, Fine
from core.enums import PositionLevel, PunishmentType, FineStatus
from core.regulators import RegulatorService, format_duration
from core.laws_service import LawService
from core.fine_service import FineService
from core.exceptions import TownBaseException, UserNotFoundError
from bot.utils import extract_target_user
from config import settings

router = Router(name="justice_router")


@router.message(Command("наказать"))
async def cmd_punish(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /наказать @юзер [номер_статьи] [опциональный_срок_в_сек/причина]
    (или в ответ на сообщение нарушителя: /наказать [номер_статьи])
    Налагает санкцию строго по Городскому Своду Законов с проверкой регуляторов.
    """
    raw_args = message.text.split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "Использование: <code>/наказать @юзер [номер_статьи]</code> "
            "или ответом на сообщение нарушителя: <code>/наказать [номер_статьи]</code>"
        )
        return

    if not remaining_args:
        await message.answer("⚠️ Укажите номер статьи Закона! Пример: <code>/наказать @юзер 2.1</code>")
        return

    article_number = remaining_args[0].strip()
    custom_reason = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else None

    try:
        # 1. Получаем статью закона
        law = await LawService.get_law(session, article_number)

        # 2. Определяем тип санкции по статье
        if law.is_ban_applicable and (law.default_mute_seconds is None or law.default_mute_seconds == 0):
            # Санкция — изгнание (бан)
            regulator = await RegulatorService.validate_ban(
                session=session,
                issuer=db_user,
                target=target_user,
                duration_seconds=regulator_max_ban if (regulator_max_ban := 0) else 0
            )

            # Баним в Telegram
            try:
                await message.chat.ban(user_id=target_user.telegram_id)
            except Exception:
                pass  # В ЛС или нет прав в чате

            # Если статья 1.4 — статус Врага города
            if law.article_number == "1.4":
                target_user.is_enemy = True
                target_user.enemy_reason = custom_reason or law.title

            punishment_type = PunishmentType.BAN
            duration_sec = regulator.max_ban_time
            sanction_descr = "Изгнание из города (Бан)"

        else:
            # Санкция — мут (ограничение речи)
            mute_sec = law.default_mute_seconds or 3600
            regulator = await RegulatorService.validate_mute(
                session=session,
                issuer=db_user,
                target=target_user,
                duration_seconds=mute_sec
            )

            # Применяем restrict в чате
            until = int(time.time() + mute_sec)
            try:
                await message.chat.restrict(
                    user_id=target_user.telegram_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception:
                pass

            punishment_type = PunishmentType.MUTE
            duration_sec = mute_sec
            sanction_descr = f"Ограничение речи на {format_duration(mute_sec)}"

        # 3. Фиксируем в протокол городского суда
        reason = custom_reason or f"Нарушение ст. {law.article_number}: {law.title}"
        await LawService.log_punishment(
            session=session,
            target_user=target_user,
            issuer_user=db_user,
            punishment_type=punishment_type,
            law_article=law.article_number,
            duration_seconds=duration_sec,
            reason=reason,
        )

        target_user.warns_count += 1
        await session.commit()

        # 4. Формируем вердикт
        verdict = (
            f"⚖️ <b>СУДЕБНЫЙ ПРИГОВОР ВСТУПИЛ В СИЛУ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Нарушитель:</b> {target_user.full_name} ({target_user.position_title})\n"
            f"👮 <b>Блюститель:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"📜 <b>Статья закона:</b> № {law.article_number} — {law.title}\n"
            f"⚡ <b>Мера пресечения:</b> {sanction_descr}\n"
            f"📝 <b>Основание:</b> {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Запись внесена в протокол городского суда.</i>"
        )
        await message.answer(verdict)

        # Отправка в лог-канал
        if settings.LOG_CHAT_ID and message.bot:
            try:
                await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=verdict)
            except Exception:
                pass

    except TownBaseException as e:
        await message.answer(e.message)


@router.message(Command("штраф"))
async def cmd_fine(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /штраф @юзер [номер_статьи] [сумма] [причина]
    Выставляет официальный тикет штрафа с таймером на 48 часов по п. 3.12 Законов.
    """
    raw_args = message.text.split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "Использование: <code>/штраф @юзер [номер_статьи] [сумма] [причина]</code>\n"
            "или ответом: <code>/штраф [номер_статьи] [сумма] [причина]</code>"
        )
        return

    if len(remaining_args) < 2:
        await message.answer(
            "⚠️ Недостаточно аргументов!\n"
            "Формат: <code>/штраф @юзер [номер_статьи] [сумма] [причина]</code>\n"
            "Пример: <code>/штраф @ivan 2.1 15000 Оскорбление жителей</code>"
        )
        return

    article_number = remaining_args[0].strip()
    try:
        amount = int(remaining_args[1].replace(" ", "").replace("_", ""))
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Сумма штрафа должна быть положительным целым числом!")
        return

    reason = " ".join(remaining_args[2:]).strip() if len(remaining_args) > 2 else f"Нарушение ст. {article_number}"

    try:
        # Проверяем существование статьи
        law = await LawService.get_law(session, article_number)

        # Проверяем лимиты должности через Регулятор
        is_chat_sec = "Раздел II" in law.section
        await RegulatorService.validate_fine(
            session=session,
            issuer=db_user,
            target=target_user,
            amount=amount,
            is_chat_section=is_chat_sec
        )

        # Создаем тикет штрафа
        fine = await FineService.create_fine(
            session=session,
            target_user=target_user,
            issuer_user=db_user,
            law_article=law.article_number,
            amount=amount,
            reason=reason
        )

        # Логируем в протокол суда
        await LawService.log_punishment(
            session=session,
            target_user=target_user,
            issuer_user=db_user,
            punishment_type=PunishmentType.FINE,
            law_article=law.article_number,
            duration_seconds=None,
            reason=f"Штраф {amount:,}: {reason}",
        )

        ticket_card = FineService.format_fine_ticket(
            fine=fine,
            user_name=f"{target_user.full_name} (@{target_user.username or 'без_юзернейма'})",
            issuer_name=f"{db_user.full_name} ({db_user.position_title})"
        )
        await message.answer(ticket_card)

        # Отправка в лог-канал
        if settings.LOG_CHAT_ID and message.bot:
            try:
                await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=ticket_card)
            except Exception:
                pass

    except TownBaseException as e:
        await message.answer(e.message)


@router.message(Command("досье"))
async def cmd_dossier(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /досье @юзер (или ответом на сообщение):
    Выписка всех судимостей, нарушений, открытых штрафов и текущая должность.
    """
    raw_args = message.text.split()[1:]
    target_user, _ = await extract_target_user(message, session, raw_args)

    # Если цель не указана — показываем досье автора
    if not target_user:
        target_user = db_user

    # Загружаем историю наказаний
    punishments_query = (
        select(Punishment)
        .where(Punishment.user_id == target_user.id)
        .order_by(Punishment.created_at.desc())
        .limit(10)
    )
    punishments = (await session.scalars(punishments_query)).all()

    # Загружаем активные штрафы
    fines_query = (
        select(Fine)
        .where(
            Fine.user_id == target_user.id,
            Fine.status.in_([FineStatus.ACTIVE.value, FineStatus.OVERDUE.value])
        )
    )
    active_fines = (await session.scalars(fines_query)).all()

    vacation_status = "🌴 В отпуске" if target_user.on_vacation else "В строю"
    wanted_badge = "🚨 <b>В ОБЩЕГОРОДСКОМ РОЗЫСКЕ</b>\n" if target_user.is_wanted else ""
    enemy_badge = "☠️ <b>ОБЪЯВЛЕН ВРАГОМ ГОРОДА</b>\n" if target_user.is_enemy else ""

    dossier_text = [
        f"📁 <b>СУДЕБНО-СЛЕДСТВЕННОЕ ДОСЬЕ ГРАЖДАНИНА</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"{enemy_badge}{wanted_badge}"
        f"👤 <b>ФИО:</b> {target_user.full_name}",
        f"🏷 <b>Telegram ID:</b> <code>{target_user.telegram_id}</code> (@{target_user.username or '—'})",
        f"🎮 <b>Minecraft Nick:</b> <code>{target_user.minecraft_nick or 'не привязан'}</code>",
        f"🎖 <b>Должность:</b> <b>{target_user.position_title}</b> (Уровень {target_user.role_level})",
        f"🏖 <b>Служебный статус:</b> {vacation_status}",
        f"⚠️ <b>Предупреждений:</b> {target_user.warns_count}",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    # Активные неоплаченные штрафы
    if active_fines:
        dossier_text.append("💰 <b>Неоплаченные штрафы (срок 48ч):</b>")
        for f in active_fines:
            state = "❌ ПРОСРОЧЕН (x2)" if f.status == FineStatus.OVERDUE.value else "⏳ Ожидает оплаты"
            dossier_text.append(
                f"• Тикет №{f.id}: <code>{f.amount:,}</code> валюты (ст. {f.law_article}) — {state}"
            )
        dossier_text.append("")
    else:
        dossier_text.append("💰 Задолженностей по штрафам нет.\n")

    # Журнал нарушений
    if punishments:
        dossier_text.append("⚖️ <b>Последние записи протокола суда:</b>")
        for p in punishments:
            date_str = p.created_at.strftime("%d.%m.%Y")
            dossier_text.append(
                f"• [{date_str}] <b>{p.punishment_type.upper()}</b> (ст. {p.law_article or '—'}): {p.reason}"
            )
    else:
        dossier_text.append("✅ Записей о правонарушениях не найдено (чистая биография).")

    dossier_text.append("━━━━━━━━━━━━━━━━━━━━")
    await message.answer("\n".join(dossier_text))


@router.message(Command("оплатить"))
async def cmd_pay_fine(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /оплатить [номер_штрафа]
    Погашение штрафа гражданином.
    """
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/оплатить [номер_штрафа]</code>")
        return

    fine_id = int(args[1])
    fine = await session.scalar(select(Fine).where(Fine.id == fine_id))
    if not fine or fine.user_id != db_user.id:
        await message.answer("⚠️ Штраф с таким номером не найден или выписан не вам.")
        return

    if fine.status == FineStatus.PAID.value:
        await message.answer("ℹ️ Данный штраф уже был успешно оплачен ранее.")
        return

    paid_fine = await FineService.pay_fine(session, fine_id)
    await message.answer(
        f"✅ <b>ШТРАФ №{fine_id} УСПЕШНО ОПЛАЧЕН</b>\n"
        f"Сумма: <code>{paid_fine.amount:,}</code> валюты внесена в городскую казну.\n"
        f"Статус тикета: Оплачен. Претензии казначейства сняты."
    )
