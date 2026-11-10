import logging
from db.models.user import User
from core.enums import PositionLevel, GovernmentRole
from core.exceptions import TownBaseException
from config import settings

logger = logging.getLogger("townbot.hierarchy")


class HierarchyService:
    """
    Сервис государственной иерархии и проверки прав (RBAC).
    Обеспечивает строгое соблюдение субординации: Ранг_Инициатора > Ранг_Цели.
    """

    @classmethod
    def is_owner(cls, user: User) -> bool:
        """Проверяет, является ли пользователь Владельцем/Овнером города."""
        if not user:
            return False
        if user.telegram_id == settings.OWNER_ID:
            return True
        if user.username and user.username.lower() == settings.OWNER_USERNAME.lower():
            return True
        if getattr(user, "role_level", 0) >= PositionLevel.OWNER.value:
            return True
        if getattr(user, "government_rank", 0) >= 5:
            return True
        return False

    @classmethod
    def validate_seniority(cls, initiator: User, target: User, action_name: str = "наказание") -> None:
        """
        Проверяет правило старшинства: Ранг_Инициатора > Ранг_Цели.
        Никто не может наказать равного или старшего по должности.
        """
        if cls.is_owner(initiator):
            # Владелец обладает абсолютной властью
            return

        if initiator.id == target.id:
            raise TownBaseException(f"🤷 Нельзя применять {action_name} к самому себе!")

        if cls.is_owner(target):
            raise TownBaseException("🚫 Овнер города обладает абсолютным иммунитетом от любых взысканий!")

        # Конституционный судья обладает полной судебной неприкосновенностью
        if target.custom_title == GovernmentRole.CHIEF_JUSTICE.value:
            raise TownBaseException("⚖️ <b>Конституционный судья</b> обладает полной судебной неприкосновенностью!")

        initiator_rank = initiator.government_rank
        target_rank = target.government_rank

        if initiator_rank <= target_rank:
            raise TownBaseException(
                f"🚫 <b>Нарушение субординации!</b>\n"
                f"Вы ({initiator.position_title}, Ранг {initiator_rank}) не можете применить {action_name} "
                f"к равному или старшему по должности ({target.position_title}, Ранг {target_rank})."
            )

    @classmethod
    def can_appoint_role(
        cls, initiator: User, target: User, target_level: int, target_title: str
    ) -> tuple[bool, str]:
        """
        Проверяет право назначения на государственную должность:
        - Мэр: может назначать и снимать любые должности (Ранги 0–4).
        - Премьер-министр: назначает министров и ниже (Ранги 0–3).
        - Заместитель мэра: назначает блюстителей и помощников (Ранги 0–2).
        - Инициатор должен превосходить целевой ранг и текущий ранг цели.
        """
        if cls.is_owner(initiator):
            return True, "Разрешено Владельцем"

        target_rank = PositionLevel.get_rank(target_level)
        initiator_rank = initiator.government_rank

        # Субординация по текущему рангу цели
        if initiator_rank <= target.government_rank:
            return False, f"Вы не можете изменять должность равного или старшего сотрудника ({target.position_title})!"

        # Правила по конкретным высшим должностям
        initiator_title = initiator.custom_title or initiator.position_title

        if initiator_title == GovernmentRole.MAYOR.value:
            # Мэр может назначать любые должности рангов 0-4
            return True, "Разрешено Мэром"

        if initiator_title == GovernmentRole.PRIME_MINISTER.value:
            # Премьер-министр назначает министров и ниже (ранги 0-3)
            if target_rank >= 4:
                return False, "Премьер-министр не может назначать Мэра или Конституционного судью!"
            return True, "Разрешено Премьер-министром"

        if initiator_title == GovernmentRole.DEPUTY_MAYOR.value:
            # Заместитель мэра назначает помощников и блюстителей (ранги 0-2)
            if target_rank >= 3:
                return False, "Заместитель мэра может назначать только Блюстителей и Помощников (Ранги 1–2)!"
            return True, "Разрешено Заместителем мэра"

        # Если обычная администрация (Ранг 3-4 без спец-титула)
        if initiator_rank > target_rank:
            if initiator_rank < 3:
                return False, "Назначать на государственные должности разрешено только Администрации (Ранг 3+)!"
            return True, "Разрешено Администрацией"

        return False, "У вас недостаточно полномочий для назначения данной должности!"

    @classmethod
    def can_ban(cls, user: User) -> bool:
        """Проверяет право выдачи бана (изгнания). Доступно от Ранга 3 или Овнеру."""
        if cls.is_owner(user):
            return True
        return user.government_rank >= 3

    @classmethod
    def get_max_mute_seconds(cls, user: User) -> int:
        """Возвращает максимальную длительность мута в секундах для данного ранга."""
        if cls.is_owner(user):
            return 31536000  # 1 год

        rank = user.government_rank
        if rank == 1:
            return 7200       # Помощник: до 2 часов
        if rank == 2:
            return 86400      # Блюститель: до 24 часов
        if rank == 3:
            return 2592000    # Администрация: до 30 дней
        if rank >= 4:
            return 31536000   # Высшая администрация: без ограничений
        return 0
