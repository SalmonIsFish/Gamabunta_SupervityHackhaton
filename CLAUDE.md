# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **AutoPilot Template** — a FastAPI + Next.js starter kit for the AutoPilot Hackathon. The goal is to build an **AI Command Center**: a multi-agent "AI Employee" (1 Orchestrator + 5+ Operators) with policy enforcement, exception handling (Workbench), and generated insights, layered on top of this template.

**Track: Operations / Procurement Exception Command Center (Round 2).** The assigned track's brief, participant guide, and dataset live under `Operations_Case_Study/` (gitignored — was briefly committed/pushed by accident, see "Dataset handling" below): `ProblemStatement__Procurement_Exception_Commander (2).pdf`, `Autopilot_Asia_Round2_Participant_Guide.pdf`, and `dataset/csv/` (14 tables, ~1,850 rows, Coupa-style procurement data — suppliers, contracts, purchase orders, inventory, disruption notices, and six Round-2 additions: Supplier_Tiers, Warehouses, Shipments, Customer_Orders, Alternative_Suppliers, Penalties). See `NEXT_STEPS.md` for the current build plan and what's next.

**Critical constraint:** all agent orchestration (Orchestrator + Operators) MUST be built on `auto.supervity.ai` — never with LangChain/CrewAI/raw LLM loops. This repo (backend + frontend) is everything *around* that: Policies engine, Insights pipeline, Workbench, and the API/UI that talks to Auto. See `docs/hackathon-brief.md` and `docs/command-center-guide.md` for the full requirements before implementing AI Manager/Policies/Insights/Workbench features.

## Before starting the next session — re-audit against the official brief

A lot changed in the 2026-08-07/08 session: `ai_manager._dispatch()` now really calls Auto's Master
Orchestrator (structured and free-text paths both), the dashboard is live-wired, Slack + Dropbox got
real health checks and genuine use (Dropbox mirrors the Workbench queue), the AI Manager grounds
free-text answers in real records via OpenRouter, all 5 Round 2 Operators' outputs got fed into the
Workbench/Policies, and the Master Orchestrator workflow itself was rewired on the Auto side (dropped
its Outlook dependency, fixed a casing bug, and needs a critical-path human-loop fix to route through
the Workbench instead of only Slack's native buttons — see the end of that session's conversation for
the exact prompt).

Before doing more feature work, paste the full Round 2 Problem Statement and Round 2 Participant Guide
content back into the conversation (or point Claude at `Operations_Case_Study/ProblemStatement__Procurement_Exception_Commander (2).pdf`
and `Operations_Case_Study/Autopilot_Asia_Round2_Participant_Guide.pdf`) and ask for a fresh, literal
line-by-line audit against: the 4-point qualification gate, the 5 Round 2 mandatory requirements
(§11.2), the 5-criterion rubric (§11.3), and the Do's/Don'ts list — to catch anything that regressed or
was never actually finished, before the Grand Finale.

## Commands

Backend and frontend run in Docker; the Makefile wraps `docker-compose exec` for most day-to-day tasks. On Windows without `make`, use the `docker compose exec backend ...` / `docker compose exec ...` equivalents shown in the README.

```bash
# Start / stop everything
make up                          # build + start all services (docker-compose up --build -d)
make down                         # stop all services
docker compose ps                 # verify postgres/backend/frontend are healthy

# Logs
make logs-be                      # tail backend logs
make logs-fe                      # tail frontend logs

# Backend tests (pytest, async via httpx.AsyncClient)
make test-be                      # docker-compose exec backend pytest
docker compose exec backend pytest tests/test_main.py::test_health_check   # single test

# Lint / format
make lint                         # flake8 (backend) + next lint (frontend)
make format                       # black + isort (backend) + prettier (frontend)

# Database migrations (Alembic)
make migrate-create MSG='add x table'   # alembic revision --autogenerate
make migrate-up                         # alembic upgrade head
make migrate-down                       # alembic downgrade -1
make migrate-history
make reset-db                           # wipe DB, re-run scripts/seed_db.py
```

