"""ONNX Whisper engine: pure-Python parts always; the real model only when it is installed."""

import io
import os
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from app.voice import onnx_whisper as ow  # noqa: E402
from app.voice.stt import SpeechUnavailableError  # noqa: E402

MODEL_DIR = Path(
    os.environ.get("VOICEFLOW_STT_MODEL_DIR", "D:/ai-cache/models/whisper-base.en-onnx")
)
HAVE_MODEL = not ow.missing_files(MODEL_DIR)


def wav(samples) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes((np.asarray(samples) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_mel_filters_shape_and_normalisation():
    f = ow.mel_filters()
    assert f.shape == (80, 201)
    assert (f >= 0).all()
    assert (f.sum(axis=1) > 0).all()  # every band covers some frequencies


def test_features_have_whisper_shape_and_range():
    t = np.arange(16_000) / 16_000
    feats = ow.log_mel_spectrogram(np.sin(2 * np.pi * 440 * t).astype(np.float32), ow.mel_filters())
    assert feats.shape == (1, 80, 3000)
    assert feats.dtype == np.float32
    assert feats.max() <= 1.6 and feats.min() >= feats.max() - 2.01  # 8 log10 units / 4


def test_wav_round_trip():
    x = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    y = ow.wav_to_samples(wav(x))
    assert np.allclose(x, y, atol=1e-4)


def test_loop_detection():
    assert ow._is_looping([5] * 12)
    assert ow._is_looping([1, 2, 3] * 4)
    assert not ow._is_looping([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    assert not ow._is_looping([7] * 5)  # "no no no no no" is allowed


def test_missing_model_is_a_clear_503(tmp_path):
    p = ow.OnnxWhisperProvider(tmp_path, 1)
    with pytest.raises(SpeechUnavailableError) as e:
        p.transcribe(wav(np.zeros(16_000)), hints=[])
    assert "fetch_stt_model" in str(e.value)
    with pytest.raises(SpeechUnavailableError):
        ow.OnnxWhisperProvider(None, 1).transcribe(wav(np.zeros(16_000)), hints=[])


@pytest.mark.skipif(not HAVE_MODEL, reason="speech model not downloaded")
def test_tokenizer_round_trip():
    tok = ow.WhisperTokenizer(MODEL_DIR)
    text = " Names: Kavitha, Subashini, E-Commerce Application Development."
    ids = tok.encode(text)
    assert all(i < ow.FIRST_SPECIAL for i in ids)
    assert tok.decode(ids) == text


@pytest.mark.skipif(not HAVE_MODEL, reason="speech model not downloaded")
def test_silence_is_not_confident():
    p = ow.OnnxWhisperProvider(MODEL_DIR, 2)
    t = p.transcribe(wav(np.zeros(16_000)), hints=["Kavitha"])
    assert t.confident is False
    assert t.text == ""
