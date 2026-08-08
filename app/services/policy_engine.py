# app/services/policy_engine.py
"""
Policy Evaluation Engine — structured (deterministic) and natural-language.

Evaluates ACTIVE policies for a domain against a runtime entity (a lead, an
invoice, a deal — whatever the calling agent is deciding about). Structured
policies are evaluated deterministically against Policy.condition; natural-
language policies (Policy.natural_language_rule) are interpreted by an LLM
via OpenRouter (see _evaluate_natural_language_policy) — no model-specific
key required, since OpenRouter already fronts whichever model OPENROUTER_MODEL
names, same client this backend already uses for the AI Manager and Workbench
recommendations. Both types feed the same permissive/gating bucket logic and
the same verdict.

Condition DSL (stored on Policy.condition, structured policies only):
    {"all": [<node>, ...]}                     -- AND
    {"any": [<node>, ...]}                      -- OR
    {"field": "amount", "op": "gt", "value": 50000}   -- leaf comparison

`field` supports dotted paths (e.g. "vendor.status") to reach nested keys in
entity_data. Ops: eq, neq, gt, gte, lt, lte, in, contains.

Verdicts:
    no_policy_applies      -- nothing matched
    auto_approved          -- only permissive actions matched (e.g. auto_approve)
    requires_review        -- only gating actions matched (e.g. require_approval)
    blocked_pending_review -- both matched -- conflicting instructions, a WorkItem is raised
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditCategory, AuditSeverity
from ..models.policy import Policy, PolicyStatus, PolicyType
from ..models.work_item import (
    WorkItem,
    WorkItemExceptionType,
    WorkItemPriority,
    WorkItemStatus,
)
from ..schemas.policy import MatchedPolicySummary, PolicyVerdict
from . import openrouter_client
from .audit import audit

log = logging.getLogger(__name__)

# Action-name conventions. Anything not recognized is treated as gating —
# a policy engine should never silently auto-approve on an action it doesn't understand.
_PERMISSIVE_ACTIONS = {"auto_approve", "approve", "allow"}
_GATING_ACTIONS = {
    "require_approval",
    "flag_for_review",
    "escalate",
    "block",
    "reject",
    "deny",
}


def _resolve_field(entity_data: dict[str, Any], field_path: str) -> Any:
    """Resolve a dotted field path (e.g. 'vendor.status') against entity_data."""
    value: Any = entity_data
    for part in field_path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _apply_op(op: str, actual: Any, expected: Any) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op == "gt":
            return actual is not None and actual > expected
        if op == "gte":
            return actual is not None and actual >= expected
        if op == "lt":
            return actual is not None and actual < expected
        if op == "lte":
            return actual is not None and actual <= expected
        if op == "in":
            return isinstance(expected, (list, tuple, set)) and actual in expected
        if op == "contains":
            return isinstance(actual, (list, tuple, set, str)) and expected in actual
    except TypeError:
        # e.g. comparing None to an int, or a str to an int — condition can't be satisfied
        return False
    log.warning(f"Unsupported condition operator: {op!r}")
    return False


def evaluate_condition(condition: Optional[dict[str, Any]], entity_data: dict[str, Any]) -> bool:
    """
    Recursively evaluate one condition DSL node against entity_data.

    A missing/empty condition is treated as an unconditional match (a catch-all rule).
    """
    if not condition:
        return True

    if "all" in condition:
        return all(evaluate_condition(sub, entity_data) for sub in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(sub, entity_data) for sub in condition["any"])

    field_path = condition.get("field")
    op = condition.get("op")
    if field_path is None or op is None:
        log.warning(f"Malformed condition node (missing field/op): {condition}")
        return False

    actual = _resolve_field(entity_data, field_path)
    return _apply_op(op, actual, condition.get("value"))


async def _evaluate_natural_language_policy(
    policy: Policy, entity_data: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """
    Ask the LLM whether a natural-language rule applies to this entity, and
    if so what action it implies. Returns None if the rule doesn't apply, if
    OpenRouter isn't configured, or if the response can't be parsed — all of
    which the caller treats as "this policy didn't match," never guessing.
    """
    if not policy.natural_language_rule or not openrouter_client.is_configured():
        return None

    prompt = (
        "You are a policy compliance engine. Decide whether the following business rule "
        "applies to the given data, and if so, what action it requires.\n\n"
        f"Rule: {policy.natural_language_rule}\n\n"
        f"Data: {json.dumps(entity_data)}\n\n"
        "Respond with ONLY a JSON object, no other text: "
        '{"applies": <true or false>, "action": "<one of: auto_approve, require_approval, '
        'flag_for_review, escalate, block>", "reasoning": "<one sentence>"}. '
        "If the rule does not apply given this data, set applies to false."
    )
    raw = await openrouter_client.chat_completion(messages=[{"role": "user", "content": prompt}], temperature=0)
    if raw is None:
        return None

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Could not parse natural-language policy response as JSON: %r", raw[:200])
        return None

    if not parsed.get("applies"):
        return None
    action = parsed.get("action")
    if action not in (_PERMISSIVE_ACTIONS | _GATING_ACTIONS):
        action = "flag_for_review"  # unrecognized action from the model — fail safe as gating
    return {"action": action, "reasoning": parsed.get("reasoning", "")}


def _resolve_actions(policy: Policy) -> list[dict[str, Any]]:
    """
    A policy's actions, in list form.

    Prefers the new `actions` column (list of {"type","value","params"}).
    Falls back to the legacy singular `action`/`action_params` fields when
    `actions` isn't populated — zero behavior change for policies created
    before multi-action support (including every seeded procurement policy).
    """
    if policy.actions:
        return policy.actions
    if policy.action:
        return [{"type": policy.action, "value": None, "params": policy.action_params}]
    return []


def _classify_action(action: Optional[str]) -> str:
    """Bucket a policy's action into 'permissive' or 'gating'. Unknown actions default to gating."""
    if not action:
        return "gating"
    normalized = action.strip().lower()
    if normalized in _PERMISSIVE_ACTIONS:
        return "permissive"
    if normalized in _GATING_ACTIONS:
        return "gating"
    log.warning(f"Unrecognized policy action '{action}' — treating as gating by default")
    return "gating"


