# app/services/supabase_client.py
"""
Thin read-only Supabase REST client for the live procurement dataset.

Insight generation needs direct access to the operational tables (suppliers,
contracts, order_confirmations, demand_signals, inventory_positions, ...)
that the Auto Operators read from and write to — see the operational-insights
pass in app/services/insight_engine.py. This is not a general Supabase SDK:
it exists purely to let the backend sweep tables the way a business analyst
would (e.g. "contracts expiring in 90 days"), independent of what any single
Operator decision happened to touch.

Configured via SUPABASE_URL and SUPABASE_SERVICE_KEY — the service_role key
(not anon), needed to read past row-level security. Both point at the same
Supabase project the Auto workflows seed and query.
"""

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


def is_configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY"))


async def select(table: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """
    GET rows from a Supabase table via PostgREST.

    `params` are passed straight through as PostgREST query params, e.g.
    {"select": "*", "status": "eq.active"}. Returns [] on any failure or
    missing configuration rather than raising — insight generation is
    best-effort, a down/unconfigured Supabase project should mean fewer
    insights, not a broken /generate endpoint.
    """
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base_url or not service_key:
        log.info("Supabase not configured (SUPABASE_URL/SUPABASE_SERVICE_KEY) — skipping table '%s'", table)
        return []

    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    url = f"{base_url}/rest/v1/{table}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params or {"select": "*"})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        log.warning("Supabase read failed for table '%s': %s", table, exc)
        return []
