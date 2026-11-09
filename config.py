from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices, field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot
    BOT_TOKEN: str = Field(default="123456789:AABBCCDDEEFFggHHiiJJKKllMMnnOOppQQ")
    MAIN_CHAT_ID: Optional[int] = Field(default=None, description="ID основного супергруппового чата города")
    LOG_CHAT_ID: Optional[int] = Field(default=None, description="ID чата судебного протокола и логов")

    # City Owner & Creator
    OWNER_ID: int = Field(default=1965081517, description="Telegram ID владельца/овнера города")
    OWNER_USERNAME: str = Field(default="DivniDed", description="Username овнера города")
    RULES_URL: str = Field(default="https://teletype.in/@townratushabot/Rules", description="Ссылка на Свод правил на Teletype")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://town_user:town_pass@localhost:5432/towndb",
        description="Async SQLAlchemy database URL (PostgreSQL or SQLite for tests)"
    )
    DB_ECHO: bool = Field(default=False)
    RESET_DB: bool = Field(default=False, description="Принудительный сброс и пересоздание всех таблиц БД")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: str) -> str:
        """
        Преобразует строку подключения PostgreSQL к формату asyncpg.
        Хостинги вроде Render, Neon, Supabase передают postgres:// или postgresql://,
        а асинхронный SQLAlchemy требует postgresql+asyncpg://.
        """
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+asyncpg://", 1)
            if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            if "sslmode=" in v:
                v = v.replace("sslmode=", "ssl=")
            # Удаляем специфичный параметр Prisma ?pgbouncer=true, который asyncpg не поддерживает
            if "?pgbouncer=true" in v:
                v = v.replace("?pgbouncer=true", "")
            elif "&pgbouncer=true" in v:
                v = v.replace("&pgbouncer=true", "")
            return v
        return v

    # Cross-bot API (Intercom)
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(
        default=8000,
        validation_alias=AliasChoices("PORT", "API_PORT"),
        description="Порт для FastAPI (автоматически подхватывает PORT от Render или API_PORT)"
    )
    INTERCOM_SECRET_TOKEN: str = Field(
        default="town_cross_bot_secret_token_12345",
        description="Секретный токен для авторизации между ботом города и ботом опросов"
    )
    POLL_BOT_API_URL: str = Field(
        default="http://localhost:8001/api/v1",
        description="URL эндпоинта второго бота (для опросов/референдумов)"
    )

    # Defaults & Regulators
    FINE_EXPIRATION_HOURS: int = Field(default=48, description="Срок оплаты штрафа (часов)")
    FINE_DOUBLE_MULTIPLIER: float = Field(default=2.0, description="Множитель штрафа при просрочке")


settings = Settings()
