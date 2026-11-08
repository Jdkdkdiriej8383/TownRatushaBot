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

    # Проверка преобразования sslmode= в ssl= для совместимости с asyncpg
    s5 = Settings(DATABASE_URL="postgresql://user:pass@ep-host.neon.tech/neondb?sslmode=require")
    assert s5.DATABASE_URL == "postgresql+asyncpg://user:pass@ep-host.neon.tech/neondb?ssl=require"

    # Проверка удаления ?pgbouncer=true для совместимости с asyncpg
    s6 = Settings(DATABASE_URL="postgresql://user:pass@ep-host.supabase.com:6543/postgres?pgbouncer=true")
    assert s6.DATABASE_URL == "postgresql+asyncpg://user:pass@ep-host.supabase.com:6543/postgres"


def test_settings_port_alias():
    # Проверка поддержки Render env переменной PORT
    s = Settings(PORT=10000)
    assert s.API_PORT == 10000
