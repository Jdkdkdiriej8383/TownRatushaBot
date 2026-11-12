import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import User, ChatSettings
from core.enums import PositionLevel
from core.hierarchy_service import HierarchyService
from core.topic_service import TopicService
from bot.utils import extract_target_user

logger = logging.getLogger("townbot.treasury")
router = Router(name="treasury_router")


@router.message(Command("казна", "treasury", "казны", "бюджет", "бюджет_города", "budget"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "казна", "/казна", "treasury", "/treasury", "бюджет", "/бюджет", "казны", "/казны"
))))
async def cmd_treasury(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /казна — Просмотр баланса Государственной казны города и статистики.
    Доступна всем жителям города для обеспечения открытости городского бюджета.
    """
    target_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else settings.MAIN_CHAT_ID
    if not target_chat_id or target_chat_id > 0:
        target_chat_id = await TopicService.get_primary_group_chat_id(session) or settings.MAIN_CHAT_ID

    chat_settings = None
    if target_chat_id:
        chat_settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == target_chat_id))

    if not chat_settings:
        chat_settings = ChatSettings(chat_id=target_chat_id or settings.MAIN_CHAT_ID or 0)
        session.add(chat_settings)
        await session.commit()

    treasury_val = chat_settings.treasury_balance or 0
    fines_val = chat_settings.total_fines_collected or 0
    salaries_val = chat_settings.total_salaries_paid or 0

    if treasury_val >= 200000:
        status_text = "🟢 Профицит (Казна наполнена)"
    elif treasury_val >= 50000:
        status_text = "🟡 Стабильный резерв"
    else:
        status_text = "🔴 Дефицит (Требуются поступления)"

    text = (
        "🏛️ <b>ГОСУДАРСТВЕННАЯ КАЗНА ГОРОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Текущий резерв:</b> <code>{treasury_val:,}</code> ₽\n"
        f"📥 <b>Собрано со штрафов и аукционов:</b> <code>{fines_val:,}</code> ₽\n"
        f"📤 <b>Выплачено зарплат и премий:</b> <code>{salaries_val:,}</code> ₽\n"
        f"📊 <b>Состояние бюджета:</b> {status_text}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚖️ <i>Бюджет города формируется из штрафов за правонарушения, пошлин "
        "и выручки от аукционов конфиската. Расходуется на жалование госслужащим и развитие инфраструктуры.</i>"
    )
    await message.reply(text)


@router.message(Command("баланс", "balance", "кошелек", "карман", "счет", "деньги"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "баланс", "/баланс", "balance", "/balance", "кошелек", "/кошелек", "карман", "/карман"
))))
async def cmd_balance(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /баланс [@юзер] — Просмотр личного счета гражданина в Банке города.
    """
    raw_args = (message.text or "").split()[1:]
    target_user, _ = await extract_target_user(message, session, raw_args)

    if not target_user:
        target_user = db_user

    balance_val = getattr(target_user, "balance", 5000) or 0
    user_handle = f"@{target_user.username}" if target_user.username else f"ID {target_user.telegram_id}"

    text = (
        "💳 <b>ГОСУДАРСТВЕННЫЙ БАНКОВСКИЙ СЧЕТ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Гражданин:</b> {target_user.full_name} ({user_handle})\n"
        f"🎖️ <b>Должность:</b> {target_user.position_title} (Ранг {target_user.government_rank})\n"
        f"💰 <b>Личный баланс:</b> <code>{balance_val:,}</code> ₽\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Для перевода другому жителю используйте:</i>\n"
        "<code>/перевод @username сумма [комментарий]</code>"
    )
    await message.reply(text)


@router.message(Command("зарплата", "премия", "salary", "bonus", "выплатить", "награда", "премировать"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "зарплата", "/зарплата", "премия", "/премия", "salary", "/salary", "bonus", "/bonus", "выплатить", "/выплатить"
))))
async def cmd_salary(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /зарплата @сотрудник <сумма> [причина] (или /премия, /выплатить).
    Выплата жалования или разовой премии сотруднику/гражданину из Государственной казны.
    Полномочия: Администрация (Ранг 3+), Мэрия (Ранг 4+) и Владелец города.
    """
    is_admin = (
        HierarchyService.is_owner(db_user)
        or db_user.government_rank >= 3
        or db_user.role_level >= PositionLevel.ADMINISTRATION.value
    )
    if not is_admin:
        await message.reply("🚫 <b>Отказано:</b> Распоряжаться казной и выплачивать жалование вправе только Администрация (Ранг 3+) и Мэр!")
        return

    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "💼 <b>ВЫПЛАТА ЖАЛОВАНИЯ И ПРЕМИЙ ИЗ КАЗНЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Использование:\n"
            "• <code>/зарплата @сотрудник 10000 За дежурство</code>\n"
            "• Или ответьте на сообщение сотрудника: <code>/премия 15000 Отличная служба</code>"
        )
        return

    if target_user.is_enemy:
        await message.reply("🚫 <b>Запрещено:</b> Врагам города заблокированы любые финансовые выплаты из государственной казны!")
        return

    if not remaining_args or not remaining_args[0].isdigit():
        await message.reply("⚠️ Укажите корректную сумму выплаты (целое число больше нуля)!\nПример: <code>/зарплата @username 10000</code>")
        return

    amount = int(remaining_args[0])
    if amount <= 0:
        await message.reply("⚠️ Сумма выплаты должна быть положительной!")
        return

    reason = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else "За добросовестную службу и вклад в развитие города"

    # Проверяем средства в казне
    target_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else settings.MAIN_CHAT_ID
    if not target_chat_id or target_chat_id > 0:
        target_chat_id = await TopicService.get_primary_group_chat_id(session) or settings.MAIN_CHAT_ID

    chat_settings = None
    if target_chat_id:
        chat_settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == target_chat_id))

    if not chat_settings:
        chat_settings = ChatSettings(chat_id=target_chat_id or settings.MAIN_CHAT_ID or 0)
        session.add(chat_settings)

    if (chat_settings.treasury_balance or 0) < amount:
        await message.reply(
            f"❌ <b>В Государственной казне недостаточно средств!</b>\n\n"
            f"Текущий резерв казны: <code>{chat_settings.treasury_balance:,}</code> ₽\n"
            f"Запрошено к выдаче: <code>{amount:,}</code> ₽\n\n"
            f"💡 Пополните казну сбором штрафов или проведением аукционов конфиската."
        )
        return

    # Списание с казны и начисление сотруднику
    chat_settings.treasury_balance -= amount
    chat_settings.total_salaries_paid = (chat_settings.total_salaries_paid or 0) + amount
    target_user.balance = (getattr(target_user, "balance", 5000) or 0) + amount

    await session.commit()

    recipient_handle = f"@{target_user.username}" if target_user.username else f"ID {target_user.telegram_id}"
    decree_text = (
        "🏛️ <b>ГОСУДАРСТВЕННЫЙ УКАЗ О ПРЕМИРОВАНИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Сотрудник:</b> {target_user.full_name} ({recipient_handle})\n"
        f"🎖️ <b>Должность:</b> {target_user.position_title} (Ранг {target_user.government_rank})\n"
        f"💰 <b>Сумма к выплате:</b> <code>+{amount:,}</code> ₽\n"
        f"📝 <b>Основание:</b> {reason}\n"
        f"👑 <b>Распорядитель казны:</b> {db_user.full_name}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Остаток в казне:</b> <code>{chat_settings.treasury_balance:,}</code> ₽\n"
        f"💳 <b>Новый баланс сотрудника:</b> <code>{target_user.balance:,}</code> ₽"
    )
    await message.reply(decree_text)

    # Уведомление в ЛС сотруднику, если возможно
    if message.bot and target_user.telegram_id:
        try:
            await message.bot.send_message(
                chat_id=target_user.telegram_id,
                text=(
                    f"🎉 <b>ВАМ НАЧИСЛЕНА ГОСУДАРСТВЕННАЯ ВЫПЛАТА!</b>\n\n"
                    f"💰 Сумма: <code>+{amount:,}</code> ₽\n"
                    f"📝 Причина: <i>{reason}</i>\n"
                    f"👑 Распорядитель: {db_user.full_name}\n\n"
                    f"Ваш текущий баланс: <code>{target_user.balance:,}</code> ₽"
                )
            )
        except Exception:
            pass


@router.message(Command("перевод", "pay_user", "перевести", "give_money", "send_money"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "перевод", "/перевод", "перевести", "/перевести", "pay_user", "/pay_user"
))))
async def cmd_transfer_money(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /перевод @юзер <сумма> [комментарий]
    Прямой межбанковский перевод средств между гражданами города.
    """
    raw_args = (message.text or "").split()[1:]
    target_user, remaining_args = await extract_target_user(message, session, raw_args)

    if not target_user:
        await message.reply(
            "💸 <b>БАНКОВСКИЙ ПЕРЕВОД МЕЖДУ ЖИТЕЛЯМИ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Использование:\n"
            "• <code>/перевод @username 2500 Возврат долга</code>\n"
            "• Или ответьте на сообщение жителя: <code>/перевод 1000 На чай</code>"
        )
        return

    if target_user.id == db_user.id:
        await message.reply("⚠️ Нельзя осуществлять перевод самому себе!")
        return

    if not remaining_args or not remaining_args[0].isdigit():
        await message.reply("⚠️ Укажите корректную сумму для перевода!\nПример: <code>/перевод @username 1000</code>")
        return

    amount = int(remaining_args[0])
    if amount <= 0:
        await message.reply("⚠️ Сумма перевода должна быть больше нуля!")
        return

    user_balance = getattr(db_user, "balance", 5000) or 0
    if user_balance < amount:
        await message.reply(
            f"❌ <b>Недостаточно средств на вашем счете!</b>\n"
            f"Ваш баланс: <code>{user_balance:,}</code> ₽\n"
            f"Требуется для перевода: <code>{amount:,}</code> ₽"
        )
        return

    comment = " ".join(remaining_args[1:]).strip() if len(remaining_args) > 1 else "Частный перевод"

    # Перевод
    db_user.balance = user_balance - amount
    target_user.balance = (getattr(target_user, "balance", 5000) or 0) + amount

    await session.commit()

    recipient_handle = f"@{target_user.username}" if target_user.username else f"ID {target_user.telegram_id}"
    await message.reply(
        "✅ <b>ПЕРЕВОД УСПЕШНО ВЫПОЛНЕН</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 <b>Отправитель:</b> {db_user.full_name}\n"
        f"📥 <b>Получатель:</b> {target_user.full_name} ({recipient_handle})\n"
        f"💰 <b>Сумма:</b> <code>{amount:,}</code> ₽\n"
        f"💬 <b>Назначение:</b> {comment}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Ваш новый остаток:</b> <code>{db_user.balance:,}</code> ₽"
    )

    if message.bot and target_user.telegram_id:
        try:
            await message.bot.send_message(
                chat_id=target_user.telegram_id,
                text=(
                    f"💳 <b>Вам поступил банковский перевод!</b>\n\n"
                    f"👤 От: {db_user.full_name}\n"
                    f"💰 Сумма: <code>+{amount:,}</code> ₽\n"
                    f"💬 Комментарий: <i>{comment}</i>\n\n"
                    f"Ваш баланс: <code>{target_user.balance:,}</code> ₽"
                )
            )
        except Exception:
            pass
