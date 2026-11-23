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

const HANDS_FREE_KEY = 'vf.handsFree'

function readHandsFree(): boolean {
  try {
    return localStorage.getItem(HANDS_FREE_KEY) !== 'off'
  } catch {
    return true
  }
}

function saveHandsFree(on: boolean) {
  try {
    localStorage.setItem(HANDS_FREE_KEY, on ? 'on' : 'off')
  } catch {
    /* private window: the choice just isn't remembered */
  }
}

/** Phases after which hands-free mode opens the microphone again by itself. */
const RELISTEN: VoicePhase[] = ['ready', 'attention', 'confirm', 'error']

/**
 * The voice state machine. The phase is only 'listening' while the recorder is truly running.
 *
 * Hands-free mode (default on): the microphone opens by itself, waits for the person to speak,
 * sends the sentence, speaks the answer, and opens again. It is closed while VoiceFlow talks,
 * so it never hears itself. Sentences that are not commands (other people talking nearby) are
 * shown but not answered aloud. Changes still need a spoken "yes".
 */
export function useVoice(tts: TextToSpeech = defaultSpeech) {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const summary = useContext(PageSummaryContext)
  const [phase, setPhase] = useState<VoicePhase>('ready')
  const [muted, setMuted] = useState(false)
  const [handsFree, setHandsFree] = useState(readHandsFree)
  const [needsTap, setNeedsTap] = useState(false)
  const [level, setLevel] = useState(0)
  const [captions, setCaptions] = useState<Captions>({})
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [checks, setChecks] = useState<VoiceCheck[]>([])
  const [plan, setPlan] = useState<VoicePlanRow[]>([])
  const [awaiting, setAwaiting] = useState(false)
  const recorder = useRef<MicRecorder | null>(null)
  const lastSpeech = useRef('')
  const interrupted = useRef(false) // the open microphone was closed on purpose (typing, announcement)

  useEffect(() => () => void recorder.current?.abort(), [])

  const context = useCallback(
    () => ({ path: location.pathname + location.search, pageSummary: summary.current }),
    [location.pathname, location.search, summary],
  )

  /** Close the microphone without sending anything. */
  const closeMic = useCallback(() => {
    if (!recorder.current) return
    interrupted.current = true
    void recorder.current.abort()
    recorder.current = null
  }, [])

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
    async (turn: VoiceTurn, overheard: boolean) => {
      // Hands-free: a sentence that is not a command (or too unclear) is probably someone else
      // talking. Show it, but do not answer aloud and do not change the screen.
      if (overheard && (turn.outcome === 'unsupported' || turn.outcome === 'repeat')) {
        setCaptions({ you: turn.transcript ?? undefined, bot: 'Not a command, so I ignored it. Say “help” to hear what you can say.' })
        setPhase('ready')
        return
      }
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
    async (send: () => Promise<VoiceTurn>, overheard = false) => {
      setProblem(null)
      setPhase('understanding')
      try {
        await apply(await send(), overheard)
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
      closeMic()
      tts.cancel()
      setCaptions({ you: text })
      void run(() => voiceApi.text(text, context()))
    },
    [closeMic, context, run, tts],
  )

  /** Listen for one sentence. `auto` = opened by hands-free mode, not by a button press. */
  const listen = useCallback(
    async (auto: boolean) => {
      if (muted || recorder.current) return
      tts.cancel()
      setProblem(null)
      if (!auto) setCaptions({})
      interrupted.current = false
      const rec = new MicRecorder(setLevel, { waitForSpeech: auto })
      recorder.current = rec
      try {
        const pending = rec.record()
        setPhase('listening')
        const clip = await pending
        if (recorder.current === rec) recorder.current = null
        if (interrupted.current) return // closed on purpose; whoever closed it sets the phase
        if (!clip || !clip.heardSpeech) {
          if (auto) {
            setPhase('ready') // nothing said: hands-free simply listens again
            return
          }
          setCaptions({ bot: 'I didn’t hear anything. Press the microphone and speak.' })
          setPhase('attention')
          return
        }
        await run(() => voiceApi.audio(clip.wav, context()), auto)
      } catch (err) {
        if (recorder.current === rec) recorder.current = null
        if (err instanceof MicrophoneError && err.kind === 'needs-gesture') {
          setNeedsTap(true)
          setPhase('ready')
        } else if (err instanceof MicrophoneError) {
          setProblem(err.kind === 'denied' ? 'Microphone permission was refused. Allow it in the browser’s site settings, then try again.' : 'No microphone is available on this device.')
          setPhase('unavailable')
        } else {
          setProblem(errorMessage(err))
          setPhase('error')
        }
      }
    },
    [context, muted, run, tts],
  )

  /** Mic button: stop now and send what was said, or start listening. */
  const toggleListening = useCallback(async () => {
    if (muted) return
    if (recorder.current) {
      await recorder.current.stop() // the pending record() promise continues in listen()
      return
    }
    setNeedsTap(false)
    await listen(false)
  }, [listen, muted])

  // Hands-free loop: whenever VoiceFlow is idle, open the microphone again.
  useEffect(() => {
    if (!handsFree || muted || needsTap || !MicRecorder.supported()) return
    if (!RELISTEN.includes(phase) || recorder.current) return
    const t = setTimeout(() => void listen(true), phase === 'error' ? 3000 : 300)
    return () => clearTimeout(t)
  }, [handsFree, muted, needsTap, phase, listen])

  // Browsers allow the microphone/sound only after one click or key press on the page.
  useEffect(() => {
    if (!needsTap) return
    const unlock = () => setNeedsTap(false)
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [needsTap])

  const toggleHandsFree = useCallback(() => {
    setHandsFree((on) => {
      const next = !on
      saveHandsFree(next)
      if (!next) {
        closeMic()
        setPhase('ready')
      }
      return next
    })
  }, [closeMic])

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m
      if (next) {
        closeMic()
        tts.cancel()
        setPhase('muted')
      } else {
        setPhase('ready')
      }
      return next
    })
  }, [closeMic, tts])

  /** Speak an unprompted announcement (e.g. a new notification) when nobody is talking. */
  const announce = useCallback(
    (text: string) => {
      if (muted || !text) return false
      const waiting = phase === 'listening' && handsFree && recorder.current && !recorder.current.hasSpeech
      if (phase !== 'ready' && !waiting) return false
      if (waiting) closeMic()
      setCaptions({ bot: text })
      setSuggestions([])
      void say(text, 'ready')
      return true
    },
    [closeMic, handsFree, muted, phase, say],
  )

  return useMemo(
    () => ({ phase, muted, handsFree, needsTap, level, captions, suggestions, problem, checks, plan, awaiting, sendText, toggleListening, toggleMute, toggleHandsFree, announce, speechAvailable: tts.available }),
    [phase, muted, handsFree, needsTap, level, captions, suggestions, problem, checks, plan, awaiting, sendText, toggleListening, toggleMute, toggleHandsFree, announce, tts.available],
  )
}

const defaultSpeech = new BrowserSpeech()
