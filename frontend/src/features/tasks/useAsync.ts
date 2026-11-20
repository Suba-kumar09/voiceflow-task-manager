import { useEffect, useState } from 'react'

import { ApiError } from '../../services/api'

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

/** Load data once per `deps` change, with cancellation and a readable error message. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    load()
      .then((data) => !cancelled && setState({ status: 'ready', data }))
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof ApiError && err.status === 403
            ? 'You do not have access to this.'
            : 'Could not load this. Try again shortly.'
        setState({ status: 'error', message })
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
