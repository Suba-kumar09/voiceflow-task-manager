import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { manager, mockApi, prefs, shellRoutes } from '../../tests/mockApi'

beforeEach(() => window.history.pushState({}, '', '/settings'))
afterEach(() => vi.restoreAllMocks())

describe('settings', () => {
  it('turns spoken notifications off and sets quiet hours', async () => {
    let sent: Record<string, unknown> | undefined
    mockApi({
      ...shellRoutes(manager),
      'PATCH /api/v1/users/me/preferences': (init) => {
        sent = JSON.parse(String(init?.body))
        return { status: 200, body: { ...prefs, voice_announcements: false, quiet_start: '21:00:00', quiet_end: '08:00:00' } }
      },
    })
    const user = userEvent.setup()
    render(<App />)

    const voice = await screen.findByLabelText(/Read new notifications aloud/)
    expect(voice).toBeChecked()
    const save = screen.getByRole('button', { name: 'Save settings' })
    expect(save).toBeDisabled() // nothing changed yet

    await user.click(voice)
    await user.click(screen.getByRole('checkbox', { name: /Quiet hours/ }))
    expect(screen.getByLabelText('From')).toHaveValue('21:00')
    expect(screen.getByLabelText('Until')).toHaveValue('08:00')
    await user.click(save)

    await waitFor(() => expect(sent).toEqual({ voice_announcements: false, quiet_start: '21:00', quiet_end: '08:00' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })
})
