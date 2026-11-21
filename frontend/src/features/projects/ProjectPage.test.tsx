import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { manager, mockApi, ok, page, plan, progress, project, shellRoutes, task } from '../../tests/mockApi'

const review = task({ id: 'task9', external_key: 'EC02', title: 'UI design mockups', status: 'PENDING_REVIEW', assignee: { id: 'u-mee', display_name: 'Meena' }, depends_on: [] })
const waiting = task({ id: 'task7', external_key: 'EC06', title: 'Checkout UI', status: 'UNASSIGNED', assignee: null, depends_on: ['EC02', 'EC04'] })

function routes(extra = {}) {
  return {
    ...shellRoutes(manager),
    'GET /api/v1/projects/p1': ok(project),
    'GET /api/v1/projects/p1/progress': ok(progress),
    'GET /api/v1/tasks?limit=200&project_id=p1': ok(page([task(), review, waiting])),
    'GET /api/v1/extension-requests?project_id=p1': ok([extension]),
    ...extra,
  }
}

const extension = {
  id: 'ext1',
  task_id: 'task1',
  task_title: 'Product listing page',
  task_key: 'EC05',
  project_id: 'p1',
  requested_by: 'Subashini',
  previous_due_at: '2026-11-27T12:30:00Z',
  requested_due_at: '2026-11-30T12:30:00Z',
  reason: 'The design changed',
  status: 'PENDING',
  decision_note: null,
  created_at: '2026-11-21T10:00:00Z',
}

describe('project page (manager)', () => {
  it('shows who has which task, dependencies, and lets the manager approve with CSRF + idempotency', async () => {
    window.history.pushState({}, '', '/projects/p1?tab=tasks')
    let headers: Record<string, string> = {}
    const { calls } = mockApi(
      routes({
        'POST /api/v1/tasks/task9/approve-completion': (init: RequestInit | undefined) => {
          headers = init?.headers as Record<string, string>
          return { status: 200, body: { ...review, status: 'COMPLETED' } }
        },
      }),
    )
    render(<App />)
    const table = await screen.findByRole('table')
    const checkout = within(table).getByText('Checkout UI').closest('tr')!
    expect(within(checkout).getByText('Not assigned')).toBeInTheDocument()
    expect(within(checkout).getByText('EC02, EC04')).toBeInTheDocument()
    const listing = within(table).getByText('Product listing page').closest('tr')!
    expect(within(listing).getByText('Subashini')).toBeInTheDocument()
    expect(within(listing).getByText('Needs React')).toBeInTheDocument()

    await userEvent.setup().click(within(table).getByRole('button', { name: 'Approve' }))
    await screen.findByRole('table')
    expect(calls.some((c) => c.key === 'POST /api/v1/tasks/task9/approve-completion')).toBe(true)
    expect(headers['X-CSRF-Token']).toBe('csrf-123')
    expect(headers['Idempotency-Key']).toMatch(/.{8,}/)
  })

  it('overview lists what needs attention: review, decisions', async () => {
    window.history.pushState({}, '', '/projects/p1')
    mockApi(routes())
    render(<App />)
    expect(await screen.findByText(/UI design mockups is awaiting your review/)).toBeInTheDocument()
    expect(screen.getByText(/iOS build setup needs your decision/)).toBeInTheDocument()
    expect(screen.getByText('No one on the team has ios.')).toBeInTheDocument()
  })

  it('shows extension requests and approves one', async () => {
    window.history.pushState({}, '', '/projects/p1')
    const { calls } = mockApi(routes({ 'POST /api/v1/extension-requests/ext1/approve': ok({ ...extension, status: 'APPROVED' }) }))
    render(<App />)
    const item = (await screen.findByText(/Subashini asks for more time on EC05 · Product listing page/)).closest('div')!.parentElement!
    expect(item).toHaveTextContent('Reason: “The design changed”')
    await userEvent.setup().click(within(item).getByRole('button', { name: 'Approve' }))
    await screen.findByText(/Subashini asks for more time/)
    expect(calls.some((c) => c.key === 'POST /api/v1/extension-requests/ext1/approve')).toBe(true)
  })

  it('"Assign ready tasks" reads the plan back, then assigns on confirmation', async () => {
    window.history.pushState({}, '', '/projects/p1')
    const { calls } = mockApi(
      routes({
        'GET /api/v1/projects/p1/assignment-plan': ok(plan),
        'POST /api/v1/projects/p1/assign-ready': ok({
          project_id: 'p1',
          assigned: [{ task_id: 'a', key: 'EC10', title: 'Wishlist page', priority: 'HIGH', reason: '', assignee_name: 'Priya' }],
          waiting_for_capacity: [],
          needs_decision: [],
          skipped: [],
        }),
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Assign ready tasks' }))
    const dialog = await screen.findByRole('dialog', { name: 'Assign the ready tasks by priority' })
    expect(await within(dialog).findByText('Needs react; Priya has no active task.')).toBeInTheDocument()
    expect(within(dialog).getByText('Needs your decision')).toBeInTheDocument()
    expect(calls.some((c) => c.key.startsWith('POST'))).toBe(false) // nothing changed yet

    await user.click(within(dialog).getByRole('button', { name: 'Assign 1 task' }))
    expect(await screen.findByRole('dialog', { name: 'Tasks assigned' })).toHaveTextContent('Priya')
  })
})
