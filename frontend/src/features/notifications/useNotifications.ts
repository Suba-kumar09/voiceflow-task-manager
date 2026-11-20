import { useQuery } from '@tanstack/react-query'

import { notificationsApi } from '../../services/api'

/** Shared by the sidebar badge and the Notifications page; refreshes every 30 s. */
export function useNotifications() {
  return useQuery({ queryKey: ['notifications'], queryFn: notificationsApi.list, refetchInterval: 30_000 })
}
