# app/models/work_item.py
"""
WorkItem Model - AI Workbench exception queue.

An AI Employee routes anything it can't confidently handle here for human
review (see docs/command-center-guide.md, "AI Workbench — The Safety Net").
Each row is one exception raised by an agent, plus the human's eventual
resolution of it.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text, func

from ..core.database import Base


class WorkItemExceptionType(str, Enum):
    """Why an agent couldn't handle this on its own."""

    LOW_CONFIDENCE = "low_confidence"  # Model confidence below threshold
    POLICY_CONFLICT = "policy_conflict"  # Two policies gave contradictory instructions
    MISSING_DATA = "missing_data"  # Can't evaluate without required info
    HIGH_STAKES = "high_stakes"  # Policy requires human approval above a threshold
    NOVEL_SCENARIO = "novel_scenario"  # No precedent for this case


class WorkItemStatus(str, Enum):
    """Queue state of the work item."""

    PENDING = "pending"  # Awaiting a human
    IN_REVIEW = "in_review"  # A human has opened it
    RESOLVED = "resolved"  # Approved or modified and applied
    REJECTED = "rejected"  # Rejected outright


class WorkItemPriority(str, Enum):
    """Queue ordering hint."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkItemResolution(str, Enum):
    """The human's final decision. Set only once the item is resolved."""

    APPROVED = "approved"  # AI's recommendation accepted as-is
    REJECTED = "rejected"  # AI's recommendation declined
    MODIFIED = "modified"  # Human changed the outcome before applying it


class WorkItem(Base):
    """
    A single exception routed to the AI Workbench.

    Design principles (mirrors AuditLog):
    - Context-rich: carries everything the human needs to decide, in one row
    - Queryable: indexed on the fields the queue view filters/sorts by
    - Flexible: `context` JSON holds the full payload for the detail panel
    """

    __tablename__ = "work_items"

    id = Column(Integer, primary_key=True, index=True)

    # What
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    exception_type = Column(String(50), nullable=False, index=True)  # WorkItemExceptionType
    status = Column(String(20), nullable=False, default=WorkItemStatus.PENDING.value, index=True)
    priority = Column(String(20), nullable=False, default=WorkItemPriority.MEDIUM.value, index=True)

    # Who/what raised it
    source_agent = Column(String(255), nullable=True, index=True)  # e.g. "Deal Analyst"

    # AI's side of the story
    ai_recommendation = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)

    # On what (the entity this exception is about)
    resource_type = Column(String(100), nullable=True, index=True)
    resource_id = Column(String(255), nullable=True, index=True)
    context = Column(JSON, nullable=True)

    # Resolution
    resolution = Column(String(20), nullable=True)  # WorkItemResolution
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<WorkItem {self.id}: {self.title} ({self.status})>"
