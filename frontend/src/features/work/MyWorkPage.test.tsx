import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { employee, mockApi, ok, page, shellRoutes, task } from '../../tests/mockApi'

beforeEach(() => window.history.pushState({}, '', '/my-work'))

describe('my work (employee)', () => {
  it('cannot report a NOTE task done without a note, and sends the note to review', async () => {
    const noteTask = task({ evidence_policy: 'NOTE' })
    let sent: unknown
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': ok({ task: noteTask }),
      'GET /api/v1/me/tasks?limit=200': ok(page([noteTask])),
      'POST /api/v1/tasks/task1/request-completion': (init) => {
        sent = JSON.parse(String(init?.body))
        return { status: 200, body: { ...noteTask, status: 'PENDING_REVIEW' } }
      },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Report done' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/manager will be notified and will review it/)).toBeInTheDocument()
    const submit = within(dialog).getByRole('button', { name: 'Send for review' })
    expect(submit).toBeDisabled()

    await user.type(within(dialog).getByLabelText(/Completion note/), 'All products show price, stock and images.')
    await user.click(submit)
    expect(sent).toEqual({ note: 'All products show price, stock and images.' })
  })

  it('asks for more time with a date and a reason; shows the pending request afterwards', async () => {
    let sent: { requested_due_at: string; reason: string } | undefined
    let current = task()
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': () => ({ status: 200, body: { task: current } }),
      'GET /api/v1/me/tasks?limit=200': () => ({ status: 200, body: page([current]) }),
      'POST /api/v1/tasks/task1/extension-requests': (init) => {
        sent = JSON.parse(String(init?.body))
        current = task({ pending_extension: { id: 'e1', requested_due_at: sent!.requested_due_at, reason: sent!.reason } })
        return { status: 201, body: {} }
      },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Need more time' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/the deadline changes only if they approve/)).toBeInTheDocument()
    const send = within(dialog).getByRole('button', { name: 'Send request' })
    expect(send).toBeDisabled()
    // Date pickers report their value through a change event (typing does not apply in jsdom).
    fireEvent.change(within(dialog).getByLabelText(/New due date/), { target: { value: '2026-11-30' } })
    await user.type(within(dialog).getByLabelText(/Why do you need more time/), 'The design changed')
    expect(within(dialog).getByLabelText(/New due date/)).toHaveValue('2026-11-30')
    expect(within(dialog).getByLabelText(/Why do you need more time/)).toHaveValue('The design changed')
    expect(send).toBeEnabled()
    await user.click(send)
    await waitFor(() => expect(sent?.reason).toBe('The design changed'))
    expect(new Date(sent!.requested_due_at).toISOString()).toBe(sent!.requested_due_at) // a real timestamp
    expect(await screen.findByText(/waiting for your manager/)).toBeInTheDocument()
  })

  it('a blocker needs a reason', async () => {
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': ok({ task: task() }),
      'GET /api/v1/me/tasks?limit=200': ok(page([task()])),
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'I’m blocked' }))
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Report blocker' })).toBeDisabled()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('says plainly when nothing is assigned', async () => {
    mockApi({
      ...shellRoutes(employee),
      'GET /api/v1/me/tasks/current': ok({ task: null }),
      'GET /api/v1/me/tasks?limit=200': ok(page([])),
    })
    render(<App />)
    expect(await screen.findByText('Nothing assigned right now')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Talk to VoiceFlow' })).toBeEnabled()
  })
})
