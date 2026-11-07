import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import get_session_maker, get_engine, Base
from db.models import Regulator, Law, ChatSettings
from core.enums import PositionLevel, LawSection
from config import settings

logger = logging.getLogger(__name__)


DEFAULT_REGULATORS = [
    {
        "role_level": PositionLevel.CITIZEN.value,
        "title": "Гражданин",
        "max_mute_time": 0,
        "max_fine_amount": 0,
        "can_ban": False,
        "max_ban_time": 0,
        "can_edit_laws": False,
        "can_appoint_level": -1,
        "can_create_referendum": False,
    },
    {
        "role_level": PositionLevel.ASSISTANT.value,
        "title": "Помощник",
        "max_mute_time": 7200,          # 2 часа (7200 сек)
        "max_fine_amount": 0,
        "can_ban": False,
        "max_ban_time": 0,
        "can_edit_laws": False,
        "can_appoint_level": -1,
        "can_create_referendum": False,
    },
    {
        "role_level": PositionLevel.CHAT_WARDEN.value,
        "title": "Блюститель чата",
        "max_mute_time": 86400,         # 24 часа (86400 сек)
        "max_fine_amount": 50000,       # Штрафы по статьям Раздела II
        "can_ban": False,
        "max_ban_time": 0,
        "can_edit_laws": False,
        "can_appoint_level": -1,
        "can_create_referendum": False,
    },
    {
        "role_level": PositionLevel.SENIOR_WARDEN.value,
        "title": "Старший блюститель",
        "max_mute_time": 604800,        # 7 дней
        "max_fine_amount": 200000,      # Игровые штрафы до 200 000
        "can_ban": True,
        "max_ban_time": 604800,         # Изгнание до 7 дней
        "can_edit_laws": False,
        "can_appoint_level": 1,         # Может назначать помощников
        "can_create_referendum": False,
    },
    {
        "role_level": PositionLevel.ADMINISTRATION.value,
        "title": "Администрация",
        "max_mute_time": 2592000,       # 30 дней
        "max_fine_amount": 1000000,
        "can_ban": True,
        "max_ban_time": 0,              # Перманент
        "can_edit_laws": True,          # Редактирование статей
        "can_appoint_level": 3,         # Назначение до Старшего блюстителя
        "can_create_referendum": True,
    },
    {
        "role_level": PositionLevel.SENIOR_ADMINISTRATION.value,
        "title": "Старшая администрация",
        "max_mute_time": 31536000,      # Без ограничений
        "max_fine_amount": 10000000,
        "can_ban": True,
        "max_ban_time": 0,              # Перманент
        "can_edit_laws": True,          # Полное редактирование
        "can_appoint_level": 5,         # Назначение любых должностей
        "can_create_referendum": True,  # Создание референдумов
    },
]


