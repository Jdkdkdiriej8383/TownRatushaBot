import time
import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Law, Punishment, Fine, ChatSettings
from core.enums import PositionLevel, PunishmentType, FineStatus
from core.regulators import RegulatorService, format_duration
from core.laws_service import LawService
from core.fine_service import FineService
from core.exceptions import TownBaseException, UserNotFoundError
from bot.utils import extract_target_user
from config import settings

logger = logging.getLogger("townbot.justice")

router = Router(name="justice_router")


@router.message(Command("наказать", "punish"))
async def cmd_punish(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /наказать @юзер [номер_статьи/срок] [причина]
    (или в ответ на сообщение нарушителя: /наказать [номер_статьи/срок] [причина])
    Поддерживает:
    - Статьи закона: /наказать 2.1, /наказать @user 1.4
    - Временные муты: /наказать 1h спам, /наказать @user 30m флуд
    - Причины: /наказать @user спам в чате
    """
    from core.moderation_service import parse_duration

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "⚠️ <b>Использование команды /наказать:</b>\n"
            "• <b>Ответом:</b> ответьте на сообщение нарушителя: <code>/наказать [статья|срок] [причина]</code>\n"
            "• <b>По тегу:</b> <code>/наказать @username [статья|срок] [причина]</code>\n\n"
            "<b>Примеры:</b>\n"
            "• <code>/наказать 2.1</code> — по статье 2.1 Свода Законов\n"
            "• <code>/наказать 1h спам</code> — ограничение речи на 1 час\n"
            "• <code>/наказать @user 24ч оскорбления</code>\n"
            "• <code>/наказать 1.4</code> — изгнание (бан) по ст. 1.4"
        )
        return

    # Разбираем статью / срок / причину
    law = None
    mute_sec = 3600
    is_ban = False
    custom_reason = None
    sanction_descr = ""
    law_article_str = "2.1"
    law_title_str = "Нарушение регламента чата"

    if not remaining_args:
        # Без аргументов ответом: применяем дефолтную ст. 2.1 (1 час мута)
        try:
            law = await LawService.get_law(session, "2.1")
            mute_sec = law.default_mute_seconds or 3600
            law_article_str = law.article_number
            law_title_str = law.title
            custom_reason = f"Нарушение ст. {law.article_number}: {law.title}"
        except Exception:
            custom_reason = "Нарушение порядка чата"
    else:
        first_token = remaining_args[0].strip().lstrip("№")
        # 1. Проверяем, является ли первый токен статьей закона
        try:
            law = await LawService.get_law(session, first_token)
            law_article_str = law.article_number
            law_title_str = law.title
            custom_reason = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else f"Нарушение ст. {law.article_number}: {law.title}"
            if law.is_ban_applicable and (law.default_mute_seconds is None or law.default_mute_seconds == 0):
                is_ban = True
            else:
                mute_sec = law.default_mute_seconds or 3600
        except Exception:
            # 2. Не статья — проверяем, является ли сроком (1h, 30m, 1d, 2ч и т.д.)
            parsed_sec = parse_duration(first_token)
            if parsed_sec > 0:
                mute_sec = parsed_sec
                custom_reason = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else "Нарушение регламента чата"
            else:
                # Вся строка — причина, мут 1 час
                custom_reason = " ".join(remaining_args).strip()
                mute_sec = 3600

    try:
        if is_ban:
            regulator = await RegulatorService.validate_ban(
                session=session,
                issuer=db_user,
                target=target_user,
                duration_seconds=0
            )

            try:
                await message.chat.ban(user_id=target_user.telegram_id)
            except Exception as e:
                logger.warning("Не удалось забанить в Telegram: %s", e)

            if law and law.article_number == "1.4":
                target_user.is_enemy = True
                target_user.enemy_reason = custom_reason

            punishment_type = PunishmentType.BAN
            duration_sec = regulator.max_ban_time
            sanction_descr = "Изгнание из города (Бан)"

        else:
            regulator = await RegulatorService.validate_mute(
                session=session,
                issuer=db_user,
                target=target_user,
                duration_seconds=mute_sec
            )

            until = int(time.time() + mute_sec)
            restrict_ok = True
            try:
                await message.chat.restrict(
                    user_id=target_user.telegram_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception as e:
                restrict_ok = False
                logger.warning("Не удалось выдать restrict в Telegram: %s", e)

            punishment_type = PunishmentType.MUTE
            duration_sec = mute_sec
            sanction_descr = f"Ограничение речи на {format_duration(mute_sec)}"
            if not restrict_ok:
                sanction_descr += " <i>(требуются права администратора боту в чате)</i>"

        # Фиксируем в протокол городского суда
        reason = custom_reason or f"Нарушение порядка"
        await LawService.log_punishment(
            session=session,
            target_user=target_user,
            issuer_user=db_user,
            punishment_type=punishment_type,
            law_article=law_article_str,
            duration_seconds=duration_sec,
            reason=reason,
        )

        target_user.warns_count += 1
        await session.commit()

        # Формируем вердикт
        verdict = (
            f"⚖️ <b>СУДЕБНЫЙ ПРИГОВОР ВСТУПИЛ В СИЛУ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Нарушитель:</b> {target_user.full_name} ({target_user.position_title})\n"
            f"👮 <b>Блюститель:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"📜 <b>Основание:</b> ст. {law_article_str} — {law_title_str}\n"
            f"⚡ <b>Мера пресечения:</b> {sanction_descr}\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Запись внесена в протокол городского суда.</i>"
        )
        await message.answer(verdict)

        if settings.LOG_CHAT_ID and message.bot:
            try:
                await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=verdict)
            except Exception:
                pass

    except TownBaseException as e:
        await message.answer(e.message)


@router.message(Command("штраф", "fine"))
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


@router.message(Command("досье", "dossier"))
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
        f"📋 <b>Служебных выговоров:</b> {getattr(target_user, 'reprimands_count', 0)}/3",
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


@router.message(Command("оплатить", "pay"))
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


@router.message(Command("амнистия", "amnesty", "unban", "unmute"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("амнистия", "amnesty", "/амнистия", "/amnesty", "разбан", "размут"))))
async def cmd_amnesty(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /амнистия @юзер [причина] (или /amnesty, или ответом на сообщение нарушителя,
    или /амнистия все для общегородской амнистии).
    Полное прощение нарушений:
    - Обнуление предупреждений (варнов) и служебных выговоров
    - Аннулирование активных/просроченных штрафов (статус cancelled)
    - Снятие розыска (is_wanted = False)
    - Восстановление из статуса «Враг города» (is_enemy = False, возврат статуса Гражданина)
    - Размут и разбан в Telegram супергруппе
    - Запись в протокол суда (реестр правонарушений)
    """
    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    if not is_admin and message.chat.type in ("group", "supergroup") and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Объявлять амнистию вправе только Администрация города (уровни 4-5) и Владелец!")
        return

    raw_args = message.text.split()[1:] if message.text else []

    target_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else settings.MAIN_CHAT_ID
    if not target_chat_id or target_chat_id > 0:
        known = await session.scalar(select(ChatSettings.chat_id).where(ChatSettings.chat_id < 0).limit(1))
        if known:
            target_chat_id = known

    # 1. Режим общегородской амнистии (/амнистия все / /амнистия all)
    if raw_args and raw_args[0].lower() in ("все", "all", "всё"):
        manifest_text = " ".join(raw_args[1:]).strip() if len(raw_args) > 1 else "Всеобщая городская амнистия"

        # Аннулируем все активные и просроченные штрафы
        fines_res = await session.scalars(
            select(Fine).where(Fine.status.in_([FineStatus.ACTIVE.value, FineStatus.OVERDUE.value]))
        )
        all_fines = list(fines_res.all())
        for f in all_fines:
            f.status = FineStatus.CANCELLED.value

        # Снимаем варны, выговоры и розыск со всех граждан + снимаем муты и баны в Telegram
        users_res = await session.scalars(
            select(User).where((User.warns_count > 0) | (User.reprimands_count > 0) | (User.is_wanted.is_(True)) | (User.is_enemy.is_(True)))
        )
        affected_users = list(users_res.all())
        for u in affected_users:
            u.warns_count = 0
            u.reprimands_count = 0
            u.is_wanted = False
            if u.is_enemy:
                u.is_enemy = False
                u.enemy_reason = None
                if u.role_level == PositionLevel.ENEMY.value:
                    u.role_level = PositionLevel.CITIZEN.value

            if target_chat_id and target_chat_id < 0 and message.bot:
                try:
                    await message.bot.restrict_chat_member(
                        chat_id=target_chat_id,
                        user_id=u.telegram_id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_audios=True,
                            can_send_documents=True,
                            can_send_photos=True,
                            can_send_videos=True,
                            can_send_video_notes=True,
                            can_send_voice_notes=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_invite_users=True,
                        ),
                        use_independent_chat_permissions=True,
                    )
                except Exception:
                    try:
                        await message.bot.restrict_chat_member(
                            chat_id=target_chat_id,
                            user_id=u.telegram_id,
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_audios=True,
                                can_send_documents=True,
                                can_send_photos=True,
                                can_send_videos=True,
                                can_send_video_notes=True,
                                can_send_voice_notes=True,
                                can_send_polls=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True,
                            ),
                        )
                    except Exception:
                        pass
                try:
                    await message.bot.unban_chat_member(
                        chat_id=target_chat_id,
                        user_id=u.telegram_id,
                        only_if_banned=True,
                    )
                except Exception:
                    pass

        await session.commit()

        # Лог в протокол
        await LawService.log_punishment(
            session=session,
            target_user=db_user,
            issuer_user=db_user,
            punishment_type=PunishmentType.AMNESTY,
            law_article=None,
            duration_seconds=None,
            reason=f"Всеобщая амнистия: {manifest_text}",
        )

        manifest = (
            "🕊 <b>ОБЩАЯ ГОРОДСКАЯ АМНИСТИЯ ОБЪЯВЛЕНА!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏛 <b>Инициатор:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"📝 <b>Манифест:</b> {manifest_text}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Обнулены предупреждения и выговоры у <b>{len(affected_users)}</b> жителей\n"
            f"✅ Аннулировано <b>{len(all_fines)}</b> открытых штрафов казны\n"
            "✅ Сняты все ориентировки городского розыска и муты в чате\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Ратуша города объявляет новый отсчет правопорядка.</i>"
        )
        await message.answer(manifest)

        if settings.LOG_CHAT_ID and message.bot:
            try:
                await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=manifest)
            except Exception:
                pass
        return

    # 2. Индивидуальная амнистия жителя
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "🕊 <b>ГОРОДСКАЯ АМНИСТИЯ</b>\n\n"
            "Использование:\n"
            "• <code>/амнистия @юзер [причина]</code>\n"
            "• <code>/амнистия [telegram_id / ник] [причина]</code>\n"
            "• Ответом на сообщение: <code>/амнистия [причина]</code>\n"
            "• Всеобщая амнистия: <code>/амнистия все [манифест]</code>\n\n"
            "<i>Амнистия снимает предупреждения, выговоры, списывает штрафы, снимает розыск, "
            "восстанавливает гражданские права и разблокирует в чате.</i>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Городская амнистия и помилование"

    old_warns = target_user.warns_count
    old_reps = getattr(target_user, "reprimands_count", 0)
    target_user.warns_count = 0
    target_user.reprimands_count = 0
    target_user.is_wanted = False

    was_enemy = target_user.is_enemy
    if target_user.is_enemy:
        target_user.is_enemy = False
        target_user.enemy_reason = None
        if target_user.role_level == PositionLevel.ENEMY.value:
            target_user.role_level = PositionLevel.CITIZEN.value

    # Аннулируем штрафы
    fines_query = select(Fine).where(
        Fine.user_id == target_user.id,
        Fine.status.in_([FineStatus.ACTIVE.value, FineStatus.OVERDUE.value])
    )
    user_fines = (await session.scalars(fines_query)).all()
    for f in user_fines:
        f.status = FineStatus.CANCELLED.value

    # Разблокируем в чате Telegram (размут + разбан)
    telegram_unmute_status = "снят ✅"

    # Если вызов сделан в группе и есть message.chat.restrict
    if message.chat.type in ("group", "supergroup") and hasattr(message.chat, "restrict"):
        try:
            await message.chat.restrict(
                user_id=target_user.telegram_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                ),
            )
        except Exception:
            try:
                await message.chat.restrict(
                    user_id=target_user.telegram_id,
                    permissions=ChatPermissions(can_send_messages=True),
                )
            except Exception as e2:
                telegram_unmute_status = f"ошибка ({e2})"
                logger.warning("Не удалось снять мут через message.chat: %s", e2)

        try:
            await message.chat.unban(user_id=target_user.telegram_id, only_if_banned=True)
        except Exception as e:
            logger.debug("Не удалось разбанить в чате: %s", e)

    # Если вызов сделан из ЛС или message.bot доступен для целевого супергруппового чата
    elif message.bot and target_chat_id and target_chat_id < 0:
        try:
            await message.bot.restrict_chat_member(
                chat_id=target_chat_id,
                user_id=target_user.telegram_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                ),
                use_independent_chat_permissions=True,
            )
        except Exception:
            try:
                await message.bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=target_user.telegram_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
            except Exception as e2:
                telegram_unmute_status = f"ошибка ({e2})"
                logger.warning("Не удалось снять мут в Telegram для %s: %s", target_user.telegram_id, e2)

        try:
            await message.bot.unban_chat_member(
                chat_id=target_chat_id,
                user_id=target_user.telegram_id,
                only_if_banned=True,
            )
        except Exception as e:
            logger.debug("Не удалось разбанить в Telegram для %s: %s", target_user.telegram_id, e)

    # Запись в судебный реестр
    await LawService.log_punishment(
        session=session,
        target_user=target_user,
        issuer_user=db_user,
        punishment_type=PunishmentType.AMNESTY,
        law_article=None,
        duration_seconds=None,
        reason=f"Городская амнистия: {reason}",
    )
    await session.commit()

    enemy_line = "✅ Снят статус «Враг города» (гражданство восстановлено)\n" if was_enemy else ""
    reps_line = f"✅ Аннулировано выговоров: <b>{old_reps}</b>\n" if old_reps > 0 else ""

    verdict_card = (
        "🕊 <b>АКТ ГОРОДСКОЙ АМНИСТИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Гражданин:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
        f"🏛 <b>Амнистировал:</b> {db_user.full_name} ({db_user.position_title})\n"
        f"📝 <b>Основание:</b> {reason}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Аннулировано предупреждений: <b>{old_warns}</b>\n"
        f"{reps_line}"
        f"✅ Списано непогашенных штрафов: <b>{len(user_fines)}</b>\n"
        "✅ Снят статус розыска\n"
        f"{enemy_line}"
        f"🔊 Мут и ограничения чата: <b>{telegram_unmute_status}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Судебные претензии сняты. Запись внесена в городской реестр.</i>"
    )
    await message.answer(verdict_card)

    if settings.LOG_CHAT_ID and message.bot:
        try:
            await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=verdict_card)
        except Exception:
            pass


