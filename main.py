import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import settings
from db.base import get_session_maker, get_engine, Base
from db.seed import seed_database
from bot.middlewares import (
    DatabaseSessionMiddleware,
    UserSyncMiddleware,
    ChatRegulatorMiddleware,
)
from bot.handlers import get_main_router
from bot.commands import setup_bot_commands
from api import create_api_app, set_bot_instance
from tasks import start_scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("townbot")


async def run_fastapi(app, host: str, port: int):
    """Запуск FastAPI сервера в текущем асинхронном цикле событий."""
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    logger.info("Запуск Telegram-бота Города и Cross-Bot API...")

    # 1. Инициализация базы данных и сидинг (регуляторы + законы)
    try:
        await seed_database()
    except Exception as e:
        logger.warning("Не удалось выполнить seed_database (проверьте DATABASE_URL): %s", e)

    session_maker = get_session_maker()

    # 2. Инициализация бота aiogram 3.x
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # 3. Регистрация Middlewares (Outer middleware обеспечивает захват ВСЕХ пользователей и сообщений, как в Ирисе)
    dp.update.outer_middleware(DatabaseSessionMiddleware(session_maker))
    dp.message.outer_middleware(UserSyncMiddleware())
    dp.callback_query.outer_middleware(UserSyncMiddleware())
    dp.chat_member.outer_middleware(UserSyncMiddleware())
    dp.my_chat_member.outer_middleware(UserSyncMiddleware())
    dp.message.outer_middleware(ChatRegulatorMiddleware())

    # 4. Регистрация Handlers
    main_router = get_main_router()
    dp.include_router(main_router)

    # 5. Установка меню команд в интерфейсе Telegram
    await setup_bot_commands(bot)

    # 6. Инициализация Cross-Bot API (FastAPI)
    api_app = create_api_app()
    set_bot_instance(bot)

    logger.info("Все компоненты сконфигурированы. Запуск сервисов...")

    # 7. Параллельный контролируемый запуск сервисов
    polling_updates = list(dp.resolve_used_update_types())
    for upt in ("message", "callback_query", "chat_member", "my_chat_member"):
        if upt not in polling_updates:
            polling_updates.append(upt)

    tasks = [
        asyncio.create_task(
            dp.start_polling(bot, allowed_updates=polling_updates),
            name="aiogram_polling",
        ),
        asyncio.create_task(
            run_fastapi(api_app, settings.API_HOST, settings.API_PORT),
            name="fastapi_server",
        ),
        asyncio.create_task(
            start_scheduler_loop(session_maker, bot, interval_seconds=60),
            name="scheduler_loop",
        ),
    ]

    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if not task.cancelled() and task.exception():
                logger.error("Служба '%s' завершилась с ошибкой: %s", task.get_name(), task.exception())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка сервисов по сигналу завершения...")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        engine = get_engine()
        await engine.dispose()
        logger.info("TownBot успешно остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
