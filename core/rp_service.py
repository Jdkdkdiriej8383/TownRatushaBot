from db.models import User
from core.enums import PositionLevel
from core.exceptions import SubordinationViolationError, EnemyOfTownError


class RPService:
    """
    Сервис ролевых взаимодействий граждан и блюстителей
    с учетом иерархии должностей и субординации.
    """

    @staticmethod
    def salute(actor: User, target: User) -> str:
        """Отдать честь."""
        if actor.is_enemy:
            raise EnemyOfTownError("Врагам города запрещено отдавать воинскую честь!")

        if target.role_level > actor.role_level:
            return (
                f"🫡 <b>{actor.full_name}</b> вытянулся в струнку и четко отдал честь "
                f"старшему по должности <b>{target.full_name}</b> ({target.position_title})."
            )
        elif target.role_level == actor.role_level:
            return (
                f"🫡 <b>{actor.full_name}</b> обменялся уставным воинским приветствием "
                f"с коллегой по должности <b>{target.full_name}</b> ({target.position_title})."
            )
        else:
            return (
                f"🫡 <b>{actor.full_name}</b> ({actor.position_title}) отдал честь "
                f"<b>{target.full_name}</b>, выражая особое доверие и уважение младшему по чину."
            )

    @staticmethod
    def arrest(actor: User, target: User) -> str:
        """Арестовать."""
        if actor.role_level < PositionLevel.ASSISTANT.value:
            return f"🚫 <b>{actor.full_name}</b>, у гражданских лиц нет права на проведение ареста!"

        if target.is_enemy or target.is_wanted:
            return (
                f"⛓️ <b>{actor.full_name}</b> ({actor.position_title}) заломил руки и защелкнул кандалы "
                f"на особо опасном гражданине <b>{target.full_name}</b> "
                f"({'Враг города' if target.is_enemy else 'В розыске'})! Нарушитель отправлен в конвойную часть."
            )

        if actor.role_level <= target.role_level:
            raise SubordinationViolationError(actor.position_title, target.position_title)

        return (
            f"⛓️ <b>{actor.full_name}</b> ({actor.position_title}) применил спецсредства, "
            f"задержал гражданина <b>{target.full_name}</b> ({target.position_title}) "
            f"и доставил его в участок для судебного разбирательства!"
        )

    @staticmethod
    def frisk(actor: User, target: User) -> str:
        """Досмотреть."""
        if actor.role_level < PositionLevel.ASSISTANT.value:
            return f"🚫 <b>{actor.full_name}</b>, обыск и досмотр разрешены только блюстителям порядка!"

        if not target.is_enemy and not target.is_wanted and actor.role_level <= target.role_level:
            raise SubordinationViolationError(actor.position_title, target.position_title)

        return (
            f"🔍 <b>{actor.full_name}</b> ({actor.position_title}) надел перчатки и провел полный личный досмотр "
            f"гражданина <b>{target.full_name}</b> ({target.position_title}).\n"
            f"Карманы и инвентарь проверены на наличие запрещенных предметов."
        )

    @staticmethod
    def shake_hands(actor: User, target: User) -> str:
        """Пожать руку."""
        if actor.is_enemy:
            return f"🚫 Рукопожатие отклонено: <b>{actor.full_name}</b> объявлен Врагом города."
        if target.is_enemy:
            return f"🚫 <b>{actor.full_name}</b> побрезговал жать руку Врагу города (<b>{target.full_name}</b>)."

        return (
            f"🤝 <b>{actor.full_name}</b> ({actor.position_title}) крепко пожал руку "
            f"<b>{target.full_name}</b> ({target.position_title}) в знак дружбы и согласия."
        )

    @staticmethod
    def issue_subpoena(actor: User, target: User) -> str:
        """Выдать повестку."""
        if actor.role_level < PositionLevel.ASSISTANT.value:
            return f"🚫 Только городские блюстители и суд уполномочены выписывать повестки!"

        if actor.role_level <= target.role_level and not target.is_enemy:
            raise SubordinationViolationError(actor.position_title, target.position_title)

        return (
            f"📬 <b>{actor.full_name}</b> ({actor.position_title}) вручил официальную повестку "
            f"с гербовой печатью жителю <b>{target.full_name}</b> ({target.position_title})!\n"
            f"Явка в Городской Суд строго обязательна."
        )
