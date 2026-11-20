import { ApiError } from '../../services/api'

/** Turn any thrown error into a short, user-facing sentence (never a stack trace). */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'You do not have access to this.'
    return err.message
  }
  return 'Something went wrong. Try again shortly.'
}
