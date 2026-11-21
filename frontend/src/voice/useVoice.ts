import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { errorMessage } from '../components/ui/errorMessage'
import { voiceApi, type VoiceCheck, type VoicePlanRow, type VoiceTurn } from '../services/api'
import { PageSummaryContext } from './pageSummary'
import { MicRecorder, MicrophoneError } from './recorder'
import { BrowserSpeech, type TextToSpeech } from './tts'

export type VoicePhase =
  | 'ready'
  | 'listening'
  | 'understanding'
  | 'speaking'
  | 'attention' // need clarification / repeat / not allowed
  | 'confirm' // a change is read back and waits for "yes"
  | 'error'
  | 'muted'
  | 'unavailable' // no microphone or permission refused

export interface Captions {
  you?: string
  bot?: string
}

/** The voice state machine. The phase is only 'listening' while the recorder is truly running. */
export function useVoice(tts: TextToSpeech = defaultSpeech) {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const summary = useContext(PageSummaryContext)
  const [phase, setPhase] = useState<VoicePhase>('ready')
  const [muted, setMuted] = useState(false)
  const [level, setLevel] = useState(0)
  const [captions, setCaptions] = useState<Captions>({})
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [checks, setChecks] = useState<VoiceCheck[]>([])
  const [plan, setPlan] = useState<VoicePlanRow[]>([])
  const [awaiting, setAwaiting] = useState(false)
  const recorder = useRef<MicRecorder | null>(null)
  const lastSpeech = useRef('')

  useEffect(() => () => void recorder.current?.abort(), [])

  const context = useCallback(
    () => ({ path: location.pathname + location.search, pageSummary: summary.current }),
    [location.pathname, location.search, summary],
  )

  const say = useCallback(
    async (text: string, after: VoicePhase) => {
      lastSpeech.current = text || lastSpeech.current
      if (muted || !text) {
        setPhase(after)
        return
      }
      setPhase('speaking')
      await tts.speak(text)
      setPhase(after)
    },
    [muted, tts],
  )

  const apply = useCallback(
    async (turn: VoiceTurn) => {
      setCaptions({ you: turn.transcript ?? undefined, bot: turn.speech || undefined })
      setSuggestions(turn.suggestions)
      setChecks(turn.checks ?? [])
      setPlan(turn.plan ?? [])
      setAwaiting(turn.awaiting_confirmation)
      const a = turn.action
      if (a?.type === 'navigate') navigate(a.to)
      else if (a?.type === 'back') navigate(-1)
      else if (a?.type === 'stop') {
        tts.cancel()
        setPhase('ready')
        return
      } else if (a?.type === 'repeat') {
        setCaptions((c) => ({ ...c, bot: lastSpeech.current }))
        await say(lastSpeech.current, 'ready')
        return
      }
      // A change was made (or a question read fresh data): refresh every screen.
      if (turn.outcome === 'done' || turn.intent.startsWith('query.') || a?.type === 'navigate') void qc.invalidateQueries()
      const after: VoicePhase =
        turn.outcome === 'confirm' ? 'confirm' : turn.outcome === 'ok' || turn.outcome === 'done' ? 'ready' : 'attention'
      await say(turn.speech, after)
    },
    [navigate, qc, say, tts],
  )

  const run = useCallback(
    async (send: () => Promise<VoiceTurn>) => {
      setProblem(null)
      setPhase('understanding')
      try {
        await apply(await send())
      } catch (err) {
        setProblem(errorMessage(err))
        setPhase('error')
      }
    },
    [apply],
  )

  const sendText = useCallback(
    (text: string) => {
      if (!text.trim()) return
      tts.cancel()
      setCaptions({ you: text })
      void run(() => voiceApi.text(text, context()))
    },
    [context, run, tts],
  )

  const toggleListening = useCallback(async () => {
    if (muted) return
    if (recorder.current) {
      await recorder.current.stop() // the pending record() promise continues below
      return
    }
    tts.cancel()
    setProblem(null)
    setCaptions({})
    const rec = new MicRecorder(setLevel)
    recorder.current = rec
    try {
      const pending = rec.record()
      setPhase('listening')
      const clip = await pending
      recorder.current = null
      if (!clip || !clip.heardSpeech) {
        setCaptions({ bot: 'I didn’t hear anything. Press the microphone and speak.' })
        setPhase('attention')
        return
      }
      await run(() => voiceApi.audio(clip.wav, context()))
    } catch (err) {
      recorder.current = null
      if (err instanceof MicrophoneError) {
        setProblem(err.kind === 'denied' ? 'Microphone permission was refused. Allow it in the browser’s site settings, then try again.' : 'No microphone is available on this device.')
        setPhase('unavailable')
      } else {
        setProblem(errorMessage(err))
        setPhase('error')
      }
    }
  }, [context, muted, run, tts])

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m
      if (next) {
        void recorder.current?.abort()
        recorder.current = null
        tts.cancel()
        setPhase('muted')
      } else {
        setPhase('ready')
      }
      return next
    })
  }, [tts])

  /** Speak an unprompted announcement (e.g. a new notification). Only when idle and not muted. */
  const announce = useCallback(
    (text: string) => {
      if (muted || phase !== 'ready' || !text) return false
      setCaptions({ bot: text })
      setSuggestions([])
      void say(text, 'ready')
      return true
    },
    [muted, phase, say],
  )

  return useMemo(
    () => ({ phase, muted, level, captions, suggestions, problem, checks, plan, awaiting, sendText, toggleListening, toggleMute, announce, speechAvailable: tts.available }),
    [phase, muted, level, captions, suggestions, problem, checks, plan, awaiting, sendText, toggleListening, toggleMute, announce, tts.available],
  )
}

const defaultSpeech = new BrowserSpeech()
