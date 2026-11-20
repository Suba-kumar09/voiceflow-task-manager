import { createContext, useContext } from 'react'

import type { Me } from '../../services/api'

export type AuthState =
  | { status: 'loading' }
  | { status: 'signed-out'; notice?: string }
  | { status: 'signed-in'; me: Me }

export interface AuthContextValue {
  state: AuthState
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** For screens that only render when signed in. */
export function useMe(): Me {
  const { state } = useAuth()
  if (state.status !== 'signed-in') throw new Error('useMe called while not signed in')
  return state.me
}
