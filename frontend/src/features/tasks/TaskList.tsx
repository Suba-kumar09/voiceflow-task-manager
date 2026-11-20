import type { Task } from '../../services/api'
import { formatDue, priorityLabel, statusLabel, statusTone } from './taskLabels'

export function StatusBadge({ task }: { task: Task }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${statusTone[task.status]}`}
    >
      {statusLabel[task.status]}
    </span>
  )
}

export function TaskList({
  tasks,
  showAssignee,
  emptyText,
}: {
  tasks: Task[]
  showAssignee: boolean
  emptyText: string
}) {
  if (tasks.length === 0) {
    return <p className="py-3 text-sm text-ink-muted">{emptyText}</p>
  }
  return (
    <ul className="divide-y divide-line">
      {tasks.map((t) => {
        const due = formatDue(t.due_at, t.timezone)
        return (
          <li key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{t.title}</p>
              <p className="text-xs text-ink-muted">
                {priorityLabel[t.priority]} priority
                {due && <> · Due {due}</>}
                {showAssignee && (
                  <> · {t.assignee ? t.assignee.display_name : 'Not assigned'}</>
                )}
              </p>
            </div>
            <StatusBadge task={t} />
          </li>
        )
      })}
    </ul>
  )
}
