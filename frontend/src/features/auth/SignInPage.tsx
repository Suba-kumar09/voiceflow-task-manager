import { useId, useState, type FormEvent } from 'react'

import { brand } from '../../app/brand'
import { ApiError } from '../../services/api'
import { useAuth } from './auth-context'

export function SignInPage({ notice }: { notice?: string }) {
  const { signIn } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const userId = useId()
  const passId = useId()
  const errId = useId()

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      await signIn(username, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  const message = error ?? notice ?? null

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10 font-sans">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div
            aria-hidden="true"
            className="mb-4 grid size-12 place-items-center rounded-xl bg-accent text-lg font-bold text-panel"
          >
            {brand.name.charAt(0)}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Sign in to {brand.name}</h1>
          <p className="mt-1 text-sm text-ink-muted">{brand.tagline}</p>
        </div>

        <form
          onSubmit={onSubmit}
          noValidate
          aria-describedby={message ? errId : undefined}
          className="rounded-2xl border border-line bg-panel p-6 shadow-sm"
        >
          {message && (
            <p
              id={errId}
              role="alert"
              className="mb-4 rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad"
            >
              {message}
            </p>
          )}

          <label htmlFor={userId} className="block text-sm font-medium">
            Username
          </label>
          <input
            id={userId}
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 mb-4 w-full rounded-lg border border-line bg-surface px-3 py-2 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
          />

          <label htmlFor={passId} className="block text-sm font-medium">
            Password
          </label>
          <input
            id={passId}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 mb-6 w-full rounded-lg border border-line bg-surface px-3 py-2 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
          />

          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-panel transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-ink-muted">
          Signing in is a one-time setup step. Day-to-day work happens by voice.
        </p>
      </div>
    </main>
  )
}
