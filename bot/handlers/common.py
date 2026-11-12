import logging
import inspect
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ChatMemberUpdated
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, ChatMember
from core.enums import PositionLevel
from config import settings
from bot.commands import setup_bot_commands, BOT_COMMANDS

logger = logging.getLogger("townbot.common")
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
        "• <code>/казна</code> — баланс Государственной казны города и бюджетная сводка\n"
        "• <code>/баланс [@юзер]</code> — банковский счет гражданина\n"
        "• <code>/перевод @юзер [сумма]</code> — банковский перевод средств другому жителю\n"
        "• <code>/аукционы</code> — государственные аукционы конфиската (ставки с кнопок)\n"
        "• <code>/апелляция [ID_дела]</code> (<code>/appeal</code>) — подача судебной апелляции в Зал Суда\n\n"
        "👮 <b>БЛЮСТИТЕЛИ И ПОМОЩНИКИ (Ранги 1–2):</b>\n"
        "• <code>/аукцион создать [лот] [цена] [мин]</code> — выставить конфискованное имущество на торги\n"
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
        "• <code>/зарплата @сотрудник [сумма] [причина]</code> (<code>/премия</code>) — выплата жалования из Государственной казны\n"
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


@router.message(Command("созвать", "all", "созыв", "summon", "everyone"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "созвать", "/созвать", "all", "/all", "@all", "созыв", "/созыв", "summon", "/summon", "everyone", "/everyone"
))))
async def cmd_summon_all(message: Message, session: AsyncSession, db_user: User):
    """
    Команда /созвать [тема] или /all [тема] — общий сбор жителей конкретного чата.
    Пингует участников группы СКРЫТО через невидимые гиперссылки без засорения текста юзернеймами.
    Учитывает только реальных участников текущей группы (ChatMember) и администраторов.
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
        await message.answer("🚫 Объявлять общий сбор жителей группы может только Администрация!")
        return

    args = (message.text or "").split(maxsplit=1)
    topic = args[1].strip() if len(args) > 1 else "Срочный сбор жителей города"

    chat_id = message.chat.id
    from db.models import ChatMember

    # 1. Синхронизируем администраторов чата Telegram в ChatMember
    try:
        get_admins_func = getattr(message.chat, "get_administrators", None)
        if callable(get_admins_func):
            res = get_admins_func()
            admins = (await res) if inspect.isawaitable(res) else res
            if isinstance(admins, (list, tuple)):
                for adm in admins:
                    if hasattr(adm, "user") and not getattr(adm.user, "is_bot", False):
                        adm_u = await session.scalar(select(User).where(User.telegram_id == adm.user.id))
                        if not adm_u:
                            adm_u = User(
                                telegram_id=adm.user.id,
                                username=adm.user.username,
                                full_name=adm.user.full_name,
                                role_level=PositionLevel.CITIZEN.value,
                            )
                            session.add(adm_u)
                            await session.flush()

                        cm = await session.scalar(
                            select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.telegram_id == adm.user.id)
                        )
                        if not cm:
                            session.add(ChatMember(chat_id=chat_id, user_id=adm_u.id, telegram_id=adm.user.id, is_active=True))
                        else:
                            cm.is_active = True
                await session.commit()
    except Exception as e:
        logger.debug(f"Не удалось актуализировать админов чата {chat_id}: {e}")

    # 2. Получаем участников именно ЭТОГО чата
    cm_query = select(ChatMember.telegram_id).where(
        ChatMember.chat_id == chat_id,
        ChatMember.is_active == True,
    ).distinct()
    chat_tg_ids = set((await session.scalars(cm_query)).all())

    # Исключаем самого инициатора сбора
    if message.from_user:
        chat_tg_ids.discard(message.from_user.id)

    # Дополнительно: если участников в базе еще мало, берем из администраторов текущего чата
    if not chat_tg_ids and message.from_user:
        try:
            admins = await message.chat.get_administrators()
            for a in admins:
                if not a.user.is_bot and a.user.id != message.from_user.id:
                    chat_tg_ids.add(a.user.id)
        except Exception:
            pass

    # 3. Формируем скрытые упоминания (Zero-Width Space HTML links: <a href="tg://user?id=...">&#8288;</a>)
    # Это триггерит персональный пуш-пинг в Telegram, но визуально не забивает текст юзернеймами!
    target_ids_list = list(chat_tg_ids)
    first_chunk = target_ids_list[:35]
    hidden_mentions = "".join([f'<a href="tg://user?id={uid}">&#8288;</a>' for uid in first_chunk])

    summon_text = (
        f"📢 <b>ОБЩИЙ СБОР ЖИТЕЛЕЙ ГОРОДА!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛 <b>Инициатор сбора:</b> {message.from_user.mention_html()} ({db_user.position_title})\n"
        f"📌 <b>Повестка:</b> <b>{topic}</b>\n\n"
        f"🔔 <b>Внимание:</b> всем гражданам и блюстителям порядка надлежит явиться в чат!\n"
        f"👥 Оповещено участников чата: <b>{len(target_ids_list)}</b> (скрытый вызов){hidden_mentions}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    sent = await message.answer(summon_text)
    try:
        await message.bot.pin_chat_message(message.chat.id, sent.message_id)
    except Exception:
        pass

    # Если участников больше 35, отправляем остальным скрытые пинги отдельными тихими пакетами
    if len(target_ids_list) > 35:
        remaining = target_ids_list[35:]
        for i in range(0, len(remaining), 35):
            chunk = remaining[i:i + 35]
            more_hidden = "".join([f'<a href="tg://user?id={uid}">&#8288;</a>' for uid in chunk])
            try:
                extra_msg = await message.answer(f"🔔 <i>Оповещение участников (пакет {i // 35 + 2})...</i>{more_hidden}")
                asyncio.create_task(auto_delete_messages(message.bot, message.chat.id, [extra_msg.message_id], delay=10.0))
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


@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated, session: AsyncSession):
    """
    Автоматический учет входа/выхода участников в группе (как в Ирисе):
    Фиксирует любого нового или вернувшегося пользователя в БД и ChatMember.
    """
    if event.chat.type not in ("group", "supergroup") or event.chat.id >= 0:
        return

    new_cm = event.new_chat_member
    if not new_cm or not new_cm.user or getattr(new_cm.user, "is_bot", False):
        return

    tg_user = new_cm.user
    status = getattr(new_cm, "status", "")
    is_active = status in ("member", "administrator", "creator", "restricted")

    user = await session.scalar(select(User).where(User.telegram_id == tg_user.id))
    if not user:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name or f"User {tg_user.id}",
            role_level=PositionLevel.CITIZEN.value,
            balance=5000,
            is_enemy=False,
        )
        session.add(user)
        await session.flush()
    else:
        if tg_user.username and user.username != tg_user.username:
            user.username = tg_user.username
        if tg_user.full_name and user.full_name != tg_user.full_name:
            user.full_name = tg_user.full_name

    cm = await session.scalar(
        select(ChatMember).where(
            ChatMember.chat_id == event.chat.id,
            ChatMember.telegram_id == user.telegram_id
        )
    )
    if not cm:
        session.add(ChatMember(
            chat_id=event.chat.id,
            user_id=user.id,
            telegram_id=user.telegram_id,
            is_active=is_active,
        ))
    else:
        cm.is_active = is_active
        if is_active:
            cm.last_seen_at = datetime.now(timezone.utc)
    await session.commit()


@router.my_chat_member()
async def on_my_chat_member_update(event: ChatMemberUpdated, session: AsyncSession):
    """
    Когда бота добавляют в группу или наделяют правами:
    Автоматически сканирует и сохраняет всех администраторов группы в базу данных.
    """
    if event.chat.type not in ("group", "supergroup") or event.chat.id >= 0:
        return

    new_status = getattr(event.new_chat_member, "status", "")
    if new_status in ("administrator", "member"):
        try:
            admins = await event.bot.get_chat_administrators(event.chat.id)
            for adm in admins:
                if adm.user and not getattr(adm.user, "is_bot", False):
                    adm_u = await session.scalar(select(User).where(User.telegram_id == adm.user.id))
                    if not adm_u:
                        adm_u = User(
                            telegram_id=adm.user.id,
                            username=adm.user.username,
                            full_name=adm.user.full_name,
                            role_level=PositionLevel.CITIZEN.value,
                            balance=5000,
                            is_enemy=False,
                        )
                        session.add(adm_u)
                        await session.flush()
                    cm = await session.scalar(
                        select(ChatMember).where(
                            ChatMember.chat_id == event.chat.id,
                            ChatMember.telegram_id == adm.user.id
                        )
                    )
                    if not cm:
                        session.add(ChatMember(
                            chat_id=event.chat.id,
                            user_id=adm_u.id,
                            telegram_id=adm.user.id,
                            is_active=True,
                        ))
                    else:
                        cm.is_active = True
            await session.commit()
        except Exception as e:
            logger.debug("Не удалось просканировать админов при добавлении бота: %s", e)


@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message, session: AsyncSession):
    """Служебное сообщение о вступлении участников в группу (захват профилей как в Ирисе)."""
    if message.chat.type not in ("group", "supergroup") or message.chat.id >= 0:
        return

    for tg_user in (message.new_chat_members or []):
        if not getattr(tg_user, "is_bot", False):
            user = await session.scalar(select(User).where(User.telegram_id == tg_user.id))
            if not user:
                user = User(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    full_name=tg_user.full_name or f"User {tg_user.id}",
                    role_level=PositionLevel.CITIZEN.value,
                    balance=5000,
                    is_enemy=False,
                )
                session.add(user)
                await session.flush()
            cm = await session.scalar(
                select(ChatMember).where(
                    ChatMember.chat_id == message.chat.id,
                    ChatMember.telegram_id == user.telegram_id
                )
            )
            if not cm:
                session.add(ChatMember(
                    chat_id=message.chat.id,
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    is_active=True,
                ))
            else:
                cm.is_active = True
                cm.last_seen_at = datetime.now(timezone.utc)
    await session.commit()


@router.message(Command("sync_users", "скан_чата", "обновить_жителей", "синхронизация", "sync_members"))
@router.message(F.text.func(lambda t: bool(t and t.lower().split()[0].split("@")[0] in (
    "sync_users", "/sync_users", "!sync_users",
    "скан_чата", "/скан_чата", "!скан_чата",
    "обновить_жителей", "/обновить_жителей",
    "синхронизация", "/синхронизация"
))))
async def cmd_sync_chat_users(message: Message, session: AsyncSession, db_user: User):
    """
    Команда сканирования и актуализации участников чата (как в Ирисе):
    Синхронизирует всех администраторов чата, актуализирует базу данных группы.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("⚠️ Команда доступна только в групповых чатах!")
        return

    is_admin = (
        db_user.government_rank >= 2
        or db_user.role_level >= PositionLevel.CHAT_WARDEN.value
        or db_user.telegram_id == settings.OWNER_ID
    )
    if not is_admin and message.from_user:
        try:
            m = await message.chat.get_member(message.from_user.id)
            if getattr(m, "status", "") in ("creator", "administrator"):
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await message.reply("🚫 Сканировать участников чата вправе только Администрация и Блюстители!")
        return

    status_msg = await message.reply("🔍 <i>Сканирование участников чата и актуализация базы данных...</i>")
    total_admins = 0

    try:
        admins = await message.chat.get_administrators()
        total_admins = len(admins)
        for adm in admins:
            if adm.user and not getattr(adm.user, "is_bot", False):
                adm_u = await session.scalar(select(User).where(User.telegram_id == adm.user.id))
                if not adm_u:
                    adm_u = User(
                        telegram_id=adm.user.id,
                        username=adm.user.username,
                        full_name=adm.user.full_name or f"User {adm.user.id}",
                        role_level=PositionLevel.CITIZEN.value,
                        balance=5000,
                        is_enemy=False,
                    )
                    session.add(adm_u)
                    await session.flush()
                cm = await session.scalar(
                    select(ChatMember).where(
                        ChatMember.chat_id == message.chat.id,
                        ChatMember.telegram_id == adm.user.id
                    )
                )
                if not cm:
                    session.add(ChatMember(
                        chat_id=message.chat.id,
                        user_id=adm_u.id,
                        telegram_id=adm.user.id,
                        is_active=True,
                    ))
                else:
                    cm.is_active = True
        await session.commit()
    except Exception as e:
        logger.warning(f"Ошибка при скан-синхронизации: {e}")

    total_in_group = await session.scalar(
        select(func.count(ChatMember.id)).where(ChatMember.chat_id == message.chat.id, ChatMember.is_active.is_(True))
    ) or 0

    await status_msg.edit_text(
        "👥 <b>СИНХРОНИЗАЦИЯ ЧАТА ЗАВЕРШЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Администраторов обнаружено: <b>{total_admins}</b>\n"
        f"📊 Всего зарегистрировано в группе: <b>{total_in_group}</b> участников\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Бот работает аналогично Ирису: он автоматически фиксирует каждого жителя, "
        "как только тот отправляет любое сообщение (текст, стикер, медиа) или заходит в группу.</i>"
    )



