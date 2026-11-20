import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import type { Me, Task } from '../../services/api'

const ORG = { id: 'org1', name: 'Demo Organization (DEMO DATA)', is_demo: true, timezone: 'Asia/Kolkata' }

const manager: Me = {
  id: 'u1',
  username: 'kavitha',
  display_name: 'Kavitha',
  role: 'MANAGER',
  organization: ORG,
  teams: [{ team_id: 't1', team_name: 'Web Platform', membership_role: 'MANAGER' }],
  csrf_token: 'csrf-123',
}

const employee: Me = {
  ...manager,
  id: 'u2',
  username: 'subashini',
  display_name: 'Subashini',
  role: 'EMPLOYEE',
  teams: [{ team_id: 't1', team_name: 'Web Platform', membership_role: 'MEMBER' }],
}

const webTesting: Task = {
  id: 'task1',
  team_id: 't1',
  project_id: null,
  external_key: null,
  title: 'Website testing',
  description: '',
  acceptance_criteria: 'All checkout pages pass',
  priority: 'HIGH',
  status: 'IN_PROGRESS',
  assignee: { id: 'u2', display_name: 'Subashini' },
  due_at: '2026-11-27T12:30:00Z',
  timezone: 'Asia/Kolkata',
  requires_approval: false,
  evidence_policy: 'NONE',
  version: 3,
  created_at: '2026-11-20T10:00:00Z',
  updated_at: '2026-11-20T10:00:00Z',
}

type Handler = (init: RequestInit | undefined) => { status: number; body?: unknown }

const employeeTaskRoutes: Record<string, Handler> = {
  'GET /api/v1/me/tasks/current': () => ({ status: 200, body: { task: webTesting } }),
  'GET /api/v1/me/tasks?limit=200': () => ({
    status: 200,
    body: { items: [webTesting], total: 1, limit: 200, offset: 0 },
  }),
}

function mockApi(routes: Record<string, Handler>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    const key = `${init?.method ?? 'GET'} ${url}`
    const handler = routes[key]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    const { status, body } = handler(init)
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

const unauthorized = { status: 401, body: { error: { code: 'unauthorized', message: 'Not signed in' } } }

async function signIn(username: string, password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Username'), username)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return user
}

describe('sign-in flow', () => {
  it('shows the server message on a wrong password and clears the password field', async () => {
    mockApi({
      'GET /api/v1/users/me': () => unauthorized,
      'POST /api/v1/auth/login': () => ({
        status: 401,
        body: { error: { code: 'unauthorized', message: 'Invalid username or password.' } },
      }),
    })
    render(<App />)
    await signIn('kavitha', 'wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })

  it('signs a manager in and shows their team tasks, roster and a demo-data banner', async () => {
    mockApi({
      'GET /api/v1/users/me': () => unauthorized,
      'POST /api/v1/auth/login': () => ({ status: 200, body: manager }),
      'GET /api/v1/tasks?limit=200&team_id=t1': () => ({
        status: 200,
        body: { items: [webTesting], total: 1, limit: 200, offset: 0 },
      }),
      'GET /api/v1/teams/t1/employees?limit=200': () => ({
        status: 200,
        body: {
          items: [
            { id: 'u2', display_name: 'Subashini', role: 'EMPLOYEE', membership_role: 'MEMBER', is_active: true },
          ],
          total: 1,
          limit: 200,
          offset: 0,
        },
      }),
    })
    render(<App />)
    await signIn('kavitha', 'a-good-password')
    expect(await screen.findByRole('heading', { name: 'Welcome, Kavitha' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Teams you manage' })).toBeInTheDocument()
    expect(await screen.findByText('Website testing')).toBeInTheDocument()
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.getByText(/High priority · .*· Subashini/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Demo data')
  })

  it('restores an employee session and shows their current task, not team rosters', async () => {
    mockApi({
      'GET /api/v1/users/me': () => ({ status: 200, body: employee }),
      ...employeeTaskRoutes,
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Welcome, Subashini' })).toBeInTheDocument()
    expect(screen.getByText(/You are on the Web Platform team/)).toBeInTheDocument()
    expect(await screen.findByText('Current task')).toBeInTheDocument()
    expect(screen.getByText('All checkout pages pass')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Teams you manage' })).not.toBeInTheDocument()
  })

  it('tells an employee plainly when they have no active task', async () => {
    mockApi({
      'GET /api/v1/users/me': () => ({ status: 200, body: employee }),
      'GET /api/v1/me/tasks/current': () => ({ status: 200, body: { task: null } }),
      'GET /api/v1/me/tasks?limit=200': () => ({
        status: 200,
        body: { items: [], total: 0, limit: 200, offset: 0 },
      }),
    })
    render(<App />)
    expect(await screen.findByText('You have no active task right now.')).toBeInTheDocument()
  })

  it('sends the CSRF token when signing out and returns to sign-in', async () => {
    let sentCsrf: string | undefined
    mockApi({
      'GET /api/v1/users/me': () => ({ status: 200, body: employee }),
      ...employeeTaskRoutes,
      'POST /api/v1/auth/logout': (init) => {
        sentCsrf = (init?.headers as Record<string, string>)['X-CSRF-Token']
        return { status: 204 }
      },
    })
    render(<App />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: /Sign in to/ })).toBeInTheDocument()
    expect(sentCsrf).toBe('csrf-123')
  })

  it('returns to sign-in with a clear notice when the session expires', async () => {
    mockApi({
      'GET /api/v1/users/me': () => ({ status: 200, body: manager }),
      'GET /api/v1/teams/t1/employees?limit=200': () => unauthorized,
      'GET /api/v1/tasks?limit=200&team_id=t1': () => unauthorized,
    })
    render(<App />)
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Your session ended. Please sign in again.'),
    )
  })
})
