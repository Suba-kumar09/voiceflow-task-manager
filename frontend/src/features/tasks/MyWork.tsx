import { tasksApi, type Task } from '../../services/api'
import { StatusBadge, TaskList } from './TaskList'
import { formatDue, priorityLabel } from './taskLabels'
import { useAsync } from './useAsync'

function CurrentTask({ task }: { task: Task }) {
  const due = formatDue(task.due_at, task.timezone)
  return (
    <div className="rounded-xl border border-accent/30 bg-accent-soft/50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-accent">Current task</p>
          <p className="mt-1 text-lg font-semibold">{task.title}</p>
        </div>
        <StatusBadge task={task} />
      </div>
      <p className="mt-1 text-sm text-ink-muted">
        {priorityLabel[task.priority]} priority{due && <> · Due {due}</>}
      </p>
      {task.acceptance_criteria && (
        <p className="mt-3 text-sm">
          <span className="font-medium">Done when: </span>
          {task.acceptance_criteria}
        </p>
      )}
    </div>
  )
}

export function MyWork({ teamNames }: { teamNames: string[] }) {
  const state = useAsync(
    async () => {
      const [current, mine] = await Promise.all([tasksApi.current(), tasksApi.mine()])
      return { current: current.task, mine: mine.items }
    },
    [],
  )

  return (
    <section aria-labelledby="my-work" className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
      <h2 id="my-work" className="text-lg font-semibold">
        Your work
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        {teamNames.length > 0
          ? `You are on the ${teamNames.join(', ')} team.`
          : 'You are not on a team yet. Your manager will add you.'}
      </p>

      <div className="mt-4 flex flex-col gap-4" aria-live="polite">
        {state.status === 'loading' && <p className="text-sm text-ink-muted">Loading your tasks…</p>}
        {state.status === 'error' && (
          <p role="alert" className="text-sm text-bad">
            {state.message}
          </p>
        )}
        {state.status === 'ready' && (
          <>
            {state.data.current ? (
              <CurrentTask task={state.data.current} />
            ) : (
              <p className="rounded-xl border border-dashed border-line p-4 text-sm text-ink-muted">
                You have no active task right now.
              </p>
            )}
            <div>
              <h3 className="text-sm font-semibold">All your tasks</h3>
              <TaskList tasks={state.data.mine} showAssignee={false} emptyText="No tasks yet." />
            </div>
          </>
        )}
      </div>
    </section>
  )
}
