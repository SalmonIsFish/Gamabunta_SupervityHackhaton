# app/routers/data_manager.py
"""
Data Manager endpoints - the live registry of every connected system.

Not a database-backed resource: this reports integration health at request
time, straight from a live probe where one is possible, or from honest
config-presence where it isn't. See docs/command-center-guide.md,
"Data Manager — every connected system, what it's for, whether it's healthy."

Supabase is the one integration this backend actually holds credentials for,
so it gets a real live query. Slack and Microsoft Outlook are configured
inside the Supervity Auto workspace directly (see the Round 1 workflow
exports' `envs` declarations) — this backend never sees those tokens, so
fabricating a health signal for them would be dishonest; they're reported as
"external" instead. Supervity Auto itself *is* something this backend holds
credentials for (SUPERVITY_AUTO_API_KEY etc.), so it gets a real
configured/not_configured check.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..security import get_current_user
from ..services import supabase_client

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
            "SUPERVITY_AUTO_API_KEY is set — not yet a live ping, ai_manager._dispatch() doesn't call out to "
            "Auto yet (see NEXT_STEPS.md)"
            if present
            else "SUPERVITY_AUTO_API_KEY not set in this backend's .env"
        ),
        last_checked_at=_now(),
    )


def _external_channel(name: str, purpose: str) -> IntegrationStatus:
    """Slack/Outlook — configured inside the Auto workspace itself, invisible to this backend."""
    return IntegrationStatus(
        name=name,
        category="channel",
        purpose=purpose,
        status="external",
        checked_live=False,
        detail="Configured directly in the Supervity Auto workspace — this backend holds no credential for it",
        last_checked_at=_now(),
    )


@router.get("/status", response_model=DataManagerStatusResponse)
async def get_data_manager_status(user: dict = Depends(get_current_user)):
    """Live registry of every connected system: what it's for, and whether it's healthy."""
    integrations = [
        await _check_supabase(),
        _auto_status(),
        _external_channel("Slack", "Human-in-the-loop approval notifications from the Master Orchestrator"),
        _external_channel("Microsoft Outlook", "Disruption-notice email ingestion for the Master Orchestrator"),
    ]
    return DataManagerStatusResponse(integrations=integrations)
