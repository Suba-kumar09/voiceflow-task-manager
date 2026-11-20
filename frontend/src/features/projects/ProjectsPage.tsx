import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Empty, ErrorBox, Loading, ProgressBar } from '../../components/ui/States'
import { projectsApi, type Project } from '../../services/api'
import { useMe } from '../auth/auth-context'
import { ProjectBadge } from '../tasks/Badges'

function Flag({ children, tone }: { children: React.ReactNode; tone: string }) {
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}>{children}</span>
}

function ProjectCard({ project, teamName }: { project: Project; teamName: string }) {
  const progress = useQuery({ queryKey: ['progress', project.id], queryFn: () => projectsApi.progress(project.id) })
  const p = progress.data
  return (
    <article className="flex flex-col gap-4 rounded-2xl border border-line bg-panel p-5 transition hover:border-control-line">
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-soft text-sm font-bold text-accent-strong">
          {project.name.replace(/^\[DEMO\]\s*/, '').slice(0, 2).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-snug text-ink-strong">{project.name}</h2>
          <p className="mt-0.5 text-sm text-ink-muted">{teamName}</p>
        </div>
        <ProjectBadge status={project.status} />
      </div>

      {progress.isLoading && <Loading label="Loading progress…" />}
      {progress.isError && <ErrorBox error={progress.error} />}
      {p && (
        <>
          <div>
            <div className="mb-1.5 flex justify-between text-sm">
              <span className="text-ink-muted">
                {p.completed} of {p.total} tasks done
              </span>
              <span className="font-semibold text-ink-strong">{p.percent_complete}%</span>
            </div>
            <ProgressBar percent={p.percent_complete} label={`${p.completed} of ${p.total} tasks done`} />
          </div>
          <div className="flex min-h-6 flex-wrap gap-1.5">
            {p.in_progress > 0 && <Flag tone="bg-[rgba(56,189,248,.14)] text-[#7dd3fc]">{p.in_progress} in progress</Flag>}
            {p.blocked_by_issue > 0 && <Flag tone="bg-[rgba(248,113,113,.15)] text-[#fca5a5]">{p.blocked_by_issue} blocked</Flag>}
            {p.awaiting_review > 0 && <Flag tone="bg-[rgba(251,191,36,.14)] text-[#fcd34d]">{p.awaiting_review} awaiting review</Flag>}
            {p.needs_decision.length > 0 && <Flag tone="bg-[rgba(192,132,252,.16)] text-[#d8b4fe]">{p.needs_decision.length} needs decision</Flag>}
            {p.ready_to_assign > 0 && <Flag tone="bg-[rgba(52,211,153,.12)] text-[#6ee7b7]">{p.ready_to_assign} ready to assign</Flag>}
          </div>
        </>
      )}

      <div className="mt-auto flex justify-end border-t border-line-soft pt-4">
        <Link to={`/projects/${project.id}`} className="inline-flex h-9 items-center rounded-lg border border-control-line bg-control px-4 text-sm font-semibold text-ink hover:border-ink-faint">
          Open project
        </Link>
      </div>
    </article>
  )
}

export function ProjectsPage() {
  const me = useMe()
  const projects = useQuery({ queryKey: ['projects'], queryFn: projectsApi.list })
  const teamName = (id: string) => me.teams.find((t) => t.team_id === id)?.team_name ?? 'Team'
  const list = projects.data ?? []
  const count = (s: Project['status']) => list.filter((p) => p.status === s).length

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Projects</h1>
        <p className="mt-1 text-sm text-ink-muted">Welcome back, {me.display_name.split(' ')[0]}. Here is everything you manage.</p>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
        {[
          ['Active', count('ACTIVE'), '#2dd4bf'],
          ['Ready to start', count('READY'), '#a5b4fc'],
          ['Drafts', count('DRAFT'), '#94a3b8'],
          ['Total projects', list.length, '#e6ebf2'],
        ].map(([label, value, color]) => (
          <div key={label as string} className="rounded-2xl border border-line bg-panel p-4">
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              <span aria-hidden="true" className="size-2 rounded-full" style={{ background: color as string }} />
              {label}
            </p>
            <p className="mt-1 text-3xl font-bold text-ink-strong">{value}</p>
          </div>
        ))}
      </div>

      {projects.isLoading && <Loading label="Loading projects…" />}
      {projects.isError && <ErrorBox error={projects.error} />}
      {projects.isSuccess && list.length === 0 && <Empty>No projects yet.</Empty>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-5">
        {list.map((p) => (
          <ProjectCard key={p.id} project={p} teamName={teamName(p.team_id)} />
        ))}
      </div>
    </div>
  )
}