@router.message(Command("выговор", "reprimand"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("выговор", "reprimand", "/выговор", "/reprimand"))))
async def cmd_reprimand(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /выговор @юзер [причина] (или /reprimand, или ответом на сообщение служащего)
    Вынесение официального выговора. При получении 3 выговоров (3/3)
    бот автоматически отстраняет от должности (понижает до Гражданина)
    и отзывает права администратора чата.
    """
    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    if not is_admin and message.chat.type in ("group", "supergroup") and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Объявлять служебный выговор может только Администрация города (уровни 4-5) и Владелец!")
        return

    raw_args = message.text.split()[1:] if message.text else []
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "⚠️ <b>СЛУЖЕБНЫЙ ВЫГОВОР</b>\n\n"
            "Использование:\n"
            "• <code>/выговор @юзер [причина]</code>\n"
            "• <code>/выговор [telegram_id / ник] [причина]</code>\n"
            "• Ответом на сообщение служащего: <code>/выговор [причина]</code>\n\n"
            "<i>При получении 3-го выговора бот автоматически отстраняет служащего от должности и лишает полномочий.</i>"
        )
        return

    if db_user.id == target_user.id:
        await message.answer("🤷 Нельзя выносить выговор самому себе!")
        return

    if target_user.telegram_id == settings.OWNER_ID or (target_user.username and target_user.username.lower() == settings.OWNER_USERNAME.lower()):
        await message.answer("🚫 Овнер города обладает абсолютным иммунитетом от взысканий!")
        return

    is_owner = (db_user.telegram_id == settings.OWNER_ID or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower()))
    if not is_owner and db_user.role_level <= target_user.role_level:
        await message.answer("🚫 Нарушение субординации: нельзя выносить выговор равному или старшему по должности!")
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Служебное несоответствие и нарушение регламента"

    target_user.reprimands_count = getattr(target_user, "reprimands_count", 0) + 1

    if target_user.reprimands_count < 3:
        await LawService.log_punishment(
            session=session,
            target_user=target_user,
            issuer_user=db_user,
            punishment_type=PunishmentType.REPRIMAND,
            law_article=None,
            duration_seconds=None,
            reason=f"Служебный выговор ({target_user.reprimands_count}/3): {reason}",
        )
        await session.commit()

        card = (
            "⚠️ <b>ОФИЦИАЛЬНЫЙ СЛУЖЕБНЫЙ ВЫГОВОР</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Служащий:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
            f"🎖 <b>Должность:</b> {target_user.position_title} (Уровень {target_user.role_level})\n"
            f"👮 <b>Вынес выговор:</b> {db_user.full_name} ({db_user.position_title})\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"📊 <b>Выговоры:</b> <b>{target_user.reprimands_count} / 3</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>Внимание: при получении 3-го выговора служащий автоматически отстраняется от занимаемой должности!</i>"
        )
        await message.answer(card)

        if settings.LOG_CHAT_ID and message.bot:
            try:
                await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=card)
            except Exception:
                pass
        return

    # 3-й выговор -> Автоматическое отстранение от должности
    old_title = target_user.position_title
    old_level = target_user.role_level
    target_user.role_level = PositionLevel.CITIZEN.value
    target_user.reprimands_count = 0  # Сброс счетчика после отстранения

    # Отзываем права Telegram-администратора, если бот в супергруппе
    if message.chat.type in ("group", "supergroup"):
        try:
            await message.chat.promote(
                user_id=target_user.telegram_id,
                can_manage_chat=False,
                can_change_info=False,
                can_delete_messages=False,
                can_invite_users=False,
                can_restrict_members=False,
                can_pin_messages=False,
                can_promote_members=False,
                can_manage_video_chats=False,
                can_post_stories=False,
                can_edit_stories=False,
                can_delete_stories=False,
            )
        except Exception as e:
            logger.debug("Не удалось разжаловать в чате: %s", e)

    await LawService.log_punishment(
        session=session,
        target_user=target_user,
        issuer_user=db_user,
        punishment_type=PunishmentType.DISMISSAL,
        law_article=None,
        duration_seconds=None,
        reason=f"Отстранение от должности за 3/3 выговоров: {reason}",
    )
    await session.commit()

    card = (
        "🚨 <b>СЛУЖЕБНОЕ ОТСТРАНЕНИЕ ОТ ДОЛЖНОСТИ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Служащий:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
        f"🎖 <b>Бывшая должность:</b> {old_title} (Уровень {old_level})\n"
        f"👮 <b>Вынес 3-й выговор:</b> {db_user.full_name} ({db_user.position_title})\n"
        f"📝 <b>Причина:</b> {reason}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "❌ <b>Лимит выговоров исчерпан (3/3)!</b>\n"
        f"⚡ <b>РЕШЕНИЕ:</b> Гражданин <b>{target_user.full_name}</b> отстранен от должности <b>«{old_title}»</b> и переведен в статус <b>Гражданина</b> (Уровень 0).\n"
        "🔒 Полномочия блюстителя порядка и администратора отозваны.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Запись о служебном несоответствии внесена в протокол Ратуши.</i>"
    )
    await message.answer(card)

    if settings.LOG_CHAT_ID and message.bot:
        try:
            await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=card)
        except Exception:
            pass


@router.message(Command("снять_выговор", "unreprimand", "снятьвыговор"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("снять_выговор", "unreprimand", "снятьвыговор", "/снять_выговор", "/unreprimand", "/снятьвыговор"))))
async def cmd_unreprimand(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /снять_выговор @юзер [причина] — аннулирование одного служебного выговора.
    Доступно Администрации (уровни 4-5) и Владельцу.
    """
    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    if not is_admin and message.chat.type in ("group", "supergroup") and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Снимать выговоры вправе только Администрация города (уровни 4-5) и Владелец!")
        return

    raw_args = message.text.split()[1:] if message.text else []
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "Использование: <code>/снять_выговор @юзер [причина]</code>\n"
            "или ответом на сообщение служащего: <code>/снять_выговор [причина]</code>"
        )
        return

    current_reps = getattr(target_user, "reprimands_count", 0)
    if current_reps <= 0:
        await message.answer(f"ℹ️ У служащего <b>{target_user.full_name}</b> нет активных выговоров (0/3).")
        return

    target_user.reprimands_count = current_reps - 1
    reason = " ".join(remaining_args).strip() if remaining_args else "Ходатайство руководства / исправление"

    await LawService.log_punishment(
        session=session,
        target_user=target_user,
        issuer_user=db_user,
        punishment_type="снятие выговора",
        law_article=None,
        duration_seconds=None,
        reason=f"Снят выговор: {reason}",
    )
    await session.commit()

    await message.answer(
        f"✅ <b>СЛУЖЕБНЫЙ ВЫГОВОР АННУЛИРОВАН</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Служащий:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
        f"🏛 <b>Снял выговор:</b> {db_user.full_name} ({db_user.position_title})\n"
        f"📝 <b>Основание:</b> {reason}\n"
        f"📊 <b>Текущие выговоры:</b> <b>{target_user.reprimands_count} / 3</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


@router.message(Command("выдать_адм", "дать_адм", "promote", "makeadmin", "админ"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("выдать_адм", "дать_адм", "promote", "makeadmin", "админ", "/выдать_адм", "/дать_адм", "/promote", "/makeadmin", "/админ"))))
async def cmd_promote_admin(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /выдать_адм @юзер [титул] (или /promote)
    Выдача прав администратора чата Telegram.
    Доступно Администрации (уровни 4-5), Владельцу и создателю/администраторам супергруппы.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚠️ Выдача прав администратора возможна только в групповых чатах города!")
        return

    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    if not is_admin and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Назначать администраторов чата вправе только Администрация города и Владелец!")
        return

    raw_args = message.text.split()[1:] if message.text else []
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "Использование:\n"
            "• <code>/выдать_адм @юзер [титул]</code>\n"
            "• Ответом на сообщение: <code>/выдать_адм [титул]</code>"
        )
        return

    custom_title = " ".join(remaining_args).strip()[:16] if remaining_args else target_user.position_title[:16]

    try:
        await message.chat.promote(
            user_id=target_user.telegram_id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_invite_users=True,
            can_promote_members=False,
            can_change_info=False,
        )
        try:
            await message.chat.set_administrator_custom_title(
                user_id=target_user.telegram_id,
                custom_title=custom_title
            )
        except Exception:
            pass
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Ошибка при назначении в Telegram:</b> {e}\n\n"
            f"<i>Убедитесь, что у бота в Telegram включено право «Добавление администраторов» (Add Admins)!</i>"
        )
        return

    card = (
        "👑 <b>НАЗНАЧЕНИЕ АДМИНИСТРАТОРА ЧАТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Служащий:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
        f"🎖 <b>Должность в городе:</b> {target_user.position_title}\n"
        f"🏛 <b>Назначил:</b> {db_user.full_name} ({db_user.position_title})\n"
        f"🏷 <b>Титул в чате:</b> {custom_title}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Права администратора чата Telegram успешно предоставлены!"
    )
    await message.answer(card)

    if settings.LOG_CHAT_ID and message.bot:
        try:
            await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=card)
        except Exception:
            pass


