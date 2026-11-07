import httpx
import logging
from typing import Optional
from config import settings
from api.schemas import ReferendumType

logger = logging.getLogger(__name__)


class PollBotClient:
    """
    Клиент для взаимодействия со вторым Telegram-ботом опросов.
    Передает команды на создание референдумов и судов присяжных.
    """

    def __init__(self, base_url: str = settings.POLL_BOT_API_URL, token: str = settings.INTERCOM_SECRET_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Source-Bot": "townbot"
        }

    async def create_poll(
        self,
        question: str,
        options: list[str],
        referendum_type: ReferendumType,
        article_number: Optional[str] = None,
        target_user_id: Optional[int] = None,
        proposed_text: Optional[str] = None,
        duration_hours: int = 24
    ) -> bool:
        """Отправляет команду боту опросов на создание голосования в чате."""
        payload = {
            "question": question,
            "options": options,
            "referendum_type": referendum_type.value,
            "article_number": article_number,
            "target_user_id": target_user_id,
            "proposed_text": proposed_text,
            "duration_hours": duration_hours,
            "callback_webhook_url": f"http://{settings.API_HOST}:{settings.API_PORT}/api/v1/referendum/result"
        }
        url = f"{self.base_url}/polls/create"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=self.headers)
                if response.status_code in (200, 201):
                    logger.info("Успешно отправлен запрос на создание опроса в poll-bot: %s", question)
                    return True
                else:
                    logger.error("Ошибка при обращении к poll-bot (код %s): %s", response.status_code, response.text)
                    return False
        except Exception as e:
            logger.warning("Не удалось связаться с poll-bot по адресу %s: %s (работаем в standalone-режиме)", url, e)
            return False
