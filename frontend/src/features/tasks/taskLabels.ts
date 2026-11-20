import type { ProjectStatus, TaskPriority, TaskStatus } from '../../services/api'

/** Words, not just colours: status must be readable without colour vision or sight. */
export const statusLabel: Record<TaskStatus, string> = {
  DRAFT: 'Draft',
  UNASSIGNED: 'Open',
  ASSIGNED: 'Assigned',
  ACCEPTED: 'Accepted',
  IN_PROGRESS: 'In progress',
  BLOCKED: 'Blocked',
  PENDING_REVIEW: 'Awaiting review',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
}

export const statusTone: Record<TaskStatus, string> = {
  DRAFT: 'bg-[rgba(148,163,184,.12)] text-[#cbd5e1]',
  UNASSIGNED: 'bg-[rgba(52,211,153,.12)] text-[#6ee7b7]',
  ASSIGNED: 'bg-[rgba(129,140,248,.16)] text-[#a5b4fc]',
  ACCEPTED: 'bg-[rgba(129,140,248,.16)] text-[#a5b4fc]',
  IN_PROGRESS: 'bg-[rgba(56,189,248,.14)] text-[#7dd3fc]',
  BLOCKED: 'bg-[rgba(248,113,113,.15)] text-[#fca5a5]',
  PENDING_REVIEW: 'bg-[rgba(251,191,36,.14)] text-[#fcd34d]',
  COMPLETED: 'bg-[rgba(34,197,94,.14)] text-[#4ade80]',
  CANCELLED: 'bg-[rgba(148,163,184,.10)] text-[#94a3b8] line-through',
}

export const projectStatusLabel: Record<ProjectStatus, string> = {
  DRAFT: 'Draft',
  READY: 'Ready to start',
  ACTIVE: 'Active',
  PAUSED: 'Paused',
  CLOSED: 'Closed',
}

export const projectStatusTone: Record<ProjectStatus, string> = {
  DRAFT: 'bg-[rgba(148,163,184,.12)] text-[#cbd5e1]',
  READY: 'bg-[rgba(129,140,248,.16)] text-[#a5b4fc]',
  ACTIVE: 'bg-[rgba(45,212,191,.15)] text-[#5eead4]',
  PAUSED: 'bg-[rgba(251,191,36,.14)] text-[#fcd34d]',
  CLOSED: 'bg-[rgba(34,197,94,.14)] text-[#4ade80]',
}

export const priorityLabel: Record<TaskPriority, string> = {
  URGENT: 'Urgent',
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
}

export const priorityColor: Record<TaskPriority, string> = {
  URGENT: '#f87171',
  HIGH: '#fb923c',
  MEDIUM: '#38bdf8',
  LOW: '#94a3b8',
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

export function timeAgo(iso: string, now: Date = new Date()): string {
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}
