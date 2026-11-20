/** Typed client for the VoiceFlow API (same-origin; Vite proxies /api in development). */

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

// ---------------------------------------------------------------- types (mirror backend schemas)

export interface HealthResponse {
  status: 'ok'
}

export interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  database: 'ok' | 'unavailable' | 'not_configured'
  migrations: 'up_to_date' | 'pending' | 'unknown'
}

export type UserRole = 'ADMIN' | 'MANAGER' | 'EMPLOYEE'
export type MembershipRole = 'MEMBER' | 'MANAGER'

export interface TeamMembership {
  team_id: string
  team_name: string
  membership_role: MembershipRole
}

export interface Me {
  id: string
  username: string
  display_name: string
  role: UserRole
  organization: { id: string; name: string; is_demo: boolean; timezone: string }
  teams: TeamMembership[]
  csrf_token: string
}

export interface EmployeeSummary {
  id: string
  display_name: string
  role: UserRole
  membership_role: MembershipRole
  is_active: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type TaskStatus =
  | 'DRAFT'
  | 'UNASSIGNED'
  | 'ASSIGNED'
  | 'ACCEPTED'
  | 'IN_PROGRESS'
  | 'BLOCKED'
  | 'PENDING_REVIEW'
  | 'COMPLETED'
  | 'CANCELLED'

export type TaskPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT'
export type EvidencePolicy = 'NONE' | 'NOTE' | 'LINK' | 'MANAGER_APPROVAL'

export interface Task {
  id: string
  team_id: string
  project_id: string | null
  external_key: string | null
  title: string
  description: string
  acceptance_criteria: string
  priority: TaskPriority
  status: TaskStatus
  assignee: { id: string; display_name: string } | null
  due_at: string | null
  timezone: string
  requires_approval: boolean
  evidence_policy: EvidencePolicy
  version: number
  created_at: string
  updated_at: string
  depends_on: string[]
  required_skills: string[]
}

export type ProjectStatus = 'DRAFT' | 'READY' | 'ACTIVE' | 'PAUSED' | 'CLOSED'

export interface Project {
  id: string
  team_id: string
  name: string
  description: string
  status: ProjectStatus
  created_at: string
  backlog_approved_at: string | null
  started_at: string | null
}

export interface DecisionItem {
  task_id: string
  key: string
  title: string
  reason: string
}

export interface Progress {
  project_id: string
  name: string
  status: ProjectStatus
  total: number
  completed: number
  percent_complete: number
  in_progress: number
  ready_to_assign: number
  waiting_on_dependencies: number
  blocked_by_issue: number
  awaiting_review: number
  needs_decision: DecisionItem[]
  draft: number
  cancelled: number
}

export interface PlanItem {
  task_id: string
  key: string
  title: string
  priority: TaskPriority
  outcome: 'ASSIGN' | 'NO_CAPACITY' | 'NO_QUALIFIED'
  reason: string
  assignee_id?: string | null
  assignee_name?: string | null
}

export interface EvaluationItem {
  task_id: string
  key: string
  title: string
  priority: TaskPriority
  reason: string
  assignee_name?: string
}

export interface Evaluation {
  project_id: string
  assigned: EvaluationItem[]
  waiting_for_capacity: EvaluationItem[]
  needs_decision: EvaluationItem[]
  skipped: EvaluationItem[]
}

export interface TeamMember {
  id: string
  display_name: string
  membership_role: MembershipRole
  is_active: boolean
  skills: string[]
  active_tasks: number
  wip_limit: number
  completed_in_project: number
  current_task: { id: string; key: string | null; title: string; status: TaskStatus } | null
}

export interface AppNotification {
  id: string
  kind:
    | 'TASK_ASSIGNED'
    | 'COMPLETION_SUBMITTED'
    | 'COMPLETION_APPROVED'
    | 'COMPLETION_REJECTED'
    | 'TASK_BLOCKED'
    | 'TASK_DECLINED'
    | 'PROJECT_SUMMARY'
    | 'NEEDS_DECISION'
  title: string
  body: string
  task_id: string | null
  project_id: string | null
  created_at: string
  read: boolean
}

export interface NotificationPage {
  items: AppNotification[]
  total: number
  unread: number
  limit: number
  offset: number
}

// ---------------------------------------------------------------- transport

let csrfToken: string | null = null

/** Remember the CSRF token for the current session (sent on every state-changing request). */
export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

/** Called when any request finds the session gone (401), so the app can return to sign-in. */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

/** A fresh key per user action, so a network retry of the same action is applied once. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

async function toApiError(resp: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `Request failed (${resp.status})`
  try {
    const body = (await resp.json()) as ApiErrorBody
    code = body.error.code
    message = body.error.message
  } catch {
    /* non-JSON error (e.g. backend not running): keep the generic message */
  }
  return new ApiError(resp.status, code, message)
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /** Status codes to treat as data rather than errors (e.g. 503 readiness). */
  acceptStatuses?: number[]
  /** Do not trigger the global sign-out handler on 401 (used by the sign-in call itself). */
  ignoreUnauthorized?: boolean
  idempotencyKey?: string
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey

  let resp: Response
  try {
    resp = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the VoiceFlow server.')
  }

  if (resp.ok || opts.acceptStatuses?.includes(resp.status)) {
    if (resp.status === 204) return undefined as T
    return (await resp.json()) as T
  }
  const err = await toApiError(resp)
  if (resp.status === 401 && !opts.ignoreUnauthorized) onUnauthorized?.()
  throw err
}

