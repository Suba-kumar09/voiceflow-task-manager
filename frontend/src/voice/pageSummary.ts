import { createContext, useContext, useEffect } from 'react'

/** What "read this page" should say for the current screen. Pages set it; the voice panel reads it. */
export const PageSummaryContext = createContext<{ current: string }>({ current: '' })

export function usePageSummary(summary: string) {
  const ref = useContext(PageSummaryContext)
  useEffect(() => {
    ref.current = summary
  }, [ref, summary])
}
