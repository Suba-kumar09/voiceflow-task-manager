import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useMemo } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AuthProvider } from '../features/auth/AuthProvider'
import { useAuth } from '../features/auth/auth-context'
import { SignInPage } from '../features/auth/SignInPage'
import { NotificationsPage } from '../features/notifications/NotificationsPage'
import { ProjectPage } from '../features/projects/ProjectPage'
import { ProjectsPage } from '../features/projects/ProjectsPage'
import { SystemStatus } from '../features/system/SystemStatus'
import { TeamPage } from '../features/team/TeamPage'
import { MyWorkPage } from '../features/work/MyWorkPage'
import { ApiError } from '../services/api'
import { AppShell } from './AppShell'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Do not hammer the server on permission or validation errors; retry once on network blips.
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 1,
        refetchOnWindowFocus: true,
        staleTime: 5_000,
      },
    },
  })
}

function Gate() {
  const { state } = useAuth()
  const userId = state.status === 'signed-in' ? state.me.id : null
  // A fresh cache per signed-in user: one person's data never shows for the next.
  const client = useMemo(() => makeQueryClient(), [userId]) // eslint-disable-line react-hooks/exhaustive-deps

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
  const home = state.me.role === 'EMPLOYEE' ? '/my-work' : '/projects'
  return (
    <QueryClientProvider client={client}>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/my-work" element={<MyWorkPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route
            path="/system"
            element={
              <div className="flex justify-center">
                <SystemStatus />
              </div>
            }
          />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </AppShell>
    </QueryClientProvider>
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
