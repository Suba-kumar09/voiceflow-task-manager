"""Voice evaluation: real speech recognition + real intent parser, clean and with noise.

    python -m evals.run_voice_eval --audio D:\\voiceflow-eval\\audio --out D:\\voiceflow-eval

Each recording (from evals/synthesize.ps1) is tested clean and mixed with noise at fixed
signal-to-noise ratios. Noise is deterministic (fixed seed) so runs are comparable.

Scored per condition:
- intent accuracy: the right command was recognised;
- slot accuracy: the expected details (task, person, reason, percent...) were present;
- asked to repeat: the recogniser was unsure, so VoiceFlow asked again (safe);
- word error rate (WER) of the transcript;
- unsafe: a confident, WRONG result that is a change command or a "yes". Even then the harness
  reads the change back and needs a "yes", so this is a near-miss count, not a wrong change.
"""

import argparse
import io
import json
import re
import wave
from pathlib import Path

import numpy as np

from app.agent.intents import parse
from app.core.config import get_settings
from app.voice.stt import FasterWhisperProvider

HERE = Path(__file__).parent
CHANGES = {
    "task.start",
    "task.complete",
    "task.block",
    "task.extend",
    "task.progress",
    "task.decline",
    "task.assign",
    "task.approve",
    "task.reject",
    "task.resume",
    "extension.approve",
    "extension.deny",
    "project.start",
    "project.assign_ready",
    "confirm.yes",
}
CONDITIONS = [
    ("clean", None, None),
    ("office 20 dB", "babble", 20),
    ("office 10 dB", "babble", 10),
    ("office 5 dB", "babble", 5),
    ("hiss 10 dB", "white", 10),
]


def read(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)


def to_wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    p_s = np.mean(speech**2) + 1e-9
    p_n = np.mean(noise**2) + 1e-9
    return speech + noise * np.sqrt(p_s / (p_n * 10 ** (snr_db / 10)))


def babble(others: list[np.ndarray], length: int, rng: np.random.Generator) -> np.ndarray:
    """Office background: three other people talking at once, plus a little room hum."""
    out = np.zeros(length, dtype=np.float32)
    for o in rng.choice(len(others), size=3, replace=False):
        clip = np.tile(others[o], length // len(others[o]) + 2)
        start = rng.integers(0, len(others[o]))
        out += clip[start : start + length]
    hum = 0.02 * np.std(out) * np.sin(2 * np.pi * 100 * np.arange(length) / 16_000)
    return out + hum


def words(s: str) -> list[str]:
    s = s.lower().replace("%", " percent").replace("-", " ")
    return re.findall(r"[a-z0-9']+", s)


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def slots_ok(expected: dict, got: dict) -> bool:
    return all(v.lower() in str(got.get(k, "")).lower() for k, v in expected.items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--engine",
        choices=["onnx-whisper", "faster-whisper"],
        default=None,
        help="default: VOICEFLOW_STT_PROVIDER",
    )
    ap.add_argument("--model", default="base.en", help="faster-whisper model name")
    args = ap.parse_args()

    data = json.loads((HERE / "voice_dataset.json").read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in data["items"]}
    files = sorted(args.audio.glob("*.wav"))
    clips = {f.stem: read(f) for f in files}
    settings = get_settings()
    engine = args.engine or settings.stt_provider
    if engine == "faster-whisper":
        stt = FasterWhisperProvider(args.model, 4)
    else:
        from app.voice.onnx_whisper import OnnxWhisperProvider

        stt = OnnxWhisperProvider(settings.stt_model_dir, settings.stt_cpu_threads)
    print(f"Speech engine: {stt.name}", flush=True)
    rng = np.random.default_rng(20261121)
    rows = []
    for name, kind, snr in CONDITIONS:
        for stem, speech in clips.items():
            item = by_id[stem.split("_")[0]]
            if kind is None:
                audio = speech
            else:
                if kind == "white":
                    noise = rng.normal(0, 1, len(speech)).astype(np.float32)
                else:
                    others = [c for s, c in clips.items() if s.split("_")[0] != item["id"]]
                    noise = babble(others, len(speech), rng)
                audio = mix(speech, noise, snr)
            t = stt.transcribe(to_wav(audio), hints=data["hints"])
            intent = parse(t.text) if t.confident else None
            got = intent.name if intent else "(asked to repeat)"
            correct = intent is not None and got == item["intent"]
            errs, n = wer(item["text"], t.text)
            rows.append(
                {
                    "condition": name,
                    "clip": stem,
                    "expected": item["intent"],
                    "said": item["text"],
                    "heard": t.text,
                    "confident": t.confident,
                    "got": got,
                    "correct": correct,
                    "slots_ok": correct and slots_ok(item.get("slots", {}), intent.slots),
                    "unsafe": intent is not None and not correct and got in CHANGES,
                    "wer_errors": errs,
                    "wer_words": n,
                    "ms": t.latency_ms,
                }
            )
            print(
                f"[{name}] {stem}: {'OK ' if correct else 'BAD'} heard={t.text!r} -> {got}",
                flush=True,
            )

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(
        "\n| Condition | Intent correct | Details correct | Asked to repeat | Wrong (unsafe) | WER | Median ms |"
    )
    print("|---|---|---|---|---|---|---|")
    for name, *_ in CONDITIONS:
        rs = [r for r in rows if r["condition"] == name]
        n = len(rs)

        def pct(k: str, rs=rs, n=n) -> str:
            return f"{100 * sum(r[k] for r in rs) / n:.0f}%"

        repeat = sum(not r["confident"] for r in rs)
        werr = sum(r["wer_errors"] for r in rs) / max(1, sum(r["wer_words"] for r in rs))
        print(
            f"| {name} | {pct('correct')} | {pct('slots_ok')} | {100 * repeat / n:.0f}% | "
            f"{sum(r['unsafe'] for r in rs)} of {n} | {100 * werr:.0f}% | {int(np.median([r['ms'] for r in rs]))} |"
        )
    print("\nWrong results (not 'asked to repeat'):")
    for r in rows:
        if r["confident"] and not r["correct"]:
            print(
                f"- [{r['condition']}] {r['clip']}: said {r['said']!r}, heard {r['heard']!r} -> {r['got']}"
                f"{'  (UNSAFE)' if r['unsafe'] else ''}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
