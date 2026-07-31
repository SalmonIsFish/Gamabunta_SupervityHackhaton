# Next Steps — Round 2 Operations Track

Working punch list for the Procurement Exception Command Center build. Updated 2026-07-31 after
wiring Workbench, Data Manager, Policies, and Insights to the real backend (see
`C:\Users\G2\.claude\plans\check-first-what-we-ancient-twilight.md` for the design rationale, and
`CLAUDE.md`'s "Current Status" for what's actually built).

**Timeline:** remote build 3–7 Aug · offline build + code freeze 11:59PM 8 Aug at APU · Grand Finale
9 Aug. Judges score a pass/fail gate first, then Business output 30 / Architecture-on-Auto 20 /
Policies 20 / Insights 15 / Command Center & live demo 15, +10 bonus.

## Mandatory floor — current status

| Requirement | Status |
|---|---|
| Orchestrator + 5 distinct Operators on Auto | **2 of 5** — Master Orchestrator, Impact Mapper, Alternative Sourcer exist (built in Auto, exports were in `Operations_Case_Study/Round 1 Operator/` — see note below on where that folder went). Need 3+ more; see §2. |
| Command Center wired to live agent activity | **Done.** Workbench, Data Manager, Policies, and Insights pages all call the real backend — no `DEMO_*` data anywhere in the Command Center frontend anymore. |
| 3+ active AI Policies, no-code editable, logged | **Done.** 4 seeded active policies, editable live through the Policies UI (verified: edit/toggle/create/delete all round-trip through the real API), every evaluation audit-logged. |
| Live human loop via Workbench | **Done** on the Command Center side — list/detail/resolve fully wired and verified end-to-end. Still needs a **real** Operator to raise a real exception during the live demo (today's only WorkItem was a manually-curled test). |
| 3+ live integrations, 2 categories, healthy in Data Manager | **Done.** New Data Manager page shows Supabase (live health check, `system_of_record`), Supervity Auto (config check, `orchestration`), Slack + Outlook (honestly labeled `external` — configured in the Auto workspace, not visible to this backend, `channel`). |

## 1. Dataset handling — read this before touching `Operations_Case_Study/`

The dataset folder was accidentally committed and pushed to the public `origin` remote (commit
`52e7d32`, outside a Claude session) despite the Round 2 guide stating it "may not be
redistributed." Fixed by removing it from tracking and adding it to `.gitignore` — **the files are
still on your local disk**, just no longer version-controlled. Don't `git add -f` it back. If you
need to share it with a teammate, use a non-git channel.

## 2. Build the remaining Operators on Auto

Only Impact Mapper and Alternative Sourcer exist. Proposed additions (each has an `entity_data`
contract already matched to the seeded policies — see the plan file for exact field names):

- **Supplier Cascade Mapper** — walks `Supplier_Tiers` to find every tier-1 supplier a failed tier-2/3
  supplier takes down with it.
- **Multi-Event Prioritizer** — holds state across concurrently open disruptions; arbitrates when two
  compete for the same `Alternative_Suppliers` candidate or the same warehouse buffer stock.
- **Cost & Clause Evaluator** — joins `contracts`/`Penalties` to score an expedite against escalation
  clauses and net cost after penalties. POST its result to `/api/ai/policies/evaluate` with
  `domain="procurement"`, `entity_type="expedite_decision"` — this is what the "Expedite Spend Limit"
  and "Contract Escalation Clause Block" policies gate on.
- **Logistics / Port-Cutoff Monitor** — batch-flags `Shipments` past/near `port_cutoff` against
  `purchase_order_headers.need_by_date` (the "port strike" trap — many POs at once).
- **Inventory Reallocation Planner** — cross-warehouse stock moves protecting `Customer_Orders.priority`.

For each: build and test standalone as its own Auto workflow first, then wire it into the Master
Orchestrator's branching/fan-out logic. Route anything that isn't a clean auto-approve/require-approval
through `POST /api/workbench` (the new generic create endpoint — see §4) when it doesn't fit the
policy-conflict path: e.g. orphan FK data, low-confidence disruption notices (several real rows in
`disruption_notices.csv` have blank `severity`/`confidence`).

**At least one Operator needs to actually raise a real Workbench exception before the demo** —
right now the only WorkItem ever created was a manually-curled test, and the mandatory-floor "live
human loop" item needs a real one.

## 3. Wire `ai_manager._dispatch()` to Auto (once the rate limit resets)

Still just runs `policy_engine.evaluate()` directly. `SUPERVITY_AUTO_API_KEY`/`ORG_KEY`/`BASE_URL`/
`ORCHESTRATOR_WORKFLOW_ID` are all in `.env` and confirmed loaded. Per `auto.supervity.ai/docs/api-docs`:
`POST /api/v1/workflow-runs/execute` (multipart/form-data: `workflowId`, `inputs`, `envs`) against
`https://auto.supervity.ai` — same host as the dashboard. Auth needs three headers: `Authorization:
Bearer <key>`, `x-source: external`, `x-active-org: <org-key>`. Contract (`reply_text, extra_data`)
doesn't need to change — seam confirmed reusable as-is.

## 4. Known loose ends from this session's wiring work

- **`AIManager.tsx` chat session_id bug** — still doesn't thread `session_id` back on subsequent turns;
  every message gets a fresh UUID server-side. Unrelated to this session's work, still unfixed.
- **StructuredBuilder action-vocabulary mismatch** — the Structured Builder's `COMMON_ACTIONS` list
  (`flag_review`, `auto_reject`, `notify`, ...) doesn't exactly match `policy_engine.py`'s recognized
  action strings (`flag_for_review`, `require_approval`, `auto_approve`, ...). Not a correctness bug —
  unrecognized actions fail safely to the gating bucket — but it means a policy created with "Flag for
  Review" in the UI logs a "Unrecognized policy action" warning on every evaluation. Worth aligning the
  two vocabularies if there's time.
- **"Create with AI" tab and "Generate Rules with AI" button** call `/api/ai/policies/analyze-input`,
  `/check-conflicts`, `/translate` — none of these backend endpoints exist. This is the same deferred
  item CLAUDE.md already notes (needs `ANTHROPIC_API_KEY`, not yet in `.env`). Both fail visibly now
  (error state added instead of the previous silent no-op) but aren't functional. The **Structured
  Builder tab works fully** without any LLM dependency — that's the reliable no-code path for the demo.
- **Natural-language policy evaluation** (`Policy.policy_type = natural_language`) — same
  `ANTHROPIC_API_KEY` gap, DB/schema already support it.

## 5. Verify before the demo

```bash
docker compose exec backend pytest tests/ -q       # should be 14 passed
npm run build                                        # (in frontend/) production build must succeed
docker compose up -d --build backend frontend        # rebuild both if either was edited
```
Manually re-check: Workbench resolve flow, Policies edit/toggle/create/delete, Insights "Run Analysis"
+ dismiss, Data Manager shows Supabase healthy. All four were verified working end-to-end as of
2026-07-31 — re-verify after any further changes, especially once real Operators start hitting these
endpoints instead of curl/manual tests.
