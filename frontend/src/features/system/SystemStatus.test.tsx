import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SystemStatus } from './SystemStatus'

function mockFetch(routes: Record<string, { status: number; body: unknown } | 'network-error'>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    const route = routes[url]
    if (!route || route === 'network-error') throw new TypeError('Failed to fetch')
    return new Response(JSON.stringify(route.body), {
      status: route.status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

describe('SystemStatus', () => {
  it('shows everything healthy when API, database and migrations are ready', async () => {
    mockFetch({
      '/api/v1/health': { status: 200, body: { status: 'ok' } },
      '/api/v1/ready': {
        status: 200,
        body: { status: 'ready', database: 'ok', migrations: 'up_to_date' },
      },
    })
    render(<SystemStatus />)
    expect(await screen.findByText('Everything is ready.')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL is reachable.')).toBeInTheDocument()
    expect(screen.getByText('Schema is up to date.')).toBeInTheDocument()
  })

  it('treats a 503 readiness response as data, not as a crash', async () => {
    mockFetch({
      '/api/v1/health': { status: 200, body: { status: 'ok' } },
      '/api/v1/ready': {
        status: 503,
        body: { status: 'not_ready', database: 'ok', migrations: 'pending' },
      },
    })
    render(<SystemStatus />)
    expect(await screen.findByText('Database migrations need to be applied.')).toBeInTheDocument()
  })

  it('reports clearly when the backend is not running', async () => {
    mockFetch({ '/api/v1/health': 'network-error' })
    render(<SystemStatus />)
    expect(await screen.findByText('The backend server is not responding.')).toBeInTheDocument()
  })
})
