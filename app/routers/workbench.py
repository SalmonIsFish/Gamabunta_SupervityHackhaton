# app/routers/workbench.py
"""
AI Workbench endpoints - the human-in-the-loop exception queue.

Agents route anything they can't confidently handle here (see WorkItem in
app/models/work_item.py). Humans review, then resolve — approve, reject, or
modify the AI's recommendation. Every resolution is written to the audit log.
"""

import logging
from datetime import datetime, timezone
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, case
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.audit import AuditCategory, AuditSeverity
from ..models.work_item import (
    WorkItem,
    WorkItemExceptionType,
    WorkItemPriority,
    WorkItemResolution,
    WorkItemStatus,
)
from ..schemas.work_item import (
    WorkItemActionResponse,
    WorkItemCreate,
    WorkItemListResponse,
    WorkItemResolveRequest,
    WorkItemResponse,
)
from ..security import get_current_user
from ..services import dropbox_client
from ..services.audit import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/workbench", tags=["Workbench"])

_TERMINAL_STATUSES = {WorkItemStatus.RESOLVED.value, WorkItemStatus.REJECTED.value}

_RESOLUTION_TO_STATUS = {
    WorkItemResolution.APPROVED.value: WorkItemStatus.RESOLVED.value,
    WorkItemResolution.MODIFIED.value: WorkItemStatus.RESOLVED.value,
    WorkItemResolution.REJECTED.value: WorkItemStatus.REJECTED.value,
}


async def _mirror_commander_queue(db: Session) -> None:
    """
    Best-effort mirror of the open (pending/in_review) Workbench queue to
    Dropbox as a secondary, human-browsable "Commander Queue" view — real
    data kept genuinely in sync, not a one-off decorative write. No-ops
    silently if Dropbox isn't configured or the write fails.
    """
    if not dropbox_client.is_configured():
        return
    open_items = (
        db.query(WorkItem)
        .filter(WorkItem.status.in_([WorkItemStatus.PENDING.value, WorkItemStatus.IN_REVIEW.value]))
        .order_by(asc(WorkItem.created_at))
        .all()
    )
    snapshot = [
        {
            "id": item.id,
            "title": item.title,
            "exception_type": item.exception_type,
            "priority": item.priority,
            "status": item.status,
            "source_agent": item.source_agent,
            "created_at": item.created_at,
        }
        for item in open_items
    ]
    await dropbox_client.upload_json("/commander-queue/pending.json", snapshot)


def _apply_work_item_filters(query, filters: dict):
    """Apply filters to a work item query. Reused for listing and future export."""
    if filters.get("status"):
        query = query.filter(WorkItem.status == filters["status"])
    if filters.get("exception_type"):
        query = query.filter(WorkItem.exception_type == filters["exception_type"])
    if filters.get("priority"):
        query = query.filter(WorkItem.priority == filters["priority"])
    if filters.get("resource_type"):
        query = query.filter(WorkItem.resource_type == filters["resource_type"])
    if filters.get("resource_id"):
        query = query.filter(WorkItem.resource_id == filters["resource_id"])
    if filters.get("source_agent"):
        query = query.filter(WorkItem.source_agent.ilike(f"%{filters['source_agent']}%"))
    return query


