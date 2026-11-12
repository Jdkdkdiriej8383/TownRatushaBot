from enum import IntEnum, Enum


class PositionLevel(IntEnum):
    """
    Иерархия должностей города (0-6) и государственные ранги (0-5).
    Ранг 5: Создатель / Владелец города (level 6)
    Ранг 4: Высшая администрация (level 5)
    Ранг 3: Администрация (level 4, 3)
    Ранг 2: Блюститель (level 2)
    Ранг 1: Помощник (level 1)
    Ранг 0: Гражданин (level 0)
    Ранг -1: Враг города (level -1)
    """
    ENEMY = -1                     # Спец-статус: Враг города (лишение всех прав)
    CITIZEN = 0                   # Ранг 0: Гражданин
    ASSISTANT = 1                 # Ранг 1: Помощник
    CHAT_WARDEN = 2               # Ранг 2: Блюститель чата
    SENIOR_WARDEN = 3             # Ранг 3: Старший блюститель
    ADMINISTRATION = 4            # Ранг 3: Администрация (Зам. мэра, Министр, Судья)
    SENIOR_ADMINISTRATION = 5     # Ранг 4: Высшая администрация (Мэр, Премьер-министр, Конституционный судья)
    OWNER = 6                     # Ранг 5: Создатель / Владелец города

    @classmethod
    def get_title(cls, level: int) -> str:
        titles = {
            cls.ENEMY: "Враг города",
            cls.CITIZEN: "Гражданин",
            cls.ASSISTANT: "Помощник",
            cls.CHAT_WARDEN: "Блюститель",
            cls.SENIOR_WARDEN: "Старший блюститель",
            cls.ADMINISTRATION: "Администрация",
            cls.SENIOR_ADMINISTRATION: "Высшая администрация",
            cls.OWNER: "Высшая администрация",
        }
        return titles.get(level, f"Должность ({level})")

    @classmethod
    def get_rank(cls, level: int) -> int:
        """Возвращает государственный ранг от 0 до 5 (или -1 для врага)."""
        if level < 0:
            return -1
        if level == 0:
            return 0
        if level == 1:
            return 1
        if level == 2:
            return 2
        if level in (3, 4):
            return 3
        if level == 5:
            return 4
        return 5


class GovernmentRole(str, Enum):
    # Ранг 4: Высшая администрация (Supreme Admins)
    MAYOR = "Мэр"
    PRIME_MINISTER = "Премьер-министр"
    CHIEF_JUSTICE = "Конституционный судья"

    # Ранг 3: Администрация (Middle Admins)
    DEPUTY_MAYOR = "Заместитель мэра"
    MINISTER = "Министр"
    JUDGE = "Судья"

    # Ранг 2: Блюститель (Senior Moderator)
    WARDEN = "Блюститель"

    # Ранг 1: Помощник (Junior Moderator / Helper)
    ASSISTANT = "Помощник"

    # Ранг 0: Гражданин (Member)
    CITIZEN = "Гражданин"


