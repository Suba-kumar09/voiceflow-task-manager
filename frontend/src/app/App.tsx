import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AuthProvider } from '../features/auth/AuthProvider'
import { useAuth } from '../features/auth/auth-context'
import { SignInPage } from '../features/auth/SignInPage'
import { HomePage } from '../features/home/HomePage'
import { SystemStatus } from '../features/system/SystemStatus'
import { AppShell } from './AppShell'

function Gate() {
  const { state } = useAuth()

  if (state.status === 'loading') {
    return (
      <div className="grid min-h-dvh place-items-center font-sans text-sm text-ink-muted" aria-live="polite">
        Loading…
      </div>
    )
  }
  if (state.status === 'signed-out') {
    return <SignInPage notice={state.notice} />
  }
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route
          path="/system"
          element={
            <div className="flex justify-center">
              <SystemStatus />
            </div>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  )
}
