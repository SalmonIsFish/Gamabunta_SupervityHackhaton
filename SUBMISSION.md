# AutoPilot Asia Round 2 — Submission Sheet

Everything needed to fill in the official submission form, plus how to recover the public URLs if
this machine loses connection or restarts before judging. Submission closes **9 August, 6:00 AM MYT**.

---

## Submission form — field by field

| Form field | Value | Status |
|---|---|---|
| **Team Name** | _(fill in)_ | ⬜ TODO — you know this, I don't |
| **Selected Challenge Track** | Operations / Procurement Exception Command Center | ✅ per `CLAUDE.md` |
| **Orchestrator URL** (link to your completed AI Employee) | _(the Master Orchestrator workflow's page on `auto.supervity.ai`)_ | ⬜ TODO — open your Auto workspace, find the Master Orchestrator workflow, copy its URL. It's the same workflow whose ID is `019f797b-4a41-7000-8eb3-89e6cb784c04` in `.env` |
| **Operator Links** | _(one link per Operator's page on `auto.supervity.ai`)_ | ⬜ TODO — you have 8 total: Master Orchestrator, Impact Mapper, Alternative Sourcer, plus the 5 Round 2 Operators (Cost & Clause Evaluator, Multi-Event Prioritizer, Inventory Reallocation Planner, Substitution Matcher, Port-Cutoff Monitor — confirm exact names against your Auto workspace) |
| **GitHub Repository Link** | https://github.com/SalmonIsFish/Gamabunta_SupervityHackhaton | ✅ confirmed from `git remote -v` — **make sure the repo is set to Public** on GitHub before submitting, private repos aren't accessible to judges |
| **LinkedIn Post URL** | _(post a photo from the live hackathon, tag @Supervity @Vijay Navaluri, hashtags: #Supervity #AIEmployees #AutoPilotHackathon #Malaysia #EnterpriseAI #nocodebuild)_ | ⬜ TODO — this has to be a real post from you |

**Running instance URLs** (for the "running instance" / demo-access part of the checklist, separate
from the form fields above):

- Dashboard: **https://relating-receiver-announces-claims.trycloudflare.com**
- API: **https://recreate-maturity-senior.ngrok-free.dev**
- API docs: **https://recreate-maturity-senior.ngrok-free.dev/api/docs**

These are also listed in `README.md` so judges can find them straight from the repo.

**Before you submit:**
- [ ] Confirm the GitHub repo visibility is **Public** (Settings → General → Danger Zone → Change visibility)
- [ ] Load the dashboard URL yourself on phone data (not this machine's wifi) right before submitting, one last time
- [ ] Fill in Team Name, Orchestrator URL, Operator Links, LinkedIn Post URL above

---

## Recovery: if this laptop loses connection or shuts down

The whole demo runs on **this physical machine** — Docker (backend + frontend + Postgres) plus two
tunnel processes (`ngrok.exe` for the backend, `cloudflared.exe` for the frontend). If the machine
loses power, loses internet, or those two processes get killed, the public URLs go down and — for
the frontend specifically — **the URL itself will change** on restart (it's an unreserved Cloudflare
quick tunnel). Here's how to bring it back.

### 1. Get Docker running again

```powershell
# Open Docker Desktop first if it's not running, then:
docker compose ps
# If containers aren't "healthy", from the repo root:
docker compose up -d
```

### 2. Restart the backend tunnel (ngrok) — URL stays the same

The backend has a **reserved** ngrok domain, so this always comes back as
`https://recreate-maturity-senior.ngrok-free.dev` — no `.env` changes needed.

```powershell
$ngrok = "C:\Users\G2\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
Start-Process -FilePath $ngrok -ArgumentList "http --domain=recreate-maturity-senior.ngrok-free.dev 8001" -WindowStyle Hidden
```

Verify: `curl -H "ngrok-skip-browser-warning: true" https://recreate-maturity-senior.ngrok-free.dev/api/health` should return `{"status":"ok"}`.

### 3. Restart the frontend tunnel (Cloudflare) — URL WILL CHANGE

```powershell
$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
Start-Process -FilePath $cf -ArgumentList "tunnel --url http://localhost:3001 --logfile `"$env:TEMP\cloudflared_frontend.log`"" -WindowStyle Hidden
Start-Sleep -Seconds 8
Get-Content "$env:TEMP\cloudflared_frontend.log" -Tail 10
```

Look for a line like:
```
|  https://<new-random-words>.trycloudflare.com  |
```
**That URL is different every time this process restarts** — copy it, you need it for the next step.

### 4. Update `.env` with the new frontend URL

Open `.env` in the repo root and replace every occurrence of the old
`relating-receiver-announces-claims.trycloudflare.com` with the **new** URL from step 3, in these
three lines:

```
FRONTEND_URL=https://<new-random-words>.trycloudflare.com
NEXTAUTH_URL=https://<new-random-words>.trycloudflare.com
```
(`NEXT_PUBLIC_API_URL` stays pointed at the ngrok backend URL — that one doesn't change.)

### 5. Rebuild the frontend (required — `NEXT_PUBLIC_*`/`NEXTAUTH_*` are baked in at build time)

```bash
docker compose up -d --build frontend
```

Wait for it to report healthy (`docker compose ps`), then reload the dashboard at the **new**
frontend URL and confirm it loads real data (not "Couldn't load live dashboard data").

### 6. Update the pinned links

- Update `README.md`'s Live Demo table and this file's "Running instance URLs" section with the new
  frontend URL.
- If you already submitted the form, most hackathon organizers let you edit the response before the
  deadline — re-check and update the running-instance link if so; otherwise flag it to the organizer
  directly.

### Avoiding this entirely

The only way the frontend URL is guaranteed not to change is if `cloudflared.exe` is never killed
and this machine never loses power/network before judging ends. Sleep/hibernate are already disabled
on this machine for that reason (`powercfg /change standby-timeout-ac 0`, etc.) — don't manually
sleep it, close the lid if that's configured to sleep, or reboot.