ROLE_ALIASES: dict[str, tuple[int, str]] = {
    # Ранг 4: Высшая администрация (level 5)
    "мэр": (5, GovernmentRole.MAYOR.value),
    "мэра": (5, GovernmentRole.MAYOR.value),
    "мэром": (5, GovernmentRole.MAYOR.value),
    "мер": (5, GovernmentRole.MAYOR.value),
    "мера": (5, GovernmentRole.MAYOR.value),
    "мером": (5, GovernmentRole.MAYOR.value),
    "mayor": (5, GovernmentRole.MAYOR.value),
    "премьер-министр": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьер": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьера": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьером": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьер министр": (5, GovernmentRole.PRIME_MINISTER.value),
    "пм": (5, GovernmentRole.PRIME_MINISTER.value),
    "pm": (5, GovernmentRole.PRIME_MINISTER.value),
    "prime": (5, GovernmentRole.PRIME_MINISTER.value),
    "prime minister": (5, GovernmentRole.PRIME_MINISTER.value),
    "prime-minister": (5, GovernmentRole.PRIME_MINISTER.value),
    "конституционный судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "конституционного судью": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "главный судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "конст судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "конст": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "ксуд": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "главсудья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "chief justice": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "chief_justice": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "высшая администрация": (5, "Высшая администрация"),
    "высшая админка": (5, "Высшая администрация"),
    "4": (5, GovernmentRole.MAYOR.value),
    "5": (5, GovernmentRole.MAYOR.value),

    # Ранг 3: Администрация (level 4, 3)
    "заместитель мэра": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "зам мэра": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "зам": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "зама": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "замом": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "вице": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "вице-мэр": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "вице мэр": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "заместитель": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "deputy": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "deputy mayor": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "deputy_mayor": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "министр": (4, GovernmentRole.MINISTER.value),
    "министра": (4, GovernmentRole.MINISTER.value),
    "министром": (4, GovernmentRole.MINISTER.value),
    "minister": (4, GovernmentRole.MINISTER.value),
    "судья": (4, GovernmentRole.JUDGE.value),
    "судью": (4, GovernmentRole.JUDGE.value),
    "судьей": (4, GovernmentRole.JUDGE.value),
    "судом": (4, GovernmentRole.JUDGE.value),
    "суд": (4, GovernmentRole.JUDGE.value),
    "judge": (4, GovernmentRole.JUDGE.value),
    "администрация": (4, "Администрация"),
    "админ": (4, "Администрация"),
    "админа": (4, "Администрация"),
    "администратор": (4, "Администрация"),
    "admin": (4, "Администрация"),
    "старший блюститель": (3, "Старший блюститель"),
    "ст блюститель": (3, "Старший блюститель"),
    "ст. блюститель": (3, "Старший блюститель"),
    "старший": (3, "Старший блюститель"),
    "senior warden": (3, "Старший блюститель"),
    "senior_warden": (3, "Старший блюститель"),
    "3": (4, GovernmentRole.MINISTER.value),

    # Ранг 2: Блюститель (level 2)
    "блюститель": (2, GovernmentRole.WARDEN.value),
    "блюстителя": (2, GovernmentRole.WARDEN.value),
    "блюстителем": (2, GovernmentRole.WARDEN.value),
    "блюститель чата": (2, GovernmentRole.WARDEN.value),
    "модер": (2, GovernmentRole.WARDEN.value),
    "модера": (2, GovernmentRole.WARDEN.value),
    "модератор": (2, GovernmentRole.WARDEN.value),
    "модератора": (2, GovernmentRole.WARDEN.value),
    "модером": (2, GovernmentRole.WARDEN.value),
    "warden": (2, GovernmentRole.WARDEN.value),
    "mod": (2, GovernmentRole.WARDEN.value),
    "moderator": (2, GovernmentRole.WARDEN.value),
    "2": (2, GovernmentRole.WARDEN.value),

    # Ранг 1: Помощник (level 1)
    "помощник": (1, GovernmentRole.ASSISTANT.value),
    "помощника": (1, GovernmentRole.ASSISTANT.value),
    "помощником": (1, GovernmentRole.ASSISTANT.value),
    "хелпер": (1, GovernmentRole.ASSISTANT.value),
    "хелпера": (1, GovernmentRole.ASSISTANT.value),
    "хелпером": (1, GovernmentRole.ASSISTANT.value),
    "саппорт": (1, GovernmentRole.ASSISTANT.value),
    "assistant": (1, GovernmentRole.ASSISTANT.value),
    "helper": (1, GovernmentRole.ASSISTANT.value),
    "support": (1, GovernmentRole.ASSISTANT.value),
    "1": (1, GovernmentRole.ASSISTANT.value),

    # Ранг 0: Гражданин (level 0)
    "гражданин": (0, GovernmentRole.CITIZEN.value),
    "гражданина": (0, GovernmentRole.CITIZEN.value),
    "гражданином": (0, GovernmentRole.CITIZEN.value),
    "житель": (0, GovernmentRole.CITIZEN.value),
    "жителя": (0, GovernmentRole.CITIZEN.value),
    "дефолт": (0, GovernmentRole.CITIZEN.value),
    "снять": (0, GovernmentRole.CITIZEN.value),
    "разжаловать": (0, GovernmentRole.CITIZEN.value),
    "citizen": (0, GovernmentRole.CITIZEN.value),
    "user": (0, GovernmentRole.CITIZEN.value),
    "member": (0, GovernmentRole.CITIZEN.value),
    "0": (0, GovernmentRole.CITIZEN.value),
}


def resolve_role_alias(role_input: str) -> tuple[int, str] | None:
    """
    Разрешает пользовательский ввод должности/ранга в (role_level, role_title).
    Поддерживает точные совпадения, числовые ранги, частичные совпадения и очистку префиксов/суффиксов.
    """
    if not role_input:
        return None
    import re
    cleaned = role_input.strip().lower()
    # Убираем префиксы: "ранг 3", "уровень: 2", "должность = министр", "rank 4"
    cleaned = re.sub(r'^(?:ранг|уровень|должность|rank|level)\s*[:=]?\s*', '', cleaned).strip()
    cleaned = re.sub(r'\s*(?:ранг|уровень|ранга)$', '', cleaned).strip()

    if cleaned in ROLE_ALIASES:
        return ROLE_ALIASES[cleaned]

    # Поиск по подстроке (исключаем короткие алиасы вроде цифр)
    for alias, info in ROLE_ALIASES.items():
        if len(alias) > 2 and (alias in cleaned or cleaned in alias):
            return info

    return None


class LawSection(str, Enum):
    SECTION_1 = "Раздел I. Общие положения"
    SECTION_2 = "Раздел II. Чат Telegram"
    SECTION_3 = "Раздел III. Внутриигровые законы"
    SECTION_4 = "Раздел IV. Служба и работа"


class PunishmentType(str, Enum):
    WARN = "предупреждение"
    UNWARN = "снятие предупреждения"
    MUTE = "мут"
    UNMUTE = "размут"
    KICK = "кик"
    BAN = "бан"
    UNBAN = "разбан"
    FINE = "штраф"
    AMNESTY = "амнистия"
    REPRIMAND = "выговор"
    DISMISSAL = "отстранение"
    APPEAL = "апелляция"
    VERDICT = "вердикт суда"


class FineStatus(str, Enum):
    ACTIVE = "active"             # Выставлен, ожидает оплаты (до 48ч)
    PAID = "paid"                 # Оплачен
    OVERDUE = "overdue"           # Просрочен (>48ч), удвоен (x2), розыск
    CANCELLED = "cancelled"       # Отменен судом/старшей администрацией


class AuctionStatus(str, Enum):
    ACTIVE = "active"             # Активные торги
    COMPLETED = "completed"       # Успешно завершен с победителем
    CANCELLED = "cancelled"       # Отменен или завершен без ставок


class ReportStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    FALSE_REPORT = "false_report"


class TicketStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class TicketCategory(str, Enum):
    MAYOR = "Мэрия / Кабинет Министров"
    COURT = "Конституционный Суд / Суд"
    STAFF_COMPLAINT = "Жалоба на персонал"
    GENERAL = "Общий вопрос / Помощь"


class TopicType(str, Enum):
    COMMUNITY = "community"
    REPORTS = "reports"
    TICKETS = "tickets"
    COURT = "court"
    ADMIN = "admin"
    DECREES = "decrees"
    LOGS = "logs"
