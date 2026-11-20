# Decisions and measurements

Each entry: what was decided, why, and when. Newest last. Owner approval noted where given.

## 2026-11-20 — Product decisions (owner approved "go with recommendations")

| # | Decision |
|---|---|
| D1 | This laptop is for development only; a production server comes later. |
| D2 | Local PostgreSQL runs from portable binaries on D: (port 5433), not Docker Desktop (RAM). |
| D3 | Auto-assigned tasks are auto-accepted. An employee may decline with a reason; the task returns to the pool and that employee is skipped for it. |
| D4 | Workload = maximum active tasks per employee (WIP limit), default 1, configurable. |
| D5 | Completion evidence policies: `NONE`, `NOTE` (spoken), `LINK` (UI), `MANAGER_APPROVAL`, set per task in the backlog. |
| D6 | English only for v1; Tamil only after testing real speech samples. |
| D7 | One organization in v1, but `organization_id` on every row from day one. |
| D8 | Backlog import: CSV template + JSON; predecessors listed as `T1;T4`. |
| D9 | Local username/password accounts for v1; server-side sessions in HttpOnly cookies. |
| D10 | Whole project and all large files live on the D: drive (owner request). |
| D11 | **Voice-only operation** (owner request): every screen is reachable by voice ("open my tasks", "go to project board", "go back", "read this page"). Navigation commands change no data, so they run immediately without confirmation. Each screen has a spoken summary. Text is kept only as captions and recovery controls. The browser still needs one initial click for microphone and audio permission. |

## 2026-11-20 — Engineering decisions

| # | Decision | Why |
|---|---|---|
| E1 | Python **3.11** for the backend. | 3.14 lacks wheels for speech/ONNX packages. |
| E2 | **Synchronous** SQLAlchemy sessions + psycopg 3. | psycopg async cannot run on Windows' default ProactorEventLoop; FastAPI runs sync dependencies in a threadpool. |
| E3 | SQLAlchemy installed **without compiled extensions**. | Smart App Control blocks its unsigned Cython `.pyd` files. Pure-Python mode is official and fast enough at team scale. |
| E4 | Run Python tools as `python -m <tool>`. | Smart App Control blocks pip-generated `.exe` launchers (e.g. `uvicorn.exe`). |
| E5 | Frontend lint with **ESLint**, not oxlint. | Smart App Control blocks oxlint's native binary. |
| E6 | **TypeScript 6.0**, not 7.0. | typescript-eslint supports TS < 6.1; TS 7 is a new native rewrite. `strict: true` is set explicitly (TS 6 does not default it). |
| E7 | PostgreSQL **18.6** (EDB portable ZIP) in `D:\tools\pgsql`, data in `D:\tools\pgdata`, localhost only, SCRAM auth. | 18.x is mature; 19.0 is a fresh major. An unrelated PostgreSQL 18 service already uses port 5432 on C:; VoiceFlow does not touch it. |
| E8 | Postgres is started in its own hidden console. | Sharing a terminal's console makes new backends fail with `0xC0000142` after that terminal closes. |
| E9 | Docker Compose deferred. | Docker Desktop is installed but not running and needs ~2 GB RAM on an 8 GB laptop. Revisit for the production server. |

## 2026-11-20 — Phase 2: authentication and authorization

