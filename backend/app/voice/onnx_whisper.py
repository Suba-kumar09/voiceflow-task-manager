"""Whisper speech recognition on ONNX Runtime (the default engine, Phase 10).

Why this exists: Windows Smart App Control on the development laptop started blocking the
unsigned native library behind faster-whisper (CTranslate2) on 2026-11-21, although it had
loaded the day before. ONNX Runtime's native files are signed by Microsoft, so they load under
Smart App Control. Everything else here is plain Python + NumPy: the log-mel features, the
GPT-2 style tokenizer and greedy decoding. No other native code is added.

Model: OpenAI Whisper `base.en` (MIT), ONNX export `onnx-community/whisper-base.en`, int8
encoder + merged decoder (with key/value cache). Fetch it with `python -m app.cli.fetch_stt_model`.

Behaviour matches the faster-whisper provider: English, greedy decoding (beam 1), no
timestamps, team/project names passed as a prompt ("Names: ..."), and the same confidence
proxies (no-speech probability and average log-probability of the chosen tokens).
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import wave
from pathlib import Path

from app.voice.stt import SpeechUnavailableError, Transcript, _is_confident

logger = logging.getLogger(__name__)

# Whisper audio front end (fixed by the model).
SAMPLE_RATE = 16_000
N_FFT = 400
HOP = 160
N_MELS = 80
CHUNK_SAMPLES = 30 * SAMPLE_RATE  # the encoder always sees 30 s (3000 frames)

# Special tokens of the English-only Whisper vocabulary.
EOT = 50256
SOT = 50257
PREV = 50360  # <|startofprev|>: the prompt follows
NO_SPEECH = 50361  # <|nocaptions|>
NO_TIMESTAMPS = 50362
FIRST_SPECIAL = 50257  # everything from here on is never emitted as text
MAX_PROMPT_TOKENS = 223  # Whisper's limit: half the 448-token context, minus one
MAX_NEW_TOKENS = 128  # a 20 s voice command is far shorter than this

ENCODER_FILE = "onnx/encoder_model_int8.onnx"
DECODER_FILE = "onnx/decoder_model_merged_int8.onnx"
REQUIRED_FILES = (ENCODER_FILE, DECODER_FILE, "vocab.json", "merges.txt", "generation_config.json")

# Below this RMS level (int16 scale ~ -60 dBFS) the clip is silence: skip the model.
SILENCE_RMS = 0.001


# ---------------------------------------------------------------------------------------------
# Audio features
# ---------------------------------------------------------------------------------------------


def _hz_to_mel(f):
    """Slaney mel scale (librosa default, as used by Whisper)."""
    import numpy as np

    f = np.asarray(f, dtype=np.float64)
    f_sp = 200.0 / 3
    mels = f / f_sp
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(
        f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mels
    )


def _mel_to_hz(m):
    import numpy as np

    m = np.asarray(m, dtype=np.float64)
    f_sp = 200.0 / 3
    freqs = f_sp * m
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), freqs)


def mel_filters():
    """80 x 201 Slaney-normalised triangular filters (= librosa.filters.mel(16000, 400, 80))."""
    import numpy as np

    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, 1 + N_FFT // 2)
    mel_pts = _mel_to_hz(np.linspace(_hz_to_mel(0.0), _hz_to_mel(SAMPLE_RATE / 2), N_MELS + 2))
    fdiff = np.diff(mel_pts)
    ramps = mel_pts[:, None] - fft_freqs[None, :]
    weights = np.zeros((N_MELS, len(fft_freqs)))
    for i in range(N_MELS):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_pts[2 : N_MELS + 2] - mel_pts[:N_MELS]))[:, None]
    return weights.astype(np.float32)


def log_mel_spectrogram(samples, filters):
    """Whisper's input features: (1, 80, 3000) float32 for up to 30 s of 16 kHz audio."""
    import numpy as np

    audio = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
    n = min(len(samples), CHUNK_SAMPLES)
    audio[:n] = samples[:n]
    padded = np.pad(audio, N_FFT // 2, mode="reflect")  # torch.stft(center=True)
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]  # 3001 frames
    power = np.abs(np.fft.rfft(frames * window, axis=-1)) ** 2  # (3001, 201)
    mel = filters @ power[:-1].T  # drop the last frame, like Whisper -> (80, 3000)
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)[None, :, :]


