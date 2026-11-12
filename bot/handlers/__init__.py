from aiogram import Router
from bot.handlers.reports import router as reports_router
from bot.handlers.tickets import router as tickets_router
from bot.handlers.moderation import router as moderation_router
from bot.handlers.court import router as court_router
from bot.handlers.admin import router as admin_router
from bot.handlers.common import router as common_router
from bot.handlers.laws import router as laws_router
from bot.handlers.justice import router as justice_router
from bot.handlers.passport import router as passport_router
from bot.handlers.rp_actions import router as rp_actions_router
from bot.handlers.referendum import router as referendum_router
from bot.handlers.regulators_admin import router as regulators_router
from bot.handlers.network import router as network_router
from bot.handlers.broadcast import router as broadcast_router
from bot.handlers.treasury import router as treasury_router
from bot.handlers.auction import router as auction_router


def get_main_router() -> Router:
    main_router = Router(name="main_router")
    main_router.include_router(reports_router)
    main_router.include_router(tickets_router)
    main_router.include_router(moderation_router)
    main_router.include_router(court_router)
    main_router.include_router(admin_router)
    main_router.include_router(network_router)
    main_router.include_router(broadcast_router)
    main_router.include_router(treasury_router)
    main_router.include_router(auction_router)
    main_router.include_router(common_router)
    main_router.include_router(laws_router)
    main_router.include_router(justice_router)
    main_router.include_router(passport_router)
    main_router.include_router(rp_actions_router)
    main_router.include_router(referendum_router)
    main_router.include_router(regulators_router)
    return main_router


__all__ = ["get_main_router"]