| # | Decision | Why |
|---|---|---|
| A1 | Passwords hashed with **argon2id** (argon2-cffi; loads under Smart App Control). Minimum 12 characters. Rehashed on login if parameters change. | Current recommended password hash. |
| A2 | **Server-side sessions**: random 256-bit token in an HttpOnly, SameSite=Lax cookie scoped to `/api`; only its SHA-256 is stored. 12 h absolute expiry, 2 h idle expiry. `Secure` is on automatically in production. | A database leak cannot be replayed as a login; revocation is immediate. |
| A3 | **CSRF**: per-session token returned by login and `/users/me`; required as `X-CSRF-Token` on every state-changing request. | Cookies are sent automatically, so writes need a second proof. |
| A4 | **Login throttling**: 5 failures per username or per IP within 15 minutes → HTTP 429. Unknown usernames still pay the hashing cost, and all failures use one generic message. | Slows password guessing without revealing which usernames exist. **In-memory, single process only** — must move to PostgreSQL/Redis before running several backend processes. |
| A5 | One role per user (`ADMIN`, `MANAGER`, `EMPLOYEE`) plus team memberships (`MEMBER` / `MANAGER`). A manager's scope is the set of teams where their membership is `MANAGER`. | Simple, explicit scope; matches CLAUDE.md section 3. |
| A6 | All access decisions are pure functions in `app/auth/policy.py`. Another organization's data returns **404** (existence not revealed); same organization but not permitted returns **403**. Every denial is written to `audit_events`. | One auditable place for permission rules. |
| A7 | Employees may see only their own profile; team rosters are visible to the team's managers and to administrators. | "Employees cannot access other employees' private data." Revisit if employees need a coworker directory. |
| A8 | Demo data comes only from `python -m app.cli.seed_demo`; the organization is flagged `is_demo` and the UI shows a "Demo data" banner. Passwords are random and written to a local file outside git. | CLAUDE.md: label demo data clearly; never put credentials in the repo. |

## 2026-11-20 — Phase 3: task core

| # | Decision | Why |
|---|---|---|
| T1 | The transition table lives in `app/services/tasks/lifecycle.py` and is the only source of allowed status changes. It matches CLAUDE.md section 9, plus: managers may **unassign** (ASSIGNED/ACCEPTED/BLOCKED → UNASSIGNED) and **reassign** from ASSIGNED, ACCEPTED or BLOCKED. **Cancel** is allowed only from DRAFT, UNASSIGNED or ASSIGNED, as in the spec. | One testable place; anything unlisted is refused (409 `invalid_transition`). |
| T2 | Actor rules: managers/admins create, assign, reassign, unassign, cancel, approve and reject. Only the **assignee** accepts, declines, starts, blocks and reports completion — a manager cannot claim an employee's work is done, and nobody can approve their own work. The orchestrator (SYSTEM) may only **assign**. | Accountability; matches CLAUDE.md section 3. |
| T3 | A reason is required for reassign, unassign, decline, block, reject and cancel. | Every exception path leaves an explanation in the history. |
| T4 | "Done" goes to `COMPLETED` only when the task needs no approval and no evidence; otherwise `PENDING_REVIEW`. NOTE and LINK evidence are checked and stored; links must be full http(s) URLs. | A spoken "done" is a claim, not proof. |
| T5 | **No double assignment**, three layers: (1) `SELECT … FOR UPDATE` on the task, (2) lock on the employee row while checking their workload, (3) a partial unique index allowing one open assignment per task, plus a CHECK that owner and status agree. Verified by concurrent-thread tests. | Correctness must not depend on a single mechanism. |
| T6 | **Workload limit** = tasks in ASSIGNED/ACCEPTED/IN_PROGRESS/BLOCKED, per user (`users.wip_limit`, default 1). A manager may override on manual assignment; the override is recorded in the audit event. | D4; PENDING_REVIEW work does not block new work. |
| T7 | **Idempotency-Key is required** on create, assign and reassign, and optional on other actions. Keys are per user; reusing a key for a different request is refused (422). The stored result is written in the same transaction as the change. | Safe retries over unreliable networks and voice turns. |
| T8 | Tasks use optimistic concurrency (`version`); edits must send the version they saw. Completed and cancelled tasks cannot be edited. | Prevents silently overwriting someone else's change. |
| T9 | `projects` exists only minimally (name, team, status). Backlog import, dependencies, skills and the automatic matching/ranking policy are Phase 4. | Smallest useful slice. |

## 2026-11-21 — Phase 4: projects, backlog and automatic assignment

