# app/models/chat.py
"""
ChatMessage Model - AI Manager conversation history.

Persists every message exchanged with the AI Manager chat, grouped by
session_id, so a conversation can be replayed or audited later. See
app/services/ai_manager.py for how replies are produced.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func

from ..core.database import Base


class ChatRole(str, Enum):
    """Who sent this message."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    """
    A single message in an AI Manager conversation.

    Design principles (mirrors Insight):
    - Sessioned: `session_id` groups messages into one conversation
    - Traceable: `extra_data` carries the policy engine's verdict, matched
      policy ids, and workbench item id behind an assistant reply
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)

    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # ChatRole
    content = Column(Text, nullable=False)
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<ChatMessage {self.id}: {self.role} in session {self.session_id}>"
