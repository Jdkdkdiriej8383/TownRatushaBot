from sqlalchemy import BigInteger, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class ChatSettings(Base):
    """
    Таблица настроек регуляторов чата:
    - Переключатель анти-капса (>70% капса)
    - Переключатель медиа-спама (>3 ГС/кружков/стикеров подряд)
    - Переключатель ссылок/рекламы
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

    def __repr__(self) -> str:
        return f"<ChatSettings chat_id={self.chat_id} caps={self.anti_caps_enabled} spam={self.media_spam_enabled}>"
