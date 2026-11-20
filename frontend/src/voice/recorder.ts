/**
 * Push-to-talk microphone recorder.
 * - Records ONLY between start() and stop(); the microphone is released immediately after.
 * - Auto-stops after ~1.2 s of silence once speech was heard, or after maxSeconds.
 * - Returns a 16 kHz mono 16-bit WAV ready for the server.
 */
import { concat, encodeWav, resample, rms } from './wav'

export type MicError = 'denied' | 'unavailable'

export class MicrophoneError extends Error {
  readonly kind: MicError
  constructor(kind: MicError, message: string) {
    super(message)
    this.kind = kind
  }
}

const SPEECH_LEVEL = 0.02 // RMS above this counts as speech
const SILENCE_MS = 1200
const MAX_SECONDS = 15

// Runs in the audio thread; posts raw float frames back to the page.
const WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor('vf-capture', Capture);
`

export interface Recording {
  wav: Blob
  seconds: number
  heardSpeech: boolean
}

export class MicRecorder {
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private chunks: Float32Array[] = []
  private heard = false
  private lastLoud = 0
  private started = 0
  private resolveStop: ((r: Recording | null) => void) | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private readonly onLevel: (level: number) => void

  constructor(onLevel: (level: number) => void = () => {}) {
    this.onLevel = onLevel
  }

  static supported(): boolean {
    return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioWorkletNode !== 'undefined'
  }

  /** Starts recording; resolves when recording ends (auto-stop or stop()). */
  async record(): Promise<Recording | null> {
    if (!MicRecorder.supported()) {
      throw new MicrophoneError('unavailable', 'This browser cannot record audio.')
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch (err) {
      const denied = err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError')
      throw new MicrophoneError(denied ? 'denied' : 'unavailable', denied ? 'Microphone permission was refused.' : 'No microphone was found.')
    }
    this.ctx = new AudioContext()
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    try {
      await this.ctx.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    const source = this.ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.ctx, 'vf-capture')
    this.chunks = []
    this.heard = false
    this.started = this.lastLoud = performance.now()
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      this.chunks.push(e.data)
      const level = rms(e.data)
      this.onLevel(Math.min(1, level * 8))
      if (level > SPEECH_LEVEL) {
        this.heard = true
        this.lastLoud = performance.now()
      }
    }
    source.connect(this.node)
    this.timer = setInterval(() => {
      const now = performance.now()
      if ((this.heard && now - this.lastLoud > SILENCE_MS) || now - this.started > MAX_SECONDS * 1000) void this.stop()
    }, 100)
    return new Promise((resolve) => (this.resolveStop = resolve))
  }

  /** Stop now (button press). Safe to call more than once. */
  async stop(): Promise<void> {
    const resolve = this.resolveStop
    if (!resolve) return
    this.resolveStop = null
    if (this.timer) clearInterval(this.timer)
    const rate = this.ctx?.sampleRate ?? 48_000
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop()) // release the microphone immediately
    await this.ctx?.close()
    this.onLevel(0)
    const samples = resample(concat(this.chunks), rate)
    this.chunks = []
    if (samples.length < 16_000 * 0.25) return resolve(null) // too short to be speech
    resolve({ wav: new Blob([encodeWav(samples)], { type: 'audio/wav' }), seconds: samples.length / 16_000, heardSpeech: this.heard })
  }

  /** Discard without sending (cancel / unmount). */
  async abort(): Promise<void> {
    this.chunks = []
    const resolve = this.resolveStop
    this.resolveStop = null
    if (this.timer) clearInterval(this.timer)
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    await this.ctx?.close().catch(() => {})
    this.onLevel(0)
    resolve?.(null)
  }
}