DEFAULT_LAWS = [
    # Раздел I. Общие положения (1.1 - 1.4)
    {
        "article_number": "1.1",
        "section": LawSection.SECTION_1.value,
        "title": "Суверенитет и верховенство Закона",
        "description": "Городской Свод Законов является высшим нормативным актом. Все жители и гости города обязаны неукоснительно соблюдать его положения.",
        "sanction_text": "Предупреждение или штраф 5 000 за демонстративное непризнание законов.",
        "default_mute_seconds": None,
        "default_fine_amount": 5000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.2",
        "section": LawSection.SECTION_1.value,
        "title": "Гражданство и паспортный режим",
        "description": "Каждый житель обязан иметь зарегистрированный паспорт с привязкой Minecraft-ника.",
        "sanction_text": "Ограничение доступа к городским сервисам и казне до регистрации паспорта.",
        "default_mute_seconds": None,
        "default_fine_amount": 2000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.3",
        "section": LawSection.SECTION_1.value,
        "title": "Субординация и авторитет властей",
        "description": "Запрещено публичное неповиновение законным распоряжениям блюстителей и администрации.",
        "sanction_text": "Мут от 30 мин до 2 часов или штраф 10 000.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 10000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.4",
        "section": LawSection.SECTION_1.value,
        "title": "Статус Врага города",
        "description": "Лицо, совершившее государственную измену, теракт или массовый вредительский саботаж, объявляется Врагом города.",
        "sanction_text": "Бессрочное изгнание (бан) и поражение во всех гражданских правах.",
        "default_mute_seconds": None,
        "default_fine_amount": 500000,
        "is_ban_applicable": True,
    },

    # Раздел II. Чат Telegram (2.1 - 2.12)
    {
        "article_number": "2.1",
        "section": LawSection.SECTION_2.value,
        "title": "Оскорбления и токсичность",
        "description": "Запрещены прямые оскорбления горожан, унижение человеческого достоинства и провокации конфликтов.",
        "sanction_text": "Мут на 1-4 часа, при повторе — штраф 15 000.",
        "default_mute_seconds": 7200,
        "default_fine_amount": 15000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.2",
        "section": LawSection.SECTION_2.value,
        "title": "Капс и визуальный мусор",
        "description": "Злоупотребление верхним регистром (>70% сообщения) и растягивание букв.",
        "sanction_text": "Предупреждение или мут на 30 минут.",
        "default_mute_seconds": 1800,
        "default_fine_amount": 3000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.3",
        "section": LawSection.SECTION_2.value,
        "title": "Медиа-спам и флуд",
        "description": "Отправка более 3 стикеров, голосовых сообщений, видеосообщений или бессмысленных сообщений подряд.",
        "sanction_text": "Мут на 1 час.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 5000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.4",
        "section": LawSection.SECTION_2.value,
        "title": "Несанкционированная реклама и ссылки",
        "description": "Публикация сторонних ссылок, рекламы каналов, серверов и коммерческих ресурсов без одобрения администрации.",
        "sanction_text": "Мут на 24 часа или изгнание (бан).",
        "default_mute_seconds": 86400,
        "default_fine_amount": 50000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.5",
        "section": LawSection.SECTION_2.value,
        "title": "Нецензурная лексика",
        "description": "Чрезмерное и агрессивное употребление мата в официальных городских чатах.",
        "sanction_text": "Мут от 30 мин до 2 часов.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 5000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.6",
        "section": LawSection.SECTION_2.value,
        "title": "Дезинформация и клевета",
        "description": "Распространение заведомо ложной информации о решениях властей или жителях города.",
        "sanction_text": "Мут на 6 часов и штраф 20 000.",
        "default_mute_seconds": 21600,
        "default_fine_amount": 20000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.7",
        "section": LawSection.SECTION_2.value,
        "title": "Обсуждение политики и деструктивных тем",
        "description": "Разжигание реальных политических, религиозных, национальных конфликтов.",
        "sanction_text": "Мут на 24 часа, при рецидиве — изгнание на 7 дней.",
        "default_mute_seconds": 86400,
        "default_fine_amount": 40000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.8",
        "section": LawSection.SECTION_2.value,
        "title": "Провокация бунта и саботаж",
        "description": "Призывы к массовому нарушению законов города и неповиновению органам правопорядка.",
        "sanction_text": "Мут до 48 часов или изгнание на 7 дней.",
        "default_mute_seconds": 172800,
        "default_fine_amount": 50000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.9",
        "section": LawSection.SECTION_2.value,
        "title": "Выпрашивание должностей и ресурсов",
        "description": "Навязчивое выпрашивание должностей у администрации или игровой валюты в общем чате.",
        "sanction_text": "Мут на 1 час.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 5000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.10",
        "section": LawSection.SECTION_2.value,
        "title": "Оффтоп в профильных каналах",
        "description": "Нарушение тематики специальных каналов (суд, казна, объявления).",
        "sanction_text": "Предупреждение, удаление сообщений, при повторе — мут на 30 мин.",
        "default_mute_seconds": 1800,
        "default_fine_amount": 3000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.11",
        "section": LawSection.SECTION_2.value,
        "title": "Публичное оспаривание санкций",
        "description": "Выяснение отношений с блюстителем в общем чате. Все апелляции подаются строго в суд или через /жалоба.",
        "sanction_text": "Мут на 2 часа.",
        "default_mute_seconds": 7200,
        "default_fine_amount": 10000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.12",
        "section": LawSection.SECTION_2.value,
        "title": "Твинки и обход наказаний",
        "description": "Использование вторых аккаунтов для обхода мута или изгнания.",
        "sanction_text": "Перманентное изгнание всех связанных аккаунтов.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": True,
    },

    # Раздел III. Внутриигровые законы (3.1 - 3.28)
    # Безопасность 3.1 - 3.12
    {
        "article_number": "3.1",
        "section": LawSection.SECTION_3.value,
        "title": "Гриферство и порча имущества",
        "description": "Умышленное повреждение или разрушение построек граждан или городских объектов.",
        "sanction_text": "Штраф до 100 000 + компенсация ущерба x2, изгнание от 3 до 7 дней.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.2",
        "section": LawSection.SECTION_3.value,
        "title": "Кража и мародерство",
        "description": "Хищение чужого имущества из незаприваченных или вскрытых сундуков.",
        "sanction_text": "Штраф 50 000 и возврат украденного.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.3",
        "section": LawSection.SECTION_3.value,
        "title": "Несанкционированное PvP и нападение",
        "description": "Убийство или нападение на жителя города без РП-причины или вне зоны арены.",
        "sanction_text": "Штраф 30 000 и арест.",
        "default_mute_seconds": None,
        "default_fine_amount": 30000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.4",
        "section": LawSection.SECTION_3.value,
        "title": "Использование запрещенного ПО (Читы)",
        "description": "Применение чит-клиентов, рентгена (X-Ray), кликеров и эксплойтов.",
        "sanction_text": "Перманентное изгнание и объявление Врагом города.",
        "default_mute_seconds": None,
        "default_fine_amount": 200000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.12",
        "section": LawSection.SECTION_3.value,
        "title": "Регламент уплаты штрафов",
        "description": "На уплату выписанного штрафа гражданину дается ровно 48 часов. При неуплате сумма удваивается (х2), а житель объявляется в розыск.",
        "sanction_text": "Авто-удвоение штрафа (x2) и объявление в розыск.",
        "default_mute_seconds": None,
        "default_fine_amount": 10000,
        "is_ban_applicable": False,
    },
    # Стройка 3.13 - 3.20
    {
        "article_number": "3.13",
        "section": LawSection.SECTION_3.value,
        "title": "Архитектурный регламент",
        "description": "Строительство «коробок» из земли/булыжника и построек, нарушающих стиль города.",
        "sanction_text": "Предписание на снос 24ч, штраф 25 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 25000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.14",
        "section": LawSection.SECTION_3.value,
        "title": "Столбы и ямы (порча ландшафта)",
        "description": "Оставление столбов высотой 1 блок («земляные столбы») или глубоких незасыпанных ям.",
        "sanction_text": "Штраф 10 000 и обязанность ликвидировать нарушение.",
        "default_mute_seconds": None,
        "default_fine_amount": 10000,
        "is_ban_applicable": False,
    },
    # Экономика 3.21 - 3.28
    {
        "article_number": "3.21",
        "section": LawSection.SECTION_3.value,
        "title": "Демпинг цен и экономический саботаж",
        "description": "Умышленный срыв рыночных цен на базовые товары с целью банкротства конкурентов.",
        "sanction_text": "Штраф 70 000 и закрытие торговой точки на 3 дня.",
        "default_mute_seconds": None,
        "default_fine_amount": 70000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.25",
        "section": LawSection.SECTION_3.value,
        "title": "Статус отпуска и сохранение недвижимости",
        "description": "Житель имеет право оформить официальный статус отпуска до 30 дней. Имущество жителя в отпуске защищено от сноса за неактивность.",
        "sanction_text": "Оформление через /паспорт отпуск [дней]. При самовольной экспроприации чужого отпускного участка — штраф 100 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },

    # Раздел IV. Служба и работа (4.1 - 4.4)
    {
        "article_number": "4.1",
        "section": LawSection.SECTION_4.value,
        "title": "Превышение должностных полномочий",
        "description": "Применение санкций блюстителем вне рамок регуляторов или в личных корыстных целях.",
        "sanction_text": "Понижение в должности, штраф 50 000 или отстранение от службы.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "4.2",
        "section": LawSection.SECTION_4.value,
        "title": "Халатность и бездействие",
        "description": "Игнорирование грубых нарушений законов в присутствии блюстителя на дежурстве.",
        "sanction_text": "Выговор, при двух выговорах — понижение в должности.",
        "default_mute_seconds": None,
        "default_fine_amount": 20000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "4.3",
        "section": LawSection.SECTION_4.value,
        "title": "Разглашение служебной тайны",
        "description": "Передача информации из закрытых каналов администрации и суда третьим лицам.",
        "sanction_text": "Немедленное увольнение со службы, штраф 150 000, изгнание на 7 дней.",
        "default_mute_seconds": None,
        "default_fine_amount": 150000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "4.4",
        "section": LawSection.SECTION_4.value,
        "title": "Коррупция и взятки",
        "description": "Получение игровых ценностей или валюты за сокрытие нарушений или фальсификацию досье.",
        "sanction_text": "Снятие со всех должностей, конфискация взятки x3, статус Врага города.",
        "default_mute_seconds": None,
        "default_fine_amount": 200000,
        "is_ban_applicable": True,
    },
]


async def seed_database(max_retries: int = 5, retry_delay: float = 3.0):
    """Создает таблицы и наполняет базу данных базовыми регуляторами и законами."""
    engine = get_engine()
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if attempt == max_retries:
                logger.error(f'DB connection failed after {max_retries} attempts: {e}')
                raise
            logger.warning(f'DB attempt {attempt}/{max_retries} failed ({e}). Retrying in {retry_delay}s...')
            await asyncio.sleep(retry_delay)

    session_factory = get_session_maker()
    async with session_factory() as session:
        # 1. Заполняем регуляторы
        for reg_data in DEFAULT_REGULATORS:
            query = select(Regulator).where(Regulator.role_level == reg_data["role_level"])
            existing = await session.scalar(query)
            if not existing:
                session.add(Regulator(**reg_data))

        # 2. Заполняем законы
        for law_data in DEFAULT_LAWS:
            query = select(Law).where(Law.article_number == law_data["article_number"])
            existing = await session.scalar(query)
            if not existing:
                session.add(Law(**law_data))

        # 3. Базовые настройки чата (если задан MAIN_CHAT_ID)
        if settings.MAIN_CHAT_ID:
            query = select(ChatSettings).where(ChatSettings.chat_id == settings.MAIN_CHAT_ID)
            existing = await session.scalar(query)
            if not existing:
                session.add(ChatSettings(chat_id=settings.MAIN_CHAT_ID))

        await session.commit()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed_database())
