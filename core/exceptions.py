class TownBaseException(Exception):
    """Базовое исключение ролевого города."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SubordinationViolationError(TownBaseException):
    """
    Нарушение субординации: Блюститель может наказывать
    ТОЛЬКО пользователей с должностью строго ниже своей.
    """
    def __init__(self, issuer_title: str, target_title: str):
        message = (
            f"⛔ <b>Нарушение субординации!</b>\n\n"
            f"Ваша должность: <b>{issuer_title}</b>.\n"
            f"Должность гражданина: <b>{target_title}</b>.\n\n"
            f"Блюститель имеет право применять санкции "
            f"<b>исключительно</b> к лицам, чья должность строго ниже собственной!"
        )
        super().__init__(message)


class RegulatorLimitExceededError(TownBaseException):
    """Превышение лимита прав, установленного Регулятором."""
    pass


class EnemyOfTownError(TownBaseException):
    """Пользователь признан Врагом города и поражен в правах."""
    def __init__(self, reason: str = "Лишение всех гражданских прав"):
        message = (
            f"☠️ <b>Отказ в доступе!</b>\n"
            f"Данный житель имеет статус <b>«Враг города»</b>.\n"
            f"Причина: {reason}."
        )
        super().__init__(message)


class LawNotFoundError(TownBaseException):
    """Статья Свода Законов не найдена."""
    def __init__(self, article_number: str):
        message = (
            f"⚖️ Статья <b>№ {article_number}</b> не найдена в Городском Своде Законов.\n"
            f"Используйте <code>/закон</code> для получения списка доступных статей."
        )
        super().__init__(message)


class UserNotFoundError(TownBaseException):
    """Пользователь не зарегистрирован в базе данных города."""
    def __init__(self, identifier: str):
        message = f"🔍 Гражданин с идентификатором <b>{identifier}</b> не найден в реестре города."
        super().__init__(message)


class SelfPunishmentError(TownBaseException):
    """Попытка применить санкцию к самому себе."""
    def __init__(self):
        super().__init__("🤦 Блюститель не может наказывать самого себя!")
