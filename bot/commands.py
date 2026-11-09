import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

logger = logging.getLogger("townbot.commands")

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу с ботом"),
    BotCommand(command="help", description="Справка по командам (/помощь)"),
    BotCommand(command="passport", description="Паспорт гражданина (/паспорт)"),
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
    BotCommand(command="referendum", description="Общегородской референдум (/референдум)"),
    BotCommand(command="jury", description="Суд присяжных (/присяжные)"),
    BotCommand(command="regulators", description="Регуляторы и защиты чата (/регуляторы)"),
    BotCommand(command="anticaps", description="Регулятор антикапса (/антикапс)"),
    BotCommand(command="antispam", description="Регулятор медиа-спама (/спам)"),
    BotCommand(command="antilinks", description="Регулятор ссылок и рекламы (/ссылки)"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """
    Устанавливает официальное меню команд бота в интерфейсе Telegram (кнопка 'Меню' / '/').
    Включает только реально существующие команды города.
    """
    try:
        await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
        logger.info("Меню команд Telegram успешно установлено (%d команд).", len(BOT_COMMANDS))
    except Exception as e:
        logger.warning("Не удалось установить меню команд Telegram: %s", e)
