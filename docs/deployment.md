# Deploying VoiceFlow

VoiceFlow is one backend program (FastAPI), two background workers (reminders, maintenance), a PostgreSQL
database and a folder of static web files (the built frontend). Everything runs on hardware
you control; no paid or cloud AI service is used.

## 1. What you need

| Part | Minimum | Notes |
|---|---|---|
| Server | 4 CPU cores, 8 GB RAM | Speech recognition (Whisper `base.en` on ONNX Runtime) uses about 0.5 GB RAM and ~1.1 s per command on a 4-core laptop CPU. No GPU needed. |
| PostgreSQL | 15 or newer | Tested with 18. |
| Python | 3.11 | |
| Node.js | 20+ | Only to build the frontend. |
| HTTPS certificate | **required** | Browsers only allow the microphone on HTTPS pages (or `localhost`). |

## 2. One web address for both parts (important)

Serve the frontend and the API from the **same HTTPS address** through a reverse proxy
(Caddy, nginx or IIS):

```
https://voiceflow.yourcompany.example/        -> frontend/dist (static files, index.html fallback)
https://voiceflow.yourcompany.example/api/... -> http://127.0.0.1:8000 (the backend)
```

Why: sign-in uses a secure `HttpOnly` cookie limited to `/api` plus a CSRF header. One
address keeps the cookie first-party and avoids cross-site rules. Do not expose port 8000
directly; bind uvicorn to `127.0.0.1`.

Example Caddyfile (Caddy obtains the certificate automatically):

```
voiceflow.yourcompany.example {
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        root * /srv/voiceflow/frontend/dist
        try_files {path} /index.html
        file_server
    }
}
```

## 3. Configure

1. Create a database and an application user (not a superuser):
   `CREATE USER voiceflow PASSWORD '...'; CREATE DATABASE voiceflow OWNER voiceflow;`
2. Copy `.env.example` to `backend/.env` and set at least:
   - `VOICEFLOW_ENVIRONMENT=production` (turns on secure cookies and HSTS, turns off `/api/docs`)
   - `VOICEFLOW_DATABASE_URL=postgresql+psycopg://voiceflow:<password>@localhost:5432/voiceflow`
   - `VOICEFLOW_CORS_ORIGINS=["https://voiceflow.yourcompany.example"]`
   - `VOICEFLOW_DEFAULT_TIMEZONE` for your organisation.
3. Keep `backend/.env` readable only by the service account. Never commit it.
4. Speech model (~78 MB): set `VOICEFLOW_STT_MODEL_DIR` to a folder outside the code, e.g.
   `D:/ai-cache/models/whisper-base.en-onnx`, then run `python -m app.cli.fetch_stt_model`
   (resumes if the download breaks). `/api/v1/ready` shows `"speech": "ok"` when it is in place.
