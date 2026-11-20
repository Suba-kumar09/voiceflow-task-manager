import { tasksApi } from '../../services/api'
import { TaskList } from './TaskList'
import { useAsync } from './useAsync'

export function TeamTasks({ teamId, teamName }: { teamId: string; teamName: string }) {
  const state = useAsync(() => tasksApi.list(teamId), [teamId])

  return (
    <section
      aria-labelledby={`tasks-${teamId}`}
      className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
    >
      <h3 id={`tasks-${teamId}`} className="text-base font-semibold">
        {teamName} tasks
      </h3>
      <div aria-live="polite">
        {state.status === 'loading' && <p className="mt-3 text-sm text-ink-muted">Loading tasks…</p>}
        {state.status === 'error' && (
          <p role="alert" className="mt-3 text-sm text-bad">
            {state.message}
          </p>
        )}
        {state.status === 'ready' && (
          <TaskList
            tasks={state.data.items}
            showAssignee
            emptyText="No tasks for this team yet."
          />
        )}
      </div>
    </section>
  )
}
