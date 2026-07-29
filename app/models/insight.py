# app/models/insight.py
"""
Insight Model - AI Insights, the visibility layer.

Insights are AI-generated observations about system behavior — patterns,
anomalies, and recommendations — surfaced from operational data (see
docs/command-center-guide.md, "AI Insights — The Visibility Layer"). The
first-pass generator (app/services/insight_engine.py) derives these purely
statistically from audit log activity; no LLM is required.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text, func

from ..core.database import Base


class InsightType(str, Enum):
    """What kind of observation this is."""

    PATTERN = "pattern"  # A recurring behavior (e.g. "Policy X matches 80% of evaluations")
    ANOMALY = "anomaly"  # A statistical outlier vs. recent baseline
    RECOMMENDATION = "recommendation"  # An actionable suggestion


class InsightSeverity(str, Enum):
    """How urgently this insight deserves attention."""

    CRITICAL = "critical"  # Immediate attention required
    WARNING = "warning"  # Needs review soon
    INFO = "info"  # Good to know, optimize later


class InsightStatus(str, Enum):
    """Where this insight is in the operator's review workflow."""

    NEW = "new"  # Not yet looked at
    REVIEWED = "reviewed"  # An operator has seen it
    ACTIONED = "actioned"  # An operator acted on it (e.g. created a policy)
    DISMISSED = "dismissed"  # An operator decided it doesn't need action


class Insight(Base):
    """
    A single AI-generated observation.

    Design principles (mirrors Policy/WorkItem):
    - Traceable: `related_policy_id` and `extra_data` carry the numbers behind the claim
    - Actionable: `suggested_action` gives the operator a concrete next step
    """

    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, index=True)

    # What
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    insight_type = Column(String(20), nullable=False, index=True)  # InsightType
    severity = Column(String(20), nullable=False, default=InsightSeverity.INFO.value, index=True)
    confidence = Column(Float, nullable=True)

    # Lifecycle
    status = Column(String(20), nullable=False, default=InsightStatus.NEW.value, index=True)

    # The numbers behind the claim. Named `extra_data` at the Python/ORM level —
    # `metadata` is reserved on declarative model classes (it's SQLAlchemy's own
    # Base.metadata) — but the physical column is still called `metadata`,
    # exactly like AuditLog.extra_data does for the same reason.
    extra_data = Column("metadata", JSON, nullable=True)

    suggested_action = Column(Text, nullable=True)

    # On what (optional — not every insight traces back to a single policy)
    related_policy_id = Column(Integer, ForeignKey("policies.id"), nullable=True, index=True)

    # Who/what generated it
    generated_by = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<Insight {self.id}: {self.title} ({self.insight_type})>"
