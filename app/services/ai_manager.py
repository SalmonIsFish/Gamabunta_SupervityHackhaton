# app/services/ai_manager.py
"""
AI Manager chat service.

Handles one chat turn: persists the user's message, runs a structured policy
check via app/services/policy_engine.py (always the gate), optionally kicks
off the Auto Master Orchestrator workflow via supervity_auto_client.py when
the message looks like a disruption notice, composes a templated (not
LLM-generated) reply describing the outcome, and persists it.

`_dispatch` was the seam for Auto integration; now wired for real — see its
docstring for how the local policy gate and Auto's response compose.
"""

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditCategory, AuditSeverity
from ..models.chat import ChatMessage, ChatRole
from ..schemas.policy import PolicyVerdict
from . import policy_engine, supervity_auto_client
from .audit import audit

log = logging.getLogger(__name__)

_NOTICE_REQUIRED_FIELDS = ("notice_id", "supplier_id", "item_number", "notice_type")


def _looks_like_disruption_notice(entity_data: dict[str, Any]) -> bool:
    """True if entity_data has enough fields to hand to the Auto Master
    Orchestrator, whose workflow requires notice_id/supplier_id/item_number/
    notice_type (see supervity_auto_client.py's docstring)."""
    return all(entity_data.get(field) for field in _NOTICE_REQUIRED_FIELDS)


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

    The local structured policy engine is always the gate: it runs first and
    its verdict is never overridden, regardless of whether Auto is
    configured, reachable, or successful this turn — a policy conflict still
    routes to the Workbench even if the Auto call below fails or is skipped.

    When entity_data looks like a disruption notice, this also kicks off the
    Auto Master Orchestrator workflow (informational — auto_response is
    appended to the reply and stashed in extra_data, it doesn't change the
    verdict). That call is fire-and-forget: POST /workflow-runs/execute
    returns {"accepted": bool, "message": str} immediately and the actual
    run proceeds asynchronously on Auto's side (confirmed via a live call).
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
    extra_data: dict[str, Any] = {
        "verdict": result.verdict.value,
        "matched_policy_ids": [m.id for m in result.matched_policies],
        "workbench_item_id": result.workbench_item_id,
    }

    if supervity_auto_client.is_configured() and _looks_like_disruption_notice(entity_data):
        auto_response = await supervity_auto_client.execute_workflow(
            inputs={
                "notice_id": str(entity_data.get("notice_id", "")),
                "supplier_id": str(entity_data.get("supplier_id", "")),
                "item_number": str(entity_data.get("item_number", "")),
                "notice_type": str(entity_data.get("notice_type", domain)),
                "slack_channel": str(entity_data.get("slack_channel", "#alerts")),
            },
        )
        if auto_response is not None:
            extra_data["auto_response"] = auto_response
            if auto_response.get("accepted"):
                reply = f"{reply} Auto Orchestrator run started: {auto_response.get('message', 'execution accepted')}."
            else:
                reply = f"{reply} Auto Orchestrator did not accept the run: {auto_response.get('message', 'no reason given')}."

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
