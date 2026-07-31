# app/models/policy.py
"""
Policy Model - AI Policies, the governance layer.

Policies are business rules that constrain how agents behave at runtime (see
docs/command-center-guide.md, "AI Policies — The Guardrails"). A policy is
either STRUCTURED (deterministic condition -> action) or NATURAL_LANGUAGE
(free-text instructions interpreted by an LLM with full context).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func

from ..core.database import Base


class PolicyType(str, Enum):
    """How the policy's rule is expressed and evaluated."""

    STRUCTURED = "structured"  # Deterministic IF/THEN condition -> action
    NATURAL_LANGUAGE = "natural_language"  # Free text interpreted by an LLM


class PolicyStatus(str, Enum):
    """Where the policy is in its lifecycle (Create -> Test -> Activate -> Monitor -> Refine)."""

    DRAFT = "draft"  # Being written/tested, not yet enforced
    ACTIVE = "active"  # Enforced at runtime
    PAUSED = "paused"  # Temporarily disabled, can be reactivated
    ARCHIVED = "archived"  # Retired, kept for history only


class Policy(Base):
    """
    A single business rule constraining agent behavior.

    Design principles (mirrors WorkItem/AuditLog):
    - Auditable: every activate/deactivate is traced (who, when, why)
    - Flexible: `condition`/`action_params` JSON hold the structured rule shape
    - Monitorable: `trigger_count`/`last_evaluated_at` support the Insights pipeline
    """

    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)

    # What
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    policy_type = Column(String(20), nullable=False, index=True)  # PolicyType
    domain = Column(String(100), nullable=True, index=True)  # e.g. "sales", "marketing"

    # The rule itself — one of these is populated depending on policy_type
    condition = Column(JSON, nullable=True)  # Structured: {"field": "amount", "op": ">", "value": 50000}
    natural_language_rule = Column(Text, nullable=True)  # Natural language: free-text instruction

    # What happens when the rule matches — legacy single-action fields, kept
    # for backward compatibility. New policies should prefer `actions` below;
    # policy_engine.py falls back to these when `actions` is empty/null.
    action = Column(String(255), nullable=True)  # e.g. "require_approval", "flag_for_review"
    action_params = Column(JSON, nullable=True)

    # Multi-action support: list of {"type": str, "value": Any, "params": dict}.
    # A policy can now land in both the permissive and gating bucket at once
    # if its actions include both kinds — see policy_engine.py's evaluate().
    actions = Column(JSON, nullable=True)

    # Authoring/display metadata from the Command Center UI (Create with AI,
    # tags, entity scoping). Descriptive only — not read by evaluate().
    tags = Column(JSON, nullable=False, default=list)  # list[str]
    entity_name = Column(String(255), nullable=True)
    policy_scope = Column(String(20), nullable=False, default="custom")  # 'base' | 'instruction' | 'custom'
    summary = Column(Text, nullable=True)
    refined_instruction = Column(Text, nullable=True)
    ai_instruction = Column(Text, nullable=True)
    source = Column(String(50), nullable=True)

    # Evaluation order: lower number = evaluated first
    priority = Column(Integer, nullable=False, default=100, index=True)

    # Lifecycle
    status = Column(String(20), nullable=False, default=PolicyStatus.DRAFT.value, index=True)

    # Monitoring (for the Insights pipeline)
    trigger_count = Column(Integer, nullable=False, default=0)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)

    # Who
    created_by = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Policy {self.id}: {self.name} ({self.status})>"
