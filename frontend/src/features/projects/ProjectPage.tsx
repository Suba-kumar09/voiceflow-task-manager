import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Avatar, Unassigned } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'
import { Card, Empty, ErrorBox, Loading, ProgressBar } from '../../components/ui/States'
import { projectsApi, tasksApi, type Progress, type Task, type TaskStatus } from '../../services/api'
import { useMe } from '../auth/auth-context'
import { Priority, ProjectBadge, StatusBadge } from '../tasks/Badges'
import { TaskActions } from '../tasks/TaskActions'
import { formatDue } from '../tasks/taskLabels'
import { AssignReadyDialog } from './AssignReadyDialog'

const TABS = [
  ['overview', 'Overview'],
  ['tasks', 'Tasks'],
  ['team', 'Team'],
] as const
type Tab = (typeof TABS)[number][0]

const FILTERS: [string, string, TaskStatus[] | null][] = [
  ['all', 'All', null],
  ['active', 'In progress', ['ASSIGNED', 'ACCEPTED', 'IN_PROGRESS']],
  ['blocked', 'Blocked', ['BLOCKED']],
  ['review', 'Awaiting review', ['PENDING_REVIEW']],
  ['open', 'Open', ['UNASSIGNED']],
  ['done', 'Completed', ['COMPLETED']],
]

function Tile({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-2xl border border-line bg-panel px-4 py-3">
      <p className="flex items-center gap-2 text-xs font-medium text-ink-muted">
        <span aria-hidden="true" className="size-2 rounded-full" style={{ background: color }} />
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-ink-strong">{value}</p>
    </div>
  )
}

