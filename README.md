# VoiceFlow — Agentic Task Management

Voice-first task management: a manager starts a prepared project by voice, a deterministic
orchestrator assigns all eligible tasks, and employees receive and update work by voice.
`CLAUDE.md` is the product and engineering source of truth; `docs/decisions.md` records
decisions and measurements.

**Status:** Phase 4 — projects, backlog import + validation, dependencies, skills, the
deterministic orchestrator (automatic assignment) and notifications, on top of the task core
(Phase 3), sign-in/roles (Phase 2) and the foundation (Phase 1).

## Layout

```text
backend/    FastAPI app (Python 3.11), SQLAlchemy, Alembic, pytest
frontend/   Vite + React + TypeScript + Tailwind, Vitest
scripts/    Windows setup/run scripts for local development
docs/       Decisions and design notes
```

Large files live outside the repo on D: — `D:\tools\pgsql` (PostgreSQL), `D:\tools\pgdata`
(database files), `D:\ai-cache` (AI models and download caches).

## First-time setup (Windows)

```powershell
cd D:\voiceflow
.\scripts\setup-backend.ps1        # Python venv + dependencies
.\scripts\setup-dev-db.ps1         # PostgreSQL on localhost:5433, writes backend\.env
cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head; cd ..
cd frontend; npm install; cd ..

# Optional: clearly labelled DEMO organization and accounts (passwords go to the file, never git)
cd backend; .\.venv\Scripts\python.exe -m app.cli.seed_demo --credentials-file D:\tools\voiceflow-demo-logins.txt; cd ..
cd backend; .\.venv\Scripts\python.exe -m app.cli.seed_demo_tasks; cd ..   # a few [DEMO] tasks
cd backend; .\.venv\Scripts\python.exe -m app.cli.seed_demo_project; cd ..   # [DEMO] E-Commerce project, started
```

Requires Python 3.11 (`py -3.11`), Node 24+, and the portable PostgreSQL in `D:\tools\pgsql`.

> **Windows Smart App Control is on** on the development laptop. Always run Python tools as
> `python -m <tool>` (pip's `.exe` launchers are blocked). See `docs/decisions.md`.

## Run

```powershell
.\scripts\dev-db.ps1 start                                          # database
cd backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000   # API
cd frontend; npm run dev                                             # UI
```

- UI: http://localhost:5173 (sign in with a demo account from `D:\tools\voiceflow-demo-logins.txt`)
- API docs: http://localhost:8000/api/docs
- Health: `GET /api/v1/health` (process up) · Readiness: `GET /api/v1/ready` (DB + migrations)

## Checks

```powershell
# backend
cd backend
.\.venv\Scripts\python.exe -m pytest          # unit + integration (integration needs the DB)
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .

# frontend
cd frontend
npm run typecheck; npm run lint; npm test; npm run build
```
