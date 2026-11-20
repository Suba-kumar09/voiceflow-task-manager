import { SystemStatus } from '../features/system/SystemStatus'
import { brand } from './brand'

export function App() {
  return (
    <div className="flex min-h-dvh flex-col font-sans">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3 sm:px-6">
          <div
            aria-hidden="true"
            className="grid size-8 place-items-center rounded-lg bg-accent text-sm font-bold text-panel"
          >
            {brand.name.charAt(0)}
          </div>
          <div>
            <p className="text-base font-semibold leading-tight">{brand.name}</p>
            <p className="text-xs text-ink-muted">{brand.tagline}</p>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-6 px-4 py-10 sm:px-6">
        <SystemStatus />
        <p className="max-w-xl text-center text-sm text-ink-muted">
          Foundation build. Voice workspaces for managers and employees are added in the next
          phases.
        </p>
      </main>
    </div>
  )
}