function Overview({ progress, tasks }: { progress: Progress; tasks: Task[] }) {
  const review = tasks.filter((t) => t.status === 'PENDING_REVIEW')
  const blocked = tasks.filter((t) => t.status === 'BLOCKED')
  const nothing = review.length + blocked.length + progress.needs_decision.length === 0
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3">
        <Tile label="Completed" value={progress.completed} color="#4ade80" />
        <Tile label="In progress" value={progress.in_progress} color="#38bdf8" />
        <Tile label="Ready to assign" value={progress.ready_to_assign} color="#34d399" />
        <Tile label="Waiting on other tasks" value={progress.waiting_on_dependencies} color="#94a3b8" />
        <Tile label="Blocked" value={progress.blocked_by_issue} color="#f87171" />
        <Tile label="Awaiting review" value={progress.awaiting_review} color="#fbbf24" />
        <Tile label="Needs decision" value={progress.needs_decision.length} color="#c084fc" />
      </div>

      <Card>
        <h2 className="text-base font-semibold text-ink-strong">Needs your attention</h2>
        <div className="mt-4 flex flex-col gap-3">
          {nothing && <p className="text-sm text-ink-muted">Nothing needs you right now. VoiceFlow will tell you when it does.</p>}
          {review.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-[#5a4512] bg-[rgba(251,191,36,.07)] px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink-strong">{t.external_key} · {t.title} is awaiting your review</p>
                <p className="text-sm text-ink-muted">Reported done by {t.assignee?.display_name ?? 'the assignee'}.</p>
              </div>
              <TaskActions task={t} role="manager" />
            </div>
          ))}
          {blocked.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-[#5b2328] bg-[rgba(239,68,68,.07)] px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink-strong">{t.external_key} · {t.title} is blocked</p>
                <p className="text-sm text-ink-muted">Held by {t.assignee?.display_name ?? '—'}. Open Notifications for the reason.</p>
              </div>
              <TaskActions task={t} role="manager" />
            </div>
          ))}
          {progress.needs_decision.map((d) => (
            <div key={d.task_id} className="rounded-xl border border-[#4c2d73] bg-[rgba(168,85,247,.07)] px-4 py-3">
              <p className="text-sm font-semibold text-ink-strong">{d.key} · {d.title} needs your decision</p>
              <p className="text-sm text-ink-muted">{d.reason}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function TasksTab({ tasks }: { tasks: Task[] }) {
  const [filter, setFilter] = useState('all')
  const statuses = FILTERS.find((f) => f[0] === filter)?.[2]
  const shown = statuses ? tasks.filter((t) => statuses.includes(t.status)) : tasks
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink-strong">
          Tasks <span className="font-normal text-ink-muted">· {shown.length} shown</span>
        </h2>
        <div role="group" aria-label="Filter tasks" className="flex flex-wrap gap-1.5">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
              className={`h-8 rounded-full border px-3 text-xs font-semibold ${filter === key ? 'border-accent bg-accent text-accent-ink' : 'border-control-line bg-control text-ink-muted hover:text-ink'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-faint">
              {['ID', 'Task', 'Assigned to', 'Status', 'Priority', 'Due', 'Depends on', ''].map((h) => (
                <th key={h} scope="col" className="border-b border-line px-2 py-2.5 font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t.id} className={t.status === 'BLOCKED' ? 'bg-[rgba(239,68,68,.04)]' : ''}>
                <td className="border-b border-line-soft px-2 py-3 font-semibold text-ink-faint">{t.external_key ?? '—'}</td>
                <td className="border-b border-line-soft px-2 py-3">
                  <p className="font-semibold text-ink">{t.title}</p>
                  {t.required_skills.length > 0 && <p className="text-xs text-ink-muted">Needs {t.required_skills.join(', ')}</p>}
                </td>
                <td className="border-b border-line-soft px-2 py-3">
                  <span className="flex items-center gap-2">
                    {t.assignee ? <Avatar name={t.assignee.display_name} seed={t.assignee.id} size={26} /> : <Unassigned size={26} />}
                    <span className={t.assignee ? 'text-ink' : 'text-ink-faint'}>{t.assignee?.display_name ?? 'Not assigned'}</span>
                  </span>
                </td>
                <td className="border-b border-line-soft px-2 py-3"><StatusBadge status={t.status} /></td>
                <td className="border-b border-line-soft px-2 py-3"><Priority priority={t.priority} /></td>
                <td className="whitespace-nowrap border-b border-line-soft px-2 py-3 text-ink">{formatDue(t.due_at, t.timezone) ?? '—'}</td>
                <td className="border-b border-line-soft px-2 py-3 text-ink-muted">{t.depends_on.length ? t.depends_on.join(', ') : '—'}</td>
                <td className="border-b border-line-soft px-2 py-3"><TaskActions task={t} role="manager" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <div className="mt-3"><Empty>No tasks match this filter.</Empty></div>}
      </div>
    </Card>
  )
}

function TeamTab({ projectId }: { projectId: string }) {
  const team = useQuery({ queryKey: ['team', projectId], queryFn: () => projectsApi.team(projectId) })
  if (team.isLoading) return <Loading label="Loading team…" />
  if (team.isError) return <ErrorBox error={team.error} />
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
      {(team.data ?? []).map((m) => {
        const full = m.wip_limit > 0 && m.active_tasks >= m.wip_limit
        const state = m.membership_role === 'MANAGER' ? 'Manager' : m.current_task?.status === 'BLOCKED' ? 'Blocked' : m.active_tasks ? 'Busy' : 'Available'
        const tone = state === 'Available' ? 'bg-[rgba(34,197,94,.14)] text-[#4ade80]' : state === 'Blocked' ? 'bg-[rgba(248,113,113,.15)] text-[#fca5a5]' : state === 'Busy' ? 'bg-[rgba(56,189,248,.14)] text-[#7dd3fc]' : 'bg-[rgba(148,163,184,.12)] text-[#cbd5e1]'
        return (
          <article key={m.id} className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-4">
            <div className="flex items-center gap-3">
              <Avatar name={m.display_name} seed={m.id} size={44} />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-ink-strong">{m.display_name}</p>
                <p className="text-xs text-ink-muted">{m.completed_in_project} completed in this project</p>
              </div>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`}>{state}</span>
            </div>
            <div className="rounded-xl border border-line-soft bg-inset px-3 py-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Working on</p>
              <p className="text-sm font-medium text-ink">{m.current_task ? `${m.current_task.key ? m.current_task.key + ' · ' : ''}${m.current_task.title}` : 'Nothing right now'}</p>
            </div>
            {m.membership_role === 'MEMBER' && (
              <div>
                <div className="mb-1 flex justify-between text-xs text-ink-muted"><span>Workload</span><span>{m.active_tasks} of {m.wip_limit} active</span></div>
                <ProgressBar percent={m.wip_limit ? (m.active_tasks * 100) / m.wip_limit : 0} label={`Workload ${m.active_tasks} of ${m.wip_limit}`} color={full ? '#fb923c' : '#2dd4bf'} height={6} />
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {m.skills.length ? m.skills.map((s) => <span key={s} className="rounded-md bg-control px-2 py-0.5 text-xs text-ink">{s}</span>) : <span className="text-xs text-ink-faint">No skills recorded</span>}
            </div>
          </article>
        )
      })}
    </div>
  )
}

