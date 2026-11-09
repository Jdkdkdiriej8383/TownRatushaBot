"""
Скрипт полной очистки и пересоздания базы данных Supabase (PostgreSQL / SQLite).

Использование:
    python -m db.reset
"""
import asyncio
import logging
from db.seed import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

if __name__ == "__main__":
    print("=" * 60)
    print("Запуск полной каскадной очистки и пересоздания Supabase...")
    print("=" * 60)
    asyncio.run(seed_database(force_wipe=True))
    print("=" * 60)
    print("База данных Supabase успешно очищена и наполнена с нуля!")
    print("=" * 60)
