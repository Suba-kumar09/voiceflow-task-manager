"""Validate uploaded audio before any speech engine sees it (stdlib only)."""

import io
import wave
from dataclasses import dataclass

from app.services.errors import DomainError, RuleViolationError

SAMPLE_RATE = 16_000


class AudioTooLargeError(DomainError):
    status_code = 413
    code = "audio_too_large"


@dataclass(frozen=True)
class AudioClip:
    wav_bytes: bytes
    duration_s: float


def validate_wav(data: bytes, *, max_seconds: float) -> AudioClip:
    """Accept only 16 kHz, mono, 16-bit PCM WAV, at most `max_seconds` long."""
    # 16 kHz * 2 bytes * max_seconds, plus header slack.
    if len(data) > int(SAMPLE_RATE * 2 * max_seconds) + 1024:
        raise AudioTooLargeError(f"Recordings can be at most {max_seconds:g} seconds.")
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate, frames = (
                w.getnchannels(),
                w.getsampwidth(),
                w.getframerate(),
                w.getnframes(),
            )
    except (wave.Error, EOFError) as exc:
        raise RuleViolationError("The audio must be a WAV file.", code="audio_invalid") from exc
    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise RuleViolationError(
            "The audio must be 16 kHz, mono, 16-bit PCM.", code="audio_invalid"
        )
    duration = frames / rate
    if duration < 0.2:
        raise RuleViolationError("The recording is too short.", code="audio_too_short")
    if duration > max_seconds:
        raise AudioTooLargeError(f"Recordings can be at most {max_seconds:g} seconds.")
    return AudioClip(wav_bytes=data, duration_s=duration)
