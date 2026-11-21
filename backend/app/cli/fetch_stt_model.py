"""Download the speech recognition model used by the default `onnx-whisper` engine.

Usage (from backend/):
    python -m app.cli.fetch_stt_model                      # into VOICEFLOW_STT_MODEL_DIR
    python -m app.cli.fetch_stt_model --dir D:\\ai-cache\\models\\whisper-base.en-onnx

Model: OpenAI Whisper base.en (MIT licence), ONNX export from Hugging Face
`onnx-community/whisper-base.en`, pinned to one revision so every install is identical.
Downloads one file at a time and resumes partial files (works on a slow mobile hotspot).
About 78 MB in total. Files that are already complete are skipped.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

from app.core.config import get_settings

REPO = "onnx-community/whisper-base.en"
REVISION = "51eefc0af78b103839eda9e7e4f4186acc6517fe"
# file -> exact size in bytes (a wrong size means a broken or changed download)
FILES = {
    "config.json": None,
    "generation_config.json": None,
    "preprocessor_config.json": None,
    "vocab.json": 999_186,
    "merges.txt": 456_318,
    "added_tokens.json": 34_604,
    "onnx/encoder_model_int8.onnx": 23_201_297,
    "onnx/decoder_model_merged_int8.onnx": 53_692_803,
}


def fetch(url: str, dest: Path, size: int | None) -> None:
    done = dest.stat().st_size if dest.exists() else 0
    if size is not None and done == size:
        print(f"  ok      {dest.name}")
        return
    if size is None or done > size:
        done = 0
    req = urllib.request.Request(url, headers={"User-Agent": "voiceflow-setup"})  # noqa: S310
    if done:
        req.add_header("Range", f"bytes={done}-")
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (fixed https URL)
        mode = "ab" if done and r.status == 206 else "wb"
        with dest.open(mode) as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    got = dest.stat().st_size
    if size is not None and got != size:
        raise RuntimeError(f"{dest.name}: expected {size} bytes, got {got}. Run again to resume.")
    print(f"  fetched {dest.name} ({got / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=None)
    args = ap.parse_args()
    target = args.dir or (Path(d) if (d := get_settings().stt_model_dir) else None)
    if target is None:
        print("Give --dir or set VOICEFLOW_STT_MODEL_DIR.", file=sys.stderr)
        return 2
    print(f"Speech model -> {target}")
    for name, size in FILES.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        fetch(f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}", dest, size)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
