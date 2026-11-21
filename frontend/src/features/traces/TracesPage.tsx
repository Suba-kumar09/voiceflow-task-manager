import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Card, Empty, ErrorBox, Loading } from '../../components/ui/States'
import { tracesApi, type TraceRow } from '../../services/api'
import { usePageSummary } from '../../voice/pageSummary'
import { timeAgo } from '../tasks/taskLabels'

function tone(outcome: string) {
  if (['ok', 'done', 'executed', 'navigated'].includes(outcome)) return 'text-ok'
  if (['denied', 'failed', 'error', 'rejected'].includes(outcome)) return 'text-bad'
  return 'text-warn' // asked for confirmation / clarification, cancelled, unknown
}

function Row({ t }: { t: TraceRow }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="py-3">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-start gap-3 text-left">
        <span className="w-20 shrink-0 text-xs text-ink-faint">{timeAgo(t.at)}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-ink-strong">“{t.transcript ?? '—'}”</span>
          <span className="mt-0.5 block text-xs text-ink-muted">
            {t.user} · {t.channel} · {t.intent ?? 'not understood'}
            {t.tool ? ` → ${t.tool}` : ''}
          </span>
        </span>
        <span className={`shrink-0 text-xs font-semibold ${tone(t.outcome)}`}>{t.outcome}</span>
        <span className="w-16 shrink-0 text-right text-xs text-ink-faint">{t.total_ms != null ? `${t.total_ms} ms` : ''}</span>
      </button>
      {open && (
        <div className="mt-3 flex flex-col gap-2 rounded-xl bg-inset p-3 text-xs sm:ml-23">
          {t.speech && (
            <p>
              <span className="font-semibold text-ink-muted">Replied: </span>
              <span className="text-ink">{t.speech}</span>
            </p>
          )}
          {t.error && <p className="text-bad">Error: {t.error}</p>}
          {t.stt_ms != null && <p className="text-ink-muted">Speech recognition: {t.stt_ms} ms</p>}
          {t.slots && Object.keys(t.slots).length > 0 && (
            <p className="text-ink-muted">
              Understood: <code className="break-all text-ink">{JSON.stringify(t.slots)}</code>
            </p>
          )}
          {t.steps && t.steps.length > 0 && (
            <ol className="list-decimal pl-5 text-ink-muted">
              {t.steps.map((s, i) => (
                <li key={i}>
                  <code className="break-all text-ink">{JSON.stringify(s)}</code>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  )
}

/** Administrators: how each voice command was understood and handled (agent traces). */
export function TracesPage() {
  const traces = useQuery({ queryKey: ['traces'], queryFn: tracesApi.list, refetchInterval: 15_000 })
  const list = traces.data ?? []
  usePageSummary(
    `Voice traces. ${list.length} recent voice commands.` +
      (list[0] ? ` The latest: ${list[0].user} said "${list[0].transcript ?? ''}".` : ''),
  )
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Voice traces</h1>
        <p className="mt-1 text-sm text-ink-muted">
          How each voice command was heard, understood and handled. Newest first. Select a row to see its steps.
        </p>
      </div>
      <Card className="py-1">
        {traces.isLoading && <Loading />}
        {traces.isError && <ErrorBox error={traces.error} />}
        {traces.isSuccess && list.length === 0 && (
          <div className="py-4">
            <Empty>No voice commands yet.</Empty>
          </div>
        )}
        <ul className="divide-y divide-line-soft">
          {list.map((t) => (
            <Row key={t.id} t={t} />
          ))}
        </ul>
      </Card>
    </div>
  )
}
