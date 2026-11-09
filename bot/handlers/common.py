from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.enums import PositionLevel
from config import settings

router = Router(name="common_router")


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User):
    await message.answer(
        f"🏛 <b>ДОБРО ПОЖАЛОВАТЬ В РОЛЕВОЙ ГОРОД!</b>\n\n"
        f"Приветствуем вас, гражданин <b>{db_user.full_name}</b>!\n"
        f"Ваша текущая должность: <b>{db_user.position_title}</b> (Уровень {db_user.role_level}).\n\n"
        f"Этот бот обеспечивает правопорядок, исполнение Городского Свода Законов "
        f"и заменяет устаревшие чат-менеджеры.\n\n"
        f"📋 <b>Основные команды:</b>\n"
        f"• <code>/паспорт</code> — ваш электронный паспорт и профиль\n"
        f"• <code>/ник [Minecraft-ник]</code> — привязка игрового никнейма\n"
        f"• <code>/законы</code> — реестр статей Свода Законов\n"
        f"• <code>/закон [номер]</code> — карточка статьи с регламентом\n"
        f"• <code>/досье</code> — судебная история и открытые штрафы\n"
        f"• <code>/help</code> — полный список возможностей"
    )


@router.message(Command("help", "помощь"))
async def cmd_help(message: Message, db_user: User):
    help_text = (
        "📜 <b>СПРАВОЧНИК КОМАНД ГОРОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>Для всех жителей:</b>\n"
        "• <code>/паспорт</code> — паспорт гражданина\n"
        "• <code>/ник [Minecraft_ник]</code> — привязка/смена ника\n"
        "• <code>/отпуск [1-30]</code> — оформление отпуска (ст. 3.25)\n"
        "• <code>/законы</code> — оглавление Свода Законов\n"
        "• <code>/закон [номер]</code> — просмотр диспозиции и санкции\n"
        "• <code>/досье [@юзер]</code> — выписка правонарушений\n"
        "• <code>/оплатить [id_штрафа]</code> — погашение штрафа\n\n"
        "🎭 <b>Ролевые действия (РП):</b>\n"
        "• <code>отдать честь [@юзер]</code>\n"
        "• <code>пожать руку [@юзер]</code>\n"
        "• <code>арестовать [@юзер]</code> <i>(для блюстителей)</i>\n"
        "• <code>досмотреть [@юзер]</code> <i>(для блюстителей)</i>\n"
        "• <code>выдать повестку [@юзер]</code> <i>(для блюстителей)</i>\n\n"
        "👮 <b>Для Блюстителей (субординация строго соблюдается!):</b>\n"
        "• <code>/наказать @юзер [статья]</code> — наложение санкции по закону\n"
        "• <code>/штраф @юзер [статья] [сумма] [причина]</code> — выписка тикета (таймер 48ч)\n\n"
        "🏛 <b>Для Администрации (уровни 4-5):</b>\n"
        "• <code>/созвать [тема]</code> (<code>/all</code>) — общий сбор жителей чата\n"
        "• <code>/амнистия @юзер [причина]</code> (<code>/amnesty</code>) — городская амнистия\n"
        "• <code>/закон_ред [номер] [новый_текст]</code> — редакция закона\n"
        "• <code>/должность @юзер [0-5]</code> — изменение должности жителя\n"
        "• <code>/ник @юзер [ник]</code> — принудительная привязка ника жителю\n"
        "• <code>/референдум [номер] [поправка]</code> — всеобщее голосование\n"
        "• <code>/присяжные @юзер [номер] [обвинение]</code> — суд присяжных\n"
        "• <code>/регуляторы</code> — сводка прав и защит чата\n"
        "• <code>/антикапс</code>, <code>/спам</code>, <code>/ссылки</code> [вкл/выкл] — переключение фильтров\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(help_text)


@router.message(Command("созвать", "all", "созыв", "summon"))
@router.message(F.text.lower().startswith("созвать всех"))
@router.message(F.text.lower() == "созвать")
async def cmd_summon_all(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /созвать [тема] или /all [тема] — общий сбор жителей города в чате.
    Доступно Администрации (уровни 4-5), Овнеру и Администраторам чата в Telegram.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚠️ Команда общего сбора <code>/созвать</code> доступна только в групповых чатах города!")
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
        await message.answer("🚫 Объявлять общий сбор жителей города может только Администрация!")
        return

    args = (message.text or "").split(maxsplit=1)
    topic = args[1].strip() if len(args) > 1 else "Срочный сбор жителей города"

    # Получаем список зарегистрированных жителей с никнеймами
    users_res = await session.scalars(
        select(User).where(User.username.isnot(None), User.is_enemy.is_(False))
    )
    citizens = list(users_res.all())

    mentions_text = ""
    if citizens:
        usernames = [f"@{u.username}" for u in citizens if u.username and u.telegram_id != message.from_user.id]
        if usernames:
            mentions_text = "\n\n🔔 " + " ".join(usernames[:35])

    summon_text = (
        f"📢 <b>ОБЩИЙ СБОР ЖИТЕЛЕЙ ГОРОДА!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛 <b>Инициатор сбора:</b> {message.from_user.mention_html()} ({db_user.position_title})\n"
        f"📌 <b>Повестка:</b> <b>{topic}</b>\n\n"
        f"🔔 Всем гражданам и блюстителям порядка надлежит явиться в чат Ратуши!"
        f"{mentions_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    sent = await message.answer(summon_text)
    try:
        await message.bot.pin_chat_message(message.chat.id, sent.message_id)
    except Exception:
        pass