def wav_to_samples(wav_bytes: bytes):
    """16 kHz mono 16-bit WAV (already validated by app.voice.audio) -> float32 in [-1, 1]."""
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("expected 16 kHz mono 16-bit WAV")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------------------------
# Tokenizer (GPT-2 byte-level BPE, pure Python)
# ---------------------------------------------------------------------------------------------


def _bytes_to_unicode() -> dict[int, str]:
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs), strict=True))


# GPT-2 pre-tokenizer, written with the standard `re` module (\p{L} ~ [^\W\d_]).
_PRETOKEN = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?(?:[^\s\w]|_)+|\s+(?!\S)|\s+"""
)


class WhisperTokenizer:
    def __init__(self, model_dir: Path) -> None:
        vocab: dict[str, int] = json.loads((model_dir / "vocab.json").read_text("utf-8"))
        self._encoder = vocab
        self._decoder = {v: k for k, v in vocab.items()}
        merges = (model_dir / "merges.txt").read_text("utf-8").splitlines()
        pairs = [tuple(m.split()) for m in merges if m and not m.startswith("#version")]
        self._ranks = {p: i for i, p in enumerate(pairs) if len(p) == 2}
        self._byte_enc = _bytes_to_unicode()
        self._byte_dec = {v: k for k, v in self._byte_enc.items()}
        self._cache: dict[str, list[str]] = {}

    def _bpe(self, word: str) -> list[str]:
        if word in self._cache:
            return self._cache[word]
        parts = list(word)
        while len(parts) > 1:
            best = min(
                (
                    (self._ranks.get((a, b), 1 << 30), i)
                    for i, (a, b) in enumerate(zip(parts, parts[1:], strict=False))
                ),
            )
            if best[0] == 1 << 30:
                break
            i = best[1]
            parts = parts[:i] + [parts[i] + parts[i + 1]] + parts[i + 2 :]
        self._cache[word] = parts
        return parts

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for piece in _PRETOKEN.findall(text):
            mapped = "".join(self._byte_enc[b] for b in piece.encode("utf-8"))
            ids.extend(self._encoder[t] for t in self._bpe(mapped) if t in self._encoder)
        return ids

    def decode(self, ids: list[int]) -> str:
        text = "".join(self._decoder.get(i, "") for i in ids if i < FIRST_SPECIAL)
        return bytes(self._byte_dec[c] for c in text if c in self._byte_dec).decode(
            "utf-8", errors="replace"
        )


# ---------------------------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------------------------


def missing_files(model_dir: Path) -> list[str]:
    return [f for f in REQUIRED_FILES if not (model_dir / f).is_file()]


class OnnxWhisperProvider:
    name = "onnx-whisper"

    def __init__(self, model_dir: str | Path | None, cpu_threads: int) -> None:
        self._dir = Path(model_dir) if model_dir else None
        self._threads = cpu_threads
        self._lock = threading.Lock()  # one transcription at a time on a small CPU
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self._dir is None:
            raise SpeechUnavailableError(
                "Speech recognition is not set up: VOICEFLOW_STT_MODEL_DIR is empty."
            )
        if missing := missing_files(self._dir):
            raise SpeechUnavailableError(
                f"Speech recognition model is missing in {self._dir} ({', '.join(missing)}). "
                "Run: python -m app.cli.fetch_stt_model"
            )
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as exc:  # the optional "voice" extra is not installed
            raise SpeechUnavailableError("Speech recognition is not installed.") from exc

        t0 = time.perf_counter()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self._threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        providers = ["CPUExecutionProvider"]
        self._encoder = ort.InferenceSession(
            str(self._dir / ENCODER_FILE), opts, providers=providers
        )
        self._decoder = ort.InferenceSession(
            str(self._dir / DECODER_FILE), opts, providers=providers
        )
        self._dec_inputs = [i.name for i in self._decoder.get_inputs()]
        self._dec_outputs = [o.name for o in self._decoder.get_outputs()]
        self._n_layers = sum(1 for n in self._dec_inputs if n.endswith(".decoder.key"))
        self._tokenizer = WhisperTokenizer(self._dir)
        self._filters = mel_filters()

        gen = json.loads((self._dir / "generation_config.json").read_text("utf-8"))
        suppress = np.zeros(self._decoder.get_outputs()[0].shape[-1] or 51864, dtype=bool)
        suppress[[t for t in gen.get("suppress_tokens", []) if t < len(suppress)]] = True
        suppress[FIRST_SPECIAL:] = True  # no special or timestamp tokens in the text
        self._suppress = suppress
        self._begin_suppress = [t for t in gen.get("begin_suppress_tokens", [220, EOT])]
        self._np = np
        self._loaded = True
        logger.info(
            "STT model loaded",
            extra={"data": {"engine": self.name, "s": round(time.perf_counter() - t0, 1)}},
        )

    # -- decoding ---------------------------------------------------------------------------

    def _prompt(self, hints: list[str]) -> list[int]:
        prefix: list[int] = []
        if hints:
            text = " Names: " + ", ".join(hints) + "."
            prefix = [PREV, *self._tokenizer.encode(text)[-MAX_PROMPT_TOKENS:]]
        return [*prefix, SOT, NO_TIMESTAMPS]

    def _decode(self, features, hints: list[str]) -> tuple[list[int], float, float]:
        np = self._np
        hidden = self._encoder.run(None, {"input_features": features})[0]
        prompt = self._prompt(hints)
        sot_index = len(prompt) - 2
        empty = np.zeros((1, 8, 0, 64), dtype=np.float32)
        feeds = {
            "input_ids": np.array([prompt], dtype=np.int64),
            "encoder_hidden_states": hidden,
            "use_cache_branch": np.array([False]),
        }
        for name in self._dec_inputs:
            if name.startswith("past_key_values."):
                feeds[name] = empty

        tokens: list[int] = []
        logprob_sum = 0.0
        no_speech = 0.0
        encoder_cache: dict[str, object] = {}
        for step in range(MAX_NEW_TOKENS):
            outs = dict(zip(self._dec_outputs, self._decoder.run(None, feeds), strict=True))
            logits = outs["logits"][0]
            if step == 0:
                first = logits[sot_index].astype(np.float64)
                p = np.exp(first - first.max())
                no_speech = float(p[NO_SPEECH] / p.sum())
                for i in range(self._n_layers):
                    for kind in ("key", "value"):
                        encoder_cache[f"past_key_values.{i}.encoder.{kind}"] = outs[
                            f"present.{i}.encoder.{kind}"
                        ]
            last = logits[-1].astype(np.float64)
            last[self._suppress] = -np.inf  # end of text (EOT) stays allowed
            if step == 0:
                last[self._begin_suppress] = -np.inf
            shifted = last - last.max()
            logp = shifted - np.log(np.exp(shifted).sum())
            token = int(np.argmax(logp))
            logprob_sum += float(logp[token])
            if token == EOT:
                break
            tokens.append(token)
            if _is_looping(tokens):
                break
            feeds = {
                "input_ids": np.array([[token]], dtype=np.int64),
                "encoder_hidden_states": hidden,
                "use_cache_branch": np.array([True]),
                **encoder_cache,
            }
            for i in range(self._n_layers):
                for kind in ("key", "value"):
                    feeds[f"past_key_values.{i}.decoder.{kind}"] = outs[
                        f"present.{i}.decoder.{kind}"
                    ]
        avg_logprob = logprob_sum / (len(tokens) + 1)
        return tokens, no_speech, avg_logprob

    def transcribe(self, wav_bytes: bytes, *, hints: list[str]) -> Transcript:
        with self._lock:
            self._load()
            np = self._np
            t0 = time.perf_counter()
            samples = wav_to_samples(wav_bytes)
            if samples.size == 0 or float(np.sqrt(np.mean(samples**2))) < SILENCE_RMS:
                return Transcript("", False, 1.0, -10.0, int((time.perf_counter() - t0) * 1000))
            features = log_mel_spectrogram(samples, self._filters)
            tokens, no_speech, logprob = self._decode(features, hints)
            text = self._tokenizer.decode(tokens).strip()
            latency = int((time.perf_counter() - t0) * 1000)
        return Transcript(
            text, _is_confident(text, no_speech, logprob), no_speech, logprob, latency
        )


def _is_looping(tokens: list[int], max_period: int = 6, min_len: int = 12) -> bool:
    """True when the last `min_len`+ tokens are one short phrase repeated (a hallucination
    loop such as "the the the ..."), so decoding stops instead of running to the limit."""
    for period in range(1, max_period + 1):
        length = max(min_len, 3 * period)
        if len(tokens) < length:
            continue
        tail = tokens[-length:]
        if all(tail[i] == tail[i % period] for i in range(length)):
            return True
    return False
