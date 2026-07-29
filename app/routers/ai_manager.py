# app/routers/ai_manager.py
"""
AI Manager chat endpoints.

The chat is a thin conversational surface over the policy engine today — see
app/services/ai_manager.py for the Auto-integration seam. Every message
(user + assistant) is persisted so a conversation can be replayed via
GET /chat/{session_id}.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.chat import ChatMessage
from ..schemas.chat import ChatHistoryResponse, ChatMessageCreate, ChatMessageResponse
from ..security import get_current_user
from ..services import ai_manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Manager"])


@router.post("/chat", response_model=ChatMessageResponse)
async def chat(
    payload: ChatMessageCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Send a message to the AI Manager.

    If `entity_data` + `domain` are given, this runs a real structured policy
    check (app/services/policy_engine.py) and replies based on the verdict.
    Otherwise it's a no-op chat turn — the seam Auto will plug into later.
    """
    assistant_message = await ai_manager.handle_chat_message(
        db=db,
        session_id=payload.session_id,
        message=payload.message,
        entity_data=payload.entity_data,
        domain=payload.domain,
        user=user,
    )
    return ChatMessageResponse.model_validate(assistant_message)


@router.get("/chat/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the full message history for one conversation, oldest first."""
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    if not messages:
        raise HTTPException(status_code=404, detail="No messages found for this session")

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
    )
