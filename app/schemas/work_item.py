# app/schemas/work_item.py
"""
Pydantic schemas for AI Workbench work items.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models.work_item import (
    WorkItemExceptionType,
    WorkItemPriority,
    WorkItemResolution,
    WorkItemStatus,
)


class WorkItemBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    exception_type: WorkItemExceptionType
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    source_agent: Optional[str] = None
    ai_recommendation: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class WorkItemCreate(WorkItemBase):
    """Raised by an agent (or the service routing its exception) when it can't proceed unassisted."""

    pass


class WorkItemResponse(WorkItemBase):
    id: int
    status: WorkItemStatus
    resolution: Optional[WorkItemResolution] = None
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkItemListResponse(BaseModel):
    """Paginated response for the workbench queue."""

    items: list[WorkItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class WorkItemFilters(BaseModel):
    """Filters for querying the workbench queue."""

    status: Optional[WorkItemStatus] = None
    exception_type: Optional[WorkItemExceptionType] = None
    priority: Optional[WorkItemPriority] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    source_agent: Optional[str] = None


class WorkItemResolveRequest(BaseModel):
    """Request to resolve a work item — the human's decision."""

    resolution: WorkItemResolution
    resolution_notes: Optional[str] = Field(None, max_length=2000)


class WorkItemActionResponse(BaseModel):
    """Response for workbench actions (e.g. resolve)."""

    success: bool
    work_item_id: int
    action: str
    message: str
