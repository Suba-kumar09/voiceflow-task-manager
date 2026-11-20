import { render, screen, within } from '@testing-library/react'
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
