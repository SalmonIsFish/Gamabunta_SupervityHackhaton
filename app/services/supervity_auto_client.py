# app/services/supervity_auto_client.py
"""
Thin client for calling out to auto.supervity.ai's Master Orchestrator workflow.

Mirrors app/services/supabase_client.py's pattern: module-level functions, no
class, env vars read fresh per call via os.environ.get, a fresh
httpx.AsyncClient per call, fails open (returns None) on any HTTP error so a
down/misconfigured Auto backend degrades ai_manager's reply instead of
breaking the chat endpoint.

Configured via SUPERVITY_AUTO_API_KEY, SUPERVITY_AUTO_ORG_KEY,
SUPERVITY_AUTO_BASE_URL, SUPERVITY_AUTO_ORCHESTRATOR_WORKFLOW_ID.

Response schema for POST /api/v1/workflow-runs/execute is not documented
anywhere available to this codebase — execute_workflow() returns the raw
parsed JSON body verbatim; callers must extract fields defensively.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 30.0  # workflow execution can be slower than a simple REST read
_EXECUTE_PATH = "/api/v1/workflow-runs/execute"


def is_configured() -> bool:
    return bool(os.environ.get("SUPERVITY_AUTO_API_KEY")) and bool(os.environ.get("SUPERVITY_AUTO_ORG_KEY"))


def _default_workflow_id() -> str:
    return os.environ.get("SUPERVITY_AUTO_ORCHESTRATOR_WORKFLOW_ID", "")


def _build_envs() -> dict[str, str]:
    """
    Only forward env vars this backend actually holds credentials for,
    renamed to the workflow's declared env names. The Master Orchestrator's
    own runtime inputs are literally labeled SUPABASE_URL/SUPABASE_KEY (per
    its Auto builder UI) — SUPABASE_TOKEN is also sent for compatibility
    with sub-workflows that declared the older name. POLICY_API_URL points
    at this backend's own public tunnel so the Orchestrator's fanned-out
    Operators (which POST their results back here) can reach it; SLACK_TOKEN
    is deliberately never sourced here — this backend has no credential for
    it (see data_manager.py) — Auto is expected to use its own
    workspace-configured value when it's omitted.
    """
    envs: dict[str, str] = {}
    if os.environ.get("SUPABASE_URL"):
        envs["SUPABASE_URL"] = os.environ["SUPABASE_URL"]
    if os.environ.get("SUPABASE_SERVICE_KEY"):
        envs["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_KEY"]
        envs["SUPABASE_TOKEN"] = os.environ["SUPABASE_SERVICE_KEY"]
    if os.environ.get("PUBLIC_BACKEND_URL"):
        envs["POLICY_API_URL"] = os.environ["PUBLIC_BACKEND_URL"].rstrip("/") + "/api/ai/policies/evaluate"
    return envs


async def execute_workflow(
    inputs: dict[str, Any],
    workflow_id: Optional[str] = None,
    envs: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    POST /api/v1/workflow-runs/execute — run the Auto Orchestrator.

    multipart/form-data with three parts: workflowId, inputs (JSON string),
    envs (JSON string). Returns the raw parsed JSON response, or None on any
    missing configuration / HTTP failure — callers must not assume any key
    is present in the returned dict (response schema undocumented).
    """
    base_url = os.environ.get("SUPERVITY_AUTO_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("SUPERVITY_AUTO_API_KEY", "")
    org_key = os.environ.get("SUPERVITY_AUTO_ORG_KEY", "")
    wf_id = workflow_id or _default_workflow_id()

    if not (base_url and api_key and org_key and wf_id):
        log.info("Supervity Auto not configured — skipping workflow execution")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-source": "external",
        "x-active-org": org_key,
    }
    # httpx only multipart-encodes when `files` is given; wrap the two JSON
    # fields as (None, value) "files" so they land as real form parts
    # instead of being urlencoded, per the documented multipart/form-data
    # requirement.
    files = {
        "inputs": (None, json.dumps(inputs)),
        "envs": (None, json.dumps(envs if envs is not None else _build_envs())),
    }
    data = {"workflowId": wf_id}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(f"{base_url}{_EXECUTE_PATH}", headers=headers, data=data, files=files)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        log.warning("Supervity Auto workflow execution failed: %s", exc)
        return None
