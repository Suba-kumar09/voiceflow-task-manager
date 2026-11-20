import type { TaskPriority, TaskStatus } from '../../services/api'

/** Words, not just colours: status must be readable without colour vision or sight. */
export const statusLabel: Record<TaskStatus, string> = {
  DRAFT: 'Draft',
  UNASSIGNED: 'In task pool',
  ASSIGNED: 'Assigned',
  ACCEPTED: 'Accepted',
  IN_PROGRESS: 'In progress',
  BLOCKED: 'Blocked',
  PENDING_REVIEW: 'Awaiting review',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
}

export const statusTone: Record<TaskStatus, string> = {
  DRAFT: 'border-line text-ink-muted',
  UNASSIGNED: 'border-line text-ink-muted',
  ASSIGNED: 'border-accent/40 text-accent',
  ACCEPTED: 'border-accent/40 text-accent',
  IN_PROGRESS: 'border-accent bg-accent-soft text-accent',
  BLOCKED: 'border-bad/40 bg-bad/10 text-bad',
  PENDING_REVIEW: 'border-warn/40 bg-warn/10 text-warn',
  COMPLETED: 'border-ok/40 bg-ok/10 text-ok',
  CANCELLED: 'border-line text-ink-muted line-through',
}

export const priorityLabel: Record<TaskPriority, string> = {
  URGENT: 'Urgent',
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
}

/** Due date in the task's own timezone, e.g. "Fri 27 Nov, 6:00 pm". */
export function formatDue(dueAt: string | null, timeZone: string): string | null {
  if (!dueAt) return null
  try {
    return new Intl.DateTimeFormat('en-IN', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
      timeZone,
    }).format(new Date(dueAt))
  } catch {
    return new Date(dueAt).toLocaleString()
  }
}
