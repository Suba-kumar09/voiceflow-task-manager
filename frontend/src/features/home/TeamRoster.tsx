import { useEffect, useState } from 'react'

import { ApiError, peopleApi, type EmployeeSummary } from '../../services/api'

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: EmployeeSummary[] }

export function TeamRoster({ teamId, teamName }: { teamId: string; teamName: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    peopleApi
      .teamEmployees(teamId)
      .then((page) => !cancelled && setLoad({ status: 'ready', items: page.items }))
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof ApiError && err.status === 403
            ? 'You do not have access to this team.'
            : 'Could not load this team. Try again shortly.'
        setLoad({ status: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [teamId])

  return (
    <section
      aria-labelledby={`team-${teamId}`}
      className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
    >
      <h3 id={`team-${teamId}`} className="text-base font-semibold">
        {teamName}
      </h3>

      {load.status === 'loading' && (
        <p className="mt-3 text-sm text-ink-muted" aria-live="polite">
          Loading team…
        </p>
      )}
      {load.status === 'error' && (
        <p role="alert" className="mt-3 text-sm text-bad">
          {load.message}
        </p>
      )}
      {load.status === 'ready' && load.items.length === 0 && (
        <p className="mt-3 text-sm text-ink-muted">No one is in this team yet.</p>
      )}
      {load.status === 'ready' && load.items.length > 0 && (
        <ul className="mt-3 divide-y divide-line">
          {load.items.map((e) => (
            <li key={e.id} className="flex items-center gap-3 py-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
              >
                {e.display_name.charAt(0)}
              </span>
              <span className="flex-1 text-sm font-medium">{e.display_name}</span>
              {e.membership_role === 'MANAGER' && (
                <span className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-muted">
                  Manager
                </span>
              )}
              {!e.is_active && (
                <span className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-muted">
                  Inactive
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
