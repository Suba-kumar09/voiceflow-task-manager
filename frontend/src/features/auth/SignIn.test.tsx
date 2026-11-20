import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import type { Me } from '../../services/api'

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

type Handler = (init: RequestInit | undefined) => { status: number; body?: unknown }

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

  it('signs a manager in and shows their team roster with a demo-data banner', async () => {
    mockApi({
      'GET /api/v1/users/me': () => unauthorized,
      'POST /api/v1/auth/login': () => ({ status: 200, body: manager }),
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
    expect(await screen.findByText('Subashini')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Demo data')
  })

  it('restores an existing session and shows the employee view without team rosters', async () => {
    mockApi({ 'GET /api/v1/users/me': () => ({ status: 200, body: employee }) })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Welcome, Subashini' })).toBeInTheDocument()
    expect(screen.getByText(/You are on the Web Platform team/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Teams you manage' })).not.toBeInTheDocument()
  })

  it('sends the CSRF token when signing out and returns to sign-in', async () => {
    let sentCsrf: string | undefined
    mockApi({
      'GET /api/v1/users/me': () => ({ status: 200, body: employee }),
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
    })
    render(<App />)
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Your session ended. Please sign in again.'),
    )
  })
})
