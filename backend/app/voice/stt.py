"""Speech-to-text providers. Business logic depends only on the `SpeechToTextProvider` protocol.

- FasterWhisperProvider: local, CPU, int8 (measured ~1.3 s for 7 s of speech on the dev laptop).
- FakeSpeechToText: deterministic, for tests (never depend on the real model in CI).
"""

import io
import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.services.errors import DomainError

logger = logging.getLogger(__name__)


class SpeechUnavailableError(DomainError):
    status_code = 503
    code = "speech_unavailable"


@dataclass(frozen=True)
class Transcript:
    text: str
    confident: bool  # False => ask the speaker to repeat
    no_speech_prob: float
    avg_logprob: float
    latency_ms: int


class SpeechToTextProvider(Protocol):
    name: str

    def transcribe(self, wav_bytes: bytes, *, hints: list[str]) -> Transcript: ...


def _is_confident(text: str, no_speech_prob: float, avg_logprob: float) -> bool:
    # Whisper has no calibrated confidence; these proxies catch silence and mumbles.
    return bool(text.strip()) and no_speech_prob < 0.6 and avg_logprob > -1.0


class FasterWhisperProvider:
    name = "faster-whisper"

    def __init__(self, model_size: str, cpu_threads: int) -> None:
        self._model_size = model_size
        self._threads = cpu_threads
        self._model = None
        self._lock = threading.Lock()  # one transcription at a time on a small CPU

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # the optional "voice" extra is not installed
                raise SpeechUnavailableError("Speech recognition is not installed.") from exc
            t0 = time.perf_counter()
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8", cpu_threads=self._threads
            )
            logger.info(
                "STT model loaded",
                extra={
                    "data": {"model": self._model_size, "s": round(time.perf_counter() - t0, 1)}
                },
            )
        return self._model

    def transcribe(self, wav_bytes: bytes, *, hints: list[str]) -> Transcript:
        with self._lock:
            model = self._load()
            t0 = time.perf_counter()
            prompt = ("Names: " + ", ".join(hints) + ".") if hints else None
            segments, _info = model.transcribe(
                io.BytesIO(wav_bytes),
                language="en",
                beam_size=1,
                vad_filter=True,
                initial_prompt=prompt,
                condition_on_previous_text=False,
            )
            segments = list(segments)
            latency = int((time.perf_counter() - t0) * 1000)
        text = " ".join(s.text.strip() for s in segments).strip()
        if segments:
            no_speech = max(s.no_speech_prob for s in segments)
            logprob = sum(s.avg_logprob for s in segments) / len(segments)
        else:
            no_speech, logprob = 1.0, -10.0
        return Transcript(
            text, _is_confident(text, no_speech, logprob), no_speech, logprob, latency
        )


class FakeSpeechToText:
    """Returns a scripted transcript. `confident=False` simulates a mumble."""

    name = "fake"

    def __init__(self, text: str = "", confident: bool = True) -> None:
        self.text = text
        self.confident = confident
        self.calls: list[list[str]] = []

    def transcribe(self, wav_bytes: bytes, *, hints: list[str]) -> Transcript:
        self.calls.append(hints)
        return Transcript(self.text, self.confident, 0.0 if self.confident else 0.9, -0.2, 5)


class DisabledSpeechToText:
    name = "disabled"

    def transcribe(self, wav_bytes: bytes, *, hints: list[str]) -> Transcript:
        raise SpeechUnavailableError("Speech recognition is turned off on this server.")


@lru_cache
def get_stt_provider() -> SpeechToTextProvider:
    """FastAPI dependency (overridden in tests). One shared model per process."""
    s = get_settings()
    if s.stt_provider == "disabled":
        return DisabledSpeechToText()
    return FasterWhisperProvider(s.stt_model, s.stt_cpu_threads)