5. Windows with Smart App Control: dot-source `scripts/backend-env.ps1` before starting
   anything (it makes psycopg use PostgreSQL's own `libpq.dll`). See docs/decisions.md R1–R3.

## 4. Install and start

```powershell
# backend
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[voice]"
.venv\Scripts\python.exe -m alembic upgrade head          # create / update tables
.venv\Scripts\python.exe -m app.cli.fetch_stt_model        # speech model (once)

# frontend
cd ..\frontend
npm ci
npm run build                                               # -> frontend/dist

# run (as services; see below)
cd ..\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv\Scripts\python.exe -m app.workers.reminders           # second service
.venv\Scripts\python.exe -m app.workers.maintenance         # third service (data retention, hourly)
```

Run **one** backend process. Login and voice rate limits are kept in memory per process
(see Known limitations). The workers may safely run as one or more copies.

Run all three programs as services so they restart after a reboot or a crash:
- **Windows:** Task Scheduler ("At startup", "Restart on failure") or a service wrapper.
- **Linux:** three `systemd` units with `Restart=always`.

Create the first administrator and real users with your organisation's onboarding
process. **Do not run `scripts/seed-demo` in production**: demo data is clearly labelled
but is for trials only.

## 5. Backups

```powershell
.\scripts\backup-db.ps1                     # compressed dump, keeps the newest 14
.\scripts\restore-db.ps1 -File <dump>       # restores into voiceflow_restore_check (safe)
.\scripts\restore-db.ps1 -File <dump> -Target voiceflow -Force   # real restore (stop services first)
```

- Schedule `backup-db.ps1` daily (Task Scheduler) and copy `D:\voiceflow-backups` to a
  second machine or encrypted off-site storage; a backup on the same disk is not a backup.
- **Test a restore at least monthly** with the default (safe) target. The script prints the
  migration version and row counts; compare them with the live database.
- Backups contain task data, transcripts and audit history: store them with the same care
  as the database.

## 6. Upgrading

1. Back up (`backup-db.ps1`).
2. Stop the backend and worker.
3. Update the code, then `pip install -e ".[voice]"`, `alembic upgrade head`, `npm ci && npm run build`.
4. Start the services; check `GET /api/v1/health` and `/api/v1/ready`.
5. If something is wrong: stop, restore the backup, and start the previous version.
   Every migration also has a tested downgrade.

## 7. Monitoring

- `GET /api/v1/health` (process is up) and `GET /api/v1/ready` (database reachable and migrated):
  point your uptime monitor at the second one. It also reports `speech`
  (`ok` / `model_missing` / `not_installed` / `disabled`); speech does not affect "ready",
  because people can still type their commands.
- Logs are JSON lines with a `request_id`; every response carries `X-Request-ID` so a user's
  problem can be traced to the exact log lines and agent trace.
- Administrators can see how voice commands were understood under **Voice traces**.
- The reminders worker logs one line per pass with counts of reminders sent and held for quiet
  hours; the maintenance worker logs how many old records each pass deleted.

## 8. Data retention and privacy

- Audio is never stored; it is recognised in memory and discarded.
- The maintenance worker deletes: voice traces (what people said) after 30 days
  (`VOICEFLOW_RETENTION_TRACE_DAYS`), read notifications after 90 days
  (`VOICEFLOW_RETENTION_NOTIFICATION_DAYS`), ended sessions and expired voice confirmations
  after 1 day, stored replies for retried requests after 7 days.
- Never deleted automatically: tasks, projects, task history, extension requests, progress
  updates and the audit log.
- Tell employees that commands are recognised on your own server and that transcripts are kept
  for the trace period (CLAUDE.md: obtain consent and document processing).

## 9. Release checklist

Before each release, on the target machine:

1. `ruff check .` and `ruff format --check .` (backend); `npm run typecheck; npm run lint;
   npm test; npm run build` (frontend).
2. `pytest` with `VOICEFLOW_TEST_DATABASE_URL` set: unit, integration and `tests/security`
   all pass (none skipped except the opt-in real-model test).
3. `VOICEFLOW_RUN_STT_TESTS=1 pytest -k real_whisper` passes (real model, real recording).
4. `python -m evals.run_voice_eval --audio <recordings> --out <folder>`: clean intent accuracy
   ≥ 95% and **0 wrong change commands** on clean and 20 dB audio.
5. `backup-db.ps1`, then `restore-db.ps1` into the check database: counts match the live one.
6. `alembic downgrade -1` and `alembic upgrade head` on a copy work (every migration has a downgrade).
7. `/api/v1/ready` returns `ready` with `"speech": "ok"`; sign in as a manager and an employee,
   speak one read-only command and one change command (with "yes") in Chrome or Edge over HTTPS.
8. `.env`: `ENVIRONMENT=production`, real HTTPS origin in `CORS_ORIGINS`, no demo data.

## 10. Known limitations

- **Single backend process**: sign-in throttling and the voice rate limit live in memory, so
  they reset on restart and are not shared between processes. Run one backend process.
- **English only** (Whisper `base.en`), push-to-talk only: no wake word, no streaming
  recognition, no Tamil yet.
- **Loud background talk lowers accuracy**: 92% of commands right at 20 dB SNR, 88% at 10 dB,
  68% at 5 dB (people talking right next to the microphone). Errors are almost always "please
  say it again"; change commands are always read back and need "yes". Use a headset in noisy rooms.
- Evaluation recordings are synthetic Windows voices (US English). Real Indian-English speakers
  and real microphones have not been measured at scale; record a set from real users before
  relying on the numbers above.
- Spoken replies use the browser's built-in voices; their quality depends on the PC.
- Rule-based understanding: commands phrased very differently from the examples under
  "What can I say?" are not understood (by design: the system never guesses).
- On Windows with Smart App Control on, unsigned native libraries can be blocked at any time
  (it decides by online reputation). The default speech engine and database mode avoid them;
  check any new dependency after installing it.
- No email/SMS: notifications are in the app and spoken when the person is signed in.
