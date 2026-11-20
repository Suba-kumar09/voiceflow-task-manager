import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router'

import { useAuth, useMe } from '../features/auth/auth-context'
import { brand } from './brand'

const roleLabel = { ADMIN: 'Administrator', MANAGER: 'Manager', EMPLOYEE: 'Employee' } as const

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-accent ${
          isActive ? 'bg-accent-soft text-accent' : 'text-ink-muted hover:text-ink'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe()
  const { signOut } = useAuth()
  const [signingOut, setSigningOut] = useState(false)

  return (
    <div className="flex min-h-dvh flex-col font-sans">
      {me.organization.is_demo && (
        <div role="note" className="bg-warn/15 px-4 py-1.5 text-center text-xs font-medium text-warn">
          Demo data — {me.organization.name}
        </div>
      )}

      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div
              aria-hidden="true"
              className="grid size-8 place-items-center rounded-lg bg-accent text-sm font-bold text-panel"
            >
              {brand.name.charAt(0)}
            </div>
            <span className="text-base font-semibold">{brand.name}</span>
          </div>

          <nav aria-label="Main" className="flex gap-1">
            <NavItem to="/">Home</NavItem>
            <NavItem to="/system">System status</NavItem>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <div className="text-right leading-tight">
              <p className="text-sm font-medium">{me.display_name}</p>
              <p className="text-xs text-ink-muted">{roleLabel[me.role]}</p>
            </div>
            <button
              type="button"
              disabled={signingOut}
              onClick={() => {
                setSigningOut(true)
                void signOut()
              }}
              className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">{children}</main>
    </div>
  )
}
