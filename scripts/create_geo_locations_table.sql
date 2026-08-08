-- Run this once in Supabase Studio → SQL Editor → New Query → Run.
-- Creates the Geo_Locations reference table used by the Demand Consolidation
-- Optimizer and Recovery Planner Operators (see PHASE1_CONSTRUCTION_PIVOT_SPEC.md
-- Part 1). Row population is handled separately by
-- `python scripts/seed_geo_locations.py` (via the Supabase REST API, no SQL
-- editor needed for that part) — this script only needs to create the table
-- and a uniqueness constraint so that seeding script can safely upsert.

create table if not exists "Geo_Locations" (
    id bigint generated always as identity primary key,
    location_type text not null,
    location_key text not null,
    city text not null,
    country text not null,
    lat double precision not null,
    lng double precision not null,
    constraint geo_locations_type_key_unique unique (location_type, location_key)
);
