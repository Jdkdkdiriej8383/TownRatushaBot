from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class Regulator(Base):
    """
    Таблица 'regulators' — конфигуратор прав и лимитов для каждой должности (0-5).
    Определяет жесткие рамки власти блюстителей и защиту субординации.
    """
    __tablename__ = "regulators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_level: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)

    # Лимиты наказаний
    max_mute_time: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Максимальное время мута в секундах (напр. 7200 для Помощника, 86400 для Блюстителя чата)"
    )
    max_fine_amount: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Максимальная сумма выписываемого штрафа (напр. 200000 для Старшего блюстителя)"
    )
    can_ban: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Булево право на выдачу бана (изгнания)"
    )
    max_ban_time: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Максимальное время бана в секундах (604800 = 7 дней, 0 = без ограничений/перманент)"
    )
    can_edit_laws: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Право изменять статьи закона (по умолчанию только уровни 4 и 5)"
    )
    can_appoint_level: Mapped[int] = mapped_column(
        Integer,
        default=-1,
        comment="До какого уровня должности имеет право назначать/повышать (-1 = нет прав)"
    )
    can_create_referendum: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Право инициировать общегородской референдум (уровни 4 и 5)"
    )

    def __repr__(self) -> str:
        return f"<Regulator level={self.role_level} title='{self.title}'>"
