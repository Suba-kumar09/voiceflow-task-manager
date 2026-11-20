import { vi } from 'vitest'

import type { Me, NotificationPage, PlanItem, Progress, Project, Task } from '../services/api'

export type Handler = (init: RequestInit | undefined) => { status: number; body?: unknown }

/** Route fetch calls by "METHOD url". Unknown requests fail loudly so tests stay honest. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; init?: RequestInit }[] = []
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, init })
    const handler = routes[key]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    const { status, body } = handler(init)
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return { spy, calls }
}

export const ok = (body?: unknown) => () => ({ status: body === undefined ? 204 : 200, body })
export const unauthorized = () => ({ status: 401, body: { error: { code: 'unauthorized', message: 'Not signed in' } } })

const ORG = { id: 'org1', name: 'Demo Organization (DEMO DATA)', is_demo: true, timezone: 'Asia/Kolkata' }

export const manager: Me = {
  id: 'u-kav',
  username: 'kavitha',
  display_name: 'Kavitha',
  role: 'MANAGER',
  organization: ORG,
  teams: [{ team_id: 't1', team_name: 'Web Platform', membership_role: 'MANAGER' }],
  csrf_token: 'csrf-123',
}

export const employee: Me = {
  ...manager,
  id: 'u-sub',
  username: 'subashini',
  display_name: 'Subashini',
  role: 'EMPLOYEE',
  teams: [{ team_id: 't1', team_name: 'Web Platform', membership_role: 'MEMBER' }],
}

export function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task1',
    team_id: 't1',
    project_id: 'p1',
    external_key: 'EC05',
    title: 'Product listing page',
    description: '',
    acceptance_criteria: 'Products show name, price, stock and image.',
    priority: 'HIGH',
    status: 'IN_PROGRESS',
    assignee: { id: 'u-sub', display_name: 'Subashini' },
    due_at: '2026-11-27T12:30:00Z',
    timezone: 'Asia/Kolkata',
    requires_approval: false,
    evidence_policy: 'NONE',
    version: 3,
    created_at: '2026-11-20T10:00:00Z',
    updated_at: '2026-11-20T10:00:00Z',
    depends_on: ['EC02', 'EC03'],
    required_skills: ['React'],
    ...overrides,
  }
}

export const project: Project = {
  id: 'p1',
  team_id: 't1',
  name: 'E-Commerce Application Development',
  description: 'Online store',
  status: 'ACTIVE',
  created_at: '2026-11-20T10:00:00Z',
  backlog_approved_at: '2026-11-20T10:00:00Z',
  started_at: '2026-11-20T10:00:00Z',
}

export const progress: Progress = {
  project_id: 'p1',
  name: project.name,
  status: 'ACTIVE',
  total: 12,
  completed: 3,
  percent_complete: 25,
  in_progress: 2,
  ready_to_assign: 1,
  waiting_on_dependencies: 5,
  blocked_by_issue: 0,
  awaiting_review: 1,
  needs_decision: [{ task_id: 'x', key: 'EC11', title: 'iOS build setup', reason: 'No one on the team has ios.' }],
  draft: 0,
  cancelled: 0,
}

export const plan: PlanItem[] = [
  { task_id: 'a', key: 'EC10', title: 'Wishlist page', priority: 'HIGH', outcome: 'ASSIGN', reason: 'Needs react; Priya has no active task.', assignee_id: 'u-pri', assignee_name: 'Priya' },
  { task_id: 'b', key: 'EC11', title: 'iOS build setup', priority: 'MEDIUM', outcome: 'NO_QUALIFIED', reason: 'No one on the team has ios.' },
]

export const noNotes: NotificationPage = { items: [], total: 0, unread: 0, limit: 100, offset: 0 }

export const page = <T,>(items: T[]) => ({ items, total: items.length, limit: 200, offset: 0 })

/** Calls every signed-in screen makes (sidebar projects + notification badge). */
export function shellRoutes(me: Me): Record<string, Handler> {
  return {
    'GET /api/v1/users/me': ok(me),
    'GET /api/v1/notifications?limit=100': ok(noNotes),
    ...(me.role === 'EMPLOYEE' ? {} : { 'GET /api/v1/projects': ok([project]) }),
  }
}
