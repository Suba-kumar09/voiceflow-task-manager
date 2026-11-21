import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { manager, mockApi, ok, progress, shellRoutes } from '../../tests/mockApi'

beforeEach(() => window.history.pushState({}, '', '/projects'))
afterEach(() => vi.restoreAllMocks())

describe('team today (manager)', () => {
  it('shows counts, overdue work and who is overloaded or free', async () => {
    mockApi({ ...shellRoutes(manager), 'GET /api/v1/projects/p1/progress': ok(progress) })
    render(<App />)

    const card = await screen.findByRole('region', { name: 'Team today' })
    expect(await within(card).findByText('Asia/Kolkata time')).toBeInTheDocument()
    expect(within(card).getByText('Completed').nextElementSibling).toHaveTextContent('2')
    expect(within(card).getByText(/Cart API/)).toBeInTheDocument()
    const arun = within(card).getByText('Arun').closest('li')!
    expect(within(arun).getByText('Overloaded')).toBeInTheDocument()
    const priya = within(card).getByText('Priya').closest('li')!
    expect(within(priya).getByText('Free')).toBeInTheDocument()
  })
})
