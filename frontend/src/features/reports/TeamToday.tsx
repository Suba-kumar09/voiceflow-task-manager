import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Avatar } from '../../components/ui/Avatar'
import { ErrorBox, Loading } from '../../components/ui/States'
import { reportsApi, type PersonLoad, type ReportTaskLine } from '../../services/api'

const LOAD: Record<PersonLoad['state'], { label: string; tone: string }> = {
  free: { label: 'Free', tone: 'bg-accent-soft text-accent-strong' },
  'has capacity': { label: 'Has room', tone: 'bg-accent-soft text-accent-strong' },
  'at limit': { label: 'At limit', tone: 'bg-[#2b2410] text-warn' },
  overloaded: { label: 'Overloaded', tone: 'bg-[#341818] text-bad' },
}

function due(iso: string | null, tz: string) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: tz,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

function TaskList({ title, items, tz, tone }: { title: string; items: ReportTaskLine[]; tz: string; tone: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-ink-strong">
        {title} <span className={`ml-1 ${items.length ? tone : 'text-ink-faint'}`}>{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-ink-faint">None.</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1.5">
          {items.slice(0, 5).map((t) => (
            <li key={t.id} className="flex justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-ink">
                {t.title} <span className="text-ink-faint">· {t.assignee ?? 'not assigned'}</span>
              </span>
              <span className={`shrink-0 text-xs ${tone}`}>{due(t.due_at, tz)}</span>
            </li>
          ))}
          {items.length > 5 && <li className="text-xs text-ink-faint">and {items.length - 5} more</li>}
        </ul>
      )}
    </div>
  )
}

/** Manager's at-a-glance team report. Same data as the spoken "today's summary". */
export function TeamToday() {
  const [period, setPeriod] = useState<'today' | 'week'>('today')
  const report = useQuery({
    queryKey: ['team-summary', period],
    queryFn: () => reportsApi.teamSummary(period),
    refetchInterval: 60_000,
  })
  const s = report.data

  return (
    <section aria-labelledby="team-today" className="rounded-2xl border border-line bg-panel p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="team-today" className="text-base font-semibold text-ink-strong">
          Team {period === 'today' ? 'today' : 'this week'}
        </h2>
        {s && <span className="text-xs text-ink-faint">{s.timezone} time</span>}
        <div role="group" aria-label="Period" className="ml-auto flex rounded-lg border border-control-line p-0.5">
          {(['today', 'week'] as const).map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${period === p ? 'bg-control text-ink-strong' : 'text-ink-muted hover:text-ink'}`}
            >
              {p === 'today' ? 'Today' : 'This week'}
            </button>
          ))}
        </div>
      </div>

      {report.isLoading && <Loading label="Loading team report…" />}
      {report.isError && <ErrorBox error={report.error} />}
      {s && (
        <div className="mt-4 flex flex-col gap-5">
          <dl className="grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-3">
            {(
              [
                ['Completed', s.completed, 'text-ok'],
                ['In progress', s.in_progress, 'text-ink-strong'],
                ['Awaiting review', s.awaiting_review, 'text-warn'],
                ['Blocked', s.blocked, 'text-bad'],
                ['Overdue', s.overdue.length, 'text-bad'],
              ] as const
            ).map(([label, value, tone]) => (
              <div key={label} className="rounded-xl bg-inset px-3 py-2.5">
                <dt className="text-xs text-ink-muted">{label}</dt>
                <dd className={`mt-0.5 text-2xl font-bold ${value > 0 ? tone : 'text-ink-faint'}`}>{value}</dd>
              </div>
            ))}
          </dl>
          <div className="grid gap-5 md:grid-cols-2">
            <TaskList title="Overdue" items={s.overdue} tz={s.timezone} tone="text-bad" />
            <TaskList title="Due in the next 24 hours" items={s.due_soon} tz={s.timezone} tone="text-warn" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-ink-strong">Workload</h3>
            {s.people.length === 0 ? (
              <p className="mt-1 text-sm text-ink-faint">No team members yet.</p>
            ) : (
              <ul className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-2">
                {s.people.map((x) => (
                  <li key={x.id} className="flex items-center gap-2.5 rounded-xl bg-inset px-3 py-2">
                    <Avatar name={x.name} seed={x.id} size={28} />
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">{x.name}</span>
                    <span className="text-xs text-ink-faint">
                      {x.active}/{x.limit}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${LOAD[x.state].tone}`}>{LOAD[x.state].label}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
