import { useId, useState, type FormEvent } from 'react'

import { useMe } from '../features/auth/auth-context'
import type { TextToSpeech } from './tts'
import { useVoice, type VoicePhase } from './useVoice'

const PHASE: Record<VoicePhase, { label: string; color: string }> = {
  ready: { label: 'Ready', color: '#4ade80' },
  listening: { label: 'Listening', color: '#2dd4bf' },
  understanding: { label: 'Understanding', color: '#38bdf8' },
  speaking: { label: 'Speaking', color: '#2dd4bf' },
  attention: { label: 'Need a little more', color: '#fbbf24' },
  confirm: { label: 'Waiting for your yes', color: '#fbbf24' },
  error: { label: 'Something went wrong', color: '#f87171' },
  muted: { label: 'Muted', color: '#94a3b8' },
  unavailable: { label: 'Microphone unavailable', color: '#f87171' },
}

const MANAGER_HINTS = ['What is still pending?', 'Approve it', 'Assign the ready tasks by priority', 'Read my notifications']
const EMPLOYEE_HINTS = ['What’s my task?', 'I’ve started my task', 'I’ve completed my task', 'I’m blocked']

function MicIcon({ off }: { off?: boolean }) {
  return (
    <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      {off ? (
        <>
          <line x1="2" y1="2" x2="22" y2="22" />
          <path d="M18.89 13.23A7 7 0 0 0 19 12v-2M5 10v2a7 7 0 0 0 12 5M15 9.34V5a3 3 0 0 0-5.68-1.33M9 9v3a3 3 0 0 0 5.12 2.12" />
          <line x1="12" y1="19" x2="12" y2="22" />
        </>
      ) : (
        <>
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="22" />
        </>
      )}
    </svg>
  )
}

