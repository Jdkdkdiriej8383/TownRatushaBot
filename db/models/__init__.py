from db.models.user import User
from db.models.regulator import Regulator
from db.models.chat_settings import ChatSettings
from db.models.law import Law
from db.models.fine import Fine
from db.models.punishment import Punishment
from db.models.report import Report
from db.models.ticket import Ticket
from db.models.topic_config import TopicConfig

__all__ = [
    "User",
    "Regulator",
    "ChatSettings",
    "Law",
    "Fine",
    "Punishment",
    "Report",
    "Ticket",
    "TopicConfig",
]
