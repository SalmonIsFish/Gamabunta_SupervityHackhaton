# app/schemas/policy.py
"""
Pydantic schemas for AI Policies.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models.policy import PolicyStatus, PolicyType


class PolicyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    policy_type: PolicyType
    domain: Optional[str] = Field(None, max_length=100)
    condition: Optional[dict[str, Any]] = None
    natural_language_rule: Optional[str] = None
    action: Optional[str] = Field(None, max_length=255)
    action_params: Optional[dict[str, Any]] = None
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