| # | Decision | Why |
|---|---|---|
| P1 | Project lifecycle DRAFT → READY (backlog approved) → ACTIVE (orchestrator runs). Backlog import only into an empty DRAFT project; approval re-validates the stored graph. | One controlled entry point; no half-imported backlogs. |
| P2 | Backlog import is JSON (`{"tasks": [...]}`) with `key`, `title`, `priority` (required, never guessed), `depends_on`, `required_skills`, evidence policy, etc. Validation reports **every** problem at once: missing fields, duplicate keys, unknown or self dependencies, dependency loops (with the loop path), unknown skills. A skill nobody on the team has is a **warning** (it becomes a manager decision). A `/validate` dry run saves nothing. | Planners fix everything in one pass; nothing invented. CSV import can be layered on later. |
| P3 | **Readiness is computed**: a task is ready when UNASSIGNED and every predecessor is COMPLETED. Manual assignment is also refused while dependencies are unmet (`dependencies_unmet`, checked before workload). | High priority never overrides an unmet dependency. |
| P4 | **Deterministic planner** (`orchestrator/planner.py`): ready tasks ranked by priority → due date → age → key; a person qualifies with ALL required skills and spare workload; among them lowest load → fewest tasks in this project → longest since last assignment → id. People who declined a task are skipped for it. Only team MEMBERs are auto-assigned (not managers). Every decision carries a plain-language reason. | Explainable, testable, no LLM. |
| P5 | Outcomes: ASSIGN, NO_CAPACITY (qualified people are busy — waits quietly), NO_QUALIFIED (nobody has the skill or all declined — a NEEDS_DECISION notification, sent once while unread). | The manager is interrupted only when the project cannot progress alone. |
| P6 | The orchestrator runs on project start, on the manager's **"assign the ready tasks"** (`POST /projects/{id}/assign-ready`, with a dry-run `GET .../assignment-plan` to read back first), and automatically after a task is completed, approved, declined, unassigned or cancelled — for **every active project of that team**, because a freed person may be needed elsewhere. | Matches CLAUDE.md 4.3/4.8 and the owner's voice flow. |
| P7 | One evaluation per project at a time (PostgreSQL advisory lock); each assignment still goes through the task service's row locks and workload check. Re-running is idempotent. Verified by a two-thread race test. | No double assignment even if triggers overlap. |
| P8 | **Notifications** (in-app, stored): employee on assignment, approval, rejection; team managers on completion submitted (with the note), blocked, declined, needs decision, and a summary when the orchestrator assigns. Written in the same transaction as the change. Voice delivery reads these in Phase 6+. | "Employee says done → manager is told" is guaranteed by the data model, not by the UI. |
| P9 | Not yet: pause/resume/close project, CSV import, skill management UI/API (skills are set by seed/admin helper for now). | Smallest useful slice. |

## 2026-11-20 — Phase 0 measurements (this laptop)

Hardware: AMD Ryzen 3 7320U (4C/8T), ~8 GB RAM, integrated GPU (no CUDA), Windows 11 with
Smart App Control **on**, internet via mobile hotspot.

| Component | Result |
|---|---|
| STT: faster-whisper `base.en`, int8, CPU | 6.9 s of speech transcribed in **1.3 s** (5.2× real time); model load 1.5 s. Name "Subashini" correct with a team-name hint; "Assign" heard as "A signed" → read-back confirmation is essential and the rule parser must tolerate such errors. |
| TTS: Windows built-in voice (SAPI) | One confirmation sentence in **0.3 s**. Works; used by the browser fallback. |
| TTS: Piper 1.8.0 | **Blocked by Smart App Control** (`espeakbridge` DLL). Also GPL-3.0; the tested Lessac voice's dataset license needs checking before any commercial use. |
| LLM: Phi-4-mini Q4_K_M via Ollama (MIT) | **~8–9 s** per structured extraction (warm), ~20 s cold, ~7 tokens/s, 3.1 GB RAM (0.7 GB left free). **Wrong intent on 4/4 test sentences**, even with an intent-only schema. |
| Downloads | `ollama pull` and Hugging Face Xet fail on the hotspot (parallel connections + DNS). Single-stream `curl -C -` works (~1.5 MB/s). |

### Consequences

- **Intent understanding = deterministic rule-based parser first.** The LLM is optional, off
  by default on this laptop, and its output is always validated by the harness.
- **TTS in development = browser/Windows voice** behind the `TextToSpeechProvider` adapter.
  Piper/Kokoro may run on the future Linux server.
- **STT = faster-whisper `base.en`** behind the `SpeechToTextProvider` adapter, with VAD and
  a team-name hint.
- Every new native dependency must be checked against Smart App Control right after install.
