# tests/test_insight_engine.py
"""
End-to-end tests for insight generation (app/services/insight_engine.py).

Exercises the real API against the real database (same DB the dev containers
use — AUTH_BYPASS is on, so requests run as the dev user). Each test cleans up
the policies/insights/audit logs it creates so runs don't accumulate state.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models.audit import AuditLog
from app.models.insight import Insight
from app.models.policy import Policy

pytestmark = pytest.mark.asyncio

TEST_DOMAIN = "pytest_insight_engine"
TEST_ENTITY_TYPE = "pytest_insight_entity"


def _cleanup():
    db = SessionLocal()
    try:
        policy_ids = [p.id for p in db.query(Policy).filter(Policy.domain == TEST_DOMAIN).all()]
        db.query(AuditLog).filter(AuditLog.resource_type == TEST_ENTITY_TYPE).delete()
        db.query(AuditLog).filter(AuditLog.resource_type == "insight").delete(synchronize_session=False)
        if policy_ids:
            db.query(Insight).filter(Insight.related_policy_id.in_(policy_ids)).delete(synchronize_session=False)
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


async def _run_evaluations(client: AsyncClient, count: int, amount: int):
    for i in range(count):
        resp = await client.post(
            "/api/ai/policies/evaluate",
            json={
                "domain": TEST_DOMAIN,
                "entity_type": TEST_ENTITY_TYPE,
                "entity_data": {"id": i, "amount": amount},
                "source_agent": "Test Agent",
            },
        )
        assert resp.status_code == 200, resp.text


async def test_generate_insights_produces_pattern():
    """3+ matching evaluations against an active policy yields at least one PATTERN insight."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )
            await _run_evaluations(client, count=3, amount=100)

            resp = await client.post("/api/ai/insights/generate", params={"domain": TEST_DOMAIN})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["generated_count"] >= 1
        assert any(i["insight_type"] == "pattern" for i in body["insights"])
        pattern = next(i for i in body["insights"] if i["insight_type"] == "pattern")
        assert pattern["extra_data"]["match_count"] == 3
        assert pattern["extra_data"]["total_evaluations"] == 3
    finally:
        _cleanup()


async def test_list_and_filter_insights():
    """Generated insights show up via GET, and insight_type/status filters narrow the results."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )
            await _run_evaluations(client, count=3, amount=100)

            gen_resp = await client.post("/api/ai/insights/generate", params={"domain": TEST_DOMAIN})
            assert gen_resp.status_code == 200, gen_resp.text
            generated_ids = {i["id"] for i in gen_resp.json()["insights"]}
            assert generated_ids

            list_resp = await client.get("/api/ai/insights", params={"insight_type": "pattern"})
            assert list_resp.status_code == 200, list_resp.text
            list_body = list_resp.json()
            listed_ids = {i["id"] for i in list_body["items"]}
            assert generated_ids <= listed_ids

            empty_resp = await client.get("/api/ai/insights", params={"insight_type": "anomaly", "status": "dismissed"})
            assert empty_resp.status_code == 200, empty_resp.text
            assert not (generated_ids & {i["id"] for i in empty_resp.json()["items"]})
    finally:
        _cleanup()


async def test_dismiss_insight():
    """Dismissing an insight transitions its status and can't be repeated."""
    _cleanup()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )
            await _run_evaluations(client, count=3, amount=100)

            gen_resp = await client.post("/api/ai/insights/generate", params={"domain": TEST_DOMAIN})
            insight_id = gen_resp.json()["insights"][0]["id"]

            dismiss_resp = await client.post(f"/api/ai/insights/{insight_id}/dismiss")
            assert dismiss_resp.status_code == 200, dismiss_resp.text
            body = dismiss_resp.json()
            assert body["success"] is True
            assert body["insight_id"] == insight_id
            assert body["action"] == "dismiss"

            get_resp = await client.get("/api/ai/insights", params={"status": "dismissed"})
            assert insight_id in {i["id"] for i in get_resp.json()["items"]}

            repeat_resp = await client.post(f"/api/ai/insights/{insight_id}/dismiss")
            assert repeat_resp.status_code == 400
    finally:
        _cleanup()
