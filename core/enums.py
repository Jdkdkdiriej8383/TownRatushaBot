from enum import IntEnum, Enum


class PositionLevel(IntEnum):
    """
    Иерархия должностей города (0-5) и государственные ранги (0-4).
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
        }
        return titles.get(level, f"Должность ({level})")

    @classmethod
    def get_rank(cls, level: int) -> int:
        """Возвращает государственный ранг от 0 до 4 (или -1 для врага)."""
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
        return 4


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
    "мэр": (5, GovernmentRole.MAYOR.value),
    "премьер-министр": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьер": (5, GovernmentRole.PRIME_MINISTER.value),
    "премьер министр": (5, GovernmentRole.PRIME_MINISTER.value),
    "конституционный судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "главный судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "конст судья": (5, GovernmentRole.CHIEF_JUSTICE.value),
    "высшая администрация": (5, "Высшая администрация"),
    "заместитель мэра": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "зам мэра": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "вице-мэр": (4, GovernmentRole.DEPUTY_MAYOR.value),
    "министр": (4, GovernmentRole.MINISTER.value),
    "судья": (4, GovernmentRole.JUDGE.value),
    "администрация": (4, "Администрация"),
    "старший блюститель": (3, "Старший блюститель"),
    "блюститель": (2, GovernmentRole.WARDEN.value),
    "блюститель чата": (2, GovernmentRole.WARDEN.value),
    "помощник": (1, GovernmentRole.ASSISTANT.value),
    "хелпер": (1, GovernmentRole.ASSISTANT.value),
    "гражданин": (0, GovernmentRole.CITIZEN.value),
    "житель": (0, GovernmentRole.CITIZEN.value),
}


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
