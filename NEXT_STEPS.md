# Next Steps — Round 2 Operations Track

Working punch list for the Procurement Exception Command Center build. Updated 2026-08-01. See
`C:\Users\G2\.claude\plans\check-first-what-we-ancient-twilight.md` for the design rationale behind
the Workbench/Data Manager/Policies/Insights wiring, and `CLAUDE.md`'s "Current Status" for what's
actually built.

**Timeline:** remote build 3–7 Aug · offline build + code freeze 11:59PM 8 Aug at APU · Grand Finale
9 Aug. Judges score a pass/fail gate first, then Business output 30 / Architecture-on-Auto 20 /
Policies 20 / Insights 15 / Command Center & live demo 15, +10 bonus.

## Who's doing what right now

- **Teammate** — builds the remaining 5 Operators on Auto (§2).
- **You** — full Supabase reseed (§1) — has to be your account/credentials.
- **Claude (me)** — Dashboard page wiring + the `AIManager.tsx` session_id bug, while the above two
  are in progress.

## 1. Supabase reseed — full delete + clean reload, not a patch

Audited the live Supabase project on 2026-07-31/08-01 and found it's running stale/partial data:

| Table | Status |
|---|---|
| `Supplier_Tiers`, `Warehouses`, `Shipments`, `Customer_Orders`, `Alternative_Suppliers`, `Penalties` | **Don't exist at all** (404, not empty — never created) |
| `suppliers` | 50 rows in Supabase vs 73 in the CSV |
| `contracts` | 45 vs 70 |
| `purchase_order_headers` | 80 vs 210 |
| `purchase_order_lines` | 171 vs 443 |
| `order_confirmations` | 130 vs 345 |
| `Inventory_positions` | 16 vs 39 |
| `demand_signals` | 140 vs 365 |
| `disruption_notices` | 45 vs 118 |

**Do a full delete + clean reload of all 14 tables from `Operations_Case_Study/dataset/csv/`,
not an incremental patch.** This is safe: confirmed every Operator and backend service that touches
Supabase (Impact Mapper, Alternative Sourcer, `insight_engine.py`) only ever reads (`GET`/`select`) —
nothing writes back into these tables, so there's no state to lose. The current partial data is
actively producing *wrong* numbers in Insights right now (e.g. "48 purchase orders trending at risk"
was computed against the partial set, not the real one), not just missing some.

**How** (Supabase Studio, no SQL needed):
1. The 8 existing tables above: Table Editor → select table → select all rows → Delete → Insert →
   Import data from CSV → pick the matching file.
2. The 6 missing tables: Table Editor → New Table → Import data via spreadsheet — Supabase infers
   the schema from the CSV directly, no manual column setup.
3. **Keep table names matching the CSV filenames exactly, including capitalization** — e.g.
   `Supplier_Tiers`, not `supplier_tiers`. This project already has one casing quirk
   (`Inventory_positions`, capital I, everything else in that table lowercase) that the backend code
   has to match exactly (see the bug below) — staying consistent with each CSV's own filename casing
   for the 6 new tables avoids adding more of these landmines.

**Once done, tell me** — I'll query Supabase directly to confirm all 14 tables and row counts match
before you move on, and re-run `POST /api/ai/insights/generate` to confirm the operational insights
reflect the real dataset (demand anomalies in particular never had real data to work with — see the
bug fix below).

**Bug found and fixed during this audit:** `insight_engine.py` was querying `inventory_positions`
(lowercase) when the real table is `Inventory_positions` — silently 404ing and swallowing to an empty
list every time, so the demand-anomaly insight was finding "zero anomalies" for the wrong reason (no
data loaded, not no anomalies). Fixed and pushed (`2fb2480`).

## 2. Build the remaining Operators on Auto (teammate)

Only Master Orchestrator, Impact Mapper, and Alternative Sourcer exist. Five more to build, each with
an `entity_data` contract already matched to the 4 seeded policies:

