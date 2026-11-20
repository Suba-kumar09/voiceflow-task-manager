/** Minimal typed client for the VoiceFlow API (same-origin; Vite proxies /api in dev). */

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export interface HealthResponse {
  status: 'ok'
}

export interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  database: 'ok' | 'unavailable' | 'not_configured'
  migrations: 'up_to_date' | 'pending' | 'unknown'
}

/** GET returning JSON. `acceptStatuses` lets callers treat e.g. 503 readiness as data. */
export async function getJson<T>(path: string, acceptStatuses: number[] = []): Promise<T> {
  const resp = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
  if (resp.ok || acceptStatuses.includes(resp.status)) {
    return (await resp.json()) as T
  }
  let code = 'http_error'
  let message = `Request failed (${resp.status})`
  try {
    const body = (await resp.json()) as ApiErrorBody
    code = body.error.code
    message = body.error.message
  } catch {
    /* non-JSON error (e.g. backend not running): keep the generic message */
  }
  throw new ApiError(resp.status, code, message)
}

export const systemApi = {
  health: () => getJson<HealthResponse>('/api/v1/health'),
  readiness: () => getJson<ReadinessResponse>('/api/v1/ready', [503]),
}
