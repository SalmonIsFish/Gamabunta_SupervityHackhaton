"""
Seed the Geo_Locations reference table in Supabase — the geography data the
Demand Consolidation Optimizer and Recovery Planner Operators need for
distance-based cost estimates (see PHASE1_CONSTRUCTION_PIVOT_SPEC.md Part 1).

Idempotent (upserts on location_type+location_key) — safe to re-run.

Prerequisite: the Geo_Locations table must already exist — run
`scripts/create_geo_locations_table.sql` once via Supabase Studio's SQL
Editor first (this script can only INSERT/UPSERT rows via the REST API, it
cannot create tables).

Usage:
    docker compose exec backend python scripts/seed_geo_locations.py
"""

import asyncio
import sys

from app.services import supabase_client

# warehouse rows: location_key = Warehouses.warehouse_code (from Warehouses.csv)
_WAREHOUSES = [
    ("MY01", "Shah Alam", "MY", 3.0738, 101.5183),
    ("MY02", "Johor Bahru", "MY", 1.4927, 103.7414),
    ("IN01", "Mumbai", "IN", 19.0760, 72.8777),
    ("SG01", "Jurong", "SG", 1.3400, 103.7050),
    ("TH01", "Laem Chabang", "TH", 13.0827, 100.8833),
    ("CN01", "Shanghai", "CN", 31.2304, 121.4737),
]

# supplier_country rows: location_key = suppliers.country code. Major
# trade/logistics hub per country (not always the political capital — e.g.
# Shanghai/Mumbai are reused from the warehouse rows above since they're
# also each country's dominant procurement/logistics hub).
_SUPPLIER_COUNTRIES = [
    ("CN", "Shanghai", "CN", 31.2304, 121.4737),
    ("IN", "Mumbai", "IN", 19.0760, 72.8777),
    ("MY", "Kuala Lumpur", "MY", 3.1390, 101.6869),
    ("SG", "Singapore", "SG", 1.3521, 103.8198),
    ("TH", "Bangkok", "TH", 13.7563, 100.5018),
]

# construction_site rows: location_key = Customer_Orders.customer (the 7
# distinct values in the CSV). Assigned real Malaysian cities per the brief's
# own example (Klang/Penang/Selangor) — reference/seed data, not a value
# invented at agent decision time (see spec Part 1 for why this is allowed).
_CONSTRUCTION_SITES = [
    ("KL Metro Rail", "Kuala Lumpur", "MY", 3.1390, 101.6869),
    ("Straits Construction Bhd", "Melaka", "MY", 2.1896, 102.2501),
    ("Highland Infra JV", "Ipoh", "MY", 4.5975, 101.0901),
    ("Meridian Build Group", "Penang", "MY", 5.4141, 100.3288),
    ("Zenith Motors", "Shah Alam", "MY", 3.0738, 101.5183),
    ("Nexus Retail Chain", "Johor Bahru", "MY", 1.4927, 103.7414),
    ("Andaman Resorts Ltd", "Langkawi", "MY", 6.3500, 99.8000),
]


def _rows() -> list[dict]:
    rows = []
    for key, city, country, lat, lng in _WAREHOUSES:
        rows.append({"location_type": "warehouse", "location_key": key, "city": city, "country": country, "lat": lat, "lng": lng})
    for key, city, country, lat, lng in _SUPPLIER_COUNTRIES:
        rows.append({"location_type": "supplier_country", "location_key": key, "city": city, "country": country, "lat": lat, "lng": lng})
    for key, city, country, lat, lng in _CONSTRUCTION_SITES:
        rows.append({"location_type": "construction_site", "location_key": key, "city": city, "country": country, "lat": lat, "lng": lng})
    return rows


async def main() -> None:
    if not supabase_client.is_configured():
        print("SUPABASE_URL/SUPABASE_SERVICE_KEY not configured — aborting.")
        sys.exit(1)

    rows = _rows()
    try:
        await supabase_client.upsert("Geo_Locations", rows, on_conflict="location_type,location_key")
    except Exception as exc:
        print(f"Seed failed: {exc}")
        print("If this is a 404/'relation does not exist' error, run scripts/create_geo_locations_table.sql")
        print("via Supabase Studio's SQL Editor first, then re-run this script.")
        sys.exit(1)

    print(f"Seeded {len(rows)} Geo_Locations rows ({len(_WAREHOUSES)} warehouses, "
          f"{len(_SUPPLIER_COUNTRIES)} supplier countries, {len(_CONSTRUCTION_SITES)} construction sites).")


if __name__ == "__main__":
    asyncio.run(main())
