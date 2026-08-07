# tests/test_supervity_auto_client.py
"""
Unit tests for app/services/supervity_auto_client.py — no live network access;
httpx.AsyncClient.post is monkeypatched.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import supervity_auto_client as sac

pytestmark = pytest.mark.asyncio


def _set_full_config(monkeypatch):
    monkeypatch.setenv("SUPERVITY_AUTO_BASE_URL", "https://auto.supervity.ai")
    monkeypatch.setenv("SUPERVITY_AUTO_API_KEY", "test-api-key")
    monkeypatch.setenv("SUPERVITY_AUTO_ORG_KEY", "test-org-key")
    monkeypatch.setenv("SUPERVITY_AUTO_ORCHESTRATOR_WORKFLOW_ID", "wf-123")


async def test_execute_workflow_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SUPERVITY_AUTO_API_KEY", raising=False)
    monkeypatch.delenv("SUPERVITY_AUTO_ORG_KEY", raising=False)
    monkeypatch.delenv("SUPERVITY_AUTO_BASE_URL", raising=False)
    monkeypatch.delenv("SUPERVITY_AUTO_ORCHESTRATOR_WORKFLOW_ID", raising=False)

    result = await sac.execute_workflow(inputs={"notice_id": "DN-1"})
    assert result is None


async def test_is_configured_true_only_when_both_keys_present(monkeypatch):
    monkeypatch.delenv("SUPERVITY_AUTO_API_KEY", raising=False)
    monkeypatch.delenv("SUPERVITY_AUTO_ORG_KEY", raising=False)
    assert sac.is_configured() is False

    monkeypatch.setenv("SUPERVITY_AUTO_API_KEY", "k")
    assert sac.is_configured() is False

    monkeypatch.setenv("SUPERVITY_AUTO_ORG_KEY", "o")
    assert sac.is_configured() is True


async def test_execute_workflow_returns_none_on_http_error(monkeypatch):
    _set_full_config(monkeypatch)

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 error", request=MagicMock(), response=MagicMock(status_code=500)
    )
    mock_post = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await sac.execute_workflow(inputs={"notice_id": "DN-1"})
    assert result is None


async def test_execute_workflow_sends_required_headers_and_workflow_id(monkeypatch):
    _set_full_config(monkeypatch)

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"accepted": True, "message": "Execution started"}
    mock_post = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await sac.execute_workflow(inputs={"notice_id": "DN-1", "supplier_id": "S1"})

    assert result == {"accepted": True, "message": "Execution started"}
    mock_post.assert_awaited_once()
    _, kwargs = mock_post.await_args
    assert kwargs["headers"] == {
        "Authorization": "Bearer test-api-key",
        "x-source": "external",
        "x-active-org": "test-org-key",
    }
    assert kwargs["data"] == {"workflowId": "wf-123"}
    assert "inputs" in kwargs["files"]
    assert "envs" in kwargs["files"]
