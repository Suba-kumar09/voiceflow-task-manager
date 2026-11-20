import { useId, useState } from 'react'

import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'
import { ErrorBox } from '../../components/ui/States'
import type { Task, TaskActionPath } from '../../services/api'
import { useTaskAction } from './useTaskAction'

type DialogKind = null | 'complete' | 'block' | 'decline' | 'reject'

function needsReview(task: Task): boolean {
  return task.requires_approval || task.evidence_policy !== 'NONE'
}

function TextField({ label, value, onChange, multiline, required, placeholder }: {
  label: string
  value: string
  onChange: (v: string) => void
  multiline?: boolean
  required?: boolean
  placeholder?: string
}) {
  const id = useId()
  const cls =
    'mt-1 w-full rounded-lg border border-control-line bg-inset px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent'
  return (
    <div className="mb-3">
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
        {required && <span className="text-bad"> *</span>}
      </label>
      {multiline ? (
        <textarea id={id} rows={3} value={value} required={required} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cls} />
      ) : (
        <input id={id} value={value} required={required} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cls} />
      )}
    </div>
  )
}

/** Buttons for what the signed-in user may do with this task right now. */
export function TaskActions({ task, role }: { task: Task; role: 'assignee' | 'manager' }) {
  const action = useTaskAction()
  const [dialog, setDialog] = useState<DialogKind>(null)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [link, setLink] = useState('')

  const close = () => {
    setDialog(null)
    setReason('')
    setNote('')
    setLink('')
    action.reset()
  }
  const run = (path: TaskActionPath, body?: { reason?: string; note?: string; link?: string }) =>
    action.mutate({ task, path, body }, { onSuccess: () => dialog && close() })

  const busy = action.isPending
  const buttons: React.ReactNode[] = []
  if (role === 'assignee') {
    if (task.status === 'ASSIGNED' || task.status === 'ACCEPTED')
      buttons.push(
        <Button key="start" variant="primary" disabled={busy} onClick={() => run('start')}>Start</Button>,
        <Button key="decline" disabled={busy} onClick={() => setDialog('decline')}>Decline</Button>,
      )
    if (task.status === 'IN_PROGRESS')
      buttons.push(
        <Button key="done" variant="primary" disabled={busy} onClick={() => setDialog('complete')}>Report done</Button>,
        <Button key="block" disabled={busy} onClick={() => setDialog('block')}>I’m blocked</Button>,
      )
    if (task.status === 'BLOCKED')
      buttons.push(<Button key="resume" variant="primary" disabled={busy} onClick={() => run('resume')}>Resume</Button>)
  } else if (task.status === 'PENDING_REVIEW') {
    buttons.push(
      <Button key="approve" variant="primary" size="sm" disabled={busy} onClick={() => run('approve-completion')}>Approve</Button>,
      <Button key="reject" size="sm" disabled={busy} onClick={() => setDialog('reject')}>Send back</Button>,
    )
  } else if (task.status === 'BLOCKED') {
    buttons.push(<Button key="resume" size="sm" disabled={busy} onClick={() => run('resume')}>Mark resolved</Button>)
  }

  if (!buttons.length) return null

  const evidenceNote = task.evidence_policy === 'NOTE'
  const evidenceLink = task.evidence_policy === 'LINK'
  const reasonDialogs: Record<'block' | 'decline' | 'reject', { title: string; label: string; path: TaskActionPath; cta: string }> = {
    block: { title: `Report a blocker on “${task.title}”`, label: 'What is stopping you?', path: 'block', cta: 'Report blocker' },
    decline: { title: `Decline “${task.title}”`, label: 'Why are you declining?', path: 'decline', cta: 'Decline task' },
    reject: { title: `Send “${task.title}” back`, label: 'What still needs to be done?', path: 'reject-completion', cta: 'Send back' },
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">{buttons}</div>
      {!dialog && action.isError && <div className="mt-2"><ErrorBox error={action.error} /></div>}

      {dialog === 'complete' && (
        <Modal
          title={`Report “${task.title}” done`}
          onClose={close}
          footer={
            <>
              <Button onClick={close}>Cancel</Button>
              <Button
                variant="primary"
                disabled={busy || (evidenceNote && !note.trim()) || (evidenceLink && !link.trim())}
                onClick={() => run('request-completion', { note: note.trim() || undefined, link: link.trim() || undefined })}
              >
                {needsReview(task) ? 'Send for review' : 'Mark completed'}
              </Button>
            </>
          }
        >
          <p className="mb-3 text-sm text-ink-muted">
            {needsReview(task)
              ? 'Your manager will be notified and will review it before it counts as completed.'
              : 'This task needs no review; it will be completed straight away and your manager will be told.'}
          </p>
          {task.acceptance_criteria && (
            <p className="mb-3 rounded-lg border border-line-soft bg-inset px-3 py-2 text-sm">
              <span className="font-semibold">Done when: </span>
              {task.acceptance_criteria}
            </p>
          )}
          <TextField label="Completion note" value={note} onChange={setNote} multiline required={evidenceNote} placeholder="What did you finish?" />
          {(evidenceLink || task.evidence_policy === 'MANAGER_APPROVAL') && (
            <TextField label="Evidence link" value={link} onChange={setLink} required={evidenceLink} placeholder="https://…" />
          )}
          {action.isError && <ErrorBox error={action.error} />}
        </Modal>
      )}

      {(dialog === 'block' || dialog === 'decline' || dialog === 'reject') && (
        <Modal
          title={reasonDialogs[dialog].title}
          onClose={close}
          footer={
            <>
              <Button onClick={close}>Cancel</Button>
              <Button variant={dialog === 'reject' ? 'primary' : 'danger'} disabled={busy || !reason.trim()} onClick={() => run(reasonDialogs[dialog].path, { reason: reason.trim() })}>
                {reasonDialogs[dialog].cta}
              </Button>
            </>
          }
        >
          <TextField label={reasonDialogs[dialog].label} value={reason} onChange={setReason} multiline required />
          {action.isError && <ErrorBox error={action.error} />}
        </Modal>
      )}
    </>
  )
}
