# app/services/geo.py
"""
Haversine distance helper shared by the Demand Consolidation Optimizer and
Recovery Planner Operators (see PHASE1_CONSTRUCTION_PIVOT_SPEC.md Part 1).

The actual distance-based transport-cost estimate happens Auto-side, inside
each Operator's own prompt/logic, reading the Geo_Locations table directly —
this helper exists so the backend can recompute/validate the same number, or
expose it to the frontend later, without duplicating the formula.
"""

import math

_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
