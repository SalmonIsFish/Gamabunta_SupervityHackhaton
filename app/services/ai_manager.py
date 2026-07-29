# app/services/ai_manager.py
"""
AI Manager chat service.

Handles one chat turn: persists the user's message, optionally runs a
structured policy check via app/services/policy_engine.py, composes a
templated (not LLM-generated) reply describing the outcome, and persists it.

`_dispatch` is the seam for later Auto integration: swap its body for a real
call to auto.supervity.ai's orchestrator and neither handle_chat_message's
signature nor the router that calls it needs to change.
"""

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditCategory, AuditSeverity
from ..models.chat import ChatMessage, ChatRole
from ..schemas.policy import PolicyVerdict
from . import policy_engine
from .audit import audit

log = logging.getLogger(__name__)


def _compose_reply(result: policy_engine.PolicyEvaluationResult) -> str:
    """Turn a policy evaluation result into a templated reply string."""
    names = ", ".join(f"'{m.name}'" for m in result.matched_policies)

    if result.verdict == PolicyVerdict.AUTO_APPROVED:
        return f"✅ Auto-approved under Policy {names}."
    if result.verdict == PolicyVerdict.REQUIRES_REVIEW:
        return f"⚠️ This needs human review under Policy {names} before proceeding."
    if result.verdict == PolicyVerdict.BLOCKED_PENDING_REVIEW:
        return f"⚠️ Flagged for review — conflicting policies matched, routed to the Workbench (#{result.workbench_item_id})."
    return "No active policies matched for this domain."


async def _dispatch(
    db: Session,
    message: str,
    entity_data: Optional[dict[str, Any]],
    domain: Optional[str],
    source_agent: Optional[str],
) -> tuple[str, dict[str, Any]]:
    """
    Decide what to do about this message and produce (reply_text, extra_data).

    Today this runs the local structured policy engine directly whenever the
    caller supplies entity_data + domain. This is the integration seam: a
    later version can dispatch to auto.supervity.ai instead, as long as it
    keeps returning (reply_text, extra_data).
    """
    if not (entity_data and domain):
        return "No active policies matched for this domain.", {}

    result = await policy_engine.evaluate(
        domain=domain,
        entity_type="chat_entity",
        entity_data=entity_data,
        source_agent=source_agent,
        db=db,
    )
    reply = _compose_reply(result)
    extra_data = {
        "verdict": result.verdict.value,
        "matched_policy_ids": [m.id for m in result.matched_policies],
        "workbench_item_id": result.workbench_item_id,
    }
    return reply, extra_data


async def handle_chat_message(
    db: Session,
    session_id: Optional[str],
    message: str,
    entity_data: Optional[dict[str, Any]] = None,
    domain: Optional[str] = None,
    user: Optional[dict] = None,
) -> ChatMessage:
    """
    Handle one chat turn.

    Persists the user's message, dispatches (see `_dispatch`), persists the
    assistant's reply with `extra_data` linking back to whatever the
    dispatch decided, and audit-logs the exchange. Returns the persisted
    assistant ChatMessage.
    """
    session_id = session_id or str(uuid.uuid4())
    source_agent = (user or {}).get("email") or (user or {}).get("preferred_username") or "chat_user"

    user_message = ChatMessage(session_id=session_id, role=ChatRole.USER.value, content=message)
    db.add(user_message)
    db.commit()

    reply_text, extra_data = await _dispatch(db, message, entity_data, domain, source_agent)

    assistant_message = ChatMessage(
        session_id=session_id,
        role=ChatRole.ASSISTANT.value,
        content=reply_text,
        extra_data=extra_data or None,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    await audit.log(
        action="ai_manager.chat",
        description=f"AI Manager chat turn in session {session_id}: {reply_text}",
        actor=user,
        category=AuditCategory.ADMIN,
        severity=AuditSeverity.INFO,
        resource_type="chat_session",
        resource_id=session_id,
        metadata={"domain": domain, **extra_data},
    )

    return assistant_message