export function VoicePanel({ tts }: { tts?: TextToSpeech }) {
  const me = useMe()
  const v = useVoice(tts)
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const inputId = useId()
  const p = PHASE[v.phase]
  const listening = v.phase === 'listening'
  const busy = v.phase === 'understanding'
  const hints = v.suggestions.length ? v.suggestions : me.role === 'EMPLOYEE' ? EMPLOYEE_HINTS : MANAGER_HINTS

  const submit = (e: FormEvent) => {
    e.preventDefault()
    v.sendText(text)
    setText('')
  }

  return (
    <section aria-label="Voice assistant" className="sticky bottom-0 z-20 border-t border-[#22314b] bg-[#0c1424]/95 px-6 py-3 shadow-[0_-12px_32px_rgba(0,0,0,.45)] backdrop-blur">
      <div className="flex flex-wrap items-center gap-4">
        <div className="relative grid size-16 shrink-0 place-items-center">
          {listening && <span aria-hidden="true" className="absolute inset-1 animate-ping rounded-full bg-accent/40 motion-reduce:animate-none" />}
          {busy && <span aria-hidden="true" className="absolute inset-0 animate-spin rounded-full border-[3px] border-transparent border-t-info border-r-info motion-reduce:animate-none" />}
          <button
            type="button"
            onClick={() => void v.toggleListening()}
            disabled={v.muted || busy}
            aria-pressed={listening}
            aria-label={listening ? 'Stop listening' : 'Talk to VoiceFlow'}
            className={`relative grid size-14 place-items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${listening ? 'bg-accent-strong text-accent-ink' : 'bg-accent text-accent-ink hover:bg-accent-strong'} shadow-[0_0_0_6px_rgba(20,184,166,.12),0_8px_22px_rgba(20,184,166,.3)]`}
          >
            <MicIcon off={v.muted} />
          </button>
        </div>

        <div className="min-w-0 flex-[999_1_320px]" aria-live="polite">
          <div className="flex items-center gap-2">
            <span role="status" className="inline-flex items-center gap-1.5 rounded-full border border-[#22314b] px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: p.color }}>
              <span aria-hidden="true" className="size-1.5 rounded-full" style={{ background: p.color }} />
              {p.label}
            </span>
            {listening && (
              <span aria-hidden="true" className="h-1.5 w-28 overflow-hidden rounded-full bg-[#1c283c]">
                <span className="block h-full rounded-full bg-accent-strong transition-[width] duration-75" style={{ width: `${Math.round(v.level * 100)}%` }} />
              </span>
            )}
          </div>
          {v.captions.you && (
            <p className="mt-1.5 text-sm text-ink">
              <span className="font-semibold text-ink-strong">You: </span>“{v.captions.you}”
            </p>
          )}
          {v.captions.bot && (
            <p className="mt-0.5 text-sm leading-relaxed text-ink">
              <span className="font-semibold text-accent-strong">VoiceFlow: </span>
              {v.captions.bot}
            </p>
          )}
          {v.problem && <p role="alert" className="mt-1 text-sm text-bad">{v.problem}</p>}
          {v.checks.length > 0 && (
            <ul aria-label="Checks" className="mt-2 flex flex-col gap-1 rounded-xl border border-[#22314b] bg-[#0f1a2c] px-3 py-2">
              {v.checks.map((c) => (
                <li key={c.text} className="flex items-start gap-2 text-[13px] text-ink">
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 grid size-4 shrink-0 place-items-center rounded-full text-[10px] font-extrabold ${c.state === 'ok' ? 'bg-ok/20 text-ok' : c.state === 'warn' ? 'bg-warn/20 text-warn' : 'bg-bad/20 text-bad'}`}
                  >
                    {c.state === 'ok' ? '✓' : c.state === 'warn' ? '!' : '×'}
                  </span>
                  <span>
                    <span className="sr-only">{c.state === 'ok' ? 'Passed: ' : c.state === 'warn' ? 'Needs attention: ' : 'Failed: '}</span>
                    {c.text}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {v.plan.length > 0 && (
            <ul aria-label="Assignment plan" className="mt-2 divide-y divide-[#1a2539] rounded-xl border border-[#22314b] bg-[#0f1a2c] px-3">
              {v.plan.map((row) => (
                <li key={row.key + row.title} className="flex items-center gap-3 py-1.5 text-[13px]">
                  <span className="w-14 shrink-0 text-xs font-semibold text-ink-faint">{row.priority}</span>
                  <span className="min-w-0 flex-1 text-ink">{row.title}</span>
                  <span className={`shrink-0 font-semibold ${row.assignee ? 'text-ink-strong' : 'text-warn'}`}>
                    {row.assignee ?? (row.outcome === 'NO_QUALIFIED' ? 'Needs your decision' : 'Stays ready')}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {v.awaiting && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => v.sendText('yes')} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-ink hover:bg-accent-strong">
                Yes, do it
              </button>
              <button type="button" onClick={() => v.sendText('cancel')} className="h-9 rounded-lg border border-control-line bg-control px-4 text-sm font-medium text-ink">
                Cancel
              </button>
              <span className="text-xs text-ink-faint">or say “yes” / “cancel”. Nothing changes until you confirm.</span>
            </div>
          )}
          {!v.captions.you && !v.captions.bot && !v.problem && (
            <p className="mt-1 text-sm text-ink-muted">
              {v.muted ? 'Voice is muted. Unmute to talk.' : 'Press the microphone and speak. It stops by itself when you pause.'}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={() => setTyping((t) => !t)} aria-expanded={typing} className="h-9 rounded-lg border border-control-line bg-control px-3 text-sm font-medium text-ink hover:border-ink-faint">
            Type instead
          </button>
          <button type="button" onClick={v.toggleMute} aria-pressed={v.muted} className="h-9 rounded-lg border border-control-line bg-control px-3 text-sm font-medium text-ink hover:border-ink-faint">
            {v.muted ? 'Unmute' : 'Mute'}
          </button>
        </div>
      </div>

      {typing && (
        <form onSubmit={submit} className="mt-3 flex gap-2">
          <label htmlFor={inputId} className="sr-only">Type a command</label>
          <input
            id={inputId}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Type a command, e.g. open the E-Commerce project"
            maxLength={500}
            className="h-10 min-w-0 flex-1 rounded-lg border border-control-line bg-inset px-3 text-sm text-ink placeholder:text-ink-faint focus:border-accent"
          />
          <button type="submit" disabled={!text.trim() || busy} className="h-10 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-ink disabled:opacity-50">
            Send
          </button>
        </form>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-ink-faint">Try saying:</span>
        {hints.map((h) => (
          <button key={h} type="button" disabled={busy} onClick={() => v.sendText(h)} className="h-8 rounded-full border border-control-line bg-control px-3 text-xs font-medium text-ink hover:border-accent disabled:opacity-50">
            “{h}”
          </button>
        ))}
      </div>
    </section>
  )
}
