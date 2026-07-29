# app/schemas/insight.py
"""
Pydantic schemas for AI Insights.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models.insight import InsightSeverity, InsightStatus, InsightType


class InsightBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    insight_type: InsightType
    severity: InsightSeverity = InsightSeverity.INFO
    confidence: Optional[float] = Field(None, ge=0, le=1)
    extra_data: Optional[dict[str, Any]] = None
    suggested_action: Optional[str] = None
    related_policy_id: Optional[int] = None


class InsightCreate(InsightBase):
    """Request model for creating an insight. Normally written by the insight engine, not the API."""

    generated_by: Optional[str] = None


class InsightResponse(InsightBase):
    id: int
    status: InsightStatus
    generated_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InsightListResponse(BaseModel):
    """Paginated response for insight listings."""

    items: list[InsightResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class InsightFilters(BaseModel):
    """Filters for querying insights."""

    insight_type: Optional[InsightType] = None
    severity: Optional[InsightSeverity] = None
    status: Optional[InsightStatus] = None


class InsightActionResponse(BaseModel):
    """Response for insight status-transition actions (e.g. dismiss)."""

    success: bool
    insight_id: int
    action: str
    message: str


class InsightGenerateResponse(BaseModel):
    """Response for a manually-triggered insight generation run."""

    generated_count: int
    insights: list[InsightResponse]
