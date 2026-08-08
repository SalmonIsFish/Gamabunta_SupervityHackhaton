# app/routers/data_manager.py
"""
Data Manager endpoints - the live registry of every connected system.

Not a database-backed resource: this reports integration health at request
time, straight from a live probe where one is possible, or from honest
config-presence where it isn't. See docs/command-center-guide.md,
"Data Manager — every connected system, what it's for, whether it's healthy."

Supabase is one integration this backend actually holds credentials for, so
it gets a real live query. Slack (SLACK_BOT_TOKEN) and Dropbox
(DROPBOX_TOKEN) do too — both scoped just for this backend's own use
(Slack: a live auth.test health check; Dropbox: mirroring the Workbench
queue to a JSON file, see app/routers/workbench.py's
_mirror_commander_queue, plus a live health check here) — separate from
whatever the Supervity Auto workspace itself uses. Microsoft Outlook is
still configured inside the Supervity Auto workspace directly (see the
Round 1 workflow exports' `envs` declarations) — this backend never sees
that token, so fabricating a health signal for it would be dishonest; it's
reported as "external" instead. Supervity Auto itself *is* something this
backend holds credentials for (SUPERVITY_AUTO_API_KEY etc.), so it gets a
real configured/not_configured check.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..security import get_current_user
from ..services import dropbox_client, supabase_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/data-manager", tags=["Data Manager"])


class IntegrationStatus(BaseModel):
    name: str
    category: str  # "system_of_record" | "channel" | "orchestration"
    purpose: str
    status: Literal["healthy", "unhealthy", "configured", "not_configured", "external"]
    checked_live: bool
    detail: Optional[str] = None
    last_checked_at: str


class DataManagerStatusResponse(BaseModel):
    integrations: list[IntegrationStatus]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _check_supabase() -> IntegrationStatus:
    purpose = (
        "Procurement dataset (suppliers, contracts, purchase orders, inventory, disruption "
        "notices) that the Auto Operators read/write and AI Insights queries directly"
    )
    if not supabase_client.is_configured():
        return IntegrationStatus(
            name="Supabase",
            category="system_of_record",
            purpose=purpose,
            status="not_configured",
            checked_live=False,
            detail="SUPABASE_URL / SUPABASE_SERVICE_KEY not set in this backend's .env",
            last_checked_at=_now(),
        )
    try:
        rows = await supabase_client.select("suppliers", {"select": "id", "limit": "1"})
        healthy = isinstance(rows, list) and len(rows) > 0
        return IntegrationStatus(
            name="Supabase",
            category="system_of_record",
            purpose=purpose,
            status="healthy" if healthy else "unhealthy",
            checked_live=True,
            detail=(
                f"Live query returned {len(rows)} row(s) from 'suppliers'"
                if healthy
                else "Live query reached Supabase but returned no rows — check the project is seeded"
            ),
            last_checked_at=_now(),
        )
    except Exception as exc:  # supabase_client already swallows httpx errors into []; this is a last resort
        return IntegrationStatus(
            name="Supabase",
            category="system_of_record",
            purpose=purpose,
            status="unhealthy",
            checked_live=True,
            detail=str(exc),
            last_checked_at=_now(),
        )


def _auto_status() -> IntegrationStatus:
    present = bool(os.environ.get("SUPERVITY_AUTO_API_KEY"))
    return IntegrationStatus(
        name="Supervity Auto",
        category="orchestration",
        purpose="Runs the Master Orchestrator and its Operators — the agent layer this Command Center sits around",
        status="configured" if present else "not_configured",
        checked_live=False,
        detail=(
            "SUPERVITY_AUTO_API_KEY is set — ai_manager._dispatch() calls the Master Orchestrator workflow for "
            "disruption-notice chat turns, but this status is still config-presence only, not a live ping "
            "(the only way to probe Auto is executing a real, side-effecting workflow run)"
            if present
            else "SUPERVITY_AUTO_API_KEY not set in this backend's .env"
        ),
        last_checked_at=_now(),
    )


def _external_channel(name: str, purpose: str) -> IntegrationStatus:
    """Outlook — configured inside the Auto workspace itself, invisible to this backend."""
    return IntegrationStatus(
        name=name,
        category="channel",
        purpose=purpose,
        status="external",
        checked_live=False,
        detail="Configured directly in the Supervity Auto workspace — this backend holds no credential for it",
        last_checked_at=_now(),
    )


async def _check_slack() -> IntegrationStatus:
    name = "Slack"
    purpose = "Human-in-the-loop approval notifications from the Master Orchestrator"
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return IntegrationStatus(
            name=name,
            category="channel",
            purpose=purpose,
            status="external",
            checked_live=False,
            detail="Configured directly in the Supervity Auto workspace — this backend holds no credential for it",
            last_checked_at=_now(),
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body = response.json()
        if body.get("ok"):
            return IntegrationStatus(
                name=name,
                category="channel",
                purpose=purpose,
                status="healthy",
                checked_live=True,
                detail=f"Live auth.test succeeded — connected to workspace '{body.get('team')}' as '{body.get('user')}'",
                last_checked_at=_now(),
            )
        return IntegrationStatus(
            name=name,
            category="channel",
            purpose=purpose,
            status="unhealthy",
            checked_live=True,
            detail=f"Live auth.test failed: {body.get('error', 'unknown error')}",
            last_checked_at=_now(),
        )
    except httpx.HTTPError as exc:
        return IntegrationStatus(
            name=name,
            category="channel",
            purpose=purpose,
            status="unhealthy",
            checked_live=True,
            detail=str(exc),
            last_checked_at=_now(),
        )


async def _check_dropbox() -> IntegrationStatus:
    name = "Dropbox"
    purpose = "Live mirror of the open Workbench queue (commander view), written on every raise/resolve"
    if not dropbox_client.is_configured():
        return IntegrationStatus(
            name=name,
            category="system_of_record",
            purpose=purpose,
            status="not_configured",
            checked_live=False,
            detail="Neither DROPBOX_REFRESH_TOKEN+DROPBOX_APP_KEY+DROPBOX_APP_SECRET nor DROPBOX_TOKEN set in this backend's .env",
            last_checked_at=_now(),
        )
    account = await dropbox_client.get_current_account()
    if account is not None:
        return IntegrationStatus(
            name=name,
            category="system_of_record",
            purpose=purpose,
            status="healthy",
            checked_live=True,
            detail=f"Live get_current_account succeeded — connected as '{account.get('name', {}).get('display_name', 'unknown')}'",
            last_checked_at=_now(),
        )
    return IntegrationStatus(
        name=name,
        category="system_of_record",
        purpose=purpose,
        status="unhealthy",
        checked_live=True,
        detail="Live get_current_account call failed — check DROPBOX_TOKEN hasn't expired, or that DROPBOX_REFRESH_TOKEN/APP_KEY/APP_SECRET are correct",
        last_checked_at=_now(),
    )


@router.get("/status", response_model=DataManagerStatusResponse)
async def get_data_manager_status(user: dict = Depends(get_current_user)):
    """Live registry of every connected system: what it's for, and whether it's healthy."""
    integrations = [
        await _check_supabase(),
        _auto_status(),
        await _check_slack(),
        await _check_dropbox(),
        _external_channel("Microsoft Outlook", "Disruption-notice email ingestion for the Master Orchestrator"),
    ]
    return DataManagerStatusResponse(integrations=integrations)
