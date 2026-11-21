import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { useNotifications } from '../features/notifications/useNotifications'
import { preferencesApi, type AppNotification } from '../services/api'

/** Text spoken for a batch of new notifications (at most two read in full). */
export function announcementText(items: Pick<AppNotification, 'title'>[]): string {
  if (items.length === 0) return ''
  if (items.length === 1) return `New notification: ${items[0].title}.`
  const more = items.length - 2
  return (
    `${items.length} new notifications. ${items[0].title}. ${items[1].title}.` +
    (more > 0 ? ` And ${more} more. Say "read my notifications" to hear them.` : '')
  )
}

/**
 * Reads NEW notifications aloud, as they arrive, when the person allows it.
 * - Never reads the backlog that already existed when the app opened.
 * - Respects the "spoken notifications" setting and quiet hours (worked out by the server).
 * - Waits while the assistant is busy, listening or muted: announce() returns false and
 *   this effect runs again when announce changes (i.e. when the assistant becomes idle).
 */
export function useAnnouncements(announce: (text: string) => boolean) {
  const notes = useNotifications()
  const prefs = useQuery({ queryKey: ['preferences'], queryFn: preferencesApi.get, refetchInterval: 5 * 60_000 })
  const seen = useRef<Set<string> | null>(null)
  const queue = useRef<AppNotification[]>([])

  const items = notes.data?.items
  const p = prefs.data

  useEffect(() => {
    if (!items || !p) return // wait until we know both the list and the person's preference
    if (seen.current === null) {
      seen.current = new Set(items.map((n) => n.id)) // first load: the backlog is never spoken
      return
    }
    const known = seen.current
    const fresh = items.filter((n) => !n.read && !known.has(n.id))
    fresh.forEach((n) => known.add(n.id))
    queue.current.push(...fresh.reverse()) // oldest first

    if (queue.current.length === 0) return
    if (!p.voice_announcements || p.quiet_now) {
      queue.current = [] // not spoken; they stay in the Notifications list
      return
    }
    if (announce(announcementText(queue.current))) queue.current = []
  }, [items, p, announce])
}