export function ProjectPage() {
  const { projectId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.some(([k]) => k === params.get('tab')) ? params.get('tab') : 'overview') as Tab
  const me = useMe()
  const qc = useQueryClient()
  const [dialog, setDialog] = useState<null | 'assign' | 'start'>(null)

  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => projectsApi.get(projectId) })
  const progress = useQuery({ queryKey: ['progress', projectId], queryFn: () => projectsApi.progress(projectId) })
  const tasks = useQuery({ queryKey: ['tasks', 'project', projectId], queryFn: () => tasksApi.forProject(projectId) })
  const approve = useMutation({ mutationFn: () => projectsApi.approveBacklog(projectId), onSuccess: () => qc.invalidateQueries() })
  const start = useMutation({ mutationFn: () => projectsApi.start(projectId), onSuccess: () => qc.invalidateQueries() })

  if (project.isLoading) return <Loading label="Loading project…" />
  if (project.isError) return <ErrorBox error={project.error} />
  const pr = project.data!
  const pg = progress.data
  const teamName = me.teams.find((t) => t.team_id === pr.team_id)?.team_name ?? 'Team'
  const isManager = me.role === 'ADMIN' || me.teams.some((t) => t.team_id === pr.team_id && t.membership_role === 'MANAGER')

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-ink-muted"><Link to="/projects" className="text-accent-strong hover:underline">Projects</Link> / {pr.name}</p>
      <section className="rounded-2xl border border-line bg-panel px-6 pt-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-[240px] flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight text-ink-strong">{pr.name}</h1>
              <ProjectBadge status={pr.status} />
            </div>
            <p className="mt-1 text-sm text-ink-muted">{teamName} team{pr.description ? ` · ${pr.description}` : ''}</p>
          </div>
          {pg && (
            <div className="w-full max-w-[280px]">
              <div className="mb-1.5 flex justify-between text-sm"><span className="text-ink-muted">{pg.completed} of {pg.total} tasks done</span><span className="font-bold text-ink-strong">{pg.percent_complete}%</span></div>
              <ProgressBar percent={pg.percent_complete} label={`${pg.completed} of ${pg.total} tasks done`} height={10} />
            </div>
          )}
          {isManager && (
            <div className="flex gap-2">
              {pr.status === 'DRAFT' && <Button variant="primary" disabled={approve.isPending} onClick={() => approve.mutate()}>Approve backlog</Button>}
              {pr.status === 'READY' && <Button variant="primary" onClick={() => setDialog('start')}>Start project</Button>}
              {pr.status === 'ACTIVE' && <Button variant="primary" onClick={() => setDialog('assign')}>Assign ready tasks</Button>}
            </div>
          )}
        </div>
        {approve.isError && <div className="mt-3"><ErrorBox error={approve.error} /></div>}
        <div role="tablist" aria-label="Project sections" className="mt-4 flex flex-wrap gap-1">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setParams(key === 'overview' ? {} : { tab: key })}
              className={`h-11 border-b-2 px-4 text-sm ${tab === key ? 'border-accent-strong font-semibold text-accent-strong' : 'border-transparent font-medium text-ink-muted hover:text-ink'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {(progress.isError || tasks.isError) && <ErrorBox error={progress.error ?? tasks.error} />}
      {tab === 'overview' && pg && tasks.data && <Overview progress={pg} tasks={tasks.data.items} />}
      {tab === 'tasks' && tasks.data && <TasksTab tasks={tasks.data.items} />}
      {tab === 'team' && isManager && <TeamTab projectId={projectId} />}
      {tab === 'team' && !isManager && <Empty>Only managers can see the team’s workload.</Empty>}
      {(progress.isLoading || tasks.isLoading) && <Loading />}

      {dialog === 'assign' && <AssignReadyDialog projectId={projectId} onClose={() => setDialog(null)} />}
      {dialog === 'start' && (
        <Modal
          title={`Start “${pr.name}”?`}
          onClose={() => setDialog(null)}
          footer={
            start.isSuccess ? (
              <Button variant="primary" onClick={() => { start.reset(); setDialog(null) }}>Done</Button>
            ) : (
              <>
                <Button onClick={() => setDialog(null)}>Cancel</Button>
                <Button variant="primary" disabled={start.isPending} onClick={() => start.mutate()}>Start project</Button>
              </>
            )
          }
        >
          {start.isSuccess ? (
            <p className="text-sm text-ink">
              Started. {start.data.assigned.length} task{start.data.assigned.length === 1 ? '' : 's'} assigned
              {start.data.needs_decision.length ? `, ${start.data.needs_decision.length} need your decision` : ''}. Everyone assigned has been notified.
            </p>
          ) : (
            <p className="text-sm text-ink-muted">
              VoiceFlow will assign every task that can start now to a suitable person, in parallel. Tasks that depend on unfinished work wait automatically.
            </p>
          )}
          {start.isError && <div className="mt-3"><ErrorBox error={start.error} /></div>}
        </Modal>
      )}
    </div>
  )
}
