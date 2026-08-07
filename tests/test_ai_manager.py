# tests/test_ai_manager.py
"""
End-to-end tests for the AI Manager chat (app/services/ai_manager.py).

Exercises the real API against the real database (same DB the dev containers
use — AUTH_BYPASS is on, so requests run as the dev user). Each test cleans up
the policies/chat messages/work items/audit logs it creates so runs don't
accumulate state.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import ChatMessage
from app.models.policy import Policy
from app.models.work_item import WorkItem
from app.services import ai_manager

pytestmark = pytest.mark.asyncio

TEST_DOMAIN = "pytest_ai_manager"
TEST_ENTITY_TYPE = "chat_entity"


def _cleanup(session_ids):
    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.action == "ai_manager.chat").filter(
            AuditLog.resource_id.in_(session_ids)
        ).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.resource_type == TEST_ENTITY_TYPE).delete()
        db.query(WorkItem).filter(WorkItem.resource_type == TEST_ENTITY_TYPE).delete()
        db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
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


async def test_chat_auto_approved_message_persisted():
    """A chat message matching a permissive policy gets an auto_approved reply, persisted."""
    session_ids: list[str] = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )

            resp = await client.post(
                "/api/ai/chat",
                json={
                    "message": "please check this",
                    "entity_data": {"id": 1, "amount": 100},
                    "domain": TEST_DOMAIN,
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            session_ids.append(body["session_id"])

            assert body["role"] == "assistant"
            assert "Auto-approved" in body["content"]
            assert body["response"] == body["content"]  # frontend-compat alias
            assert body["extra_data"]["verdict"] == "auto_approved"
            assert body["extra_data"]["workbench_item_id"] is None

            # Both the user turn and the assistant reply were persisted.
            db = SessionLocal()
            try:
                messages = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == body["session_id"])
                    .order_by(ChatMessage.created_at.asc())
                    .all()
                )
                assert len(messages) == 2
                assert messages[0].role == "user"
                assert messages[0].content == "please check this"
                assert messages[1].role == "assistant"
                assert messages[1].extra_data["verdict"] == "auto_approved"
            finally:
                db.close()
    finally:
        _cleanup(session_ids)


async def test_chat_conflict_creates_workbench_item():
    """A chat message that triggers a policy conflict creates a WorkItem, linked via extra_data."""
    session_ids: list[str] = []
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
                "/api/ai/chat",
                json={
                    "message": "process this big order",
                    "entity_data": {"id": 2, "amount": 20000, "vendor_status": "trusted"},
                    "domain": TEST_DOMAIN,
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            session_ids.append(body["session_id"])

            assert body["extra_data"]["verdict"] == "blocked_pending_review"
            workbench_item_id = body["extra_data"]["workbench_item_id"]
            assert workbench_item_id is not None
            assert f"#{workbench_item_id}" in body["content"]

            work_item_resp = await client.get(f"/api/workbench/{workbench_item_id}")
            assert work_item_resp.status_code == 200, work_item_resp.text
            work_item = work_item_resp.json()
            assert work_item["exception_type"] == "policy_conflict"
            assert work_item["status"] == "pending"
    finally:
        _cleanup(session_ids)


async def test_chat_history_returns_messages_in_order():
    """GET /chat/{session_id} returns the conversation oldest-first, across multiple turns."""
    session_ids: list[str] = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first_resp = await client.post("/api/ai/chat", json={"message": "hello"})
            assert first_resp.status_code == 200, first_resp.text
            session_id = first_resp.json()["session_id"]
            session_ids.append(session_id)

            second_resp = await client.post(
                "/api/ai/chat", json={"message": "how are you?", "session_id": session_id}
            )
            assert second_resp.status_code == 200, second_resp.text
            assert second_resp.json()["session_id"] == session_id

            history_resp = await client.get(f"/api/ai/chat/{session_id}")
            assert history_resp.status_code == 200, history_resp.text
            history = history_resp.json()

            assert history["session_id"] == session_id
            roles = [m["role"] for m in history["messages"]]
            contents = [m["content"] for m in history["messages"]]
            assert roles == ["user", "assistant", "user", "assistant"]
            assert contents[0] == "hello"
            assert contents[2] == "how are you?"
            timestamps = [m["created_at"] for m in history["messages"]]
            assert timestamps == sorted(timestamps)
    finally:
        _cleanup(session_ids)


async def test_chat_history_404_for_unknown_session():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/ai/chat/does-not-exist")
    assert resp.status_code == 404


async def test_chat_disruption_notice_calls_auto_and_appends_summary(monkeypatch):
    """entity_data shaped like a disruption notice triggers a Master Orchestrator
    call; its response is appended to the reply and stashed in extra_data, without
    changing the policy verdict."""
    monkeypatch.setattr(ai_manager.supervity_auto_client, "is_configured", lambda: True)
    mock_execute = AsyncMock(return_value={"accepted": True, "message": "Execution started"})
    monkeypatch.setattr(ai_manager.supervity_auto_client, "execute_workflow", mock_execute)

    session_ids: list[str] = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )

            resp = await client.post(
                "/api/ai/chat",
                json={
                    "message": "supplier delay notice",
                    "entity_data": {
                        "amount": 100,
                        "notice_id": "DN-9001",
                        "supplier_id": "3022",
                        "item_number": "SKU-EL-440",
                        "notice_type": "supplier_delay",
                    },
                    "domain": TEST_DOMAIN,
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            session_ids.append(body["session_id"])

            assert body["extra_data"]["verdict"] == "auto_approved"
            assert body["extra_data"]["auto_response"] == {"accepted": True, "message": "Execution started"}
            assert "Auto Orchestrator run started" in body["content"]

            mock_execute.assert_awaited_once()
            call_inputs = mock_execute.await_args.kwargs["inputs"]
            assert call_inputs == {
                "notice_id": "DN-9001",
                "supplier_id": "3022",
                "item_number": "SKU-EL-440",
                "notice_type": "supplier_delay",
                "slack_channel": "#alerts",
            }
    finally:
        _cleanup(session_ids)


async def test_chat_without_notice_fields_skips_auto(monkeypatch):
    """entity_data that doesn't look like a disruption notice never calls Auto,
    even when Auto is configured — existing (non-notice) chat behavior is
    unaffected by the Auto integration."""
    monkeypatch.setattr(ai_manager.supervity_auto_client, "is_configured", lambda: True)
    mock_execute = AsyncMock()
    monkeypatch.setattr(ai_manager.supervity_auto_client, "execute_workflow", mock_execute)

    session_ids: list[str] = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _create_active_policy(
                client,
                name="Auto-approve small amounts",
                condition={"field": "amount", "op": "lt", "value": 500},
                action="auto_approve",
            )

            resp = await client.post(
                "/api/ai/chat",
                json={"message": "please check this", "entity_data": {"id": 1, "amount": 100}, "domain": TEST_DOMAIN},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            session_ids.append(body["session_id"])

            assert "auto_response" not in body["extra_data"]
            mock_execute.assert_not_awaited()
    finally:
        _cleanup(session_ids)
