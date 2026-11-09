import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import get_session_maker, get_engine, Base
from db.models import Regulator, Law, ChatSettings, User
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
    # 📜 I. ОБЩИЕ ПОЛОЖЕНИЯ
    {
        "article_number": "1.1",
        "section": LawSection.SECTION_1.value,
        "title": "Соблюдение законов",
        "description": "Соблюдение законов обязательно для исполнения всеми жителями города.",
        "sanction_text": "Обязательно для исполнения всеми жителями города.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.2",
        "section": LawSection.SECTION_1.value,
        "title": "Незнание законов",
        "description": "Незнание законов не освобождает нарушителя от ответственности и наказания.",
        "sanction_text": "Не освобождает нарушителя от ответственности и наказания.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.3",
        "section": LawSection.SECTION_1.value,
        "title": "Полномочия власти",
        "description": "Руководство и суд вправе наказывать за проступки вне свода.",
        "sanction_text": "Руководство и суд вправе наказывать за проступки вне свода.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "1.4",
        "section": LawSection.SECTION_1.value,
        "title": "Субординация и этика",
        "description": "Запрещены хамство руководству, пустые пинги и попрошайничество.",
        "sanction_text": "Предупреждение → штраф 50 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },

    # 💬 II. ЧАТ TELEGRAM
    {
        "article_number": "2.1",
        "section": LawSection.SECTION_2.value,
        "title": "Оскорбление руководства",
        "description": "Неуважение и клевета на мэра и его помощников.",
        "sanction_text": "Мут 12–24ч / 100 000 / бан и изгнание.",
        "default_mute_seconds": 43200,
        "default_fine_amount": 100000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.2",
        "section": LawSection.SECTION_2.value,
        "title": "Мат и оскорбления",
        "description": "Мат разрешён в общении. Адресные оскорбления, травля и задевание родных строго запрещены!",
        "sanction_text": "Мут 2–8ч / бан.",
        "default_mute_seconds": 7200,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.3",
        "section": LawSection.SECTION_2.value,
        "title": "Угрозы и шантаж",
        "description": "Запрещены угрозы ИРЛ-расправой, деаноном, взломом и шантаж.",
        "sanction_text": "Бан от 7 дней + статус «Враг города».",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.4",
        "section": LawSection.SECTION_2.value,
        "title": "Медиа-спам",
        "description": "Флуд голосовыми («ГС»), кружочками, стикерами и GIF (>3 подряд).",
        "sanction_text": "Предупреждение → мут 1–4ч.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.5",
        "section": LawSection.SECTION_2.value,
        "title": "Капс и мусор",
        "description": "Злоупотребление CAPS LOCK и нечитаемыми символами.",
        "sanction_text": "Удаление → мут 1–2ч.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.6",
        "section": LawSection.SECTION_2.value,
        "title": "Контент 18+ (NSFW)",
        "description": "Запрещены порнография, насилие и шок-контент.",
        "sanction_text": "Бан от 3 дней до перманентного.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.7",
        "section": LawSection.SECTION_2.value,
        "title": "Политика и рознь",
        "description": "Обсуждение реальной политики, войн, религии и нац. рознь.",
        "sanction_text": "Мут 24ч / перманентный бан.",
        "default_mute_seconds": 86400,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.8",
        "section": LawSection.SECTION_2.value,
        "title": "Деанон и слив ЛС",
        "description": "Публикация чужих личных данных, фото или личных переписок.",
        "sanction_text": "Перманентный бан + изгнание из города.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.9",
        "section": LawSection.SECTION_2.value,
        "title": "Оффтоп",
        "description": "Флуд и сообщения не по теме в специальных разделах.",
        "sanction_text": "Удаление → мут 1–3ч.",
        "default_mute_seconds": 3600,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "2.10",
        "section": LawSection.SECTION_2.value,
        "title": "Реклама и ложь",
        "description": "Несогласованные ссылки, реклама и дезинформация.",
        "sanction_text": "Мут 24ч → бан.",
        "default_mute_seconds": 86400,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.11",
        "section": LawSection.SECTION_2.value,
        "title": "Торговля за реал (RMT)",
        "description": "Покупка/продажа ценностей города за реальные деньги.",
        "sanction_text": "Перманентный бан и изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "2.12",
        "section": LawSection.SECTION_2.value,
        "title": "Вторые аккаунты (Твинки)",
        "description": "Обход мута или бана с запасного аккаунта.",
        "sanction_text": "Бан твинка + x2 срок основе.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },

    # ⚔️ III. ВНУТРИИГРОВЫЕ ЗАКОНЫ: Безопасность и правопорядок
    {
        "article_number": "3.1",
        "section": LawSection.SECTION_3.value,
        "title": "Кража",
        "description": "Хищение ресурсов из чужих сундуков и хранилищ.",
        "sanction_text": "Штраф 150 000 + возврат / изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 150000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.2",
        "section": LawSection.SECTION_3.value,
        "title": "Гриферство",
        "description": "Порча чужих построек, механизмов или ландшафта.",
        "sanction_text": "Штраф 200 000 + ремонт / изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 200000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.3",
        "section": LawSection.SECTION_3.value,
        "title": "Мародёрство",
        "description": "Присвоение вещей погибших игроков или чужих ресурсов.",
        "sanction_text": "Штраф 200 000 + полный возврат.",
        "default_mute_seconds": None,
        "default_fine_amount": 200000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.4",
        "section": LawSection.SECTION_3.value,
        "title": "Несанкционированное PvP",
        "description": "Нанесение урона и убийство граждан без согласия.",
        "sanction_text": "Штраф 100 000 / за убийство 200 000 или работы.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.5",
        "section": LawSection.SECTION_3.value,
        "title": "Пропуск посторонних",
        "description": "Тайный впуск чужаков и укрывательство врагов города.",
        "sanction_text": "Штраф 100 000 / изгнание за измену.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.6",
        "section": LawSection.SECTION_3.value,
        "title": "Воинская повинность",
        "description": "Уклонение от мобилизации при войне или осаде.",
        "sanction_text": "Штраф 150 000 / лишение защиты.",
        "default_mute_seconds": None,
        "default_fine_amount": 150000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.7",
        "section": LawSection.SECTION_3.value,
        "title": "Режимные объекты",
        "description": "Проникновение на склады, бункеры и в ратушу без допуска.",
        "sanction_text": "Штраф 75 000 + выдворение.",
        "default_mute_seconds": None,
        "default_fine_amount": 75000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.8",
        "section": LawSection.SECTION_3.value,
        "title": "Неприкосновенность жилища",
        "description": "Проникновение в чужие дома (эндерперлы, баги).",
        "sanction_text": "Штраф 50 000 в пользу владельца.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.9",
        "section": LawSection.SECTION_3.value,
        "title": "Оскорбление власти в игре",
        "description": "Публичные оскорбления мэрии в чатах сервера.",
        "sanction_text": "Штраф 100 000 в казну.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.10",
        "section": LawSection.SECTION_3.value,
        "title": "Государственная измена",
        "description": "Шпионаж, слив секретов, сговор с врагами.",
        "sanction_text": "Статус «Враг города» и вечное изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "3.11",
        "section": LawSection.SECTION_3.value,
        "title": "Клевета и ложный донос",
        "description": "Ложные обвинения и сфабрикованные улики.",
        "sanction_text": "Штраф 100 000 + срок оклеветанного.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.12",
        "section": LawSection.SECTION_3.value,
        "title": "Неповиновение власти",
        "description": "Побег от стражи, неуплата штрафа за 48 часов.",
        "sanction_text": "Штраф x2 / тюрьма / изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },

    # ⚔️ III. ВНУТРИИГРОВЫЕ ЗАКОНЫ: Строительство и экология
    {
        "article_number": "3.13",
        "section": LawSection.SECTION_3.value,
        "title": "Самовольное строительство",
        "description": "Стройка вне своего участка или без плана.",
        "sanction_text": "Штраф 100 000 + снос постройки.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.14",
        "section": LawSection.SECTION_3.value,
        "title": "Эстетика и регламент",
        "description": "Коробки из грязи, столбы, брошенные каркасы.",
        "sanction_text": "24ч на исправление / снос + штраф 50 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.15",
        "section": LawSection.SECTION_3.value,
        "title": "Лаг-машины",
        "description": "Замыкания из редстоуна и перегружающие сервер фермы.",
        "sanction_text": "Демонтаж + штраф 150 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 150000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.16",
        "section": LawSection.SECTION_3.value,
        "title": "Недорубы деревьев",
        "description": "Оставление летающей листвы и недорубленных стволов.",
        "sanction_text": "Предупреждение → штраф 30 000 + уборка.",
        "default_mute_seconds": None,
        "default_fine_amount": 30000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.17",
        "section": LawSection.SECTION_3.value,
        "title": "Опасные ямы и ловушки",
        "description": "Открытые ямы 1х1, рвы, лава на участках.",
        "sanction_text": "Ликвидация + штраф 50 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.18",
        "section": LawSection.SECTION_3.value,
        "title": "Разлив жидкостей",
        "description": "Неконтролируемый спуск воды или лавы.",
        "sanction_text": "Устранение силами виновного + штраф 50 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.19",
        "section": LawSection.SECTION_3.value,
        "title": "Блокирование путей",
        "description": "Перекрытие дорог, мостов, улиц и каналов.",
        "sanction_text": "Снос заграждения + штраф 50 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.20",
        "section": LawSection.SECTION_3.value,
        "title": "Защита ландшафта",
        "description": "Срытие холмов, засыпка рек без разрешения.",
        "sanction_text": "Штраф 100 000 + восстановление рельефа.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },

    # ⚔️ III. ВНУТРИИГРОВЫЕ ЗАКОНЫ: Экономика, жилье и статус
    {
        "article_number": "3.21",
        "section": LawSection.SECTION_3.value,
        "title": "Налоговый кодекс",
        "description": "Неуплата налога за участок (чанк).",
        "sanction_text": "Арест; выкуп: налог + 50 000; >10 дней — аукцион.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.22",
        "section": LawSection.SECTION_3.value,
        "title": "Торговля без лицензии",
        "description": "Магазины и коммерция вне территории рынка.",
        "sanction_text": "Опечатывание + штраф 75 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 75000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.23",
        "section": LawSection.SECTION_3.value,
        "title": "Спекуляция казенным лутом",
        "description": "Перепродажа вещей с общих складов помощи.",
        "sanction_text": "Конфискация + штраф 150 000 + ЧС складов.",
        "default_mute_seconds": None,
        "default_fine_amount": 150000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.24",
        "section": LawSection.SECTION_3.value,
        "title": "Финансовый обман",
        "description": "Мошенничество в сделках, невозврат долгов.",
        "sanction_text": "Принудительный возврат долга + штраф 100 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 100000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.25",
        "section": LawSection.SECTION_3.value,
        "title": "Инактив (Отсутствие)",
        "description": "Оффлайн более 14 дней без заявки на отпуск.",
        "sanction_text": "Через 30 дней участок и вещи изымаются в архив.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.26",
        "section": LawSection.SECTION_3.value,
        "title": "Двойное гражданство",
        "description": "Статус жителя или посты в других городах.",
        "sanction_text": "24 часа на выбор / аннулирование гражданства.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.27",
        "section": LawSection.SECTION_3.value,
        "title": "Ответственность за гостей",
        "description": "Житель отвечает за приглашённых им лиц.",
        "sanction_text": "Ущерб и штрафы гостя списываются с жителя.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "3.28",
        "section": LawSection.SECTION_3.value,
        "title": "Выход из гражданства",
        "description": "Уход с долгами или казенными ресурсами.",
        "sanction_text": "Розыск, арест имущества на сервере, статус врага.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },

    # 💼 IV. СЛУЖБА И РАБОТА
    {
        "article_number": "4.1",
        "section": LawSection.SECTION_4.value,
        "title": "Карьерный рост",
        "description": "Повышения выдает мэр по активности и сдаче норм.",
        "sanction_text": "Повышения выдает мэр по активности и сдаче норм.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": False,
    },
    {
        "article_number": "4.2",
        "section": LawSection.SECTION_4.value,
        "title": "Халатность",
        "description": "Срыв поставленных задач и сроков сдачи ресурсов.",
        "sanction_text": "Предупреждение → штраф 50 000 → понижение.",
        "default_mute_seconds": None,
        "default_fine_amount": 50000,
        "is_ban_applicable": False,
    },
    {
        "article_number": "4.3",
        "section": LawSection.SECTION_4.value,
        "title": "Исправительные работы",
        "description": "Отработка наказания в шахте или на ферме.",
        "sanction_text": "Отказ или саботаж — пожизненное изгнание.",
        "default_mute_seconds": None,
        "default_fine_amount": 0,
        "is_ban_applicable": True,
    },
    {
        "article_number": "4.4",
        "section": LawSection.SECTION_4.value,
        "title": "Превышение полномочий",
        "description": "Кража со складов, слив бюджета служащими.",
        "sanction_text": "Снятие с должности + возврат + штраф 200 000.",
        "default_mute_seconds": None,
        "default_fine_amount": 200000,
        "is_ban_applicable": True,
    },
]


async def seed_database(max_retries: int = 5, retry_delay: float = 3.0):
    """Создает таблицы и наполняет/обновляет базу данных базовыми регуляторами, законами и овнером."""
    engine = get_engine()
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                if 'postgresql' in settings.DATABASE_URL:
                    from sqlalchemy import text
                    await conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS reprimands_count INTEGER DEFAULT 0'))
            break
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"DB connection failed after {max_retries} attempts: {e}")
                raise
            logger.warning(f"DB attempt {attempt}/{max_retries} failed ({e}). Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)

    session_factory = get_session_maker()
    async with session_factory() as session:
        # 1. Заполняем регуляторы
        for reg_data in DEFAULT_REGULATORS:
            query = select(Regulator).where(Regulator.role_level == reg_data["role_level"])
            existing_reg = await session.scalar(query)
            if not existing_reg:
                session.add(Regulator(**reg_data))
            else:
                for k, v in reg_data.items():
                    setattr(existing_reg, k, v)

        # 2. Заполняем и актуализируем законы (upsert)
        for law_data in DEFAULT_LAWS:
            query = select(Law).where(Law.article_number == law_data["article_number"])
            existing_law = await session.scalar(query)
            if not existing_law:
                session.add(Law(**law_data))
            else:
                existing_law.section = law_data["section"]
                existing_law.title = law_data["title"]
                existing_law.description = law_data["description"]
                existing_law.sanction_text = law_data["sanction_text"]
                existing_law.default_mute_seconds = law_data.get("default_mute_seconds")
                existing_law.default_fine_amount = law_data.get("default_fine_amount")
                existing_law.is_ban_applicable = law_data.get("is_ban_applicable", False)

        # 3. Регистрируем/актуализируем Овнера города (@DivniDed / 1965081517)
        if settings.OWNER_ID:
            query_owner = select(User).where(User.telegram_id == settings.OWNER_ID)
            owner_user = await session.scalar(query_owner)
            if not owner_user:
                session.add(
                    User(
                        telegram_id=settings.OWNER_ID,
                        username=settings.OWNER_USERNAME,
                        full_name="Овнер Ратуши",
                        role_level=PositionLevel.SENIOR_ADMINISTRATION.value,
                        is_enemy=False,
                    )
                )
            else:
                owner_user.role_level = PositionLevel.SENIOR_ADMINISTRATION.value
                owner_user.is_enemy = False
                if not owner_user.username:
                    owner_user.username = settings.OWNER_USERNAME

        # 4. Базовые настройки чата (если задан MAIN_CHAT_ID)
        if settings.MAIN_CHAT_ID:
            query = select(ChatSettings).where(ChatSettings.chat_id == settings.MAIN_CHAT_ID)
            existing_chat = await session.scalar(query)
            if not existing_chat:
                session.add(ChatSettings(chat_id=settings.MAIN_CHAT_ID))

        await session.commit()
    logger.info("Database seeding & law synchronization completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed_database())
