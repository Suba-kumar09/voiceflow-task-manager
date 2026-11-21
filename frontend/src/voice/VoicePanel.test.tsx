import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../app/App'
import type { VoiceTurn } from '../services/api'
import { manager, mockApi, ok, progress, project, shellRoutes } from '../tests/mockApi'

const spoken: string[] = []

class FakeUtterance {
  text: string
  voice: unknown = null
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

beforeEach(() => {
  spoken.length = 0
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  vi.stubGlobal('speechSynthesis', {
    speak: (u: FakeUtterance) => {
      spoken.push(u.text)
      u.onend?.()
    },
    cancel: () => {},
    getVoices: () => [],
  })
  window.history.pushState({}, '', '/projects')
})
afterEach(() => vi.unstubAllGlobals())

function turn(overrides: Partial<VoiceTurn>): VoiceTurn {
  return {
    transcript: null,
    heard_clearly: true,
    intent: 'nav.project',
    slots: {},
    outcome: 'ok',
    speech: '',
    action: null,
    suggestions: [],
    checks: [],
    plan: [],
    awaiting_confirmation: false,
    trace_id: null,
    stt_ms: null,
    total_ms: 5,
    ...overrides,
  }
}

function routes(onTurn: (body: { text: string; path: string; page_summary?: string }) => VoiceTurn) {
  return {
    ...shellRoutes(manager),
    'GET /api/v1/projects/p1/progress': ok(progress),
    'GET /api/v1/projects/p1': ok(project),
    'GET /api/v1/tasks?limit=200&project_id=p1': ok({ items: [], total: 0, limit: 200, offset: 0 }),
    'POST /api/v1/voice/turns': (init: RequestInit | undefined) => ({ status: 200, body: onTurn(JSON.parse(String(init?.body))) }),
  }
}

describe('voice panel', () => {
  it('a typed command navigates, shows captions and speaks the reply', async () => {
    let sent: { text: string; path: string } | undefined
    mockApi(
      routes((body) => {
        sent = body
        return turn({ transcript: body.text, speech: 'Opening E-Commerce. 3 of 12 tasks are done.', action: { type: 'navigate', to: '/projects/p1' } })
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Projects' })
    await user.click(screen.getByRole('button', { name: 'Type instead' }))
    await user.type(screen.getByLabelText('Type a command'), 'open the e-commerce project')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(window.location.pathname).toBe('/projects/p1'))
    expect(sent?.path).toBe('/projects')
    const panel = screen.getByRole('region', { name: 'Voice assistant' })
    expect(within(panel).getByText('Opening E-Commerce. 3 of 12 tasks are done.')).toBeInTheDocument()
    await waitFor(() => expect(spoken).toEqual(['Opening E-Commerce. 3 of 12 tasks are done.']))
    expect(within(panel).getByRole('status')).toHaveTextContent('Ready')
  })

  it('"read this page" sends the current screen summary', async () => {
    let summary: string | undefined
    mockApi(
      routes((body) => {
        summary = body.page_summary
        return turn({ intent: 'read_page', speech: body.page_summary ?? '' })
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('1 needs decision')
    await user.click(screen.getByRole('button', { name: 'Type instead' }))
    await user.type(screen.getByLabelText('Type a command'), 'read this page{Enter}')
    await waitFor(() => expect(summary).toMatch(/^Projects\. You have 1 project: 1 active/))
  })

  it('mute stops spoken replies but still shows captions', async () => {
    mockApi(routes(() => turn({ intent: 'help', speech: 'You can say: open the E-Commerce project.' })))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Projects' })
    await user.click(screen.getByRole('button', { name: 'Mute' }))
    expect(screen.getByRole('button', { name: 'Talk to VoiceFlow' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '“What is still pending?”' }))
    expect(await screen.findByText('You can say: open the E-Commerce project.')).toBeInTheDocument()
    expect(spoken).toEqual([])
  })

  it('reads a change back with checks and a plan, and only acts after Yes', async () => {
    const said: string[] = []
    const { calls } = mockApi(
      routes((body) => {
        said.push(body.text)
        if (body.text === 'yes') {
          return turn({ intent: 'confirm.yes', outcome: 'done', speech: 'Done. I assigned Wishlist page to Priya.' })
        }
        return turn({
          intent: 'project.assign_ready',
          outcome: 'confirm',
          awaiting_confirmation: true,
          speech: 'By priority: Wishlist page to Priya. Shall I assign 1 task?',
          checks: [{ text: '2 tasks are ready (dependencies done)', state: 'ok' }],
          plan: [
            { key: 'EC10', title: 'Wishlist page', priority: 'HIGH', outcome: 'ASSIGN', assignee: 'Priya', reason: '' },
            { key: 'EC11', title: 'iOS build setup', priority: 'MEDIUM', outcome: 'NO_QUALIFIED', assignee: null, reason: '' },
          ],
        })
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Projects' })
    await user.click(screen.getByRole('button', { name: '“Assign the ready tasks by priority”' }))

    const panel = screen.getByRole('region', { name: 'Voice assistant' })
    expect(await within(panel).findByRole('list', { name: 'Checks' })).toHaveTextContent('2 tasks are ready')
    const plan = within(panel).getByRole('list', { name: 'Assignment plan' })
    expect(plan).toHaveTextContent('Priya')
    expect(plan).toHaveTextContent('Needs your decision')
    await waitFor(() => expect(within(panel).getByRole('status')).toHaveTextContent('Waiting for your yes'))
    expect(said).toEqual(['Assign the ready tasks by priority']) // nothing confirmed yet

    const tasksFetchesBefore = calls.filter((c) => c.key.startsWith('GET /api/v1/projects')).length
    await user.click(within(panel).getByRole('button', { name: 'Yes, do it' }))
    expect(await within(panel).findByText('Done. I assigned Wishlist page to Priya.')).toBeInTheDocument()
    expect(said).toEqual(['Assign the ready tasks by priority', 'yes'])
    expect(within(panel).queryByRole('button', { name: 'Yes, do it' })).not.toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.key.startsWith('GET /api/v1/projects')).length).toBeGreaterThan(tasksFetchesBefore))
  })

  it('never pretends to listen when there is no microphone', async () => {
    mockApi(routes(() => turn({})))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Projects' })
    await user.click(screen.getByRole('button', { name: 'Talk to VoiceFlow' }))
    const panel = screen.getByRole('region', { name: 'Voice assistant' })
    expect(await within(panel).findByRole('status')).toHaveTextContent('Microphone unavailable')
    expect(within(panel).getByRole('alert')).toHaveTextContent('No microphone is available')
    expect(within(panel).queryByText('Listening')).not.toBeInTheDocument()
  })
})