| Operator | Reads | Does | Posts to this backend |
|---|---|---|---|
| **Supplier Cascade Mapper** | `Supplier_Tiers` | Given a failed `supplier_id`, walks `depends_on_supplier_id` to find every tier-1 supplier it takes down with it | — |
| **Multi-Event Prioritizer** | open disruptions, `Alternative_Suppliers`, `Inventory_positions` | Holds state across concurrent disruptions; arbitrates when two want the same alt supplier or the same buffer stock | `entity_type="customer_impact"` |
| **Cost & Clause Evaluator** | `contracts`, `Penalties` | Scores an expedite against escalation clauses + penalty cost | `entity_type="expedite_decision"` → `{id, supplier_id, item_number, expedite_cost, requires_vp_signoff, penalty_amount, net_savings}` — feeds "Expedite Spend Limit" + "Contract Escalation Clause Block" |
| **Logistics / Port-Cutoff Monitor** | `Shipments`, `purchase_order_headers` | Batch-flags shipments past/near `port_cutoff` against `need_by_date` — the "many POs at once" port-strike trap | — |
| **Inventory Reallocation Planner** | `Inventory_positions` across nodes, `Customer_Orders` | Cross-warehouse stock moves protecting `Customer_Orders.priority` | `entity_type="customer_impact"` |

`POST /api/ai/policies/evaluate` (`domain="procurement"`) and `POST /api/workbench` (raise an
exception that doesn't fit a policy check — orphan data, low-confidence notices) are both live and
tested; full API docs at `http://localhost:8001/api/docs`.

**At least one Operator needs to raise a real Workbench exception before the demo** — the only
WorkItem created so far was a manually-curled test, and the mandatory-floor "live human loop" item
needs a genuine one.

## 3. Wire `ai_manager._dispatch()` to Auto (once the rate limit resets)

Still just runs `policy_engine.evaluate()` directly. `SUPERVITY_AUTO_API_KEY`/`ORG_KEY`/`BASE_URL`/
`ORCHESTRATOR_WORKFLOW_ID` are all in `.env` and confirmed loaded. Per `auto.supervity.ai/docs/api-docs`:
`POST /api/v1/workflow-runs/execute` (multipart/form-data: `workflowId`, `inputs`, `envs`) against
`https://auto.supervity.ai` — same host as the dashboard. Auth needs three headers: `Authorization:
Bearer <key>`, `x-source: external`, `x-active-org: <org-key>`. Contract (`reply_text, extra_data`)
doesn't need to change — seam confirmed reusable as-is.

## 4. In progress (Claude)

- **Dashboard** (`frontend/src/app/page.tsx`) — still static demo stat cards, never wired this
  session. Worth 6 rubric points ("Live dashboard").
- **`AIManager.tsx` session_id bug** — doesn't thread `session_id` back on subsequent chat turns;
  every message gets a fresh UUID server-side, multi-turn conversation silently resets.

## 5. Known loose ends, lower priority

- **StructuredBuilder action-vocabulary mismatch** — its `COMMON_ACTIONS` list (`flag_review`,
  `auto_reject`, `notify`, ...) doesn't exactly match `policy_engine.py`'s recognized action strings
  (`flag_for_review`, `require_approval`, `auto_approve`, ...). Not a correctness bug — unrecognized
  actions fail safely to the gating bucket — but logs a warning on every evaluation for policies
  created with the mismatched labels.
- **"Create with AI" tab / "Generate Rules with AI" button / natural-language policy evaluation** —
  all need `ANTHROPIC_API_KEY`, not yet in `.env`. Fail visibly now instead of silently no-op-ing. The
  Structured Builder tab works fully without any LLM dependency — that's the reliable no-code path
  for the demo.

## 6. Verify before the demo

```bash
docker compose exec backend pytest tests/ -q       # should be 14 passed
npm run build                                        # (in frontend/) production build must succeed
docker compose up -d --build backend frontend        # rebuild both if either was edited
```
Manually re-check after the Supabase reseed: Insights "Run Analysis" should show materially different
(larger/more accurate) numbers than the ones already verified working against partial data
(Workbench resolve, Policies edit/toggle/create/delete, Data Manager Supabase health — all confirmed
end-to-end as of 2026-07-31 and don't depend on the reseed).
