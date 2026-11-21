import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Button } from '../../components/ui/Button'
import { Card, Empty, ErrorBox, Loading } from '../../components/ui/States'
import { notificationsApi, type AppNotification } from '../../services/api'
import { usePageSummary } from '../../voice/pageSummary'
import { useMe } from '../auth/auth-context'
import { timeAgo } from '../tasks/taskLabels'
import { useNotifications } from './useNotifications'

const dot: Record<AppNotification['kind'], string> = {
  TASK_ASSIGNED: '#2dd4bf',
  COMPLETION_SUBMITTED: '#fbbf24',
  COMPLETION_APPROVED: '#4ade80',
  COMPLETION_REJECTED: '#fb923c',
  TASK_BLOCKED: '#f87171',
  TASK_DECLINED: '#fb923c',
  PROJECT_SUMMARY: '#38bdf8',
  NEEDS_DECISION: '#c084fc',
  EXTENSION_REQUESTED: '#38bdf8',
  EXTENSION_APPROVED: '#4ade80',
  EXTENSION_DENIED: '#fb923c',
  DUE_SOON: '#fbbf24',
  OVERDUE: '#f87171',
  DAILY_DIGEST: '#38bdf8',
}

export function NotificationsPage() {
  const me = useMe()
  const qc = useQueryClient()
  const notes = useNotifications()
  const read = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) })
  const isManager = me.role !== 'EMPLOYEE'
  const unreadItems = (notes.data?.items ?? []).filter((n) => !n.read)
  usePageSummary(
    `Notifications. ${unreadItems.length} unread.` +
      (unreadItems.length ? ' ' + unreadItems.slice(0, 3).map((n) => n.title + '.').join(' ') : ''),
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Notifications</h1>
        <p className="mt-1 text-sm text-ink-muted">{notes.data ? `${notes.data.unread} unread` : ' '}</p>
      </div>
      <Card className="py-1">
        {notes.isLoading && <Loading />}
        {notes.isError && <ErrorBox error={notes.error} />}
        {notes.isSuccess && notes.data.items.length === 0 && <div className="py-4"><Empty>No notifications yet.</Empty></div>}
        <ul className="divide-y divide-line-soft">
          {notes.data?.items.map((n) => (
            <li key={n.id} className="flex gap-3 py-4">
              <span aria-hidden="true" className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: n.read ? 'transparent' : dot[n.kind], border: n.read ? '1px solid #2a3a55' : undefined }} />
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${n.read ? 'font-medium text-ink-muted' : 'font-semibold text-ink-strong'}`}>
                  {n.title}
                  {!n.read && <span className="sr-only"> (unread)</span>}
                </p>
                {n.body && <p className="mt-0.5 text-sm text-ink-muted">{n.body}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-faint">
                  <span>{timeAgo(n.created_at)}</span>
                  {n.project_id && (
                    <Link
                      to={isManager ? `/projects/${n.project_id}${n.kind === 'COMPLETION_SUBMITTED' ? '' : '?tab=tasks'}` : '/my-work'}
                      className="font-semibold text-accent-strong hover:underline"
                    >
                      {isManager ? 'Open project' : 'Open my work'}
                    </Link>
                  )}
                </div>
              </div>
              {!n.read && (
                <Button size="sm" variant="ghost" disabled={read.isPending} onClick={() => read.mutate(n.id)}>
                  Mark read
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