/** Kept for existing callers. */
export function getJson<T>(path: string, acceptStatuses: number[] = []): Promise<T> {
  return request<T>(path, { acceptStatuses })
}

const q = encodeURIComponent

// ---------------------------------------------------------------- endpoints

export const systemApi = {
  health: () => getJson<HealthResponse>('/api/v1/health'),
  readiness: () => getJson<ReadinessResponse>('/api/v1/ready', [503]),
}

export const authApi = {
  login: (username: string, password: string) =>
    request<Me>('/api/v1/auth/login', {
      method: 'POST',
      body: { username, password },
      ignoreUnauthorized: true,
    }),
  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),
  /** Restore an existing session (e.g. after reload). 401 simply means "not signed in". */
  me: () => request<Me>('/api/v1/users/me', { ignoreUnauthorized: true }),
}

export const peopleApi = {
  teamEmployees: (teamId: string) =>
    request<Page<EmployeeSummary>>(`/api/v1/teams/${q(teamId)}/employees?limit=200`),
}

export type TaskActionPath =
  | 'accept'
  | 'decline'
  | 'start'
  | 'block'
  | 'resume'
  | 'request-completion'
  | 'approve-completion'
  | 'reject-completion'
  | 'cancel'

export const tasksApi = {
  list: (teamId?: string) =>
    request<Page<Task>>(`/api/v1/tasks?limit=200${teamId ? `&team_id=${q(teamId)}` : ''}`),
  forProject: (projectId: string) =>
    request<Page<Task>>(`/api/v1/tasks?limit=200&project_id=${q(projectId)}`),
  mine: () => request<Page<Task>>('/api/v1/me/tasks?limit=200'),
  current: () => request<{ task: Task | null }>('/api/v1/me/tasks/current'),
  action: (
    taskId: string,
    path: TaskActionPath,
    body: { reason?: string; note?: string; link?: string } = {},
  ) =>
    request<Task>(`/api/v1/tasks/${q(taskId)}/${path}`, {
      method: 'POST',
      body,
      idempotencyKey: newIdempotencyKey(),
    }),
}

export const projectsApi = {
  list: () => request<Project[]>('/api/v1/projects'),
  get: (id: string) => request<Project>(`/api/v1/projects/${q(id)}`),
  progress: (id: string) => request<Progress>(`/api/v1/projects/${q(id)}/progress`),
  team: (id: string) => request<TeamMember[]>(`/api/v1/projects/${q(id)}/team`),
  plan: (id: string) => request<PlanItem[]>(`/api/v1/projects/${q(id)}/assignment-plan`),
  assignReady: (id: string) =>
    request<Evaluation>(`/api/v1/projects/${q(id)}/assign-ready`, {
      method: 'POST',
      idempotencyKey: newIdempotencyKey(),
    }),
  approveBacklog: (id: string) =>
    request<unknown>(`/api/v1/projects/${q(id)}/approve-backlog`, { method: 'POST' }),
  start: (id: string) =>
    request<Evaluation>(`/api/v1/projects/${q(id)}/start`, { method: 'POST' }),
}

export const notificationsApi = {
  list: () => request<NotificationPage>('/api/v1/notifications?limit=100'),
  markRead: (id: string) =>
    request<void>(`/api/v1/notifications/${q(id)}/read`, { method: 'POST' }),
}
