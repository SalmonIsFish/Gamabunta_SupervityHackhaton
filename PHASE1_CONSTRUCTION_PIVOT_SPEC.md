# Phase 1 — Construction Supply Chain Niche: Build Spec

For Claude Code to implement directly. Written 2026-08-08, target: done and tested by **1:00 AM**.

## Context (why this exists)

We're niching the existing Procurement Exception Command Center into **construction-material
procurement** (cement, aggregate, steel, etc.) for the Round 2 demo. This is a graft onto the
existing, already-tested backbone — not a rebuild. Do not touch anything not listed below;
everything currently working (Workbench, Policies, Insights, Data Manager, Supabase/Slack/Dropbox
integrations, the 8 existing Auto Operators) stays exactly as-is.

**The one new idea that makes this demo distinctive:** a construction site orders less material
than a supplier's minimum shipment quantity (e.g. Site A needs 20,000 kg cement, supplier's MOQ is
40,000 kg). Auto should find another site needing the same material and consolidate their demand —
but the choice of *which* other site to combine with is an optimization problem (distance, cost,
customer priority, penalty exposure), not "pick the closest one." This is genuinely new logic, not
in the current build.

**Time-box, in priority order.** If time runs out, stop at the end of the last fully-completed
numbered part below and ship that — do not leave Part 3 half-done to start Part 5.

1. Part 1 (data) — required, everything else depends on it
2. Part 2 (Demand Consolidation Optimizer) — the signature demo moment, highest priority
3. Part 3 (Recovery Planner) — closes a known judged gap, second priority
4. Part 4 (policy + AI Manager registry wiring) — required for both to actually do anything
5. Part 4b (Master Orchestrator wiring) — do not skip, see below for why
6. Part 5 (frontend labels) — cosmetic, cut first if behind
7. Part 6 (testing) — never cut, even if it means cutting Part 5

---

## Part 1 — Data: what already exists vs. what's new

**Good news: MOQ already exists in the dataset**, confirmed directly from
`Operations_Case_Study/dataset/csv/`:

