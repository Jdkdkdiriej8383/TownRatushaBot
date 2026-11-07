from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
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

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://town_user:town_pass@localhost:5432/towndb",
        description="Async SQLAlchemy database URL (PostgreSQL or SQLite for tests)"
    )
    DB_ECHO: bool = Field(default=False)

    # Cross-bot API (Intercom)
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
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
