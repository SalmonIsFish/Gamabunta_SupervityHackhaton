# Next Steps — Round 2 Operations Track

Working punch list for the Procurement Exception Command Center build. Updated 2026-07-31 after
wiring the backend (Policies/Workbench/Insights) to fit a proposed 7-Operator design — see
`C:\Users\G2\.claude\plans\check-first-what-we-ancient-twilight.md` for the fit-check analysis
behind those changes, and `CLAUDE.md`'s "Current Status" for what's actually built.

**Timeline:** remote build 3–7 Aug · offline build + code freeze 11:59PM 8 Aug at APU · Grand Finale
9 Aug. Judges score a pass/fail gate first, then Business output 30 / Architecture-on-Auto 20 /
Policies 20 / Insights 15 / Command Center & live demo 15, +10 bonus.

## Mandatory floor — current status

| Requirement | Status |
|---|---|
| Orchestrator + 5 distinct Operators on Auto | **2 of 5** — Master Orchestrator, Impact Mapper, Alternative Sourcer exist (`Operations_Case_Study/Round 1 Operator/`). Need 3+ more. |
| Command Center wired to live agent activity | **Backend ready, frontend not wired.** Policies/Workbench/Insights endpoints are real; the pages still render `DEMO_*` arrays. |
| 3+ active AI Policies, no-code editable, logged | **Done.** 4 seeded active policies (`scripts/seed_db.py`), every evaluation audit-logged via `policy_engine.evaluate()`. |
| Live human loop via Workbench | **Backend ready.** `POST /api/workbench` (raise) + `POST /api/workbench/{id}/resolve` both work and are tested. Needs a real Operator actually calling it. |
| 3+ live integrations, 2 categories, healthy in Data Manager | **Not started.** Supabase (system of record) not yet seeded; Slack/Outlook (channel) exist in the Round 1 Auto workflows but Data Manager page doesn't reflect any of it. |

## 1. Get data flowing (blocks almost everything else)

- [ ] Create/confirm the Supabase project, seed all 14 `Operations_Case_Study/dataset/csv/` tables into it
      (matches the Round 1 Auto workflows' existing pattern — they already query `inventory_positions` and
      `contracts` there).
- [ ] Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (the **service_role** key, not `anon`) to your local
      `.env` — see `.env.example` for the new section. This immediately lights up the new operational
      Insights pass (delay patterns, POs at risk, demand anomalies, single-source exposure, contract expiry)
      with zero further code changes.
- [ ] Once Auto's rate limit resets: generate/confirm a Workflow API key at `auto.supervity.ai/u/api-keys`
      and add it to `.env` too (name TBD when you wire step 3 below — check `auto.supervity.ai/docs` for
      the exact env var / auth header it expects).
- [ ] Do **not** `git add Operations_Case_Study/` — the dataset may not be redistributed per the Round 2
      guide, and `origin` is a public repo judges will access.

## 2. Verify what's already built (quick, do this first)

```bash
docker compose up -d --build backend      # scripts/ is baked into the image, not bind-mounted
docker compose exec backend python scripts/seed_db.py   # seeds the 4 procurement policies (idempotent)
docker compose exec backend pytest tests/ -q             # should be 12 passed
curl http://localhost:8001/api/ai/policies                # confirm the 4 policies list as active
```

## 3. Build the remaining Operators on Auto

Only Impact Mapper and Alternative Sourcer exist. Proposed additions (each has an `entity_data` contract
already matched to the seeded policies — see the plan file for exact field names):

- **Supplier Cascade Mapper** — walks `Supplier_Tiers` to find every tier-1 supplier a failed tier-2/3
  supplier takes down with it.
- **Multi-Event Prioritizer** — holds state across concurrently open disruptions; arbitrates when two
  compete for the same `Alternative_Suppliers` candidate or the same warehouse buffer stock.
- **Cost & Clause Evaluator** — joins `contracts`/`Penalties` to score an expedite against escalation
  clauses and net cost after penalties. Its output is what the "Expedite Spend Limit" and "Contract
  Escalation Clause Block" policies gate — POST its result to `/api/ai/policies/evaluate` with
  `domain="procurement"`, `entity_type="expedite_decision"`.
- **Logistics / Port-Cutoff Monitor** — batch-flags `Shipments` past/near `port_cutoff` against
  `purchase_order_headers.need_by_date` (the "port strike" trap — many POs at once, not one at a time).
- **Inventory Reallocation Planner** — cross-warehouse stock moves protecting `Customer_Orders.priority`.

For each: build and test standalone as its own Auto workflow first (per the Round 2 guide's own
build order), *then* wire it into the Master Orchestrator's branching/fan-out logic. Route anything
that isn't a clean auto-approve/require-approval through the new generic `POST /api/workbench` when it
doesn't fit the policy-conflict path (e.g. orphan FK data, low-confidence disruption notices with blank
`severity`/`confidence` — several real rows in `disruption_notices.csv` have these blank).

## 4. Wire the frontend off demo data

- `frontend/src/app/ai/policies/page.tsx` — replace `DEMO_POLICIES` with real `apiClient` calls.
  **Careful:** the demo data's shape doesn't match the backend at all (`operator` vs `op`, `'less_than'`
  vs `'lt'`, `is_active` vs `status`, and fields like `entity_name`/`tags`/`execution_count` that don't
  exist on the real `Policy` model) — this needs a rewrite of the page's data layer, not a field rename.
- `frontend/src/app/ai/insights/page.tsx` — same treatment, call `POST /api/ai/insights/generate` +
  `GET /api/ai/insights`.
- `frontend/src/app/workbench/page.tsx` — currently a static shell with no data fetching at all; wire to
  `GET /api/workbench` (list) and `POST /api/workbench/{id}/resolve`.
- Dashboard — wire stat cards/activity chart to real KPIs (open disruptions by severity, cost at risk vs
  avoided, time-to-recovery, supplier health) once there's real Operator activity to show.

## 5. Data Manager

Not touched by this session's work. Needs entries for: Supabase (system of record), Slack (channel,
already used by the Round 1 workflows), Outlook (channel, already used for notice ingestion) — each
showing live health, not hardcoded rows (the guide explicitly disqualifies hardcoded Data Manager entries).

## 6. Known loose ends

- `AIManager.tsx` doesn't thread `session_id` back on subsequent chat turns — every message gets a fresh
  UUID server-side, so multi-turn conversations silently reset. Unfixed as of this writing.
- `ai_manager._dispatch()` still just runs `policy_engine.evaluate()` directly — swap in the real Auto
  call once the token resets (seam confirmed reusable as-is, no signature changes needed).
- Natural-language policy evaluation (`Policy.policy_type = natural_language`) needs `ANTHROPIC_API_KEY`,
  not yet in `.env` — DB/schema already support it, only the evaluator is missing.
