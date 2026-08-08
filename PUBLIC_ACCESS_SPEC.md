# Public Access Spec — satisfying the submission checklist's deploy requirement

For Claude Code to implement directly. Written 2026-08-08. Solves: "Build runs from a clean clone"
and "All URLs (Auto workspace, repo, running instance) are publicly accessible" from the
organizer's submission checklist — currently unmet, confirmed by grep: no deploy config exists
anywhere in the repo, and `NEXT_STEPS.md` documents the backend as Docker Desktop on a personal
machine, localhost-only, by deliberate choice.

**Do this before any further feature work (including `PHASE1_CONSTRUCTION_PIVOT_SPEC.md`).** This
is a mandatory checklist box, not a nice-to-have.

## Two options — recommendation: do A, not B, given tonight's constraints

**Option A — expose the existing local stack via a tunnel.** Fast (~20-30 min), and most of the
plumbing already exists in this codebase for exactly this (see `.env.example`'s
`PUBLIC_BACKEND_URL` — already wired into `supervity_auto_client.py`). Keeps every bit of demo
state already built up locally (the resolved Workbench item, audit history, seeded policies,
everything the last audit verified working) — nothing to migrate.

**Option B — real hosted deploy (Railway/Render).** More robust long-term (survives the laptop
being off), but means standing up a fresh empty Postgres and re-creating all the local demo state
(seeded policies are idempotent and fine; the already-resolved Workbench item and audit history
are not — they'd need a `pg_dump`/restore under time pressure, or to be re-created by hand). More
moving parts, more that can go wrong before 6AM.

**Recommendation: do Option A now.** It satisfies "running instance judges can reach live" and
"publicly accessible URL" literally, using the exact stack that's already tested and demoed
against. Only fall back to Option B if the laptop genuinely cannot stay on/connected through
whenever judges will check (confirm this with the organizer if unsure — if it's a live demo slot
rather than asynchronous browsing, Option A is enough).

---

## Option A — tunnel setup (do this)

**1. Get two public URLs** — one for the backend (currently `127.0.0.1:8001`), one for the
frontend (currently `127.0.0.1:3001`). Use Cloudflare Tunnel or ngrok, whichever you can set up
faster — but use a **named/reserved** subdomain for each, not a random quick-tunnel URL. A random
one changes every restart and silently breaks CORS/API calls until every URL is manually
re-pointed — exactly the failure mode `.env.example`'s own comment on `PUBLIC_BACKEND_URL` already
warns about. ngrok's free tier includes one reserved static domain per account; Cloudflare Tunnel's
named tunnels are free and stable if you'd rather use that.

```bash
# example with ngrok (two separate reserved domains needed, or two separate tunnel processes)
ngrok http --domain=<your-reserved-backend-domain>.ngrok-free.app 8001
ngrok http --domain=<your-reserved-frontend-domain>.ngrok-free.app 3001
```

Run both in a way that survives you closing the terminal (`tmux`/`screen`, or run as a background
service) — and disable sleep/screen-lock on the machine for the duration judges might check.

**2. Update `.env`** with the real tunnel URLs:

```
FRONTEND_URL=https://<your-frontend-domain>
PUBLIC_BACKEND_URL=https://<your-backend-domain>
NEXT_PUBLIC_API_URL=https://<your-backend-domain>
NEXTAUTH_URL=https://<your-frontend-domain>
NEXTAUTH_SECRET=<generate a real one — currently blank in .env.example, see the comment there for the openssl/PowerShell one-liner>
```

**3. Rebuild the frontend, restart the backend.** This distinction matters and is easy to get
wrong:
- `NEXT_PUBLIC_API_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET` are all passed as Docker **build args**
  in `docker-compose.yml` (see the `frontend.build.args` block) — Next.js inlines
  `NEXT_PUBLIC_*` vars at build time, not runtime. Changing `.env` alone does nothing until you
  rebuild: `docker compose up -d --build frontend`. If you skip the rebuild, the deployed frontend
  will silently keep calling `localhost:8001` from a judge's browser, which can't reach it, and
  the dashboard will just look broken with no obvious error.
- `FRONTEND_URL` (backend's CORS allow-list, read via `os.getenv` in `app/main.py`) and
  `PUBLIC_BACKEND_URL` (read at request time in `supervity_auto_client.py`) are both runtime env
  vars — a restart is enough, no rebuild needed: `docker compose up -d backend`.

**4. Verify from a network that isn't your own** — phone on cellular data, not the same wifi.
Load the frontend tunnel URL, confirm the dashboard loads and pulls real data (not a CORS error in
the browser console, which is the #1 symptom of step 2/3 being incomplete or the rebuild being
skipped).

**5. Bonus, not required for the checklist:** once `PUBLIC_BACKEND_URL` is real,
`supervity_auto_client.py`'s `_build_envs()` automatically forwards it to the Auto Master
Orchestrator as `POLICY_API_URL` on every run. That means the 5 existing Round 2 Operators
*could* stop relying on the manual copy-paste relay (`TEAMMATE_BRIEF.md`'s "print, don't send"
pattern) and POST their results directly — but only if each Operator's own Auto workflow is
edited to add that POST step, since they were originally built to just print. That's an Auto-side
edit, not a backend change, and it's optional — the manual relay during a live demo isn't itself
disqualifying, it's just weaker than full automation and was already flagged as a known limitation
in `NOT_YET_COMPLETE.md`. Only pursue this if Parts above are done with time to spare.

---

## Option B — hosted deploy (only if Option A won't work for your situation)

Railway is the fastest fit for this shape (3 services + managed Postgres, deploys straight from
the GitHub repo). Condensed steps if you go this route:

1. New Railway project from the GitHub repo → add a Postgres plugin (gives you a `DATABASE_URL`
   automatically) → add a service for the backend (`Dockerfile` at repo root) → add a service for
   the frontend (`frontend/Dockerfile`, target `prod`).
2. **Order matters** because of the same build-time-vs-runtime split as Option A: deploy the
   backend first to get its Railway-generated domain, then set the frontend's
   `NEXT_PUBLIC_API_URL` build variable to that domain and deploy the frontend, then go back and
   set the backend's `FRONTEND_URL` to the frontend's domain and redeploy the backend once more.
   Railway's build-time vs. runtime variable distinction is a separate setting per service —
   confirm `NEXT_PUBLIC_API_URL`/`NEXTAUTH_URL`/`NEXTAUTH_SECRET` are set as **build** variables
   on the frontend service, not just runtime ones, or the same silent-localhost-call bug from
   Option A step 3 happens here too.
3. Migrations run automatically — `start_gunicorn.sh` already runs `alembic upgrade head` on every
   production boot, no extra step needed.
4. Re-seed: `docker compose exec` doesn't apply to a hosted service — use Railway's shell/CLI to
   run `python scripts/seed_db.py` once against the new empty database (gets you the 4+ seeded
   policies back). The already-resolved Workbench item and prior audit history will **not**
   transfer automatically — either accept a fresh start on those (fine if you re-trigger one real
   Operator exception and resolve it again post-deploy) or `pg_dump` the local DB and restore it
   into Railway's Postgres if you want to preserve the exact history already verified.
5. Set `PUBLIC_BACKEND_URL` on the backend service to its own Railway domain (same reasoning as
   Option A step 5).
6. Supabase (the operational procurement dataset) and Slack/Dropbox are already cloud services —
   nothing changes there regardless of which option you pick.

---

## Verification (do not skip)

- [ ] Frontend URL loads from a network you don't control (phone on cellular), not just localhost
- [ ] Dashboard shows real data, not a CORS error or blank page
- [ ] `<backend-url>/api/docs` loads and a live request against it (e.g. `GET /api/health`)
      succeeds
- [ ] AI Manager chat in the deployed frontend gets a real reply (proves backend + OpenRouter +
      CORS are all correctly wired end-to-end, not just individually reachable)
- [ ] Both URLs are stable — restart your machine/containers once and confirm the same URLs still
      work, so you're not caught out by a URL changing right before judging
