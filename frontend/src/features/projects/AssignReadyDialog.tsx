import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'
import { ErrorBox, Loading } from '../../components/ui/States'
import { projectsApi, type PlanItem } from '../../services/api'
import { Priority } from '../tasks/Badges'

const outcomeText: Record<PlanItem['outcome'], string> = {
  ASSIGN: '',
  NO_CAPACITY: 'Stays ready',
  NO_QUALIFIED: 'Needs your decision',
}

/** "Assign the ready tasks by priority": read the plan back first, then confirm. */
export function AssignReadyDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const plan = useQuery({ queryKey: ['plan', projectId], queryFn: () => projectsApi.plan(projectId), staleTime: 0 })
  const assign = useMutation({
    mutationFn: () => projectsApi.assignReady(projectId),
    onSuccess: () => qc.invalidateQueries(),
  })
  const items = plan.data ?? []
  const assignable = items.filter((i) => i.outcome === 'ASSIGN').length

  if (assign.isSuccess) {
    const r = assign.data
    return (
      <Modal title="Tasks assigned" onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
        {r.assigned.length === 0 ? (
          <p className="text-sm text-ink-muted">Nothing could be assigned right now.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {r.assigned.map((a) => (
              <li key={a.task_id} className="flex items-center gap-3 text-sm">
                <span className="font-semibold text-ok">✓</span>
                <span className="flex-1">{a.title}</span>
                <span className="font-medium text-ink-strong">{a.assignee_name}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-ink-faint">Each person has been notified.</p>
      </Modal>
    )
  }

  return (
    <Modal
      title="Assign the ready tasks by priority"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={assignable === 0 || assign.isPending} onClick={() => assign.mutate()}>
            {assignable === 0 ? 'Nothing to assign' : `Assign ${assignable} task${assignable === 1 ? '' : 's'}`}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-muted">
        Ranked by priority and due date. Each task goes to someone with all the skills it needs and room in their workload.
      </p>
      {plan.isLoading && <Loading label="Working out the plan…" />}
      {plan.isError && <ErrorBox error={plan.error} />}
      {plan.isSuccess && items.length === 0 && <p className="text-sm text-ink-muted">No tasks are ready right now.</p>}
      <ul className="flex flex-col divide-y divide-line-soft">
        {items.map((i) => (
          <li key={i.task_id} className="flex items-center gap-3 py-2.5">
            <Priority priority={i.priority} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-strong">
                {i.key && <span className="mr-1.5 text-ink-faint">{i.key}</span>}
                {i.title}
              </p>
              <p className="text-xs text-ink-muted">{i.reason}</p>
            </div>
            {i.outcome === 'ASSIGN' && i.assignee_name ? (
              <span className="flex items-center gap-2 text-sm font-semibold text-ink-strong">
                <Avatar name={i.assignee_name} seed={i.assignee_id ?? undefined} size={26} />
                {i.assignee_name}
              </span>
            ) : (
              <span className={`text-xs font-semibold ${i.outcome === 'NO_QUALIFIED' ? 'text-violet' : 'text-warn'}`}>{outcomeText[i.outcome]}</span>
            )}
          </li>
        ))}
      </ul>
      {assign.isError && <div className="mt-3"><ErrorBox error={assign.error} /></div>}
    </Modal>
  )
}
