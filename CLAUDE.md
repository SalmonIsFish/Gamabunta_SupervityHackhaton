# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **AutoPilot Template** — a FastAPI + Next.js starter kit for the AutoPilot Hackathon. The goal is to build an **AI Command Center**: a multi-agent "AI Employee" (1 Orchestrator + 5+ Operators) with policy enforcement, exception handling (Workbench), and generated insights, layered on top of this template.

**Critical constraint:** all agent orchestration (Orchestrator + Operators) MUST be built on `auto.supervity.ai` — never with LangChain/CrewAI/raw LLM loops. This repo (backend + frontend) is everything *around* that: Policies engine, Insights pipeline, Workbench, and the API/UI that talks to Auto. See `docs/hackathon-brief.md` and `docs/command-center-guide.md` for the full requirements before implementing AI Manager/Policies/Insights/Workbench features.

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

### Authorization is declarative, not code

- `app/public.map.json` — regex list of paths that skip auth entirely.
- `app/authz.map.json` — maps path regexes to role requirements (`ALL`/`ANY` role lists), including advanced claim-based rules (`claims`, `claims_lte`/`gte`, `claims_contains`, `claims_timediff_lte`, ownership/tenancy/step-up-auth patterns). `app/authz.py`'s `AuthzEngine` evaluates these; `app/security.py`'s `verify_access` is a single dependency applied to the whole `api_router` in `main.py` — it auto-decides simple role rules and "steps aside" (letting the endpoint call `authz_engine.check(request, user, context)` manually) when a rule needs runtime context (e.g. resource ownership).
- `/api/ai/chat.*`, `/api/ai/policies.*`, `/api/ai/insights.*`, `/api/workbench.*` are all present in `authz.map.json` (role `ANY: ["admin","user"]`) and backed by real routers now (see "Current Status" below) — new sub-paths under those prefixes are already authorized, no map edit needed. Note `/api/ai/chat` had to be changed from an exact match to `/api/ai/chat.*` to cover the `GET /chat/{session_id}` history endpoint — check a rule is actually a wildcard before assuming a new sub-path is covered.
- `AUTH_BYPASS=true` (the default in `.env`) skips all auth and injects a fixed dev user (`admin`+`user` roles) — this is why local dev doesn't need Keycloak configured.

### Frontend (`frontend/`) — Next.js 15 / React 19

- `src/app/` — route pages: `ai/` (Policies, Insights), `admin/`, `workbench/`, `settings/`, `auth/`. See "Current Status" below for which of these actually call the backend vs. still show demo data.
- `src/lib/api-client.ts` — the only way frontend code should call the backend. `apiClient.get/post/put/patch/delete(endpoint, ...)` auto-attaches the NextAuth session bearer token and prepends `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_BASE_PATH`; endpoint strings must include the `/api` prefix.
- `src/context/AIContext.tsx` — shared state for the AI Manager/Policies/Insights UI.
- Auth is NextAuth.js (`src/app/api/auth/[...nextauth]/route.ts`); backend validates the JWT via Keycloak unless `AUTH_BYPASS` is set.

### Database

PostgreSQL 15 via SQLAlchemy 2 + Alembic. Migrations live in `alembic/versions/`; always generate them with `make migrate-create MSG='...'` (autogenerate from model changes) rather than hand-writing, then review the generated file before `make migrate-up`.

### Request flow

`main.py` builds one `api_router` (prefix `{BASE_PATH}/api`, single global `verify_access` dependency) and mounts every resource router onto it — this is why individual routers don't declare auth dependencies for basic role checks, only for endpoints needing the authenticated user object itself (`Depends(get_current_user)`) or context-aware checks. `AuditMiddleware` (`app/middleware/`) wraps every request for automatic HTTP-level audit logging, separate from the manual `audit` service calls.

## Current Status (as of 2026-07-30)

**Done, tested, audit-logged:**
- **Workbench** — model/schema/router, `POST /api/workbench/{id}/resolve` flow, idempotency guard against re-resolving a terminal item.
- **Policies** — full CRUD + activate/deactivate lifecycle, plus structured-only evaluation at `POST /api/ai/policies/evaluate`. A conflict (permissive + gating policy both match) auto-creates a `WorkItem` (`exception_type=POLICY_CONFLICT`).
- **Insights** — statistical pattern/anomaly/recommendation generation over recent audit-log activity via `POST /api/ai/insights/generate`. No LLM involved.
- **AI Manager** — `POST /api/ai/chat` + `GET /api/ai/chat/{session_id}` history. Replies are templated strings driven by a `policy_engine.evaluate(...)` call, not an LLM.

All four have pytest coverage in `tests/` (`test_policy_engine.py`, `test_insight_engine.py`, `test_ai_manager.py`) and were verified live against the running Docker containers, not just unit-tested.

**Deliberately deferred, not forgotten:**
- Natural-language policy evaluation (`Policy.policy_type = natural_language`) — needs `ANTHROPIC_API_KEY`, not yet in `.env`. The DB/schema already support this policy type; only the evaluator is missing.
- Real LLM-based insight generation — current `insight_engine.py` is pure statistics (counts, rate comparisons). Swapping in an LLM pass is a separate follow-up, not a rewrite of the existing engine.

**Auto by Supervity integration — not started. Blocked on API token.**
`app/services/ai_manager.py`'s private `_dispatch(...)` function is the intended seam. Once the token arrives, that's where a real Auto API call replaces (or sits alongside) the direct `policy_engine.evaluate(...)` call — `handle_chat_message`'s public signature and the router don't need to change.

**Known pre-existing drift, safe to ignore:**
Every `alembic revision --autogenerate` run flags orphaned `items.status`/`items.priority` columns and two missing `audit_logs` indexes not reflected in current model files. Predates all four features above (confirmed via `git log`/model inspection before starting), not touched by any of them. Gets manually trimmed from each generated migration before applying — don't let autogenerate silently include it in a future migration.

**Unverified, check first when work resumes:**
Whether `AIManager.tsx` actually threads `session_id` back on subsequent messages — as of this writing it does not (grepped `frontend/src/` for `session_id`/`sessionId`, no match outside admin pages). If that's still true, every chat message gets a fresh UUID server-side and multi-turn conversation silently resets each turn. The backend test suite doesn't catch this because it explicitly passes a fixed `session_id` across turns.

**Frontend wiring status** (verified by grepping for `apiClient` usage):
- `frontend/src/components/ai/AIManager.tsx` (chat modal) — wired to `POST /api/ai/chat` and reads the response correctly (`ChatMessageResponse.response` was added specifically to match what this component expects). Session continuity issue above still applies.
- `frontend/src/app/ai/policies/page.tsx` and `frontend/src/app/ai/insights/page.tsx` — **not wired**, still render hardcoded `DEMO_*` data, no calls to the new `/api/ai/policies` or `/api/ai/insights` endpoints.
- `frontend/src/app/workbench/page.tsx` — **not wired**, still a static generic-tools shell (no data fetching at all, predates the real Workbench API).
