from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from core.enums import PositionLevel
from config import settings
from bot.commands import setup_bot_commands, BOT_COMMANDS

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
    user_rank = db_user.government_rank
    user_title = db_user.position_title

    help_text = (
        "🏛 <b>СПРАВОЧНИК СИСТЕМЫ ГОСУДАРСТВЕННОЙ АДМИНИСТРАЦИИ</b>\n"
        f"Ваш статус: <b>{user_title}</b> (Ранг {user_rank})\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>ТАБЕЛЬ О РАНГАХ И СУБОРДИНАЦИЯ:</b>\n"
        "• <b>Ранг 4:</b> Высшая администрация (Мэр, Премьер-министр, Конституционный судья)\n"
        "• <b>Ранг 3:</b> Зам. мэра, Министр, Судья\n"
        "• <b>Ранг 2:</b> Блюститель (Старший модератор)\n"
        "• <b>Ранг 1:</b> Помощник (Хелпер / Младший модератор)\n"
        "• <b>Ранг 0:</b> Гражданин (Житель города)\n"
        "<i>Правило субординации: Ранг_Инициатора > Ранг_Цели. Старшие неприкосновенны!</i>\n\n"
        "👤 <b>ДЛЯ ВСЕХ ГРАЖДАН (Ранг 0+):</b>\n"
        "• <code>/паспорт</code> (<code>/profile</code>) — электронный паспорт, статус, игровой ник\n"
        "• <code>/ник [Minecraft_ник]</code> — привязать или изменить игровой никнейм\n"
        "• <code>/report [причина]</code> (<code>!жб</code>) — конфиденциальная жалоба на нарушение (ответом на сообщение или <code>/report @user [причина]</code>)\n"
        "• <code>/приемная</code> (<code>/ticket_panel</code>) — Государственная Приемная (подача обращений и тикетов)\n"
        "• <code>/отпуск [1-30]</code> — оформление временного отпуска (ст. 3.25)\n"
        "• <code>/законы</code> — оглавление и реестр Городского Свода Законов\n"
        "• <code>/закон [номер]</code> — карточка статьи, санкции и регламент\n"
        "• <code>/досье [@юзер]</code> — судебно-следственная выписка и открытые штрафы\n"
        "• <code>/оплатить [ID_штрафа]</code> — погашение назначенного штрафа\n"
        "• <code>/апелляция [ID_дела]</code> (<code>/appeal</code>) — подача судебной апелляции в Зал Суда\n\n"
        "👮 <b>БЛЮСТИТЕЛИ И ПОМОЩНИКИ (Ранги 1–2):</b>\n"
        "• <code>/warn [@юзер|reply] [причина]</code> — выдать предупреждение (3 варна = автокик/мут)\n"
        "• <code>/unwarn [@юзер|reply]</code> — снять предупреждение\n"
        "• <code>/mute [@юзер|reply] [время] [причина]</code> — ограничение переписки (Помощник: до 2ч, Блюститель: до 24ч)\n"
        "• <code>/unmute [@юзер|reply]</code> — досрочное снятие ограничения переписки\n"
        "• <code>/clear [1-100]</code> (<code>/del</code>) — служебное удаление спама и сообщений\n"
        "• <code>/наказать @юзер [статья]</code> — наложение санкции строго по закону\n"
        "• <code>/штраф @юзер [статья] [сумма] [причина]</code> — выписка официального штрафа (48ч на оплату)\n"
        "• <code>/принять [ID]</code> (<code>/claim</code>) — взять тикет гражданина в работу\n"
        "• <code>/передать [ID] [категория]</code> (<code>/transfer</code>) — перенаправить тикет в другой отдел\n"
        "• <code>/закрыть [ID] [вердикт]</code> (<code>/close</code>) — закрыть тикет с вердиктом заявителю\n\n"
        "🏛 <b>АДМИНИСТРАЦИЯ И СУД (Ранги 3–5):</b>\n"
        "• <code>/ban [@юзер|reply] [время] [причина]</code> — санкционированное изгнание (бан) из города\n"
        "• <code>/unban [@юзер|ID]</code> — городское помилование и разбан\n"
        "• <code>/кик [@юзер|reply] [причина]</code> — исключение нарушителя из группы\n"
        "• <code>/суд</code> (<code>/court</code>) — регламент судебных заседаний и апелляций\n"
        "• <code>/вердикт [ID_дела] [приговор]</code> — вынесение окончательного судебного вердикта\n"
        "• <code>/указ [текст]</code> (<code>/decree</code>) — публикация государственного указа (Мэр / Кабмин)\n"
        "• <code>/setrole [@юзер|reply] [должность]</code> — назначение государственной должности по табелю\n"
        "• <code>/разжаловать [@юзер|reply]</code> (<code>/demote</code>) — отстранение от должности в Граждане\n"
        "• <code>/staff</code> (<code>/состав</code>) — табель действующего состава администрации по рангам\n"
        "• <code>/settopic [тип]</code> — привязка функциональных тем форума (community, reports, tickets, court, admin, decrees, logs)\n"
        "• <code>/report_settings</code> (<code>/настройки_жалоб</code>) — конфигурация маршрутизации (ЛС/топик) и анонимности жалоб\n"
        "• <code>/созвать [тема]</code> (<code>/all</code>) — общий сбор жителей чата\n"
        "• <code>/выговор @юзер [причина]</code> — служебный выговор должностному лицу (3/3 — отстранение)\n"
        "• <code>/снять_выговор @юзер</code> — аннулировать выговор\n"
        "• <code>/амнистия [@юзер|all]</code> — городская амнистия (очистка варнов/штрафов)\n"
        "• <code>/закон_ред [номер] [текст]</code> — редакция статьи Городского Свода Законов\n"
        "• <code>/регуляторы</code> — сводка защитных систем чата и ролевых лимитов\n"
        "• <code>/антикапс</code>, <code>/спам</code>, <code>/ссылки</code> [вкл/выкл] — управление автоматическими фильтрами\n"
        "• <code>/обновить_меню</code> (<code>/sync_menu</code>) — синхронизация меню команд с серверами Telegram\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎭 <b>Ролевые действия (РП):</b>\n"
        "• <code>отдать честь [@юзер]</code> • <code>пожать руку [@юзер]</code>\n"
        "• <code>арестовать [@юзер]</code> • <code>досмотреть [@юзер]</code> • <code>выдать повестку [@юзер]</code>"
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


@router.message(Command("обновить_меню", "sync_menu", "update_menu", "обновитьменю", "menu_sync"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("обновить_меню", "sync_menu", "update_menu", "обновитьменю", "/обновить_меню", "/sync_menu", "/update_menu", "/обновитьменю"))))
async def cmd_sync_menu(message: Message, db_user: User):
    """
    Команда /обновить_меню (или /sync_menu) — принудительно обновляет меню команд в Telegram.
    Доступна Администрации (уровни 4-5), Владельцу и создателям/администраторам групп.
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
        await message.answer("🚫 Обновлять меню команд Telegram может только Администрация города!")
        return

    status_msg = await message.answer("⏳ <i>Синхронизация официального меню команд с серверами Telegram...</i>")
    try:
        count = await setup_bot_commands(message.bot)
        await status_msg.edit_text(
            "✅ <b>МЕНЮ КОМАНД TELEGRAM УСПЕШНО ОБНОВЛЕНО!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Зарегистрировано команд: <b>{count}</b>\n"
            "🌐 Области видимости:\n"
            "  • По умолчанию (Default)\n"
            "  • Личные сообщения (Private Chats)\n"
            "  • Группы и Супергруппы (Group Chats)\n"
            "  • Администраторы чатов (Chat Administrators)\n"
            "🇷🇺 Языковые схемы: Default + RU\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Совет: если кнопка «Меню» или список команд при вводе «/» не обновились сразу, "
            "перезапустите клиент Telegram или очистите его локальный кэш.</i>"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Ошибка при обновлении меню команд:</b> {e}")


@router.message(Command("сброс_бд", "reset_db", "wipe_db", "пересоздать_бд"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in ("сброс_бд", "reset_db", "wipe_db", "пересоздать_бд", "/сброс_бд", "/reset_db", "/wipe_db", "/пересоздать_бд"))))
async def cmd_reset_database(message: Message, db_user: User):
    """
    Команда полного сброса и пересоздания всех таблиц в Supabase.
    Доступна ИСКЛЮЧИТЕЛЬНО Овнеру города (OWNER_ID).
    Требует обязательного подтверждения: /сброс_бд ПОДТВЕРЖДАЮ
    """
    is_owner = (
        db_user.telegram_id == settings.OWNER_ID
        or (db_user.username and db_user.username.lower() == settings.OWNER_USERNAME.lower())
    )
    if not is_owner:
        await message.answer("🚫 Команда полного сброса базы данных доступна исключительно Владельцу города!")
        return

    raw_args = message.text.split()[1:] if message.text else []
    if not raw_args or raw_args[0].upper() not in ("ПОДТВЕРЖДАЮ", "CONFIRM", "YES"):
        await message.answer(
            "⚠️ <b>ВНИМАНИЕ! КРИТИЧЕСКОЕ ДЕЙСТВИЕ!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Эта команда <b>полностью удалит все таблицы</b> в Supabase (пользователи, штрафы, история, предупреждения) "
            "и пересоздаст их с нуля с чистым каноническим наполнением (законы, регуляторы, овнер)!\n\n"
            "Чтобы подтвердить операцию, отправьте команду:\n"
            "<code>/сброс_бд ПОДТВЕРЖДАЮ</code>"
        )
        return

    status_msg = await message.answer("⏳ <i>Выполняется каскадная очистка Supabase и пересоздание всех таблиц...</i>")
    try:
        from db.seed import seed_database
        await seed_database(force_wipe=True)
        await status_msg.edit_text(
            "♻️ <b>БАЗА ДАННЫХ SUPABASE ПОЛНОСТЬЮ ОЧИЩЕНА И ПЕРЕСОЗДАНА!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Удалены все старые таблицы, представления и типы\n"
            "✅ Созданы заново таблицы: <code>users</code>, <code>regulators</code>, <code>laws</code>, <code>fines</code>, <code>punishments</code>, <code>chat_settings</code>\n"
            "✅ Зарегистрирован Овнер города (@DivniDed)\n"
            "✅ Загружен полный реестр статей Свода Законов и матрица регуляторов\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>База данных готова к чистой работе с нуля.</i>"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Ошибка при сбросе базы данных:</b> {e}")


