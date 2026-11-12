from typing import Optional
from sqlalchemy import BigInteger, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class ChatSettings(Base):
    """
    Таблица настроек регуляторов и подсистем чата:
    - Переключатель анти-капса (>70% капса)
    - Переключатель медиа-спама (>3 ГС/кружков/стикеров подряд)
    - Переключатель ссылок/рекламы
    - Конфигурация системы жалоб (Reports):
      * reports_destination: "both" (ЛС + топик), "topic" (только топик), "pm" (только в ЛС)
      * reports_anonymous: скрывать ли заявителя (True/False)
      * reports_topic_id: кастомный ID топика для жалоб
    """
    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Регулятор анти-капса
    anti_caps_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_caps_threshold: Mapped[float] = mapped_column(Float, default=0.70)
    anti_caps_min_chars: Mapped[int] = mapped_column(Integer, default=6)

    # Регулятор медиа-спама (>3 подряд)
    media_spam_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    media_spam_threshold: Mapped[int] = mapped_column(Integer, default=3)

    # Регулятор ссылок и несанкционированной рекламы
    anti_link_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Авто-мут нарушителям чата (в секундах)
    auto_mute_seconds: Mapped[int] = mapped_column(Integer, default=1800)  # 30 мин

    # Настройки системы жалоб (Reports)
    reports_destination: Mapped[str] = mapped_column(String(32), default="both")  # "both", "topic", "pm"
    reports_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    reports_topic_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Сетка чатов (Мульти-чат объединение / Федерация)
    network_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    network_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Государственная казна и городской бюджет
    treasury_balance: Mapped[int] = mapped_column(Integer, default=100000)      # Резерв казны (100 000 ₽)
    total_salaries_paid: Mapped[int] = mapped_column(Integer, default=0)        # Выплачено зарплат и премий
    total_fines_collected: Mapped[int] = mapped_column(Integer, default=0)      # Собрано штрафов и аукционов

    def __repr__(self) -> str:
        return f"<ChatSettings chat_id={self.chat_id} net={self.network_id} treasury={self.treasury_balance}>"
