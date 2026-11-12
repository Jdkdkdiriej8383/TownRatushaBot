import logging
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)

logger = logging.getLogger("townbot.commands")

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу с ботом"),
    BotCommand(command="help", description="Справка по командам (/помощь)"),
    BotCommand(command="passport", description="Паспорт гражданина (/паспорт)"),
    BotCommand(command="profile", description="Профиль гражданина (/профиль)"),
    BotCommand(command="nick", description="Привязать Minecraft ник (/ник)"),
    BotCommand(command="vacation", description="Оформить отпуск / вернуться (/отпуск)"),
    BotCommand(command="position", description="Управление должностями (/должность)"),
    BotCommand(command="laws", description="Полный Свод Законов (/законы)"),
    BotCommand(command="law", description="Посмотреть статью закона (/закон)"),
    BotCommand(command="edit_law", description="Редактировать статью (/закон_ред)"),
    BotCommand(command="dossier", description="Судебно-следственное досье (/досье)"),
    BotCommand(command="punish", description="Наказать нарушителя (/наказать)"),
    BotCommand(command="fine", description="Выписать штраф (/штраф)"),
    BotCommand(command="pay", description="Оплатить штраф (/оплатить)"),
    BotCommand(command="amnesty", description="Городская амнистия (/амнистия)"),
    BotCommand(command="all", description="Созвать всех жителей в чате (/созвать)"),
    BotCommand(command="reprimand", description="Служебный выговор (/выговор)"),
    BotCommand(command="unreprimand", description="Снять выговор (/снять_выговор)"),
    BotCommand(command="promote", description="Выдать права админа чата (/выдать_адм)"),
    BotCommand(command="demote", description="Снять с должности / админки (/разжаловать)"),
    BotCommand(command="referendum", description="Общегородской референдум (/референдум)"),
    BotCommand(command="jury", description="Суд присяжных (/присяжные)"),
    BotCommand(command="regulators", description="Регуляторы и защиты чата (/регуляторы)"),
    BotCommand(command="anticaps", description="Регулятор антикапса (/антикапс)"),
    BotCommand(command="antispam", description="Регулятор медиа-спама (/спам)"),
    BotCommand(command="antilinks", description="Регулятор ссылок и рекламы (/ссылки)"),
    BotCommand(command="report", description="Подать жалобу на нарушителя (/репорт, !жб)"),
    BotCommand(command="report_settings", description="Настройки системы жалоб (/настройки_жалоб)"),
    BotCommand(command="ticket_panel", description="Панель государственной приемной (/приемная)"),
    BotCommand(command="claim", description="Взять обращение в работу (/принять)"),
    BotCommand(command="transfer", description="Перенаправить обращение (/передать)"),
    BotCommand(command="close", description="Закрыть обращение с вердиктом (/закрыть)"),
    BotCommand(command="warn", description="Выдать предупреждение (/варн)"),
    BotCommand(command="unwarn", description="Снять предупреждение (/анварн)"),
    BotCommand(command="mute", description="Ограничить переписку (/мут)"),
    BotCommand(command="unmute", description="Снять ограничение переписки (/размут)"),
    BotCommand(command="kick", description="Исключить из чата (/кик)"),
    BotCommand(command="ban", description="Изгнание из города / бан (/бан)"),
    BotCommand(command="unban", description="Снять бан / помиловать (/разбан)"),
    BotCommand(command="clear", description="Очистить сообщения чата (/del)"),
    BotCommand(command="appeal", description="Подать судебную апелляцию (/апелляция)"),
    BotCommand(command="verdict", description="Вынести судебный вердикт (/вердикт)"),
    BotCommand(command="court", description="Зал государственного суда (/суд)"),
    BotCommand(command="setrole", description="Назначить государственную должность (/роль)"),
    BotCommand(command="staff", description="Государственный аппарат по рангам (/состав)"),
    BotCommand(command="decree", description="Государственный указ Мэра/Премьера (/указ)"),
    BotCommand(command="settopic", description="Привязать топик форума (/топик)"),
    BotCommand(command="network", description="Сетка чатов и федерация (/сетка)"),
    BotCommand(command="bc", description="Глобальная рассылка гражданам (/рассылка)"),
    BotCommand(command="treasury", description="Государственная казна города (/казна)"),
    BotCommand(command="balance", description="Банковский счет гражданина (/баланс)"),
    BotCommand(command="salary", description="Выплата жалования / премии (/зарплата, /премия)"),
    BotCommand(command="auction", description="Аукцион конфиската (/аукцион, /аукционы)"),
    BotCommand(command="transfer_money", description="Банковский перевод гражданину (/перевод)"),
    BotCommand(command="sync_menu", description="Обновить меню команд (/обновить_меню)"),
]


async def setup_bot_commands(bot: Bot) -> int:
    """
    Устанавливает официальное меню команд бота в интерфейсе Telegram (кнопка 'Меню' / '/').
    Обновляет все области (Default, Личные чаты, Группы, Супергруппы, Администраторы)
    и языковые коды (Default и RU), принудительно сбрасывая устаревший кэш Telegram.
    Возвращает количество зарегистрированных команд.
    """
    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]

    for scope in scopes:
        # Очищаем старые команды для данной области (сброс кэша)
        try:
            await bot.delete_my_commands(scope=scope)
        except Exception as e:
            logger.debug("Не удалось удалить старые команды для %s: %s", scope, e)

        # Устанавливаем обновленный список команд (по умолчанию и для русской локали)
        for lang in (None, "ru"):
            try:
                await bot.set_my_commands(BOT_COMMANDS, scope=scope, language_code=lang)
            except Exception as e:
                logger.debug("Не удалось установить команды для scope=%s lang=%s: %s", scope, lang, e)

    logger.info("Меню команд Telegram успешно установлено во всех областях (%d команд).", len(BOT_COMMANDS))
    return len(BOT_COMMANDS)
