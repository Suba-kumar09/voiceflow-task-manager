import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  ApiError,
  authApi,
  setCsrfToken,
  setUnauthorizedHandler,
  type Me,
} from '../../services/api'
import { AuthContext, type AuthState } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  const applySignedIn = useCallback((me: Me) => {
    setCsrfToken(me.csrf_token)
    setState({ status: 'signed-in', me })
  }, [])

  const applySignedOut = useCallback((notice?: string) => {
    setCsrfToken(null)
    setState({ status: 'signed-out', notice })
  }, [])

  // Restore an existing session on load; 401 just means "not signed in".
  useEffect(() => {
    let cancelled = false
    authApi
      .me()
      .then((me) => !cancelled && applySignedIn(me))
      .catch((err: unknown) => {
        if (cancelled) return
        const offline = err instanceof ApiError && err.code === 'network_error'
        applySignedOut(offline ? 'Cannot reach the VoiceFlow server.' : undefined)
      })
    return () => {
      cancelled = true
    }
  }, [applySignedIn, applySignedOut])

  // Any later 401 (expired or revoked session) returns the user to sign-in with a clear reason.
  useEffect(() => {
    setUnauthorizedHandler(() => applySignedOut('Your session ended. Please sign in again.'))
    return () => setUnauthorizedHandler(null)
  }, [applySignedOut])

  const signIn = useCallback(
    async (username: string, password: string) => {
      applySignedIn(await authApi.login(username, password))
    },
    [applySignedIn],
  )

  const signOut = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      applySignedOut()
    }
  }, [applySignedOut])

  const value = useMemo(() => ({ state, signIn, signOut }), [state, signIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
