# app/routers/geo.py
"""
Read-only geography endpoints for the operational map (frontend/src/app/map).

Both endpoints are plain reads — no new business logic, no new Supabase
table, no new audit-log writes. See PHASE2_CONSTRUCTION_PIVOT_SPEC.md Part 2.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.audit import AuditLog
from ..security import get_current_user
from ..services import supabase_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/geo", tags=["Geo"])

# Only these entity_types come from an Operator that actually changes how/when
# an order is fulfilled — the ones worth plotting a decision route for.
_DECISION_ENTITY_TYPES = {"consolidation_decision", "recovery_plan", "customer_repromise"}


@router.get("/locations")
async def get_locations(user: dict = Depends(get_current_user)):
    """All Geo_Locations rows — warehouses, supplier-country centroids, construction sites."""
    rows = await supabase_client.select(
        "Geo_Locations",
        {"select": "location_type,location_key,city,country,lat,lng"},
    )
    return {"locations": rows}


def _geo_lookup(rows: list[dict[str, Any]], location_type: str, location_key: str) -> Optional[dict[str, Any]]:
    for row in rows:
        if row.get("location_type") == location_type and row.get("location_key") == location_key:
            return row
    return None


def _summarize(entity_type: str, entity_data: dict[str, Any]) -> str:
    """A short one-line label for the decision, distinct from its full `reason`."""
    if entity_type == "consolidation_decision":
        order_count = len(entity_data.get("consolidated_order_ids") or [])
        return f"Consolidated {order_count} order(s) for {entity_data.get('item_number', '?')} " f"(supplier {entity_data.get('supplier_id', '?')})"
    if entity_type == "recovery_plan":
        return f"Recovery plan for {entity_data.get('item_number', '?')} " f"(supplier {entity_data.get('supplier_id', '?')}): {entity_data.get('recommended_plan', '?')}"
    if entity_type == "customer_repromise":
        delay = entity_data.get("delay_days") or 0
        return f"Re-promise for order {entity_data.get('order_id', '?')}: " f"{delay} day(s) delay" if delay else f"Re-promise for order {entity_data.get('order_id', '?')}: on time"
    return entity_type


@router.get("/recent-decisions")
async def get_recent_decisions(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Recent Operator decisions (Demand Consolidation Optimizer, Recovery
    Planner, Customer Re-promising), resolved to origin/destination points on
    the map from Geo_Locations. Reads existing policy.evaluate audit log
    entries — entity_data is already persisted there in full (see
    policy_engine.py's evaluate()), nothing new to log.

    Note: recovery_plan's established contract (Phase 1, unchanged) carries
    no order_id/customer field, so it can only resolve an origin point, never
    a destination — that's not invented here, `destinations` is just empty
    for those.
    """
    geo_rows = await supabase_client.select("Geo_Locations", {"select": "*"})

    # Over-fetch since entity_type filtering happens in Python (extra_data is
    # a JSON column) — recent-first, keep the first `limit` that qualify.
    candidates = (
        db.query(AuditLog)
        .filter(AuditLog.action == "policy.evaluate")
        .order_by(AuditLog.timestamp.desc())
        .limit(max(limit * 10, 100))
        .all()
    )

    supplier_country_cache: dict[str, Optional[str]] = {}
    order_customer_cache: dict[str, Optional[str]] = {}

    async def supplier_country(supplier_id: str) -> Optional[str]:
        if supplier_id not in supplier_country_cache:
            rows = await supabase_client.select("suppliers", {"select": "country", "id": f"eq.{supplier_id}"})
            supplier_country_cache[supplier_id] = rows[0]["country"] if rows else None
        return supplier_country_cache[supplier_id]

    async def order_customer(order_id: str) -> Optional[str]:
        if order_id not in order_customer_cache:
            rows = await supabase_client.select("Customer_Orders", {"select": "customer", "id": f"eq.{order_id}"})
            order_customer_cache[order_id] = rows[0]["customer"] if rows else None
        return order_customer_cache[order_id]

    decisions: list[dict[str, Any]] = []
    for entry in candidates:
        if len(decisions) >= limit:
            break

        extra = entry.extra_data or {}
        entity_type = (extra.get("entity_summary") or {}).get("entity_type")
        if entity_type not in _DECISION_ENTITY_TYPES:
            continue
        entity_data = extra.get("entity_data") or {}

        origin = None
        supplier_id = entity_data.get("supplier_id")
        if supplier_id:
            country = await supplier_country(str(supplier_id))
            if country:
                geo_row = _geo_lookup(geo_rows, "supplier_country", country)
                if geo_row:
                    origin = {"lat": geo_row["lat"], "lng": geo_row["lng"], "label": f"Supplier {supplier_id} ({country})"}

        customer_names: list[str] = []
        if entity_type == "customer_repromise" and entity_data.get("customer"):
            customer_names = [entity_data["customer"]]
        elif entity_type == "consolidation_decision":
            for order_id in entity_data.get("consolidated_order_ids") or []:
                customer = await order_customer(str(order_id))
                if customer:
                    customer_names.append(customer)
        # recovery_plan: no order/customer field in its contract — destinations stays empty.

        destinations = []
        for name in customer_names:
            geo_row = _geo_lookup(geo_rows, "construction_site", name)
            if geo_row:
                destinations.append({"lat": geo_row["lat"], "lng": geo_row["lng"], "label": name})

        if origin is None and not destinations:
            continue  # nothing plottable — skip rather than show an empty line

        decisions.append(
            {
                "entity_type": entity_type,
                "origin": origin,
                "destinations": destinations,
                "summary": _summarize(entity_type, entity_data),
                "reason": entity_data.get("reason") or entity_data.get("notification_message") or "",
                "created_at": entry.timestamp.isoformat() if entry.timestamp else None,
            }
        )

    return {"decisions": decisions}
