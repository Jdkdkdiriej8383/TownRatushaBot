import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.base import Base
from db.models import User, Regulator, Law, ChatSettings
from db.seed import DEFAULT_REGULATORS, DEFAULT_LAWS
from core.enums import PositionLevel


@pytest_asyncio.fixture
async def db_session():
    """Асинхронная in-memory база данных для изолированного тестирования."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        # Наполняем регуляторами
        for reg in DEFAULT_REGULATORS:
            session.add(Regulator(**reg))

        # Наполняем законами
        for law in DEFAULT_LAWS:
            session.add(Law(**law))

        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_users(db_session: AsyncSession):
    """Создает набор тестовых пользователей с разными должностями."""
    users = {
        "citizen": User(
            telegram_id=1001,
            username="citizen_ivan",
            full_name="Иван Гражданин",
            role_level=PositionLevel.CITIZEN.value,
            minecraft_nick="Ivan_Crafter"
        ),
        "assistant": User(
            telegram_id=1002,
            username="assistant_petr",
            full_name="Петр Помощник",
            role_level=PositionLevel.ASSISTANT.value,
            minecraft_nick="Petr_Guard"
        ),
        "chat_warden": User(
            telegram_id=1003,
            username="warden_alex",
            full_name="Алексей Блюститель",
            role_level=PositionLevel.CHAT_WARDEN.value,
            minecraft_nick="Alex_Warden"
        ),
        "senior_warden": User(
            telegram_id=1004,
            username="senior_dmitry",
            full_name="Дмитрий Старший Блюститель",
            role_level=PositionLevel.SENIOR_WARDEN.value,
            minecraft_nick="Dmitry_Chief"
        ),
        "admin": User(
            telegram_id=1005,
            username="admin_igor",
            full_name="Игорь Администратор",
            role_level=PositionLevel.ADMINISTRATION.value,
            minecraft_nick="Igor_Admin"
        ),
        "senior_admin": User(
            telegram_id=1006,
            username="senior_admin_max",
            full_name="Максим Старший Администратор",
            role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
            minecraft_nick="Max_Mayor"
        ),
        "enemy": User(
            telegram_id=1007,
            username="griefer_sergey",
            full_name="Сергей Вредитель",
            role_level=PositionLevel.ENEMY.value,
            is_enemy=True,
            enemy_reason="Гриферство и саботаж на спавне",
            minecraft_nick="Dark_Griefer"
        ),
    }

    for u in users.values():
        db_session.add(u)
    await db_session.commit()

    return users
