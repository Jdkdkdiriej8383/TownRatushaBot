from enum import IntEnum, Enum


class PositionLevel(IntEnum):
    """
    Иерархия должностей города (0-5).
    Примечание: термины 'Ранг' и 'Модератор' строго запрещены!
    Используются только 'Должность' и 'Блюститель'.
    """
    ENEMY = -1                     # Спец-статус: Враг города (лишение всех прав)
    CITIZEN = 0                   # Гражданин
    ASSISTANT = 1                 # Помощник (младший блюститель)
    CHAT_WARDEN = 2               # Блюститель чата
    SENIOR_WARDEN = 3             # Старший блюститель
    ADMINISTRATION = 4            # Администрация
    SENIOR_ADMINISTRATION = 5     # Высшая администрация (Старшая администрация)

    @classmethod
    def get_title(cls, level: int) -> str:
        titles = {
            cls.ENEMY: "Враг города",
            cls.CITIZEN: "Гражданин",
            cls.ASSISTANT: "Помощник",
            cls.CHAT_WARDEN: "Блюститель чата",
            cls.SENIOR_WARDEN: "Старший блюститель",
            cls.ADMINISTRATION: "Администрация",
            cls.SENIOR_ADMINISTRATION: "Высшая администрация",
        }
        return titles.get(level, f"Неизвестная должность ({level})")


class LawSection(str, Enum):
    SECTION_1 = "Раздел I. Общие положения"
    SECTION_2 = "Раздел II. Чат Telegram"
    SECTION_3 = "Раздел III. Внутриигровые законы"
    SECTION_4 = "Раздел IV. Служба и работа"


class PunishmentType(str, Enum):
    WARN = "предупреждение"
    MUTE = "мут"
    BAN = "изгнание"              # Бан в терминах города - изгнание
    FINE = "штраф"


class FineStatus(str, Enum):
    ACTIVE = "active"             # Выставлен, ожидает оплаты (до 48ч)
    PAID = "paid"                 # Оплачен
    OVERDUE = "overdue"           # Просрочен (>48ч), удвоен (x2), розыск
    CANCELLED = "cancelled"       # Отменен судом/старшей администрацией