@dataclass
class PolicyEvaluationResult:
    verdict: PolicyVerdict
    matched_policies: list[MatchedPolicySummary] = field(default_factory=list)
    workbench_item_id: Optional[int] = None


def _raise_conflict_work_item(
    db: Session,
    domain: str,
    entity_type: str,
    entity_data: dict[str, Any],
    source_agent: Optional[str],
    permissive_matches: list[Policy],
    gating_matches: list[Policy],
) -> int:
    """Route a policy conflict to the AI Workbench for a human to resolve."""

    def _action_types(p: Policy) -> list[str]:
        return [a.get("type") for a in _resolve_actions(p) if isinstance(a, dict) and a.get("type")]

    permissive_summary = [{"id": p.id, "name": p.name, "actions": _action_types(p)} for p in permissive_matches]
    gating_summary = [{"id": p.id, "name": p.name, "actions": _action_types(p)} for p in gating_matches]
    entity_id = entity_data.get("id")

    work_item = WorkItem(
        title=f"Policy conflict evaluating {entity_type}",
        description=(
            f"{len(permissive_matches)} polic{'y' if len(permissive_matches) == 1 else 'ies'} "
            f"would auto-approve this {entity_type}, while {len(gating_matches)} "
            f"require human review. A human must decide which takes precedence."
        ),
        exception_type=WorkItemExceptionType.POLICY_CONFLICT.value,
        status=WorkItemStatus.PENDING.value,
        priority=WorkItemPriority.HIGH.value,
        source_agent=source_agent,
        ai_recommendation=(
            f"Gating policies ({', '.join(p.name for p in gating_matches)}) recommend review; "
            f"permissive policies ({', '.join(p.name for p in permissive_matches)}) would auto-approve."
        ),
        resource_type=entity_type,
        resource_id=str(entity_id) if entity_id is not None else None,
        context={
            "domain": domain,
            "entity_data": entity_data,
            "permissive_policies": permissive_summary,
            "gating_policies": gating_summary,
        },
    )
    db.add(work_item)
    db.commit()
    db.refresh(work_item)
    return work_item.id


