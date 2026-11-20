import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router'

import { Avatar } from '../components/ui/Avatar'
import { useAuth, useMe } from '../features/auth/auth-context'
import { useNotifications } from '../features/notifications/useNotifications'
import { projectsApi } from '../services/api'
import { brand } from './brand'

const ICONS = {
  projects: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  team: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
  work: 'M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9 M13.73 21a2 2 0 0 1-3.46 0',
  status: 'M22 12h-4l-3 9L9 3l-3 9H2',
}

const roleLabel = { ADMIN: 'Administrator', MANAGER: 'Manager', EMPLOYEE: 'Employee' } as const

function NavItem({ to, icon, label, badge }: { to: string; icon: string; label: string; badge?: number }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition ${isActive ? 'bg-[#142034] font-semibold text-white' : 'font-medium text-[#b6c2d3] hover:bg-[#0f1829] hover:text-white'}`
      }
    >
      {({ isActive }) => (
        <>
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={isActive ? '#2dd4bf' : 'currentColor'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d={icon} />
          </svg>
          <span className="flex-1">{label}</span>
          {!!badge && (
            <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-[11px] font-bold text-accent-ink">
              {badge}
              <span className="sr-only"> unread</span>
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

function SidebarProjects() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: projectsApi.list })
  const location = useLocation()
  if (!projects.data?.length) return null
  return (
    <div>
      <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-[#7c8aa0]">Your projects</p>
      <ul className="flex flex-col gap-0.5">
        {projects.data.map((p) => {
          const active = location.pathname === `/projects/${p.id}`
          return (
            <li key={p.id}>
              <NavLink
                to={`/projects/${p.id}`}
                className={`flex min-h-9 items-center gap-2.5 rounded-lg px-3 py-1.5 text-[13px] ${active ? 'bg-[#142034] text-white' : 'text-[#b6c2d3] hover:bg-[#0f1829] hover:text-white'}`}
              >
                <span aria-hidden="true" className={`size-2 shrink-0 rounded-sm ${p.status === 'ACTIVE' ? 'bg-accent-strong' : 'bg-[#4b5b74]'}`} />
                <span className="truncate">{p.name}</span>
              </NavLink>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Slot for the voice assistant (Phase 6). It never pretends the microphone is on. */
function VoicePanel() {
  return (
    <section aria-label="Voice assistant" className="sticky bottom-0 border-t border-line bg-panel-2/95 px-6 py-3 backdrop-blur">
      <div className="flex items-center gap-4">
        <button
          type="button"
          disabled
          aria-label="Voice control is not available yet"
          className="grid size-12 shrink-0 cursor-not-allowed place-items-center rounded-full border border-control-line bg-control text-ink-faint"
        >
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        </button>
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            <span aria-hidden="true" className="size-2 rounded-full bg-[#4b5b74]" />
            Microphone off
          </p>
          <p className="text-sm text-ink-muted">Voice control arrives in the next phase. Until then, use the buttons on screen.</p>
        </div>
      </div>
    </section>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe()
  const { signOut } = useAuth()
  const [signingOut, setSigningOut] = useState(false)
  const notes = useNotifications()
  const unread = notes.data?.unread ?? 0
  const isEmployee = me.role === 'EMPLOYEE'

  return (
    <div className="flex min-h-dvh flex-wrap font-sans">
      <aside className="flex w-full flex-col gap-6 border-r border-[#172236] bg-sidebar px-3 py-5 md:sticky md:top-0 md:h-dvh md:w-64 md:overflow-y-auto">
        <div className="flex items-center gap-2.5 px-2">
          <div aria-hidden="true" className="grid size-9 place-items-center rounded-xl bg-accent text-base font-extrabold text-accent-ink">
            {brand.name.charAt(0)}
          </div>
          <div className="leading-tight">
            <p className="font-bold text-white">{brand.name}</p>
            <p className="text-xs text-[#7c8aa0]">{me.organization.name.replace(' (DEMO DATA)', '')}</p>
          </div>
        </div>

        <nav aria-label="Main" className="flex flex-col gap-0.5">
          {isEmployee ? (
            <NavItem to="/my-work" icon={ICONS.work} label="My work" />
          ) : (
            <>
              <NavItem to="/projects" icon={ICONS.projects} label="Projects" />
              <NavItem to="/team" icon={ICONS.team} label="Team" />
            </>
          )}
          <NavItem to="/notifications" icon={ICONS.bell} label="Notifications" badge={unread} />
          <NavItem to="/system" icon={ICONS.status} label="System status" />
        </nav>

        {!isEmployee && <SidebarProjects />}

        <div className="mt-auto flex items-center gap-2.5 rounded-xl border border-[#172236] bg-[#0f1829] p-3">
          <Avatar name={me.display_name} seed={me.id} size={34} />
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate text-sm font-semibold text-white">{me.display_name}</p>
            <p className="text-xs text-[#7c8aa0]">{roleLabel[me.role]}</p>
          </div>
          <button
            type="button"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true)
              void signOut()
            }}
            className="rounded-lg px-2 py-1 text-xs font-semibold text-[#b6c2d3] hover:bg-[#142034] hover:text-white disabled:opacity-50"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-[999_1_640px] flex-col">
        {me.organization.is_demo && (
          <div role="note" className="border-b border-[#3b2f12] bg-[rgba(251,191,36,.08)] px-6 py-1.5 text-center text-xs font-medium text-warn">
            Demo data — {me.organization.name}
          </div>
        )}
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-7">{children}</main>
        <VoicePanel />
      </div>
    </div>
  )
}
