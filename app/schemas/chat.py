# app/schemas/chat.py
"""
Pydantic schemas for the AI Manager chat.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field

from ..models.chat import ChatRole


class ChatMessageCreate(BaseModel):
    """A message sent to the AI Manager."""

    message: str = Field(..., min_length=1)
    entity_data: Optional[dict[str, Any]] = Field(
        None, description="Entity fields to run through the policy engine, if this message should trigger a check"
    )
    domain: Optional[str] = Field(None, description="Policy domain to evaluate against, required if entity_data is set")
    session_id: Optional[str] = Field(None, description="Conversation to continue; a new one is created if omitted")


class ChatMessageResponse(BaseModel):
    """A single persisted message (user or assistant)."""

    id: int
    session_id: str
    role: ChatRole
    content: str
    extra_data: Optional[dict[str, Any]] = None
    created_at: datetime

    @computed_field
    @property
    def response(self) -> str:
        """
        Alias for `content` — matches the `{ response, tool_calls? }` shape the
        existing AI Manager chat UI (frontend/src/components/ai/AIManager.tsx)
        already expects from POST /api/ai/chat.
        """
        return self.content

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """Full message history for one conversation, oldest first."""

    session_id: str
    messages: list[ChatMessageResponse]
