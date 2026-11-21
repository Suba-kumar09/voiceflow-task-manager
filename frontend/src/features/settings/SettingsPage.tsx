import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { Button } from '../../components/ui/Button'
import { Card, ErrorBox, Loading } from '../../components/ui/States'
import { preferencesApi, type Preferences } from '../../services/api'
import { usePageSummary } from '../../voice/pageSummary'

const hhmm = (t: string | null) => (t ? t.slice(0, 5) : '')

function spokenTime(t: string) {
  const [h, m] = t.split(':').map(Number)
  const ampm = h >= 12 ? 'PM' : 'AM'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return m ? `${h12}:${String(m).padStart(2, '0')} ${ampm}` : `${h12} ${ampm}`
}

function Form({ prefs }: { prefs: Preferences }) {
  const qc = useQueryClient()
  const ids = { voice: useId(), start: useId(), end: useId() }
  const [voice, setVoice] = useState(prefs.voice_announcements)
  const [quiet, setQuiet] = useState(prefs.quiet_start !== null)
  const [start, setStart] = useState(hhmm(prefs.quiet_start) || '21:00')
  const [end, setEnd] = useState(hhmm(prefs.quiet_end) || '08:00')
  const save = useMutation({
    mutationFn: () =>
      preferencesApi.update(
        quiet
          ? { voice_announcements: voice, quiet_start: start, quiet_end: end }
          : { voice_announcements: voice, clear_quiet_hours: true },
      ),
    onSuccess: (data) => qc.setQueryData(['preferences'], data),
  })
  const sameTime = quiet && start === end
  const dirty =
    voice !== prefs.voice_announcements ||
    quiet !== (prefs.quiet_start !== null) ||
    (quiet && (start !== hhmm(prefs.quiet_start) || end !== hhmm(prefs.quiet_end)))

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="flex items-start gap-3">
        <input id={ids.voice} type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} className="mt-1 size-4 accent-teal-400" />
        <label htmlFor={ids.voice} className="text-sm">
          <span className="font-semibold text-ink-strong">Read new notifications aloud</span>
          <span className="mt-0.5 block text-ink-muted">
            When something new arrives — a new task, an approval, a reminder — VoiceFlow says it. Only while the assistant is idle and not muted.
          </span>
        </label>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="sr-only">Quiet hours</legend>
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} className="mt-1 size-4 accent-teal-400" />
          <span>
            <span className="font-semibold text-ink-strong">Quiet hours</span>
            <span className="mt-0.5 block text-ink-muted">
              No reminders and nothing read aloud during these hours ({prefs.timezone} time). Reminders wait until quiet hours end.
            </span>
          </span>
        </label>
        {quiet && (
          <div className="ml-7 flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1">
              <label htmlFor={ids.start} className="text-xs font-medium text-ink-muted">From</label>
              <input id={ids.start} type="time" value={start} onChange={(e) => setStart(e.target.value)} className="h-10 rounded-lg border border-control-line bg-control px-3 text-sm text-ink" />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={ids.end} className="text-xs font-medium text-ink-muted">Until</label>
              <input id={ids.end} type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="h-10 rounded-lg border border-control-line bg-control px-3 text-sm text-ink" />
            </div>
            {sameTime && <p className="text-sm text-warn">Start and end must be different.</p>}
          </div>
        )}
      </fieldset>

      {save.isError && <ErrorBox error={save.error} />}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={!dirty || sameTime || !start || !end || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save settings'}
        </Button>
        {save.isSuccess && !dirty && <p role="status" className="text-sm text-ok">Saved.</p>}
      </div>
    </form>
  )
}

export function SettingsPage() {
  const prefs = useQuery({ queryKey: ['preferences'], queryFn: preferencesApi.get })
  const p = prefs.data
  usePageSummary(
    p
      ? `Settings. Spoken notifications are ${p.voice_announcements ? 'on' : 'off'}. ` +
          (p.quiet_start && p.quiet_end
            ? `Quiet hours from ${spokenTime(p.quiet_start)} to ${spokenTime(p.quiet_end)}${p.quiet_now ? ', and they are on right now' : ''}.`
            : 'No quiet hours set.')
      : 'Settings.',
  )
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-strong">Settings</h1>
        <p className="mt-1 text-sm text-ink-muted">How VoiceFlow talks to you.</p>
      </div>
      <Card className="p-6">
        {prefs.isLoading && <Loading />}
        {prefs.isError && <ErrorBox error={prefs.error} />}
        {p && <Form prefs={p} />}
      </Card>
      {p?.quiet_now && (
        <p role="status" className="text-sm text-ink-muted">Quiet hours are on right now: reminders are held and nothing is read aloud.</p>
      )}
    </div>
  )
}
