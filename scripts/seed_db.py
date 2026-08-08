#!/usr/bin/env python3
"""
Database seeding script.
Populates the database with initial sample data.
Used by the seed-db Cloud Run Job.
"""

import logging
import os
import sys

# Configure logging for scripts
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker

from app.core.database import engine
from app.models.item import Item
from app.models.policy import Policy, PolicyStatus, PolicyType

# Create a new session for this script
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Operations/Procurement domain policies — active by default so the demo
# doesn't start from zero. Fully editable afterwards through the AI Policies
# UI; seeding here is just a starting point, not the source of truth.
PROCUREMENT_POLICIES = [
    {
        "name": "Expedite Spend Limit",
        "description": (
            "Expedites over RM50,000 require human approval before dispatch — "
            "the agent may not auto-approve high-value expedites alone."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {"field": "expedite_cost", "op": "gt", "value": 50000},
        "action": "require_approval",
        "priority": 10,
    },
    {
        "name": "Contract Escalation Clause Block",
        "description": (
            "Some supplier contracts require VP Procurement sign-off before any "
            "expedite (see contracts.x_escalation_clause / Penalties.escalation_threshold). "
            "The agent must not dispatch an expedite that breaches that clause."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {"field": "requires_vp_signoff", "op": "eq", "value": True},
        "action": "block",
        "priority": 5,
    },
    {
        "name": "Substitution Eligibility",
        "description": (
            "An alternative-supplier substitution needs human review if the "
            "candidate's minimum order quantity isn't met or its quote has expired."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {
            "any": [
                {"field": "alt_moq_met", "op": "eq", "value": False},
                {"field": "quote_expired", "op": "eq", "value": True},
            ]
        },
        "action": "flag_for_review",
        "priority": 20,
    },
    {
        "name": "Customer-Tier Priority Escalation",
        "description": (
            "Any disruption impacting a critical-priority customer order is "
            "always escalated to a human, regardless of how routine the fix looks."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {"field": "customer_priority", "op": "eq", "value": "critical"},
        "action": "escalate",
        "priority": 15,
    },
    {
        "name": "Close Recovery Plans Escalation",
        "description": (
            "When two or more recovery plans have similar outcomes (within the "
            "Recovery Planner's own cost-closeness threshold), a human must choose "
            "between them rather than the agent silently picking one."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {"field": "plans_are_close", "op": "eq", "value": True},
        "action": "require_approval",
        "priority": 8,
    },
    {
        "name": "Significant Delay Notification Approval",
        "description": (
            "A customer re-promise pushing an order more than 3 days past its original "
            "promised_date must be approved by a human before the notification is 'sent' "
            "(recorded) — not logged and delivered silently."
        ),
        "policy_type": PolicyType.STRUCTURED.value,
        "domain": "procurement",
        "condition": {"field": "delay_days", "op": "gt", "value": 3},
        "action": "require_approval",
        "priority": 12,
    },
]


def seed_data():
    """Populates the database with initial data."""
    db = SessionLocal()
    try:
        log.info("Seeding initial data...")

        # Check if items already exist
        if db.query(Item).count() == 0:
            log.info("Adding sample items...")
            item1 = Item(
                name="First Sample Item",
                description="This is a test item from the seeder.",
            )
            item2 = Item(
                name="Second Sample Item",
                description="Another test item for demonstration.",
            )
            db.add_all([item1, item2])
            db.commit()
            log.info("Sample items added.")
        else:
            log.info("Items table is not empty, skipping seeding.")

        log.info("Seeding procurement policies...")
        for policy_data in PROCUREMENT_POLICIES:
            existing = db.query(Policy).filter(Policy.name == policy_data["name"]).first()
            if existing:
                continue
            db.add(Policy(status=PolicyStatus.ACTIVE.value, created_by="seed_script", **policy_data))
        db.commit()
        log.info("Procurement policies seeded.")

        log.info("✅ Data seeding complete.")

    except Exception as e:
        log.error(f"❌ An error occurred during data seeding: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    log.info("--- Starting Database Seeding ---")
    seed_data()
