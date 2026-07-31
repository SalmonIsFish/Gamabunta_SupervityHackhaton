# app/schemas/policy.py
"""
Pydantic schemas for AI Policies.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models.policy import PolicyStatus, PolicyType


class PolicyAction(BaseModel):
    """One action a policy triggers when its condition matches."""

    type: str = Field(..., min_length=1, max_length=255, description="e.g. 'require_approval', 'auto_approve'")
    value: Optional[Any] = None
    params: Optional[dict[str, Any]] = None


class PolicyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    policy_type: PolicyType
    domain: Optional[str] = Field(None, max_length=100)
    condition: Optional[dict[str, Any]] = None
    natural_language_rule: Optional[str] = None

    # Legacy single-action fields — kept for backward compatibility with
    # policies created before multi-action support (e.g. the seeded
    # procurement policies). Prefer `actions` for new policies.
    action: Optional[str] = Field(None, max_length=255)
    action_params: Optional[dict[str, Any]] = None

    # Multi-action support
    actions: Optional[list[PolicyAction]] = None

    # Authoring/display metadata — descriptive only, not read by evaluate()
    tags: list[str] = Field(default_factory=list)
    entity_name: Optional[str] = Field(None, max_length=255)
    policy_scope: str = Field("custom", description="'base' | 'instruction' | 'custom'")
    summary: Optional[str] = None
    refined_instruction: Optional[str] = None
    ai_instruction: Optional[str] = None
    source: Optional[str] = Field(None, max_length=50)

    priority: int = Field(100, ge=0, description="Lower number = evaluated first")


class PolicyCreate(PolicyBase):
    """Request model for creating a policy. Always starts in DRAFT status."""

    pass


class PolicyUpdate(BaseModel):
    """Request model for updating a policy. Only mutable rule fields — use activate/deactivate for status."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    domain: Optional[str] = Field(None, max_length=100)
    condition: Optional[dict[str, Any]] = None
    natural_language_rule: Optional[str] = None
    action: Optional[str] = Field(None, max_length=255)
    action_params: Optional[dict[str, Any]] = None
    actions: Optional[list[PolicyAction]] = None
    tags: Optional[list[str]] = None
    entity_name: Optional[str] = Field(None, max_length=255)
    policy_scope: Optional[str] = None
    summary: Optional[str] = None
    refined_instruction: Optional[str] = None
    ai_instruction: Optional[str] = None
    source: Optional[str] = Field(None, max_length=50)
    priority: Optional[int] = Field(None, ge=0)


class PolicyResponse(PolicyBase):
    id: int
    status: PolicyStatus
    trigger_count: int
    last_evaluated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PolicyListResponse(BaseModel):
    """Paginated response for policy listings."""

    items: list[PolicyResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PolicyFilters(BaseModel):
    """Filters for querying policies."""

    policy_type: Optional[PolicyType] = None
    domain: Optional[str] = None
    status: Optional[PolicyStatus] = None


class PolicyActionResponse(BaseModel):
    """Response for policy lifecycle actions (activate/deactivate)."""

    success: bool
    policy_id: int
    action: str
    message: str


# =============================================================================
# EVALUATION SCHEMAS
# =============================================================================


class PolicyVerdict(str, Enum):
    """Outcome of evaluating all applicable structured policies against an entity."""

    NO_POLICY_APPLIES = "no_policy_applies"  # Nothing matched
    AUTO_APPROVED = "auto_approved"  # Only permissive actions matched (e.g. auto_approve)
    REQUIRES_REVIEW = "requires_review"  # Only gating actions matched (e.g. require_approval)
    BLOCKED_PENDING_REVIEW = "blocked_pending_review"  # Both matched — conflict, routed to Workbench


class PolicyEvaluationRequest(BaseModel):
    """Request to evaluate structured policies for a domain against a runtime entity."""

    domain: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(..., min_length=1, max_length=100, description="e.g. 'lead', 'invoice', 'deal'")
    entity_data: dict[str, Any] = Field(..., description="The entity's fields, checked against policy conditions")
    source_agent: Optional[str] = Field(None, description="The agent/operator requesting the decision")


class MatchedPolicySummary(BaseModel):
    """One policy that matched during evaluation."""

    id: int
    name: str
    action: Optional[str] = None
    bucket: str = Field(..., description="'permissive' or 'gating'")


class PolicyEvaluationResponse(BaseModel):
    """Result of a policy evaluation."""

    verdict: PolicyVerdict
    matched_policies: list[MatchedPolicySummary]
    workbench_item_id: Optional[int] = None
