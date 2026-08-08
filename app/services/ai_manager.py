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

import json
import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditCategory, AuditSeverity
from ..models.chat import ChatMessage, ChatRole
from ..models.insight import Insight
from ..models.policy import Policy, PolicyStatus
from ..models.work_item import WorkItem, WorkItemStatus
from ..schemas.policy import PolicyVerdict
from . import openrouter_client, policy_engine, supervity_auto_client
from .audit import audit

log = logging.getLogger(__name__)

_NOTICE_REQUIRED_FIELDS = ("notice_id", "supplier_id", "item_number", "notice_type")

# The 5 Round 2 Operators, individually re-triggerable from AI Manager chat —
# workflow IDs are each Operator's stable rootWorkflowId (confirmed against
# the Master Orchestrator's own ID, which matches SUPERVITY_AUTO_ORCHESTRATOR_
# WORKFLOW_ID exactly, so these don't drift even as a workflow's steps are
# edited). required_inputs lists what the model must extract before firing —
# anything not on this list for a given operator is never sent, since an
# Operator that takes no inputs (per its own Auto trigger form) would reject
# unexpected ones.
_OPERATOR_REGISTRY: dict[str, dict[str, Any]] = {
    "supplier cascade mapper": {
        "workflow_id": "019fcd28-2dab-7000-a5f9-2eb2bf71814b",
        "required_inputs": ["failed_supplier_id"],
    },
    "multi-event prioritizer": {
        "workflow_id": "019fcd2e-bc0e-7000-bdc0-1713a205a5d4",
        "required_inputs": [],
    },
    "cost & clause evaluator": {
        "workflow_id": "019fcd38-7d0e-7000-98b1-e239761a9654",
        "required_inputs": ["supplier_id", "item_number"],
    },
    "logistics / port-cutoff monitor": {
        "workflow_id": "019fcd3d-2ccf-7000-a9fa-225ec46b228c",
        "required_inputs": [],
    },
    "inventory reallocation planner": {
        "workflow_id": "019fcd45-abb6-7000-9067-f1ff0e5ce207",
        "required_inputs": [],
    },
    "demand consolidation optimizer": {
        "workflow_id": "019fe20e-cd27-7000-8111-b5399b73ba9e",
        "required_inputs": [],
    },
    "recovery planner": {
        "workflow_id": "019fe1e0-546e-7000-b3a8-0c75b8c4e8a3",
        "required_inputs": ["supplier_id", "item_number"],
    },
}

_FREEFORM_SYSTEM_PROMPT = """You are the AI Manager for a procurement/operations Command Center. \
You answer questions ONLY using the CONTEXT JSON given to you below — never invent facts, numbers, \
titles, or records that are not present in it. If the context doesn't contain enough to answer, say \
so plainly and suggest checking the Workbench, Insights, or Policies pages instead of guessing.

If the user is asking you to check on, investigate, or trigger action for a specific supply \
disruption, and you can identify a notice_id, supplier_id, item_number, and notice_type from the \
CONTEXT or the user's own message, set trigger_workflow to true and fill in those four fields \
exactly as given. Otherwise set trigger_workflow to false and leave those fields null. Never guess \
or invent a notice_id/supplier_id/item_number/notice_type that wasn't actually provided to you.

Separately, if the user is asking you to run, re-run, or trigger one specific named Operator \
(rather than the whole disruption-notice flow above), set trigger_operator to that Operator's exact \
name from this list, and nothing else: "Supplier Cascade Mapper", "Multi-Event Prioritizer", \
"Cost & Clause Evaluator", "Logistics / Port-Cutoff Monitor", "Inventory Reallocation Planner", \
"Demand Consolidation Optimizer", "Recovery Planner". \
Fill operator_inputs with only the specific fields that Operator needs, using only values the user \
or the CONTEXT actually gave you — never invent a supplier_id, item_number, or any other value. If \
the user didn't ask to trigger a specific named Operator, set trigger_operator to null and \
operator_inputs to an empty object.

Respond with ONLY a single JSON object, no other text before or after it, in exactly this shape:
{"answer": "<your natural-language answer to the user, 1-4 sentences>", "trigger_workflow": \
<true or false>, "notice_id": <string or null>, "supplier_id": <string or null>, "item_number": \
<string or null>, "notice_type": <string or null>, "trigger_operator": <string or null>, \
"operator_inputs": <object>}"""


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


def _gather_context(db: Session) -> dict[str, Any]:
    """Real, current records for the free-text path to ground its answer in —
    nothing here is fabricated, it's a direct read of the same tables the
    Workbench/Insights/Policies pages show."""
    open_items = (
        db.query(WorkItem)
        .filter(WorkItem.status.in_([WorkItemStatus.PENDING.value, WorkItemStatus.IN_REVIEW.value]))
        .order_by(WorkItem.created_at.desc())
        .limit(5)
        .all()
    )
    recent_insights = db.query(Insight).order_by(Insight.created_at.desc()).limit(5).all()
    active_policies = db.query(Policy).filter(Policy.status == PolicyStatus.ACTIVE.value).all()

    return {
        "open_workbench_items": [
            {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "priority": item.priority,
                "exception_type": item.exception_type,
                "source_agent": item.source_agent,
            }
            for item in open_items
        ],
        "recent_insights": [
            {"id": i.id, "title": i.title, "severity": i.severity, "status": i.status}
            for i in recent_insights
        ],
        "active_policies": [{"id": p.id, "name": p.name, "domain": p.domain} for p in active_policies],
    }


