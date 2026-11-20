import { useCallback, useEffect, useState } from 'react'

import { systemApi, type ReadinessResponse } from '../../services/api'

type Level = 'ok' | 'warn' | 'bad' | 'loading'

interface Check {
  label: string
  level: Level
  detail: string
}

const levelStyles: Record<Level, string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  bad: 'bg-bad',
  loading: 'bg-ink-muted animate-pulse',
}

const levelWords: Record<Level, string> = {
  ok: 'Healthy',
  warn: 'Needs attention',
  bad: 'Unavailable',
  loading: 'Checking',
}

function describeReadiness(r: ReadinessResponse): Check[] {
  const db: Check =
    r.database === 'ok'
      ? { label: 'Database', level: 'ok', detail: 'PostgreSQL is reachable.' }
      : r.database === 'not_configured'
        ? { label: 'Database', level: 'warn', detail: 'No database is configured yet.' }
        : { label: 'Database', level: 'bad', detail: 'PostgreSQL cannot be reached.' }
  const mig: Check =
    r.migrations === 'up_to_date'
      ? { label: 'Migrations', level: 'ok', detail: 'Schema is up to date.' }
      : r.migrations === 'pending'
        ? { label: 'Migrations', level: 'warn', detail: 'Database migrations need to be applied.' }
        : { label: 'Migrations', level: 'warn', detail: 'Unknown until the database is available.' }
  return [db, mig]
}

export function SystemStatus() {
  const [checks, setChecks] = useState<Check[]>([
    { label: 'Backend API', level: 'loading', detail: 'Contacting the server…' },
  ])

  const refresh = useCallback(async () => {
    try {
      await systemApi.health()
    } catch {
      setChecks([
        { label: 'Backend API', level: 'bad', detail: 'The backend server is not responding.' },
      ])
      return
    }
    const api: Check = { label: 'Backend API', level: 'ok', detail: 'The server is running.' }
    try {
      setChecks([api, ...describeReadiness(await systemApi.readiness())])
    } catch {
      setChecks([api, { label: 'Database', level: 'bad', detail: 'Readiness check failed.' }])
    }
  }, [])

  useEffect(() => {
    // Initial load; the async work sets state after the fetch resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const allOk = checks.every((c) => c.level === 'ok')

  return (
    <section aria-labelledby="system-status-title" className="w-full max-w-xl">
      <div className="rounded-2xl border border-line bg-panel p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="system-status-title" className="text-lg font-semibold">
              System status
            </h2>
            <p className="mt-1 text-sm text-ink-muted">
              {allOk ? 'Everything is ready.' : 'Checking the services VoiceFlow depends on.'}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Refresh
          </button>
        </div>

        <ul className="mt-5 divide-y divide-line" aria-live="polite">
          {checks.map((c) => (
            <li key={c.label} className="flex items-center gap-3 py-3">
              <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${levelStyles[c.level]}`} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{c.label}</p>
                <p className="text-sm text-ink-muted">{c.detail}</p>
              </div>
              <span className="text-xs font-medium text-ink-muted">{levelWords[c.level]}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
