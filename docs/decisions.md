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
