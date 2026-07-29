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

### Authorization is declarative, not code

- `app/public.map.json` — regex list of paths that skip auth entirely.
- `app/authz.map.json` — maps path regexes to role requirements (`ALL`/`ANY` role lists), including advanced claim-based rules (`claims`, `claims_lte`/`gte`, `claims_contains`, `claims_timediff_lte`, ownership/tenancy/step-up-auth patterns). `app/authz.py`'s `AuthzEngine` evaluates these; `app/security.py`'s `verify_access` is a single dependency applied to the whole `api_router` in `main.py` — it auto-decides simple role rules and "steps aside" (letting the endpoint call `authz_engine.check(request, user, context)` manually) when a rule needs runtime context (e.g. resource ownership).
- `/api/ai/chat`, `/api/ai/policies.*`, `/api/ai/insights.*` are **already present** in `authz.map.json` (role `ANY: ["admin","user"]"`) even though no backend router implements them yet — that's the gap this project exists to fill; new sub-paths under those prefixes are already authorized, no map edit needed.
- `AUTH_BYPASS=true` (the default in `.env`) skips all auth and injects a fixed dev user (`admin`+`user` roles) — this is why local dev doesn't need Keycloak configured.

### Frontend (`frontend/`) — Next.js 15 / React 19

- `src/app/` — route pages: `ai/` (Manager, Policies, Insights — currently demo data only), `admin/`, `workbench/`, `settings/`, `auth/`.
- `src/lib/api-client.ts` — the only way frontend code should call the backend. `apiClient.get/post/put/patch/delete(endpoint, ...)` auto-attaches the NextAuth session bearer token and prepends `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_BASE_PATH`; endpoint strings must include the `/api` prefix.
- `src/context/AIContext.tsx` — shared state for the AI Manager/Policies/Insights UI.
- Auth is NextAuth.js (`src/app/api/auth/[...nextauth]/route.ts`); backend validates the JWT via Keycloak unless `AUTH_BYPASS` is set.

### Database

PostgreSQL 15 via SQLAlchemy 2 + Alembic. Migrations live in `alembic/versions/`; always generate them with `make migrate-create MSG='...'` (autogenerate from model changes) rather than hand-writing, then review the generated file before `make migrate-up`.

### Request flow

`main.py` builds one `api_router` (prefix `{BASE_PATH}/api`, single global `verify_access` dependency) and mounts every resource router onto it — this is why individual routers don't declare auth dependencies for basic role checks, only for endpoints needing the authenticated user object itself (`Depends(get_current_user)`) or context-aware checks. `AuditMiddleware` (`app/middleware/`) wraps every request for automatic HTTP-level audit logging, separate from the manual `audit` service calls.