async def evaluate(
    domain: str,
    entity_type: str,
    entity_data: dict[str, Any],
    source_agent: Optional[str],
    db: Session,
) -> PolicyEvaluationResult:
    """
    Evaluate all ACTIVE policies (structured and natural-language) for
    `domain` against `entity_data`.

    Every matched policy has its trigger_count incremented and last_evaluated_at
    refreshed. If permissive and gating policies both match, a WorkItem is raised
    and the verdict is `blocked_pending_review`. Every call is audit-logged.
    """
    policies = (
        db.query(Policy)
        .filter(Policy.status == PolicyStatus.ACTIVE.value)
        .filter(Policy.domain == domain)
        .order_by(Policy.priority.asc(), Policy.id.asc())
        .all()
    )

    matched: list[MatchedPolicySummary] = []
    permissive_matches: list[Policy] = []
    gating_matches: list[Policy] = []
    nl_reasoning: dict[int, str] = {}
    now = datetime.now(timezone.utc)

    for policy in policies:
        nl_result: Optional[dict[str, Any]] = None
        if policy.policy_type == PolicyType.STRUCTURED.value:
            if not evaluate_condition(policy.condition, entity_data):
                continue
            policy_actions = _resolve_actions(policy)
        elif policy.policy_type == PolicyType.NATURAL_LANGUAGE.value:
            nl_result = await _evaluate_natural_language_policy(policy, entity_data)
            if nl_result is None:
                continue
            policy_actions = [{"type": nl_result["action"], "value": None, "params": None}]
            nl_reasoning[policy.id] = nl_result["reasoning"]
        else:
            continue

        touched_permissive = False
        touched_gating = False

        if not policy_actions:
            # Matched but has no action at all — fail-safe as gating, same
            # default _classify_action uses for an unset/unrecognized action.
            bucket = _classify_action(None)
            matched.append(MatchedPolicySummary(id=policy.id, name=policy.name, action=None, bucket=bucket))
            touched_gating = True
        else:
            for act in policy_actions:
                action_type = act.get("type") if isinstance(act, dict) else act
                bucket = _classify_action(action_type)
                matched.append(MatchedPolicySummary(id=policy.id, name=policy.name, action=action_type, bucket=bucket))
                if bucket == "permissive":
                    touched_permissive = True
                else:
                    touched_gating = True

        # A policy lands in a bucket at most once here even if several of its
        # actions share that bucket — a self-conflicting multi-action policy
        # (one permissive action + one gating action) legitimately touches both.
        if touched_permissive:
            permissive_matches.append(policy)
        if touched_gating:
            gating_matches.append(policy)

        policy.trigger_count = (policy.trigger_count or 0) + 1
        policy.last_evaluated_at = now

    if matched:
        db.commit()

    if not matched:
        verdict = PolicyVerdict.NO_POLICY_APPLIES
    elif permissive_matches and gating_matches:
        verdict = PolicyVerdict.BLOCKED_PENDING_REVIEW
    elif gating_matches:
        verdict = PolicyVerdict.REQUIRES_REVIEW
    else:
        verdict = PolicyVerdict.AUTO_APPROVED

    workbench_item_id: Optional[int] = None
    if verdict == PolicyVerdict.BLOCKED_PENDING_REVIEW:
        workbench_item_id = _raise_conflict_work_item(
            db, domain, entity_type, entity_data, source_agent, permissive_matches, gating_matches
        )

    entity_id = entity_data.get("id")
    await audit.log(
        action="policy.evaluate",
        description=f"Policy evaluation for {entity_type} in domain '{domain}': verdict={verdict.value}",
        category=AuditCategory.POLICY,
        severity=AuditSeverity.WARNING if verdict == PolicyVerdict.BLOCKED_PENDING_REVIEW else AuditSeverity.INFO,
        resource_type=entity_type,
        resource_id=str(entity_id) if entity_id is not None else None,
        metadata={
            "verdict": verdict.value,
            "domain": domain,
            "source_agent": source_agent,
            "matched_policy_ids": [m.id for m in matched],
            "entity_summary": {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_count": len(entity_data),
            },
            # Full entity_data (not just the summary above) so numeric business
            # fields an Operator proposed — net_savings, penalty_amount, etc. —
            # survive past this one request. Without this, evaluate() was the
            # only place that ever saw those numbers; they were evaluated for
            # a verdict and then discarded, with no way to ever answer "how
            # much has this actually saved" (see policies.py's /metrics
            # endpoint, which sums this back out for the Dashboard).
            "entity_data": entity_data,
            "workbench_item_id": workbench_item_id,
            # Populated only for matched natural-language policies (see
            # _evaluate_natural_language_policy) — the LLM's one-sentence
            # justification for why the rule applied, kept for auditability
            # since there's no deterministic condition to point back to.
            "natural_language_reasoning": nl_reasoning,
        },
    )

    return PolicyEvaluationResult(verdict=verdict, matched_policies=matched, workbench_item_id=workbench_item_id)
