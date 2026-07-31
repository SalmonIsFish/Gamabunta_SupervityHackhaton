# tests/test_policy_engine.py
"""
End-to-end tests for structured policy evaluation (app/services/policy_engine.py).

Exercises the real API against the real database (same DB the dev containers
use — AUTH_BYPASS is on, so requests run as the dev user). Each test cleans up
the policies/work items/audit logs it creates so runs don't accumulate state.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models.audit import AuditLog
from app.models.policy import Policy
from app.models.work_item import WorkItem

pytestmark = pytest.mark.asyncio

TEST_DOMAIN = "pytest_policy_engine"
TEST_ENTITY_TYPE = "pytest_entity"


def _cleanup():
    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.resource_type == TEST_ENTITY_TYPE).delete()
        db.query(WorkItem).filter(WorkItem.resource_type == TEST_ENTITY_TYPE).delete()
        db.query(Policy).filter(Policy.domain == TEST_DOMAIN).delete()
        db.commit()
    finally:
        db.close()


async def _create_active_policy(client: AsyncClient, **overrides) -> int:
    payload = {
        "name": "Test Policy",
        "policy_type": "structured",
        "domain": TEST_DOMAIN,
        "condition": {"field": "amount", "op": "lt", "value": 500},
        "action": "auto_approve",
        "priority": 10,
    }
    payload.update(overrides)

    create_resp = await client.post("/api/ai/policies", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    policy_id = create_resp.json()["id"]

    activate_resp = await client.post(f"/api/ai/policies/{policy_id}/activate")
    assert activate_resp.status_code == 200, activate_resp.text

    return policy_id


async def test_evaluate_auto_approved():
    """A single matching permissive policy yields auto_approved, no workbench item."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )

            resp = await client.post(
                "/api/ai/policies/evaluate",
                json={
                    "domain": TEST_DOMAIN,
                    "entity_type": TEST_ENTITY_TYPE,
                    "entity_data": {"id": 1, "amount": 100},
                    "source_agent": "Test Agent",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verdict"] == "auto_approved"
        assert len(body["matched_policies"]) == 1
        assert body["matched_policies"][0]["bucket"] == "permissive"
        assert body["workbench_item_id"] is None
    finally:
        _cleanup()


async def test_evaluate_requires_review():
    """A single matching gating policy yields requires_review, no workbench item."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Escalate large amounts",
                condition={"field": "amount", "op": "gte", "value": 1000},
                action="require_approval",
            )

            resp = await client.post(
                "/api/ai/policies/evaluate",
                json={
                    "domain": TEST_DOMAIN,
                    "entity_type": TEST_ENTITY_TYPE,
                    "entity_data": {"id": 2, "amount": 5000},
                    "source_agent": "Test Agent",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verdict"] == "requires_review"
        assert len(body["matched_policies"]) == 1
        assert body["matched_policies"][0]["bucket"] == "gating"
        assert body["workbench_item_id"] is None
    finally:
        _cleanup()


async def test_evaluate_conflict_creates_work_item():
    """A permissive policy and a gating policy both matching yields blocked_pending_review + a WorkItem."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve trusted vendor",
                condition={"field": "vendor_status", "op": "eq", "value": "trusted"},
                action="auto_approve",
                priority=5,
            )
            await _create_active_policy(
                client,
                name="Escalate high value",
                condition={"field": "amount", "op": "gte", "value": 10000},
                action="require_approval",
                priority=10,
            )

            resp = await client.post(
                "/api/ai/policies/evaluate",
                json={
                    "domain": TEST_DOMAIN,
                    "entity_type": TEST_ENTITY_TYPE,
                    "entity_data": {"id": 3, "amount": 20000, "vendor_status": "trusted"},
                    "source_agent": "Test Agent",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verdict"] == "blocked_pending_review"
        assert len(body["matched_policies"]) == 2
        assert body["workbench_item_id"] is not None

        db = SessionLocal()
        try:
            work_item = db.query(WorkItem).filter(WorkItem.id == body["workbench_item_id"]).first()
            assert work_item is not None
            assert work_item.exception_type == "policy_conflict"
            assert work_item.status == "pending"
            assert work_item.context["entity_data"]["id"] == 3
            assert len(work_item.context["permissive_policies"]) == 1
            assert len(work_item.context["gating_policies"]) == 1
        finally:
            db.close()
    finally:
        _cleanup()


async def test_evaluate_multi_action_policy_auto_approved():
    """A policy with several permissive actions (new `actions` list) is still a clean auto_approved."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve and notify",
                condition={"field": "amount", "op": "lt", "value": 500},
                action=None,
                actions=[{"type": "auto_approve"}, {"type": "allow", "value": "fast_track"}],
            )

            resp = await client.post(
                "/api/ai/policies/evaluate",
                json={
                    "domain": TEST_DOMAIN,
                    "entity_type": TEST_ENTITY_TYPE,
                    "entity_data": {"id": 4, "amount": 100},
                    "source_agent": "Test Agent",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verdict"] == "auto_approved"
        # One MatchedPolicySummary per action on the matched policy
        assert len(body["matched_policies"]) == 2
        assert all(m["bucket"] == "permissive" for m in body["matched_policies"])
        assert body["workbench_item_id"] is None
    finally:
        _cleanup()


async def test_evaluate_multi_action_policy_self_conflict():
    """A single policy whose actions span both buckets legitimately raises its own conflict."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Approve but flag for review",
                condition={"field": "amount", "op": "lt", "value": 500},
                action=None,
                actions=[{"type": "auto_approve"}, {"type": "flag_for_review", "value": "audit"}],
            )

            resp = await client.post(
                "/api/ai/policies/evaluate",
                json={
                    "domain": TEST_DOMAIN,
                    "entity_type": TEST_ENTITY_TYPE,
                    "entity_data": {"id": 5, "amount": 100},
                    "source_agent": "Test Agent",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verdict"] == "blocked_pending_review"
        assert len(body["matched_policies"]) == 2
        assert body["workbench_item_id"] is not None

        db = SessionLocal()
        try:
            work_item = db.query(WorkItem).filter(WorkItem.id == body["workbench_item_id"]).first()
            assert work_item is not None
            # Same policy on both sides of its own conflict
            assert work_item.context["permissive_policies"][0]["name"] == "Approve but flag for review"
            assert work_item.context["gating_policies"][0]["name"] == "Approve but flag for review"
            assert "auto_approve" in work_item.context["permissive_policies"][0]["actions"]
            assert "flag_for_review" in work_item.context["gating_policies"][0]["actions"]
        finally:
            db.close()
    finally:
        _cleanup()