@router.message(Command("снять_адм", "забрать_адм", "demote", "разжаловать"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("снять_адм", "забрать_адм", "demote", "разжаловать", "/снять_адм", "/забрать_адм", "/demote", "/разжаловать"))))
async def cmd_demote_admin(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /снять_адм @юзер [причина] (или /demote)
    Снятие прав администратора чата Telegram.
    Доступно Администрации (уровни 4-5), Владельцу и создателю супергруппы.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚠️ Снятие прав администратора возможно только в групповых чатах города!")
        return

    is_admin = (
        db_user.role_level >= PositionLevel.ADMINISTRATION.value
        or db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )

    if not is_admin and message.from_user:
        try:
            member = await message.chat.get_member(message.from_user.id)
            if getattr(member, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.answer("🚫 Отзывать права администратора чата вправе только Администрация города и Владелец!")
        return

    raw_args = message.text.split()[1:] if message.text else []
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.answer(
            "Использование:\n"
            "• <code>/снять_адм @юзер [причина]</code>\n"
            "• Ответом на сообщение: <code>/снять_адм [причина]</code>"
        )
        return

    reason = " ".join(remaining_args).strip() if remaining_args else "Решение руководства города"

    try:
        await message.chat.promote(
            user_id=target_user.telegram_id,
            can_manage_chat=False,
            can_change_info=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        )
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Ошибка при отзыве прав в Telegram:</b> {e}\n\n"
            f"<i>Убедитесь, что бот назначен создателем или администратором с правом управления админами.</i>"
        )
        return

    card = (
        "📉 <b>ОТЗЫВ ПРАВ АДМИНИСТРАТОРА ЧАТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Пользователь:</b> {target_user.full_name} (@{target_user.username or '—'})\n"
        f"🏛 <b>Отозвал права:</b> {db_user.full_name} ({db_user.position_title})\n"
        f"📝 <b>Причина:</b> {reason}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Права администратора чата Telegram успешно отозваны!"
    )
    await message.answer(card)

    if settings.LOG_CHAT_ID and message.bot:
        try:
            await message.bot.send_message(chat_id=settings.LOG_CHAT_ID, text=card)
        except Exception:
            pass