Frontend-only commands (run inside `frontend/`, or via `npm --prefix frontend run <script>`): `dev`, `build`, `start`, `lint`, `format`.

Windows note: if `localhost:3001` gets an `ERR_CONNECTION_RESET`, it's a WSL2 IPv6 relay port conflict — use `.\scripts\start.ps1` instead of `docker compose up` directly, or run `wsl --shutdown` first.

## Architecture

### Backend (`app/`) — FastAPI

Layering is strict and file-per-resource: **models → schemas → routers**, each re-exported through an `__init__.py` barrel and wired together in `app/main.py`.

- `app/models/*.py` — SQLAlchemy models (`Base` from `app/core/database.py`). String `Enum` classes for categorical fields live alongside their model (see `models/audit.py`'s `AuditCategory`/`AuditSeverity`).
- `app/schemas/*.py` — Pydantic schemas mirroring each model file. Convention: `XCreate` for requests, `XResponse`/bare `X` for responses (`from_attributes = True` / `orm_mode = True` to validate from ORM objects), `XListResponse` for paginated results (`items/logs + total + page + page_size + total_pages`), and `{success, <id>, action, message}` for action-result responses.
- `app/routers/*.py` — one `APIRouter(prefix=..., tags=[...])` per resource. Simple CRUD (see `items.py`) uses plain sync functions with `Depends(get_db)` and `HTTPException(404)`. Richer routers (see `audit.py`) use async endpoints, explicit `Depends(get_current_user)`, a private `_apply_filters()` helper shared between list/export endpoints, and `Query(...)` descriptions for OpenAPI docs.
- New routers must be registered in `app/routers/__init__.py` and included via `api_router.include_router(...)` in `app/main.py`.
- `app/services/audit.py` — singleton `audit` service for business-event logging (fire-and-forget, never raises); call it for anything analogous to admin actions, policy decisions, or exception routing so it shows up in the audit trail.
- Four full model→schema→service→router implementations exist beyond the `item.py`/`audit.py` template examples — treat these as the reference pattern for new resources, not just `items.py`:
  - **Workbench** (`models/work_item.py`, `schemas/work_item.py`, `routers/workbench.py`) — human-in-the-loop exception queue; `WorkItemStatus`/`WorkItemPriority`/`WorkItemExceptionType`/`WorkItemResolution` enums alongside the model.
  - **Policies** (`models/policy.py`, `schemas/policy.py`, `routers/policies.py`, `services/policy_engine.py`) — CRUD + activate/deactivate lifecycle, plus a recursive structured-condition evaluator (`policy_engine.evaluate_condition`) and `policy_engine.evaluate(domain, entity_type, entity_data, source_agent, db)` that fetches ACTIVE policies, buckets matched actions into permissive/gating, and returns a `PolicyVerdict`.
  - **Insights** (`models/insight.py`, `schemas/insight.py`, `routers/insights.py`, `services/insight_engine.py`) — `Insight.extra_data` maps to a physical `metadata` DB column (Python attribute renamed to dodge SQLAlchemy's reserved `Base.metadata`, same trick as `AuditLog.extra_data`); `insight_engine.generate_insights(db, domain=None)` is pure statistics over audit-log activity, no LLM.
  - **AI Manager** (`models/chat.py`, `schemas/chat.py`, `routers/ai_manager.py`, `services/ai_manager.py`) — `handle_chat_message(...)` persists both sides of a chat turn; its private `_dispatch(...)` helper is the intended seam for swapping in a real Auto orchestrator call later without changing the public signature or router.
  - **Data Manager** (`routers/data_manager.py`, no model/schema files — not a DB-backed resource) — `GET /api/data-manager/status` computes a live registry at request time rather than storing one: a real health check for Supabase (`app/services/supabase_client.py`), env-presence checks for systems this backend holds credentials for (Supervity Auto), and honest `external`-status entries for systems it doesn't (Slack/Outlook, configured inside the Auto workspace). Pattern worth reusing for any future "is X actually connected" surface — don't fabricate a status for something you can't check.

### Authorization is declarative, not code

- `app/public.map.json` — regex list of paths that skip auth entirely.
- `app/authz.map.json` — maps path regexes to role requirements (`ALL`/`ANY` role lists), including advanced claim-based rules (`claims`, `claims_lte`/`gte`, `claims_contains`, `claims_timediff_lte`, ownership/tenancy/step-up-auth patterns). `app/authz.py`'s `AuthzEngine` evaluates these; `app/security.py`'s `verify_access` is a single dependency applied to the whole `api_router` in `main.py` — it auto-decides simple role rules and "steps aside" (letting the endpoint call `authz_engine.check(request, user, context)` manually) when a rule needs runtime context (e.g. resource ownership).
- `/api/ai/chat.*`, `/api/ai/policies.*`, `/api/ai/insights.*`, `/api/workbench.*`, `/api/data-manager.*` are all present in `authz.map.json` (role `ANY: ["admin","user"]`) and backed by real routers now (see "Current Status" below) — new sub-paths under those prefixes are already authorized, no map edit needed. Note `/api/ai/chat` had to be changed from an exact match to `/api/ai/chat.*` to cover the `GET /chat/{session_id}` history endpoint — check a rule is actually a wildcard before assuming a new sub-path is covered.
- `AUTH_BYPASS=true` (the default in `.env`) skips all auth and injects a fixed dev user (`admin`+`user` roles) — this is why local dev doesn't need Keycloak configured.

### Frontend (`frontend/`) — Next.js 15 / React 19

- `src/app/` — route pages: `ai/` (Policies, Insights), `admin/`, `workbench/`, `data-manager/`, `settings/`, `auth/`. All of `workbench/`, `data-manager/`, `ai/policies/`, `ai/insights/` are now wired to the real backend — see "Current Status" below.
- `src/lib/api-client.ts` — the only way frontend code should call the backend. `apiClient.get/post/put/patch/delete(endpoint, ...)` auto-attaches the NextAuth session bearer token and prepends `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_BASE_PATH`; endpoint strings must include the `/api` prefix. Note the update endpoint for policies is `PUT`, not `PATCH` — `apiClient` exposes both but the router only implements `PUT /api/ai/policies/{id}`.
- `src/lib/policy-adapter.ts` — translation layer between the Policies UI's richer `Policy`/`PolicyDSL` shape (`components/ai/policies/PolicyCard.tsx`) and the backend's `condition`/`actions` schema: coerces stringified condition values back to number/boolean (`StructuredBuilder` stores everything as text), converts `{all|any:[...]}` condition trees to/from flat UI condition lists, and syncs `is_active` through the real activate/deactivate endpoints since the backend has no such field on create/update. Any future Policy UI work should extend this file, not hand-roll another translation.
- Any component using `useSearchParams()` from `next/navigation` must be wrapped in `<Suspense>` or `next build` fails at prerender time (`/ai/policies` hit this — see its default export for the pattern: rename the page body to an inner component, wrap it in the default export).
- `src/context/AIContext.tsx` — shared state for the AI Manager chat modal only (open/close, message history, typing indicator). Policies/Insights/Workbench/Data Manager each manage their own fetch state locally — there's no shared data cache to update when wiring a new page to the backend.
- Auth is NextAuth.js (`src/app/api/auth/[...nextauth]/route.ts`); backend validates the JWT via Keycloak unless `AUTH_BYPASS` is set.
- For fast iteration without waiting on the Docker frontend rebuild (`docker-compose.yml`'s frontend service is hardcoded to `target: prod`, not the dev/hot-reload target `FRONTEND_TARGET` implies): create `frontend/.env.local` (gitignored, copy `.env.local.example` and change `NEXTAUTH_URL`/port to `3000`) and run `npm run dev` directly on the host — it talks to the same dockerized backend on `:8001`. Confirm the actual Docker prod build still works (`docker compose up -d --build frontend`) before considering anything done — that's what's judged.

### Database

PostgreSQL 15 via SQLAlchemy 2 + Alembic. Migrations live in `alembic/versions/`; always generate them with `make migrate-create MSG='...'` (autogenerate from model changes) rather than hand-writing, then review the generated file before `make migrate-up`.

### Request flow

`main.py` builds one `api_router` (prefix `{BASE_PATH}/api`, single global `verify_access` dependency) and mounts every resource router onto it — this is why individual routers don't declare auth dependencies for basic role checks, only for endpoints needing the authenticated user object itself (`Depends(get_current_user)`) or context-aware checks. `AuditMiddleware` (`app/middleware/`) wraps every request for automatic HTTP-level audit logging, separate from the manual `audit` service calls.

## Current Status (as of 2026-08-01)

**Backend — done, tested, audit-logged:**
- **Workbench** — model/schema/router, `POST /api/workbench/{id}/resolve` flow, idempotency guard against re-resolving a terminal item, plus `POST /api/workbench` (generic create) so an Operator/Orchestrator can raise an exception directly — `missing_data`, `low_confidence`, `high_stakes`, `novel_scenario` — not just the automatic `policy_conflict` path below.
- **Policies** — full CRUD + activate/deactivate lifecycle, structured evaluation at `POST /api/ai/policies/evaluate`. A conflict (permissive + gating policy both match) auto-creates a `WorkItem`. Model extended for multi-action support: `Policy.actions` (list of `{type,value,params}`) alongside the legacy singular `action`/`action_params` (kept for backward compat — `policy_engine._resolve_actions()` falls back to the legacy fields when `actions` is empty), plus `tags`/`entity_name`/`policy_scope`/`summary`/`refined_instruction`/`ai_instruction`/`source` for the richer frontend UI. A policy can now land in both the permissive and gating bucket if its actions span both (legitimate self-conflict → `WorkItem`). Four procurement policies seeded active by `scripts/seed_db.py` (idempotent, keyed by name) — Expedite Spend Limit, Contract Escalation Clause Block, Substitution Eligibility, Customer-Tier Priority Escalation.
- **Insights** — two families: the original audit-log statistics (pattern/anomaly/recommendation from `policy.evaluate` history — the "automation-opportunity insights" the brief describes), plus `_derive_operational_insights()` reading `app/services/supabase_client.py` (thin read-only httpx wrapper) directly against the live Supabase procurement dataset — delay patterns by supplier, POs trending at risk, demand anomalies (uses `on_hand_qty − committed_qty` as available stock, not raw on-hand — the dataset's phantom-inventory trap), single-source exposure, contracts expiring within 90 days. Degrades to zero extra insights if `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` aren't set. `generate_insights()` is `async`. **Table names read from Supabase are case-sensitive** — this project has `Inventory_positions` (capital I) while every other table is all-lowercase; a lowercase-only query 404s and `supabase_client.select()` swallows that into `[]` rather than raising, so a wrong-cased table name silently produces "zero insights" instead of an error. Caught and fixed once already (`2fb2480`) — worth double-checking exact casing against Supabase directly (not assuming from the CSV filename) before adding a query against any of the 6 Round 2 tables not yet queried by this codebase (`Supplier_Tiers`, `Warehouses`, `Shipments`, `Customer_Orders`, `Alternative_Suppliers`, `Penalties`).
- **Data Manager** (new) — `GET /api/data-manager/status`, live registry: Supabase gets a real health check, Supervity Auto reports configured/not_configured from env, Slack/Outlook honestly report `external` (configured in the Auto workspace, invisible to this backend).
- **AI Manager** — `POST /api/ai/chat` + `GET /api/ai/chat/{session_id}` history. Replies are templated strings driven by a `policy_engine.evaluate(...)` call, not an LLM.

14 tests in `tests/` (`test_policy_engine.py` incl. new multi-action cases, `test_insight_engine.py`, `test_ai_manager.py`) all pass. Note `scripts/` is baked into the backend image at build time, not bind-mounted like `app/`/`tests/` — after editing anything under `scripts/`, `docker compose up -d --build backend` before `docker compose exec backend python scripts/seed_db.py` will otherwise silently run the stale copy.

**Frontend — done, verified live against the real backend (not just unit-tested):**
- `frontend/src/app/workbench/page.tsx` — full rewrite from a static generic-tools shell to a real list/detail/resolve queue (`components/workbench/WorkItemCard.tsx`, `WorkItemDetailModal.tsx`).
- `frontend/src/app/data-manager/page.tsx` — new page (didn't exist before), `components/data-manager/IntegrationCard.tsx`, new sidebar nav entry.
- `frontend/src/app/ai/policies/page.tsx` — `DEMO_POLICIES` removed; list/create/edit/toggle/delete all call the real API through `frontend/src/lib/policy-adapter.ts`. Found and fixed a real bug in the process: `PolicyEditModal.tsx` was calling `PATCH` for updates, but the router only exposes `PUT` — every edit was silently failing before this.
- `frontend/src/app/ai/insights/page.tsx` — simplified from a 3-tab Summary/Patterns/Actions mockup (backed by demo-only `Pattern`/`ActionItem` shapes with no backend equivalent) to one filterable list of real `Insight` rows, with an expandable raw `extra_data` view for auditability. `PatternCluster.tsx`/`ActionCard.tsx` deleted (confirmed unused elsewhere).
- `frontend/src/components/ai/AIManager.tsx` (chat modal) — wired to `POST /api/ai/chat`, unchanged this session. Session-continuity issue below still applies.

**Dataset handling:** `Operations_Case_Study/` is gitignored. It was briefly committed and pushed to the public `origin` remote by accident (commit `52e7d32`, outside a Claude session) — removed from tracking (not from history; that would need a force-push, not done without explicit user sign-off). Files remain on local disk. Don't `git add -f` it back.

**Supabase is running stale/partial data as of this writing** — audited 2026-08-01: 6 of the 14 Round 2 tables (`Supplier_Tiers`, `Warehouses`, `Shipments`, `Customer_Orders`, `Alternative_Suppliers`, `Penalties`) don't exist in the project at all, and the 8 that do exist are sitting at roughly half the real Round 2 CSV row counts (e.g. `suppliers`: 50 live vs 73 in the CSV). This means every operational insight computed so far reflects a partial picture, not a bug in the computation itself — see `NEXT_STEPS.md` for the reseed plan (full delete + reload, not a patch; confirmed safe since nothing in this codebase or the Round 1 Auto workflows ever writes back into these tables).

**Deliberately deferred, not forgotten:**
- Natural-language policy evaluation (`Policy.policy_type = natural_language`), and the Policies page's "Create with AI"/"Generate Rules with AI" flows (`/api/ai/policies/analyze-input`, `/check-conflicts`, `/translate` — none of these backend endpoints exist) — all need `ANTHROPIC_API_KEY`, not yet in `.env`. These now fail with a visible error instead of silently doing nothing. The Structured Builder tab works fully without any LLM dependency.
- Real LLM-based insight generation — current `insight_engine.py` is pure statistics/live-queries, no LLM.

**Auto by Supervity integration — not started. Blocked on API token (workspace token exists but is rate-limited; waiting on a reset).**
`app/services/ai_manager.py`'s private `_dispatch(...)` function is the intended seam. `SUPERVITY_AUTO_API_KEY`/`ORG_KEY`/`BASE_URL`/`ORCHESTRATOR_WORKFLOW_ID` are all in `.env` and confirmed loaded — see `.env.example` for the real `POST /api/v1/workflow-runs/execute` contract (three auth headers, not just the bearer token). Still only 2 of the required 5+ Operators exist on Auto (Master Orchestrator, Impact Mapper, Alternative Sourcer) — see `NEXT_STEPS.md` for the proposed remaining 5.

**Known pre-existing drift, safe to ignore:**
Every `alembic revision --autogenerate` run flags orphaned `items.status`/`items.priority` columns and two missing `audit_logs` indexes not reflected in current model files. Predates every feature above, not touched by any of them (confirmed again while trimming the Policy-model-extension migration). Gets manually trimmed from each generated migration before applying — don't let autogenerate silently include it in a future migration.

**Unverified, check first when work resumes:**
Whether `AIManager.tsx` actually threads `session_id` back on subsequent messages — as of this writing it does not. Every chat message gets a fresh UUID server-side and multi-turn conversation silently resets each turn.
