import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from api.server import create_api_app
from db.base import get_db_session
from core.laws_service import LawService
from config import settings


@pytest.mark.asyncio
async def test_intercom_api(db_session: AsyncSession, sample_users):
    """
    Интеграционный тест Cross-bot API (Intercom):
    1. Авторизация по Bearer токену.
    2. Проверка статуса права голоса (Гражданин vs Враг города).
    3. Прием webhook с итогами референдума -> автоматическое обновление статьи Закона.
    4. Прием вердикта суда присяжных.
    """
    app = create_api_app()

    # Переопределяем get_db_session на тестовую сессию
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    headers = {
        "Authorization": f"Bearer {settings.INTERCOM_SECRET_TOKEN}",
        "Content-Type": "application/json"
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Проверка авторизации (без токена -> 401)
        resp_unauth = await client.get("/api/v1/users/1001/voting-status")
        assert resp_unauth.status_code == 401

        # 2. Проверка права голоса Гражданина (1001) -> can_vote = True
        resp_citizen = await client.get("/api/v1/users/1001/voting-status", headers=headers)
        assert resp_citizen.status_code == 200
        data_cit = resp_citizen.json()
        assert data_cit["can_vote"] is True
        assert data_cit["position_title"] == "Гражданин"
        assert data_cit["is_enemy"] is False

        # 3. Проверка права голоса Врага города (1007) -> can_vote = False
        resp_enemy = await client.get("/api/v1/users/1007/voting-status", headers=headers)
        assert resp_enemy.status_code == 200
        data_enemy = resp_enemy.json()
        assert data_enemy["can_vote"] is False
        assert data_enemy["is_enemy"] is True
        assert "Враг города" in data_enemy["position_title"]

        # 4. Webhook: Результаты референдума по поправке в закон
        amendment_payload = {
            "poll_id": "poll_9876",
            "referendum_type": "law_amendment",
            "article_number": "2.1",
            "proposed_text": "Оскорбления жителей категорически запрещены. Штраф 30 000.",
            "passed": True,
            "votes_for": 45,
            "votes_against": 5,
            "total_votes": 50,
            "details": "Референдум успешно завершен"
        }

        resp_webhook = await client.post("/api/v1/referendum/result", json=amendment_payload, headers=headers)
        assert resp_webhook.status_code == 200
        assert resp_webhook.json()["status"] == "ok"

        # Проверяем, что закон в БД действительно автоматически обновился!
        updated_law = await LawService.get_law(db_session, "2.1")
        assert updated_law.description == "Оскорбления жителей категорически запрещены. Штраф 30 000."

        # 5. Webhook: Вердикт суда присяжных (виновен)
        jury_payload = {
            "poll_id": "jury_1122",
            "referendum_type": "jury_trial",
            "target_user_id": 1001,
            "passed": True,  # Признан виновным
            "votes_for": 20,
            "votes_against": 4,
            "total_votes": 24
        }
        resp_jury = await client.post("/api/v1/referendum/result", json=jury_payload, headers=headers)
        assert resp_jury.status_code == 200

        # Гражданин объявлен в розыск
        citizen = sample_users["citizen"]
        await db_session.refresh(citizen)
        assert citizen.is_wanted is True
