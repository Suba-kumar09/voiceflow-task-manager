import { useMe } from '../auth/auth-context'
import { TeamRoster } from './TeamRoster'

function VoiceComingSoon() {
  return (
    <section
      aria-label="Voice assistant"
      className="rounded-2xl border border-dashed border-line bg-panel p-5 text-sm text-ink-muted"
    >
      <p className="font-medium text-ink">Voice assistant</p>
      <p className="mt-1">
        Voice control (“open my tasks”, “start the project”, “I’m done”) is added in a later
        phase. This screen shows what your account can access today.
      </p>
    </section>
  )
}

export function HomePage() {
  const me = useMe()
  const managed = me.teams.filter((t) => t.membership_role === 'MANAGER')
  const memberOf = me.teams.filter((t) => t.membership_role === 'MEMBER')

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome, {me.display_name}</h1>
        <p className="mt-1 text-sm text-ink-muted">{me.organization.name}</p>
      </div>

      <VoiceComingSoon />

      {me.role === 'MANAGER' && (
        <section aria-labelledby="my-teams" className="flex flex-col gap-4">
          <h2 id="my-teams" className="text-lg font-semibold">
            Teams you manage
          </h2>
          {managed.length === 0 ? (
            <p className="text-sm text-ink-muted">You are not assigned to manage any team yet.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {managed.map((t) => (
                <TeamRoster key={t.team_id} teamId={t.team_id} teamName={t.team_name} />
              ))}
            </div>
          )}
        </section>
      )}

      {me.role === 'EMPLOYEE' && (
        <section
          aria-labelledby="my-work"
          className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
        >
          <h2 id="my-work" className="text-lg font-semibold">
            Your work
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {memberOf.length > 0
              ? `You are on the ${memberOf.map((t) => t.team_name).join(', ')} team.`
              : 'You are not on a team yet. Your manager will add you.'}{' '}
            Your tasks will appear here once task management is added.
          </p>
        </section>
      )}

      {me.role === 'ADMIN' && (
        <section
          aria-labelledby="admin"
          className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
        >
          <h2 id="admin" className="text-lg font-semibold">
            Administration
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            You can view every team in {me.organization.name}. Team and user management screens
            are added in a later phase.
          </p>
        </section>
      )}
    </div>
  )
}
