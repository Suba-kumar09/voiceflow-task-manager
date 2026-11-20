import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { employee, manager, mockApi, ok, page, progress, shellRoutes, task, unauthorized } from '../../tests/mockApi'

async function signIn(username: string, password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Username'), username)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return user
}

beforeEach(() => window.history.pushState({}, '', '/'))

describe('sign-in flow', () => {
  it('shows the server message on a wrong password and clears the password field', async () => {
    mockApi({
      'GET /api/v1/users/me': unauthorized,
      'POST /api/v1/auth/login': () => ({ status: 401, body: { error: { code: 'unauthorized', message: 'Invalid username or password.' } } }),
    })
    render(<App />)
    await signIn('kavitha', 'wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })

  it('takes a manager to Projects with live progress and a demo-data banner', async () => {
    mockApi({
      ...shellRoutes(manager),
      'GET /api/v1/users/me': unauthorized,
      'POST /api/v1/auth/login': ok(manager),
      'GET /api/v1/projects/p1/progress': ok(progress),
    })
    render(<App />)
    await signIn('kavitha', 'a-good-password')
    expect(await screen.findByRole('heading', { name: 'Projects' })).toBeInTheDocument()
    expect(await screen.findByText('3 of 12 tasks done')).toBeInTheDocument()
    expect(screen.getByText('1 needs decision')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Demo data')
    expect(window.location.pathname).toBe('/projects')
  })

  it('restores an employee session on My work, with no manager navigation', async () => {
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': ok({ task: task() }),
      'GET /api/v1/me/tasks?limit=200': ok(page([task()])),
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Product listing page' })).toBeInTheDocument()
    expect(screen.getByText('Products show name, price, stock and image.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Projects' })).not.toBeInTheDocument()
    expect(window.location.pathname).toBe('/my-work')
  })

  it('sends the CSRF token when signing out and returns to sign-in', async () => {
    let sentCsrf: string | undefined
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': ok({ task: null }),
      'GET /api/v1/me/tasks?limit=200': ok(page([])),
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
      'GET /api/v1/users/me': ok(manager),
      'GET /api/v1/notifications?limit=100': unauthorized,
      'GET /api/v1/projects': unauthorized,
    })
    render(<App />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Your session ended. Please sign in again.'))
  })
})
