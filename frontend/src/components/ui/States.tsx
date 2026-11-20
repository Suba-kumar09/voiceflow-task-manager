import type { ReactNode } from 'react'

import { errorMessage } from './errorMessage'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <p role="status" className="py-6 text-sm text-ink-muted">
      {label}
    </p>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <p role="alert" className="rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">
      {errorMessage(error)}
    </p>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-sm text-ink-muted">{children}</p>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-panel p-5 ${className}`}>{children}</section>
}

export function ProgressBar({ percent, label, color = '#14b8a6', height = 8 }: { percent: number; label: string; color?: string; height?: number }) {
  return (
    <div role="img" aria-label={label} className="overflow-hidden rounded-full bg-[#1c283c]" style={{ height }}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, percent))}%`, background: color }} />
    </div>
  )
}
