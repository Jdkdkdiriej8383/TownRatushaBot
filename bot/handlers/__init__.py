from aiogram import Router
from bot.handlers.common import router as common_router
from bot.handlers.laws import router as laws_router
from bot.handlers.justice import router as justice_router
from bot.handlers.passport import router as passport_router
from bot.handlers.rp_actions import router as rp_actions_router
from bot.handlers.referendum import router as referendum_router
from bot.handlers.regulators_admin import router as regulators_router


def get_main_router() -> Router:
    main_router = Router(name="main_router")
    main_router.include_router(common_router)
    main_router.include_router(laws_router)
    main_router.include_router(justice_router)
    main_router.include_router(passport_router)
    main_router.include_router(rp_actions_router)
    main_router.include_router(referendum_router)
    main_router.include_router(regulators_router)
    return main_router


__all__ = ["get_main_router"]
