from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class ReferendumType(str, Enum):
    LAW_AMENDMENT = "law_amendment"   # Поправка в Городской Свод Законов
    JURY_TRIAL = "jury_trial"         # Суд присяжных (публичный вердикт)
    CITY_INITIATIVE = "initiative"     # Городская инициатива


class UserVotingStatusResponse(BaseModel):
    telegram_id: int
    can_vote: bool = Field(..., description="Имеет ли право голосовать (Гражданин+ без статуса Врага)")
    role_level: int = Field(..., description="Уровень должности (-1..5)")
    position_title: str = Field(..., description="Название должности")
    is_enemy: bool = Field(..., description="Статус Враг города")
    minecraft_nick: Optional[str] = None
    reason: Optional[str] = None


class ReferendumCreateRequest(BaseModel):
    title: str
    description: str
    referendum_type: ReferendumType = ReferendumType.LAW_AMENDMENT
    article_number: Optional[str] = None
    proposed_text: Optional[str] = None
    target_user_id: Optional[int] = None
    initiator_tg_id: int
    duration_hours: int = 24


class ReferendumResultWebhook(BaseModel):
    poll_id: str
    referendum_type: ReferendumType
    article_number: Optional[str] = None
    proposed_text: Optional[str] = None
    target_user_id: Optional[int] = None
    passed: bool = Field(..., description="Принято ли большинством голосов")
    votes_for: int
    votes_against: int
    total_votes: int
    details: Optional[str] = None


class IntercomResponse(BaseModel):
    status: str = "ok"
    message: str
