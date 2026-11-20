/** Text-to-speech provider. Phase 6 uses the browser's built-in voices (local on Windows). */

export interface TextToSpeech {
  readonly available: boolean
  speak(text: string): Promise<void>
  cancel(): void
}

function pickVoice(synth: SpeechSynthesis): SpeechSynthesisVoice | null {
  const voices = synth.getVoices().filter((v) => v.lang.toLowerCase().startsWith('en'))
  for (const lang of ['en-in', 'en-gb', 'en-us']) {
    const local = voices.find((v) => v.lang.toLowerCase() === lang && v.localService)
    if (local) return local
  }
  return voices.find((v) => v.localService) ?? voices[0] ?? null
}

export class BrowserSpeech implements TextToSpeech {
  private get synth(): SpeechSynthesis | null {
    return typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null
  }

  get available(): boolean {
    return this.synth !== null
  }

  speak(text: string): Promise<void> {
    const synth = this.synth
    if (!synth || !text.trim()) return Promise.resolve()
    synth.cancel()
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text)
      const voice = pickVoice(synth)
      if (voice) u.voice = voice
      u.rate = 1.02
      u.onend = () => resolve()
      u.onerror = () => resolve() // never block the UI on audio problems
      synth.speak(u)
    })
  }

  cancel(): void {
    this.synth?.cancel()
  }
}
