import { useQuery } from '@tanstack/react-query'

import { Card, Empty, ErrorBox, Loading } from '../../components/ui/States'
import { tasksApi } from '../../services/api'
import { usePageSummary } from '../../voice/pageSummary'
import { useMe } from '../auth/auth-context'
import { Priority, StatusBadge } from '../tasks/Badges'
import { TaskActions } from '../tasks/TaskActions'
import { formatDue, priorityLabel } from '../tasks/taskLabels'

export function MyWorkPage() {
  const me = useMe()
  const current = useQuery({ queryKey: ['tasks', 'current'], queryFn: tasksApi.current })
  const mine = useQuery({ queryKey: ['tasks', 'mine'], queryFn: tasksApi.mine })
  const task = current.data?.task ?? null
  const due = task ? formatDue(task.due_at, task.timezone) : null
  const others = (mine.data?.items ?? []).filter((t) => t.id !== task?.id)
  const reviewCount = others.filter((t) => t.status === 'PENDING_REVIEW').length
  usePageSummary(
    task
      ? `My work. Your current task is ${task.title}, ${priorityLabel[task.priority].toLowerCase()} priority${due ? `, due ${due}` : ''}. ` +
          `You have ${others.length} other task${others.length === 1 ? '' : 's'}${reviewCount ? `, ${reviewCount} waiting for review` : ''}.`
      : `My work. You have no active task right now.${reviewCount ? ` ${reviewCount} of your tasks are waiting for review.` : ''}`,
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Hello, {me.display_name.split(' ')[0]}</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {task ? 'Here is what to work on now.' : 'You have no active task right now.'}
          {reviewCount > 0 && ` ${reviewCount} of your tasks ${reviewCount === 1 ? 'is' : 'are'} waiting for review.`}
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <section aria-labelledby="current-task" className="min-w-0 flex-[2_1_440px] rounded-2xl border border-[#1d4b47] bg-[#0f2a2a] p-6">
          {current.isLoading && <Loading label="Loading your task…" />}
          {current.isError && <ErrorBox error={current.error} />}
          {current.isSuccess && !task && (
            <div>
              <p id="current-task" className="text-xs font-semibold uppercase tracking-wider text-[#5eead4]">Current task</p>
              <p className="mt-2 text-lg font-semibold text-ink-strong">Nothing assigned right now</p>
              <p className="mt-1 text-sm text-[#a7c4c2]">VoiceFlow will tell you as soon as a task is ready for you.</p>
            </div>
          )}
          {task && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <p id="current-task" className="text-xs font-semibold uppercase tracking-wider text-[#5eead4]">
                  Current task{task.external_key ? ` · ${task.external_key}` : ''}
                </p>
                <StatusBadge status={task.status} />
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-ink-strong">{task.title}</h2>
              <p className="text-sm text-[#a7c4c2]">
                <strong className="text-ink-strong">{priorityLabel[task.priority]}</strong> priority
                {due && <> · Due <strong className="text-ink-strong">{due}</strong></>}
                {task.required_skills.length > 0 && <> · Needs {task.required_skills.join(', ')}</>}
              </p>
              {task.acceptance_criteria && (
                <div className="rounded-xl border border-[#1d4b47] bg-[rgba(4,32,28,.6)] px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-[#7fb3ae]">Done when</p>
                  <p className="mt-1 text-sm leading-relaxed text-ink">{task.acceptance_criteria}</p>
                </div>
              )}
              {task.description && <p className="text-sm text-ink">{task.description}</p>}
              <TaskActions task={task} role="assignee" />
            </div>
          )}
        </section>

        <Card className="min-w-0 flex-[1_1_300px]">
          <h2 className="text-base font-semibold text-ink-strong">Your other tasks</h2>
          {mine.isLoading && <Loading />}
          {mine.isError && <ErrorBox error={mine.error} />}
          {mine.isSuccess && others.length === 0 && <div className="mt-3"><Empty>No other tasks.</Empty></div>}
          <ul className="mt-3 flex flex-col divide-y divide-line-soft">
            {others.map((t) => (
              <li key={t.id} className="flex flex-col gap-2 py-3">
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{t.external_key ? `${t.external_key} · ` : ''}{t.title}</p>
                    <p className="text-xs text-ink-muted"><Priority priority={t.priority} /></p>
                  </div>
                  <StatusBadge status={t.status} />
                </div>
                {['ASSIGNED', 'ACCEPTED', 'IN_PROGRESS', 'BLOCKED'].includes(t.status) && <TaskActions task={t} role="assignee" />}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
