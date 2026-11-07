from config import Settings


def test_settings_database_url_formatting():
    # Проверка postgres:// -> postgresql+asyncpg://
    s1 = Settings(DATABASE_URL="postgres://user:pass@host:5432/db")
    assert s1.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    # Проверка postgresql:// -> postgresql+asyncpg://
    s2 = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert s2.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    # Проверка postgresql+asyncpg:// сохраняется без изменений
    s3 = Settings(DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db")
    assert s3.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    # SQLite сохраняется
    s4 = Settings(DATABASE_URL="sqlite+aiosqlite:///local.db")
    assert s4.DATABASE_URL == "sqlite+aiosqlite:///local.db"


def test_settings_port_alias():
    # Проверка поддержки Render env переменной PORT
    s = Settings(PORT=10000)
    assert s.API_PORT == 10000