- `suppliers.csv` has `moq` and `lead_time_days` columns already.
- `Alternative_Suppliers.csv` has `moq`, `price`, `lead_time_days`, `valid_until` — per
  `item_number` + `supplier_id`, which is the more useful granularity for consolidation (a
  supplier's MOQ can vary by material).
- `Customer_Orders.csv` (45 rows) is already effectively "construction site demand": columns
  `id, item_number, customer, qty, promised_date, priority, ship_from_node, status`. 7 distinct
  `customer` values (some already construction-flavored: `KL Metro Rail`, `Highland Infra JV`,
  `Straits Construction Bhd`; others aren't, e.g. `Zenith Motors` — that's fine, don't rename rows,
  the Operator logic must work generically regardless of customer name).
- Item numbers already include `SKU-CEM-101` (cement) plus 15 other materials (aggregate, steel,
  etc.) — the cement scenario from the brief maps directly onto real seeded data, no invented SKU
  needed.

**What's genuinely missing: geography.** Nothing in the dataset has coordinates. `suppliers.csv`
only has a `country` code (5 distinct: CN, IN, MY, SG, TH). `Warehouses.csv` (6 rows) has
city/country but no lat/lng. `Customer_Orders.customer` has no location at all.

**Add one new Supabase table: `Geo_Locations`**

| column | type | notes |
|---|---|---|
| `location_type` | text | `warehouse` \| `supplier_country` \| `construction_site` |
| `location_key` | text | join key — see below |
| `city` | text | |
| `country` | text | |
| `lat` | float | |
| `lng` | float | |

Join keys:
- `warehouse` rows: `location_key` = `Warehouses.warehouse_code` (6 rows, real city already known
  from the CSV — just geocode those 6 real cities, e.g. Shah Alam, Johor Bahru, etc.)
- `supplier_country` rows: `location_key` = the country code (5 rows: CN, IN, MY, SG, TH) — use a
  representative capital/major-city centroid per country. This is a systematic reference table, not
  per-row invention — every supplier in that country resolves through it generically.
- `construction_site` rows: `location_key` = `Customer_Orders.customer` (7 rows). Assign each a real
  Malaysian city (the brief's own example uses Klang/Penang/Selangor) — round-robin across a handful
  of real cities is fine, this is seed/reference data for the demo environment, not the agent
  inventing a value at decision time (that rule is about the agent never guessing a *missing
  operational* field mid-decision — this is the team populating a master reference table before the
  agent runs, same category as seeding the other 14 tables).

This is a small table (~18 rows) — populate it via a short Python/SQL script against Supabase,
same pattern as the existing reseed scripts under `scripts/`. Distance between any two rows =
haversine(lat1,lng1,lat2,lng2). Put the haversine helper somewhere shared (e.g.
`app/services/geo.py`) since both new Operators conceptually need it — though note the actual
distance math happens Auto-side inside the Operator prompt/logic, this helper is for the backend
if we want to recompute/validate or expose it to the frontend map later.

**Do not modify `Customer_Orders`, `suppliers`, or `Alternative_Suppliers` schemas.** Everything
above joins in from a new table — zero risk to existing working queries.

---

## Part 2 — New Operator: "Demand Consolidation Optimizer"

Built on Auto, same no-code pattern as the existing 5 Round 2 Operators (see
`TEAMMATE_BRIEF.md` for the exact platform workflow — describe in plain English, approve the
generated plan, test, get a printed JSON result).

**What it does:** looks at open `Customer_Orders` for the same `item_number`, checks whether any
single order is below the matching `Alternative_Suppliers.moq` for that item, and if so searches
for a compatible second (or third) order to combine with — using a two-stage process, not a single
weighted score up front.

**Stage 1 — hard constraints** (eliminate infeasible combinations first):
- same `item_number`
- both orders `status = 'open'`
- `promised_date`s within a compatible window of each other (use 5 days as the default threshold)
- combined `qty` of the candidate group ≥ the chosen supplier's `moq` for that item

**Stage 2 — optimization** (score the surviving valid combinations):
- total transport cost, estimated from `Geo_Locations` distance (supplier's country centroid →
  each site's city) — do **not** just pick the nearest site
- total procurement cost = combined `qty` × `Alternative_Suppliers.price` for that
  item/supplier
- customer priority mix across the combined orders (critical/high/medium/low)
- do not use revenue in the score — `Customer_Orders` has no sale price, so don't invent one;
  score on cost minimized + priority protected instead, and say so plainly in the printed
  `reason` field so nobody mistakes it for a fabricated revenue figure

**Auto operator prompt** (paste into Auto, name it `Demand Consolidation Optimizer`):

```
Look at all open orders in the Customer_Orders table in our Supabase database, along with
Alternative_Suppliers and Geo_Locations — also in Supabase. Use the Supabase integration for
this, not Oracle or any other database.

Group open orders by item_number. For any item_number where a single order's qty is less than
the matching supplier's moq in Alternative_Suppliers for that item_number, look for one or more
other open orders of the same item_number whose promised_date is within 5 days of it, where the
combined qty meets or exceeds that supplier's moq.

If more than one valid combination exists, don't just pick the geographically closest site.
Estimate transport cost using the distance between the supplier's country (via Geo_Locations,
location_type='supplier_country') and each site's city (via Geo_Locations,
location_type='construction_site', matched on the customer name), add that to the material cost
(combined qty × the supplier's price for that item), and prefer the combination with the lower
total cost — unless a candidate order has 'critical' priority, in which case prefer protecting
that order even if it costs more, and say so in your reason.

Do not invent a sale price or revenue figure — Customer_Orders has no price field, so base your
decision on cost minimized and customer priority protected, not profit.

Print your decision in this exact JSON format (don't send it anywhere, just print/output it so
I can copy it):
{
  "domain": "procurement",
  "entity_type": "consolidation_decision",
  "entity_data": {
    "item_number": "<the item number>",
    "supplier_id": "<the chosen supplier ID>",
    "consolidated_order_ids": ["<order id>", "<order id>", "..."],
    "combined_qty": <number>,
    "supplier_moq": <number>,
    "total_procurement_cost": <number>,
    "total_transport_cost": <number>,
    "customer_priority": "<the highest priority among the combined orders>",
    "net_cost_avoided": <number, vs. each site ordering alone or expediting separately>,
    "reason": "<why this combination over any other valid one — mention what you didn't pick and why>"
  },
  "source_agent": "demand-consolidation-optimizer"
}
```

**Why the field names matter:** `customer_priority` is deliberately the same field name
`Multi-Event Prioritizer` and `Inventory Reallocation Planner` already use. The existing
"Customer-Tier Priority Escalation" policy conditions on that field — reusing the name means this
new Operator's output is gated by an *existing* policy with zero policy changes. Don't rename it.

---

## Part 3 — New Operator: "Recovery Planner"

**What it does:** given a disrupted supplier/item, generates several named recovery plans (not
just one recommendation) and picks the best — this was explicitly called out as a gap in the last
audit (`NOT_YET_COMPLETE.md`, "What you can add" section: Recovery Planner wasn't built). It also
directly implements the brief's requirement to escalate when "two recovery plans have similar
outcomes."

It's self-contained — it reads the same Supabase tables the existing Operators already read
(`contracts`, `Alternative_Suppliers`, `inventory_positions`, `Penalties`, `Geo_Locations`) rather
than trying to call other Auto Operators, since Operators here are independent single-responsibility
workers, not a call chain.

**Auto operator prompt** (paste into Auto, name it `Recovery Planner`):

```
When given a supplier ID and item number that's disrupted, generate several possible recovery
plans using our Supabase database (use the Supabase integration, not Oracle or any other
database):

Plan A - Alternative Supplier: look up Alternative_Suppliers for this item_number, calculate
cost = qty needed x price.
Plan B - Inventory Reallocation: check inventory_positions across other warehouse nodes for
available stock (on_hand_qty minus committed_qty) of this item, calculate transport cost via
Geo_Locations distance to move it.
Plan C - Expedite: look up the contract for this supplier in the contracts table and any related
Penalties entry, calculate expedite cost and whether it needs VP sign-off (same logic the
Cost & Clause Evaluator uses).
Plan D - Consolidate with another order: check whether this shortage could be solved by
combining with another open Customer_Orders demand for the same item to hit a supplier's moq.

Only include a plan if it's actually feasible with the data available - don't invent numbers for
a plan you don't have data to support, just leave it out.

Pick the lowest-cost feasible plan as your recommendation, unless the customer order affected has
'critical' priority, in which case weigh that more heavily even if it costs more.

If your top two plans are within 10% of each other in cost, set plans_are_close to true - a
human should choose between near-equal options rather than Auto deciding silently.

Print your evaluation in this exact JSON format (don't send it anywhere, just print/output it so
I can copy it):
{
  "domain": "procurement",
  "entity_type": "recovery_plan",
  "entity_data": {
    "supplier_id": "<the supplier ID>",
    "item_number": "<the item number>",
    "recommended_plan": "<e.g. 'Plan A: Alternative Supplier'>",
    "expedite_cost": <the cost of the recommended plan as a number, 0 if it's not an expedite>,
    "requires_vp_signoff": <true or false>,
    "customer_priority": "<the affected order's priority level>",
    "net_savings": <estimated savings vs. doing nothing, as a number>,
    "plans_are_close": <true or false>,
    "plans_considered": [
      {"name": "<plan name>", "cost": <number>, "summary": "<one line>"}
    ],
    "reason": "<why the recommended plan beats the others>"
  },
  "source_agent": "recovery-planner"
}
```

**Why the field names matter (same trick as Part 2):** `expedite_cost`, `requires_vp_signoff`, and
`customer_priority` are the exact field names `Cost & Clause Evaluator` already uses. That means
Recovery Planner's output is automatically gated by the existing "Expedite Spend Limit",
"Contract Escalation Clause Block", and "Customer-Tier Priority Escalation" policies — no new
policy required for the core gating behavior. Don't rename these fields.

---

## Part 4 — Backend wiring (required for Parts 2 & 3 to do anything)

1. **Relay path** — same as the other 5 Operators (see `TEAMMATE_BRIEF.md`'s "For me, not you"
   section): confirm whether the backend now has a reachable public URL. If yes, have these two
   new Operators `POST` directly to `/api/ai/policies/evaluate` (both print `domain`/`entity_type`
   JSON, so they always go through that endpoint, never `/api/workbench` directly — see
   `plans_are_close` handling below for the one exception). If backend is still localhost-only,
   keep the manual copy-paste relay flow.

2. **`plans_are_close` escalation** — `policy_engine.evaluate()` doesn't know about
   `plans_are_close`, it only evaluates configured policy conditions. Add one small explicit check
   in the router (`app/routers/ai.py` or wherever `/api/ai/policies/evaluate` is handled) or as a
   new structured policy: **if `entity_data.plans_are_close == true`, force the verdict to
   `requires_review` regardless of what the structured policies say** — this directly implements
   the brief's "two recovery plans have similar outcomes → escalate" requirement. Simplest
   implementation: a 6th seeded policy, domain=`procurement`, condition
   `{"field": "plans_are_close", "op": "eq", "value": true}`, action `require_approval` — no code
   change needed at all if you go this route, just add it to `scripts/seed_db.py` alongside the
   existing 4 policies. Prefer this over a router-level special case — keeps every policy editable
   without code, consistent with the mandatory requirement.

3. **`_OPERATOR_REGISTRY` in `app/services/ai_manager.py`** — add both new Operators (their Auto
   `rootWorkflowId`s, once created) so the AI Manager chat can re-trigger them by name, same as the
   existing 5:
   ```python
   "demand consolidation optimizer": {
       "workflow_id": "<from Auto once created>",
       "required_inputs": [],
   },
   "recovery planner": {
       "workflow_id": "<from Auto once created>",
       "required_inputs": ["supplier_id", "item_number"],
   },
   ```
   Also add both names to the `trigger_operator` list in `_FREEFORM_SYSTEM_PROMPT` in the same
   file — currently hardcodes the 5 existing names in that prompt string, easy to miss.

4. **Seed the `Geo_Locations` table** — extend `scripts/seed_db.py` (or add a sibling script) the
   same idempotent way the other 14 tables are seeded.

---

## Part 4b — Wire into Master Orchestrator (do not skip this)

**Why this section exists:** the first draft of this spec only wired these two new Operators to be
triggered by a human via AI Manager chat (`_OPERATOR_REGISTRY`). That's necessary but not
sufficient — it means the Master Orchestrator itself never delegates to them, which is exactly the
pattern `NOT_YET_COMPLETE.md` (Section 2) already flagged as a real, scored gap for the *existing*
5 Round 2 Operators: "the Orchestrator never waits for or collects results from the 5 Round 2
Operators... they self-report straight to the backend instead." Wiring the two new Operators the
same way would repeat that deduction instead of fixing it. Don't build it that way.

This is an Auto-side workflow edit, not new backend code — your teammate already knows the
mechanic, since calling an Operator by plain-language name via Auto's "Select a subworkflow" search
is confirmed working today for the existing Operators.

**Minimum bar — real fan-out (required):**
Open the Master Orchestrator workflow in Auto and add two branch steps to its existing
branching logic:
- If an incoming disruption notice (or a `Customer_Orders` review) indicates a quantity below a
  supplier's MOQ for that item → call `Demand Consolidation Optimizer` as a subworkflow.
- If an incoming disruption notice indicates a supplier/item can't be fulfilled as-is (the same
  trigger condition that currently might reach `Cost & Clause Evaluator`) → call
  `Recovery Planner` as a subworkflow, feeding it the `supplier_id`/`item_number` from the notice.

This alone turns "two more Operators that exist" into "two more Operators the Orchestrator
actually delegates to" — which is what Section 2 of the brief literally asks for ("Orchestrator
coordinating at least five distinct Operators... parallel, branching, or stateful behavior").

**Stretch — real fan-in (only if Parts 1-4b above are done and tested with time to spare):**
Have the Master Orchestrator actually wait for `Recovery Planner`'s subworkflow result (Auto
supports this — a subworkflow call can be blocking) and branch on it: only proceed to the
Orchestrator's own contract-checking / Slack-approval step if Recovery Planner found a feasible
plan; if it found none, the Orchestrator should raise its own escalation rather than silently
stopping. This is the literal fix for the "fan-out without fan-in" line in the last audit — worth
doing for this one path even if it's not worth retrofitting onto all 5 existing Operators tonight.

**What NOT to do under time pressure:** don't quietly drop this section and ship the two new
Operators as chat-only-triggered. That's a strictly worse outcome than not building them at all —
it would put a *second* instance of the exact gap already on the record in front of judges, in a
part of the system built *after* that gap was known.

---

## Part 5 — Frontend labels (cut first if behind schedule)

Cheap, cosmetic reframing — do only if Parts 1-4 are done and tested with time to spare:
- Command Center copy: "Customer" → "Construction Site" where it's just a label, not a schema
  change (e.g. Workbench card headers, Insights text).
- No new pages, no map UI in this phase — that's explicitly Phase 2, only if Phase 1 finishes
  early.

---

## Part 6 — Testing checklist (do not skip)

```bash
docker compose exec backend pytest tests/ -q       # must still be all passing, no regressions
```

Manually verify, in this order:
1. `Geo_Locations` table exists in Supabase with the expected ~18 rows (6 warehouses + 5 supplier
   countries + 7 construction sites), confirmed via Supabase Studio directly, not assumed.
2. Run `Demand Consolidation Optimizer` against a real open pair of `SKU-CEM-101` (or any item)
   orders below a supplier's MOQ — confirm it prints valid JSON matching the contract above, and
   that the `reason` field actually explains a trade-off (not just "closest site").
3. Feed that printed JSON into `POST /api/ai/policies/evaluate` — confirm a verdict comes back and
   a `trigger_count` increments on the matched policy (should be "Customer-Tier Priority
   Escalation" if a critical/high order was involved).
4. Run `Recovery Planner` against a real disrupted supplier/item pair — confirm it prints valid
   JSON, and specifically test one case where costs are close enough to set `plans_are_close: true`
   — confirm that one routes to the Workbench (via the new 6th policy) rather than auto-approving.
5. Ask the AI Manager chat "re-run the Recovery Planner for supplier X and item Y" — confirm it
   fires the right workflow ID, same live-verification pattern already used for the other 5
   Operators (see `NOT_YET_COMPLETE.md` Section 4).
6. **Trigger a real disruption notice through the Master Orchestrator itself** (not via the
   AI Manager's per-Operator re-trigger) and confirm in Auto's run log that it actually branched
   into `Demand Consolidation Optimizer` and/or `Recovery Planner` on its own — not just that
   they work when called directly. This is the step that proves Part 4b's fan-out is real and not
   just theoretical. If the stretch fan-in was attempted, confirm the Orchestrator's own next step
   genuinely waited on Recovery Planner's result rather than proceeding regardless.
7. `npm run build` in `frontend/` still succeeds if any frontend labels were touched.

If step 2 or 4 fail to produce a sensible decision on a record you didn't specifically prepare for
the demo, that's a real problem — the brief says explicitly "a judge may ask you to run a record
you did not prepare," so don't tune this against only the one demo pair.
