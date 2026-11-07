import logging
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from db.base import get_db_session
from db.models import User, Law, Punishment
from core.enums import PositionLevel, PunishmentType
from core.laws_service import LawService
from api.schemas import (
    UserVotingStatusResponse,
    ReferendumResultWebhook,
    IntercomResponse,
    ReferendumType,
)
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Intercom Cross-Bot API"])

# Глобальный инстанс бота aiogram для отправки оповещений о принятых законах / вердиктах
_bot_instance: Bot | None = None


def set_bot_instance(bot: Bot):
    global _bot_instance
    _bot_instance = bot


def get_bot_instance() -> Bot | None:
    return _bot_instance


async def verify_intercom_auth(
    authorization: str = Header(None),
    x_intercom_token: str = Header(None)
):
    """Проверка аутентификации между ботами."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
    elif x_intercom_token:
        token = x_intercom_token.strip()

    if not token or token != settings.INTERCOM_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен авторизации Cross-Bot API"
        )


@router.get(
    "/users/{telegram_id}/voting-status",
    response_model=UserVotingStatusResponse,
    summary="Проверка права голоса жителя для бота опросов"
)
async def check_user_voting_status(
    telegram_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(verify_intercom_auth)
):
    """
    Эндпоинт проверки права голоса для бота опросов:
    Могут голосовать только жители с должностью «Гражданин» и выше.
    «Враги города» категорически исключаются и поражены в правах.
    """
    query = select(User).where(User.telegram_id == telegram_id)
    user = await session.scalar(query)

    if not user:
        return UserVotingStatusResponse(
            telegram_id=telegram_id,
            can_vote=False,
            role_level=-1,
            position_title="Не зарегистрирован",
            is_enemy=False,
            reason="Житель не зарегистрирован в базе данных города"
        )

    if user.is_enemy:
        return UserVotingStatusResponse(
            telegram_id=telegram_id,
            can_vote=False,
            role_level=PositionLevel.ENEMY.value,
            position_title="Враг города",
            is_enemy=True,
            minecraft_nick=user.minecraft_nick,
            reason=f"Поражение во всех гражданских правах: {user.enemy_reason or 'Враг города'}"
        )

    can_vote = user.role_level >= PositionLevel.CITIZEN.value
    reason = None if can_vote else "Недостаточный уровень должности для участия в голосовании"

    return UserVotingStatusResponse(
        telegram_id=user.telegram_id,
        can_vote=can_vote,
        role_level=user.role_level,
        position_title=user.position_title,
        is_enemy=False,
        minecraft_nick=user.minecraft_nick,
        reason=reason
    )


@router.post(
    "/referendum/result",
    response_model=IntercomResponse,
    summary="Синхронизация результатов референдума от бота опросов"
)
async def receive_referendum_result(
    payload: ReferendumResultWebhook,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(verify_intercom_auth)
):
    """
    Прием webhook с итогами голосования от второго бота.
    Автоматически применяет принятое решение:
    1. Если это поправка в закон и референдум принят -> обновляет статью в БД.
    2. Если это суд присяжных -> выносит приговор или оправдывает.
    3. Публикует объявление о результатах референдума в официальный чат города.
    """
    bot = get_bot_instance()
    chat_id = settings.MAIN_CHAT_ID

    if payload.referendum_type == ReferendumType.LAW_AMENDMENT:
        if payload.passed and payload.article_number and payload.proposed_text:
            # Применяем поправку в закон
            clean_art = payload.article_number.strip().lstrip("№").strip()
            law_query = select(Law).where(Law.article_number == clean_art)
            law = await session.scalar(law_query)
            if law:
                law.description = payload.proposed_text
                await session.commit()
                msg = (
                    f"🗳 <b>РЕЗУЛЬТАТЫ ОБЩЕГОРОДСКОГО РЕФЕРЕНДУМА</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Поправка к <b>Статье № {law.article_number} ({law.title})</b> УСПЕШНО ПРИНЯТА ГОРОЖАНАМИ!\n\n"
                    f"📊 <b>Итоги голосования:</b>\n"
                    f"• ЗА: <code>{payload.votes_for}</code>\n"
                    f"• ПРОТИВ: <code>{payload.votes_against}</code>\n"
                    f"• Всего участников: <code>{payload.total_votes}</code>\n\n"
                    f"📜 <b>Новая редакция закона:</b>\n{law.description}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Решение вступило в силу немедленно на основании волеизъявления народа.</i>"
                )
            else:
                msg = f"Поправка принята, но статья {clean_art} не найдена в базе."
        else:
            msg = (
                f"🗳 <b>РЕЗУЛЬТАТЫ ОБЩЕГОРОДСКОГО РЕФЕРЕНДУМА</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Поправка к Статье № {payload.article_number or '—'} <b>ОТКЛОНЕНА</b> жителями города.\n"
                f"• ЗА: <code>{payload.votes_for}</code> | ПРОТИВ: <code>{payload.votes_against}</code>\n"
                f"Статья сохраняет прежнюю юридическую силу."
            )

    elif payload.referendum_type == ReferendumType.JURY_TRIAL:
        target_user = None
        if payload.target_user_id:
            target_user = await session.scalar(select(User).where(User.telegram_id == payload.target_user_id))

        target_name = target_user.full_name if target_user else f"ID {payload.target_user_id}"

        if payload.passed:
            # Признан виновным судом присяжных
            if target_user:
                target_user.is_wanted = True
                await session.commit()

            msg = (
                f"⚖️ <b>ВЕРДИКТ СУДА ПРИСЯЖНЫХ ЗАСЕДАТЕЛЕЙ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"В отношении гражданина <b>{target_name}</b> вынесен вердикт: <b>ВИНОВЕН</b>!\n"
                f"📊 Голоса присяжных: За виновность: <code>{payload.votes_for}</code>, Против: <code>{payload.votes_against}</code>.\n"
                f"Нарушитель объявлен в общегородской розыск, санкции подлежат немедленному исполнению!"
            )
        else:
            if target_user:
                target_user.is_wanted = False
                await session.commit()

            msg = (
                f"⚖️ <b>ВЕРДИКТ СУДА ПРИСЯЖНЫХ ЗАСЕДАТЕЛЕЙ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"В отношении гражданина <b>{target_name}</b> вынесен вердикт: <b>ОПРАВДАН</b>!\n"
                f"📊 Голоса присяжных: Оправдать: <code>{payload.votes_against}</code>, Виновен: <code>{payload.votes_for}</code>.\n"
                f"Все обвинения сняты, доброе имя жителя восстановлено."
            )
    else:
        msg = f"Итоги голосования #{payload.poll_id}: принят={payload.passed}"

    # Отправляем сообщение в чат Telegram, если бот запущен
    if bot and chat_id:
        try:
            await bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logger.error("Ошибка при отправке уведомления в Telegram чат %s: %s", chat_id, e)

    return IntercomResponse(
        status="ok",
        message="Результаты референдума успешно обработаны и применены"
    )
