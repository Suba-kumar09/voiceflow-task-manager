import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'
import { ErrorBox } from '../../components/ui/States'
import { requestsApi, type Task } from '../../services/api'
import { formatDue } from './taskLabels'

const ACTIVE = ['ASSIGNED', 'ACCEPTED', 'IN_PROGRESS', 'BLOCKED']

/** Employee: ask for more time (the deadline changes only if a manager approves) and report progress. */
export function RequestActions({ task }: { task: Task }) {
  const qc = useQueryClient()
  const [dialog, setDialog] = useState<null | 'extend' | 'progress'>(null)
  const [date, setDate] = useState('')
  const [reason, setReason] = useState('')
  const [percent, setPercent] = useState(task.progress_percent ?? 50)
  const [note, setNote] = useState('')
  const ids = { date: useId(), reason: useId(), percent: useId(), note: useId() }

  const done = () => {
    void qc.invalidateQueries()
    setDialog(null)
    setReason('')
    setNote('')
  }
  const extend = useMutation({
    // A date picked on screen means the end of that working day in the user's time zone.
    mutationFn: () => requestsApi.ask(task.id, new Date(`${date}T18:00`).toISOString(), reason.trim()),
    onSuccess: done,
  })
  const progress = useMutation({ mutationFn: () => requestsApi.progress(task.id, percent, note.trim()), onSuccess: done })

  if (!ACTIVE.includes(task.status)) return null
  const inputCls = 'mt-1 w-full rounded-lg border border-control-line bg-inset px-3 py-2 text-sm text-ink focus:border-accent'
  const current = formatDue(task.due_at, task.timezone)

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {task.pending_extension ? (
          <span className="inline-flex h-10 items-center rounded-lg border border-[#5a4512] bg-[rgba(251,191,36,.08)] px-3 text-sm text-warn">
            More time requested until {formatDue(task.pending_extension.requested_due_at, task.timezone)} — waiting for your manager
          </span>
        ) : (
          <Button onClick={() => setDialog('extend')}>Need more time</Button>
        )}
        {task.status === 'IN_PROGRESS' && <Button onClick={() => setDialog('progress')}>Update progress</Button>}
      </div>

      {dialog === 'extend' && (
        <Modal
          title={`More time for “${task.title}”`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button variant="primary" disabled={!date || !reason.trim() || extend.isPending} onClick={() => extend.mutate()}>
                Send request
              </Button>
            </>
          }
        >
          <p className="mb-3 text-sm text-ink-muted">
            {current ? `Currently due ${current}. ` : ''}Your manager decides; the deadline changes only if they approve.
          </p>
          <label htmlFor={ids.date} className="block text-sm font-medium text-ink">New due date <span className="text-bad">*</span></label>
          <input id={ids.date} type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} mb-3`} />
          <label htmlFor={ids.reason} className="block text-sm font-medium text-ink">Why do you need more time? <span className="text-bad">*</span></label>
          <textarea id={ids.reason} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} className={`${inputCls} mb-3`} />
          {extend.isError && <ErrorBox error={extend.error} />}
        </Modal>
      )}

      {dialog === 'progress' && (
        <Modal
          title={`Progress on “${task.title}”`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button variant="primary" disabled={progress.isPending} onClick={() => progress.mutate()}>Save progress</Button>
            </>
          }
        >
          <label htmlFor={ids.percent} className="block text-sm font-medium text-ink">
            How far along are you? <span className="font-semibold text-accent-strong">{percent}%</span>
          </label>
          <input id={ids.percent} type="range" min={0} max={100} step={5} value={percent} onChange={(e) => setPercent(Number(e.target.value))} className="mt-2 mb-4 w-full accent-[#14b8a6]" />
          <label htmlFor={ids.note} className="block text-sm font-medium text-ink">Short note (optional)</label>
          <textarea id={ids.note} rows={2} value={note} onChange={(e) => setNote(e.target.value)} className={`${inputCls} mb-3`} />
          {progress.isError && <ErrorBox error={progress.error} />}
        </Modal>
      )}
    </>
  )
}
