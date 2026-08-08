# app/routers/dashboard.py
"""
Read-only dashboard-summary endpoints — computed live at request time from
Supabase, nothing stored, same pattern as app/routers/data_manager.py.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..security import get_current_user
from ..services import supabase_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/inventory-summary")
async def get_inventory_summary(user: dict = Depends(get_current_user)):
    """
    Every inventory_positions row with available_qty computed the same way
    insight_engine.py's demand-anomaly pass already does (on_hand_qty minus
    committed_qty — the phantom-inventory trap this dataset is known for),
    and at_risk flagged on the same threshold (available_qty <= safety_stock)
    so this never disagrees with the Insights page about what's at risk.
    """
    rows = await supabase_client.select("inventory_positions", {"select": "*"})

    summary: list[dict[str, Any]] = []
    for row in rows:
        on_hand = row.get("on_hand_qty") or 0
        committed = row.get("committed_qty") or 0
        safety_stock = row.get("safety_stock") or 0
        available = on_hand - committed
        summary.append(
            {
                "item_number": row.get("item_number"),
                "description": row.get("description"),
                "location": row.get("location"),
                "on_hand_qty": on_hand,
                "committed_qty": committed,
                "safety_stock": safety_stock,
                "available_qty": available,
                "at_risk": available <= safety_stock,
            }
        )

    return {"items": summary}
