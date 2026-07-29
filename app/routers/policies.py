# app/routers/policies.py
"""
AI Policies endpoints - the governance layer (CRUD + lifecycle).

Policies constrain how agents behave at runtime (see Policy in
app/models/policy.py). Creating/editing a policy never enforces it — it must
be explicitly activated. Activating/deactivating is audit-logged since it's
an instant, traceable change in agent behavior.
"""

import logging
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.audit import AuditCategory, AuditSeverity
from ..models.policy import Policy, PolicyStatus, PolicyType
from ..schemas.policy import (
    PolicyActionResponse,
    PolicyCreate,
    PolicyEvaluationRequest,
    PolicyEvaluationResponse,
    PolicyListResponse,
    PolicyResponse,
    PolicyUpdate,
)
from ..security import get_current_user
from ..services import policy_engine
from ..services.audit import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/policies", tags=["AI Policies"])

_REACTIVATABLE_STATUSES = {PolicyStatus.DRAFT.value, PolicyStatus.PAUSED.value}


def _apply_policy_filters(query, filters: dict):
    """Apply filters to a policy query. Reused for listing and future export."""
    if filters.get("policy_type"):
        query = query.filter(Policy.policy_type == filters["policy_type"])
    if filters.get("domain"):
        query = query.filter(Policy.domain == filters["domain"])
    if filters.get("status"):
        query = query.filter(Policy.status == filters["status"])
    return query


def _actor_email(user: Optional[dict]) -> str:
    user = user or {}
    return user.get("email") or user.get("preferred_username") or "unknown"


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    # Filters
    policy_type: Optional[PolicyType] = Query(None, description="Filter by policy type"),
    domain: Optional[str] = Query(None, description="Filter by domain (e.g. sales, marketing)"),
    status: Optional[PolicyStatus] = Query(None, description="Filter by lifecycle status"),
    # Dependencies
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List policies with filtering and pagination.

    Sorted by priority (lower first), then oldest-first — the order the
    policy engine would evaluate them in.
    """
    query = db.query(Policy)

    filters = {
        "policy_type": policy_type.value if policy_type else None,
        "domain": domain,
        "status": status.value if status else None,
    }
    query = _apply_policy_filters(query, filters)

    total = query.count()

    offset = (page - 1) * page_size
    items = (
        query.order_by(asc(Policy.priority), asc(Policy.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    total_pages = ceil(total / page_size) if total > 0 else 1

    return PolicyListResponse(
        items=[PolicyResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=PolicyResponse)
async def create_policy(
    payload: PolicyCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new policy. Always starts in DRAFT status — activate it separately."""
    policy = Policy(
        **payload.model_dump(),
        status=PolicyStatus.DRAFT.value,
        created_by=_actor_email(user),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return PolicyResponse.model_validate(policy)


@router.post("/evaluate", response_model=PolicyEvaluationResponse)
async def evaluate_policies(
    payload: PolicyEvaluationRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Evaluate ACTIVE structured policies for a domain against a runtime entity.

    Called by an agent (via Auto) mid-workflow to check whether it can proceed,
    needs a human to review, or has hit conflicting policies. A conflict raises
    a WorkItem in the AI Workbench automatically.
    """
    result = await policy_engine.evaluate(
        domain=payload.domain,
        entity_type=payload.entity_type,
        entity_data=payload.entity_data,
        source_agent=payload.source_agent,
        db=db,
    )
    return PolicyEvaluationResponse(
        verdict=result.verdict,
        matched_policies=result.matched_policies,
        workbench_item_id=result.workbench_item_id,
    )


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return PolicyResponse.model_validate(policy)


@router.put("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: int,
    payload: PolicyUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a policy's rule fields.

    Status is not editable here — use the activate/deactivate endpoints.
    """
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)

    db.commit()
    db.refresh(policy)
    return PolicyResponse.model_validate(policy)


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a policy. Active policies must be deactivated first."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if policy.status == PolicyStatus.ACTIVE.value:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active policy. Deactivate it first.",
        )

    db.delete(policy)
    db.commit()
    return {"message": "Policy deleted"}


@router.post("/{policy_id}/activate", response_model=PolicyActionResponse)
async def activate_policy(
    policy_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate a policy — it starts being enforced at runtime immediately."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if policy.status == PolicyStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail="Policy is already active")
    if policy.status not in _REACTIVATABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot activate a policy with status '{policy.status}'",
        )

    previous_status = policy.status
    policy.status = PolicyStatus.ACTIVE.value
    db.commit()
    db.refresh(policy)

    await audit.log(
        action="policy.activate",
        description=f"Policy #{policy.id} ({policy.name}) activated",
        actor=user,
        category=AuditCategory.ADMIN,
        severity=AuditSeverity.INFO,
        resource_type="policy",
        resource_id=policy.id,
        resource_name=policy.name,
        metadata={"previous_status": previous_status, "new_status": policy.status},
    )

    return PolicyActionResponse(
        success=True,
        policy_id=policy.id,
        action="activate",
        message=f"Policy '{policy.name}' is now active",
    )


@router.post("/{policy_id}/deactivate", response_model=PolicyActionResponse)
async def deactivate_policy(
    policy_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deactivate a policy — pauses enforcement without deleting it."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if policy.status != PolicyStatus.ACTIVE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot deactivate a policy with status '{policy.status}'",
        )

    policy.status = PolicyStatus.PAUSED.value
    db.commit()
    db.refresh(policy)

    await audit.log(
        action="policy.deactivate",
        description=f"Policy #{policy.id} ({policy.name}) deactivated",
        actor=user,
        category=AuditCategory.ADMIN,
        severity=AuditSeverity.WARNING,
        resource_type="policy",
        resource_id=policy.id,
        resource_name=policy.name,
        metadata={"previous_status": PolicyStatus.ACTIVE.value, "new_status": policy.status},
    )

    return PolicyActionResponse(
        success=True,
        policy_id=policy.id,
        action="deactivate",
        message=f"Policy '{policy.name}' has been paused",
    )
