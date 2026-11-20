import type { ProjectStatus, TaskPriority, TaskStatus } from '../../services/api'
import {
  priorityColor,
  priorityLabel,
  projectStatusLabel,
  projectStatusTone,
  statusLabel,
  statusTone,
} from './taskLabels'

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusTone[status]}`}>
      {statusLabel[status]}
    </span>
  )
}

export function ProjectBadge({ status }: { status: ProjectStatus }) {
  return (
    <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${projectStatusTone[status]}`}>
      {projectStatusLabel[status]}
    </span>
  )
}

export function Priority({ priority }: { priority: TaskPriority }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm font-medium text-ink">
      <span aria-hidden="true" className="size-2 rounded-full" style={{ background: priorityColor[priority] }} />
      {priorityLabel[priority]}
    </span>
  )
}