@router.post("", response_model=WorkItemResponse, status_code=201)
async def create_work_item(
    payload: WorkItemCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Raise a new exception onto the Workbench queue.

    This is the generic escalation path for anything that isn't a policy
    conflict (those are raised automatically by policy_engine.evaluate()).
    An Orchestrator/Operator calls this directly when it hits missing or
    orphaned data, a low-confidence read, a high-stakes action, or a novel
    scenario it has no precedent for — see WorkItemExceptionType.
    """
    work_item = WorkItem(
        title=payload.title,
        description=payload.description,
        exception_type=payload.exception_type.value,
        priority=payload.priority.value,
        source_agent=payload.source_agent,
        ai_recommendation=payload.ai_recommendation,
        confidence_score=payload.confidence_score,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        context=payload.context,
    )
    db.add(work_item)
    db.commit()
    db.refresh(work_item)

    await audit.log(
        action="workbench.create",
        description=f"Work item #{work_item.id} ({work_item.title}) raised as {work_item.exception_type}",
        actor=user,
        category=AuditCategory.DATA,
        severity=AuditSeverity.WARNING,
        resource_type=work_item.resource_type,
        resource_id=work_item.resource_id,
        resource_name=work_item.title,
        metadata={
            "exception_type": work_item.exception_type,
            "priority": work_item.priority,
            "source_agent": work_item.source_agent,
        },
    )
    await _mirror_commander_queue(db)

    return WorkItemResponse.model_validate(work_item)


@router.get("", response_model=WorkItemListResponse)
async def list_work_items(
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    # Filters
    status: Optional[WorkItemStatus] = Query(None, description="Filter by queue status"),
    exception_type: Optional[WorkItemExceptionType] = Query(None, description="Filter by exception type"),
    priority: Optional[WorkItemPriority] = Query(None, description="Filter by priority"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    source_agent: Optional[str] = Query(None, description="Filter by the agent that raised the item"),
    # Dependencies
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List workbench work items with filtering and pagination.

    Sorted by priority (critical first), then oldest-first within a priority band —
    the order a human should actually work the queue in.
    """
    query = db.query(WorkItem)

    filters = {
        "status": status.value if status else None,
        "exception_type": exception_type.value if exception_type else None,
        "priority": priority.value if priority else None,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "source_agent": source_agent,
    }
    query = _apply_work_item_filters(query, filters)

    total = query.count()

    priority_order = case(
        (WorkItem.priority == WorkItemPriority.CRITICAL.value, 0),
        (WorkItem.priority == WorkItemPriority.HIGH.value, 1),
        (WorkItem.priority == WorkItemPriority.MEDIUM.value, 2),
        (WorkItem.priority == WorkItemPriority.LOW.value, 3),
        else_=99,
    )
    offset = (page - 1) * page_size
    items = (
        query.order_by(asc(priority_order), asc(WorkItem.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    total_pages = ceil(total / page_size) if total > 0 else 1

    return WorkItemListResponse(
        items=[WorkItemResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{work_item_id}", response_model=WorkItemResponse)
async def get_work_item(
    work_item_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single work item with full context for the detail panel."""
    work_item = db.query(WorkItem).filter(WorkItem.id == work_item_id).first()
    if not work_item:
        raise HTTPException(status_code=404, detail="Work item not found")
    return WorkItemResponse.model_validate(work_item)


@router.post("/{work_item_id}/resolve", response_model=WorkItemActionResponse)
async def resolve_work_item(
    work_item_id: int,
    payload: WorkItemResolveRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resolve a work item — approve, reject, or modify the AI's recommendation.

    Terminal (already resolved/rejected) items cannot be resolved again.
    Writes an audit log entry recording who resolved it and how.
    """
    work_item = db.query(WorkItem).filter(WorkItem.id == work_item_id).first()
    if not work_item:
        raise HTTPException(status_code=404, detail="Work item not found")

    if work_item.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Work item is already {work_item.status} and cannot be resolved again",
        )

    actor_email = (user or {}).get("email") or (user or {}).get("preferred_username") or "unknown"

    work_item.resolution = payload.resolution.value
    work_item.resolution_notes = payload.resolution_notes
    work_item.resolved_by = actor_email
    work_item.resolved_at = datetime.now(timezone.utc)
    work_item.status = _RESOLUTION_TO_STATUS[payload.resolution.value]

    db.commit()
    db.refresh(work_item)

    await audit.log(
        action="workbench.resolve",
        description=f"Work item #{work_item.id} ({work_item.title}) resolved as {payload.resolution.value}",
        actor=user,
        category=AuditCategory.DATA,
        severity=AuditSeverity.INFO,
        resource_type="work_item",
        resource_id=work_item.id,
        resource_name=work_item.title,
        metadata={
            "resolution": payload.resolution.value,
            "resolution_notes": payload.resolution_notes,
            "exception_type": work_item.exception_type,
            "new_status": work_item.status,
        },
    )
    await _mirror_commander_queue(db)

    return WorkItemActionResponse(
        success=True,
        work_item_id=work_item.id,
        action="resolve",
        message=f"Work item resolved as {payload.resolution.value}",
    )
