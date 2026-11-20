import { useQuery } from '@tanstack/react-query'

import { Avatar } from '../../components/ui/Avatar'
import { Card, Empty, ErrorBox, Loading } from '../../components/ui/States'
import { peopleApi } from '../../services/api'
import { useMe } from '../auth/auth-context'

function TeamRoster({ teamId, teamName }: { teamId: string; teamName: string }) {
  const roster = useQuery({ queryKey: ['roster', teamId], queryFn: () => peopleApi.teamEmployees(teamId) })
  return (
    <Card>
      <h2 className="text-base font-semibold text-ink-strong">{teamName}</h2>
      {roster.isLoading && <Loading />}
      {roster.isError && <ErrorBox error={roster.error} />}
      <ul className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
        {roster.data?.items.map((e) => (
          <li key={e.id} className="flex items-center gap-3 rounded-xl border border-line-soft bg-inset px-3 py-2.5">
            <Avatar name={e.display_name} seed={e.id} size={36} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{e.display_name}</p>
              <p className="text-xs text-ink-muted">{e.membership_role === 'MANAGER' ? 'Manager' : 'Team member'}{e.is_active ? '' : ' · inactive'}</p>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-faint">Workload and current tasks are on each project’s Team tab.</p>
    </Card>
  )
}

export function TeamPage() {
  const me = useMe()
  const managed = me.teams.filter((t) => t.membership_role === 'MANAGER')
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Team</h1>
        <p className="mt-1 text-sm text-ink-muted">Everyone in the teams you manage.</p>
      </div>
      {managed.length === 0 && <Empty>You do not manage a team yet.</Empty>}
      {managed.map((t) => (
        <TeamRoster key={t.team_id} teamId={t.team_id} teamName={t.team_name} />
      ))}
    </div>
  )
}
