import { useMutation, useQueryClient } from '@tanstack/react-query'

import { tasksApi, type Task, type TaskActionPath } from '../../services/api'

/** Run a task action, then refresh every screen (lists, progress, notifications). */
export function useTaskAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { task: Task; path: TaskActionPath; body?: { reason?: string; note?: string; link?: string } }) =>
      tasksApi.action(v.task.id, v.path, v.body),
    onSuccess: () => qc.invalidateQueries(),
  })
}