def _parse_llm_json(raw: str) -> Optional[dict[str, Any]]:
    """Best-effort JSON parse of the model's reply — strips markdown code
    fences some models wrap JSON in despite instructions not to. Returns
    None (never raises) on anything unparseable, so callers can fall back
    to a safe templated reply."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        log.warning("Could not parse OpenRouter response as JSON: %r", raw[:200])
        return None


async def _handle_freeform_message(db: Session, session_id: str) -> tuple[str, dict[str, Any]]:
    """
    Free-text chat (no structured entity_data/domain): ground an answer in
    real Workbench/Insights/Policies records plus this session's own prior
    turns via OpenRouter, and — only when the model extracts all four
    required fields from real context or the user's own message, never
    invented — trigger the Auto Master Orchestrator the same way the
    structured path does.
    """
    fallback = (
        "I can answer questions about current Workbench items, Insights, and Policies, or trigger "
        "the Auto Orchestrator for a specific disruption notice if you give me a notice ID and "
        "supplier. Ask me with those specifics, or check the Workbench/Insights pages directly."
    )
    if not openrouter_client.is_configured():
        return fallback, {}

    context = _gather_context(db)
    # The current user turn is already persisted (handle_chat_message commits
    # it before calling _dispatch), so this query's last row IS the message
    # being answered — no separate "current message" turn needs appending.
    prior_turns = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(20)
        .all()
    )
    conversation = [
        {"role": "assistant" if m.role == ChatRole.ASSISTANT.value else "user", "content": m.content}
        for m in prior_turns
    ]
    raw = await openrouter_client.chat_completion(
        messages=[
            {"role": "system", "content": f"{_FREEFORM_SYSTEM_PROMPT}\n\nCONTEXT:\n{json.dumps(context)}"},
            *conversation,
        ]
    )
    if raw is None:
        return fallback, {}

    parsed = _parse_llm_json(raw)
    if parsed is None or not parsed.get("answer"):
        return fallback, {}

    answer = str(parsed["answer"])
    extra_data: dict[str, Any] = {"grounded_context": context}

    if parsed.get("trigger_workflow") and supervity_auto_client.is_configured():
        notice_fields = {f: parsed.get(f) for f in _NOTICE_REQUIRED_FIELDS}
        missing = [f for f, v in notice_fields.items() if not v]
        if missing:
            answer += f" I can trigger the Auto Orchestrator for this, but I still need: {', '.join(missing)}."
        else:
            auto_response = await supervity_auto_client.execute_workflow(
                inputs={**{k: str(v) for k, v in notice_fields.items()}, "slack_channel": "#alerts"},
            )
            if auto_response is not None:
                extra_data["auto_response"] = auto_response
                if auto_response.get("accepted"):
                    answer += f" Triggered the Auto Orchestrator: {auto_response.get('message', 'execution accepted')}."
                else:
                    answer += f" Tried to trigger the Auto Orchestrator, but it wasn't accepted: {auto_response.get('message', 'no reason given')}."

    operator_name = parsed.get("trigger_operator")
    if operator_name and supervity_auto_client.is_configured():
        operator = _OPERATOR_REGISTRY.get(str(operator_name).strip().lower())
        if operator is None:
            answer += f" I don't have a re-triggerable Operator named '{operator_name}'."
        else:
            operator_inputs = parsed.get("operator_inputs") or {}
            missing = [f for f in operator["required_inputs"] if not operator_inputs.get(f)]
            if missing:
                answer += f" I can re-run {operator_name}, but I still need: {', '.join(missing)}."
            else:
                auto_response = await supervity_auto_client.execute_workflow(
                    inputs={k: str(v) for k, v in operator_inputs.items()},
                    workflow_id=operator["workflow_id"],
                )
                extra_data["triggered_operator"] = operator_name
                if auto_response is not None:
                    extra_data["auto_response"] = auto_response
                    if auto_response.get("accepted"):
                        answer += f" Triggered {operator_name}: {auto_response.get('message', 'execution accepted')}."
                    else:
                        answer += f" Tried to trigger {operator_name}, but it wasn't accepted: {auto_response.get('message', 'no reason given')}."

    return answer, extra_data


async def _dispatch(
    db: Session,
    message: str,
    entity_data: Optional[dict[str, Any]],
    domain: Optional[str],
    source_agent: Optional[str],
    session_id: str,
) -> tuple[str, dict[str, Any]]:
    """
    Decide what to do about this message and produce (reply_text, extra_data).

    Two paths:
    - Structured (entity_data + domain given, e.g. from an Operator or the
      Policies "test" UI): the local policy engine is always the gate — it
      runs first and its verdict is never overridden, regardless of whether
      Auto is configured, reachable, or successful this turn. When
      entity_data looks like a disruption notice, this also kicks off the
      Auto Master Orchestrator workflow (informational — auto_response is
      appended to the reply and stashed in extra_data, it doesn't change the
      verdict). That call is fire-and-forget: POST /workflow-runs/execute
      returns {"accepted": bool, "message": str} immediately and the actual
      run proceeds asynchronously on Auto's side (confirmed via a live call).
    - Free-text (a plain chat message, no entity_data/domain — the normal
      case from the AI Manager UI): see _handle_freeform_message — grounds
      an answer in real Workbench/Insights/Policies records via OpenRouter,
      and can trigger the same Auto workflow if the model extracts real
      (never invented) notice fields from the conversation.
    """
    if not (entity_data and domain):
        return await _handle_freeform_message(db, session_id)

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

    reply_text, extra_data = await _dispatch(db, message, entity_data, domain, source_agent, session_id)

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
