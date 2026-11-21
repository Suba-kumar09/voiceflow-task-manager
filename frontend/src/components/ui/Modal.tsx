import { useEffect, useId, useRef, type ReactNode } from 'react'

/** Accessible dialog: labelled, Esc closes, focus moves inside and returns afterwards. */
export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  // Callers often pass a new onClose on every render; keep the latest without re-running the
  // effect, otherwise focus would jump back to the first field on each keystroke.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  // Runs once when the dialog opens: move focus inside, close on Esc, restore focus on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const first = panel.current?.querySelector<HTMLElement>(
      'textarea, input, select, button:not([data-close])',
    )
    ;(first ?? panel.current)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
    }
    const node = panel.current
    node?.addEventListener('keydown', onKey)
    return () => {
      node?.removeEventListener('keydown', onKey)
      previous?.focus()
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-full max-w-lg rounded-2xl border border-line bg-panel shadow-2xl outline-none"
      >
        <div className="flex items-center justify-between border-b border-line-soft px-5 py-4">
          <h2 id={titleId} className="text-base font-semibold text-ink-strong">
            {title}
          </h2>
          <button
            type="button"
            data-close
            onClick={onClose}
            aria-label="Close"
            className="grid size-8 place-items-center rounded-lg text-ink-muted hover:bg-control hover:text-ink"
          >
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line-soft px-5 py-4">{footer}</div>}
      </div>
    </div>
  )
}
