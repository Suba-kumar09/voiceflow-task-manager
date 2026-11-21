import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AppNotification, Preferences } from '../services/api'
import { mockApi, ok, prefs } from '../tests/mockApi'
import { announcementText, useAnnouncements } from './useAnnouncements'

afterEach(() => vi.restoreAllMocks())

const note = (id: string, title: string, read = false): AppNotification => ({
  id,
  kind: 'TASK_ASSIGNED',
  title,
  body: '',
  task_id: null,
  project_id: null,
  created_at: '2026-11-21T10:00:00Z',
  read,
})

function Probe({ announce }: { announce: (t: string) => boolean }) {
  useAnnouncements(announce)
  return null
}

/** Renders the hook; `setNotes` changes what the next notifications fetch returns. */
function setup(preferences: Preferences, announce: (t: string) => boolean) {
  let current: AppNotification[] = [note('old', 'Old news')]
  mockApi({
    'GET /api/v1/notifications?limit=100': () => ({
      status: 200,
      body: { items: current, total: current.length, unread: current.length, limit: 100, offset: 0 },
    }),
    'GET /api/v1/users/me/preferences': ok(preferences),
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Probe announce={announce} />
    </QueryClientProvider>,
  )
  return {
    async arrive(...items: AppNotification[]) {
      current = [...items, ...current]
      await client.invalidateQueries({ queryKey: ['notifications'] })
    },
    client,
  }
}

describe('spoken notifications', () => {
  it('builds short spoken text', () => {
    expect(announcementText([{ title: 'Meena completed UI mockups' }])).toBe('New notification: Meena completed UI mockups.')
    expect(announcementText([{ title: 'A' }, { title: 'B' }, { title: 'C' }])).toBe(
      '3 new notifications. A. B. And 1 more. Say "read my notifications" to hear them.',
    )
  })

  it('reads only notifications that arrive after opening, never the backlog', async () => {
    const announce = vi.fn(() => true)
    const s = setup(prefs, announce)
    await waitFor(() => expect(s.client.getQueryData(['notifications'])).toBeDefined())
    await waitFor(() => expect(s.client.getQueryData(['preferences'])).toBeDefined())
    expect(announce).not.toHaveBeenCalled()

    await s.arrive(note('n1', 'Meena completed UI mockups'))
    await waitFor(() => expect(announce).toHaveBeenCalledWith('New notification: Meena completed UI mockups.'))
    expect(announce).toHaveBeenCalledTimes(1)
  })

  it('stays silent when spoken notifications are off or during quiet hours', async () => {
    for (const p of [{ ...prefs, voice_announcements: false }, { ...prefs, quiet_now: true }]) {
      const announce = vi.fn(() => true)
      const s = setup(p, announce)
      await waitFor(() => expect(s.client.getQueryData(['preferences'])).toBeDefined())
      await waitFor(() => expect(s.client.getQueryData(['notifications'])).toBeDefined())
      await s.arrive(note('n2', 'New task'))
      await new Promise((r) => setTimeout(r, 50))
      expect(announce).not.toHaveBeenCalled()
      vi.restoreAllMocks()
    }
  })

  it('waits while the assistant is busy, then speaks', async () => {
    let busy = true
    const announce = vi.fn(() => !busy)
    const s = setup(prefs, announce)
    await waitFor(() => expect(s.client.getQueryData(['preferences'])).toBeDefined())
    await waitFor(() => expect(s.client.getQueryData(['notifications'])).toBeDefined())
    await s.arrive(note('n3', 'Arun asked for more time'))
    await waitFor(() => expect(announce).toHaveBeenCalledTimes(1)) // tried, but busy
    busy = false
    await s.arrive(note('n4', 'Cart API is overdue')) // next refresh: both are spoken together
    await waitFor(() =>
      expect(announce).toHaveBeenLastCalledWith('2 new notifications. Arun asked for more time. Cart API is overdue.'),
    )
  })
})
