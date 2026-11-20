import { describe, expect, it } from 'vitest'

import { concat, encodeWav, resample, rms } from './wav'

describe('wav helpers', () => {
  it('encodes a 16 kHz mono 16-bit PCM WAV header the server accepts', () => {
    const buf = encodeWav(new Float32Array([0, 1, -1, 0.5]))
    const v = new DataView(buf)
    const text = (o: number, n: number) => String.fromCharCode(...new Uint8Array(buf, o, n))
    expect(text(0, 4)).toBe('RIFF')
    expect(text(8, 4)).toBe('WAVE')
    expect(v.getUint16(20, true)).toBe(1) // PCM
    expect(v.getUint16(22, true)).toBe(1) // mono
    expect(v.getUint32(24, true)).toBe(16000)
    expect(v.getUint16(34, true)).toBe(16) // bits
    expect(v.getUint32(40, true)).toBe(8) // 4 samples * 2 bytes
    expect([v.getInt16(44, true), v.getInt16(46, true), v.getInt16(48, true)]).toEqual([0, 32767, -32768])
  })

  it('resamples 48 kHz to 16 kHz (a third of the samples) and leaves 16 kHz alone', () => {
    const one = new Float32Array(48000).fill(0.25)
    const out = resample(one, 48000)
    expect(out.length).toBe(16000)
    expect(out[100]).toBeCloseTo(0.25)
    const same = new Float32Array(10)
    expect(resample(same, 16000)).toBe(same)
  })

  it('concatenates chunks and measures loudness', () => {
    expect(Array.from(concat([new Float32Array([1, 2]), new Float32Array([3])]))).toEqual([1, 2, 3])
    expect(rms(new Float32Array([0, 0, 0]))).toBe(0)
    expect(rms(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5)
  })
})
