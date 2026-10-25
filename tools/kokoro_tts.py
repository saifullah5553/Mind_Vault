"""Kokoro TTS runner — executed by the ISOLATED Python 3.12 environment.

Kokoro cannot be installed into the project's Python 3.13: it pins
numpy==1.26.4 (no 3.13 wheel) and pulls misaki->spacy, which also has no 3.13
wheel, so pip tries to compile and fails without MSVC. Rather than downgrade the
whole project, Kokoro lives in `tools/kokoro-env` (Python 3.12, created with uv)
and the pipeline calls this script as a subprocess.

That isolation is also the security posture we want: Kokoro and its dependency
tree never enter the main environment.

Usage (invoked by core/media/tts.py):
    kokoro-env/Scripts/python.exe tools/kokoro_tts.py --text-file in.txt \
        --out out.wav --voice af_heart --speed 1.0
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthesize narration with Kokoro")
    ap.add_argument("--text-file", required=True, help="UTF-8 file holding the narration")
    ap.add_argument("--out", required=True, help="output .wav path")
    ap.add_argument("--voice", default="af_heart", help="Kokoro voice id")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="a", help="'a'=American English, 'b'=British")
    args = ap.parse_args()

    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except Exception as exc:
        print(f"KOKORO_IMPORT_ERROR: {exc}", file=sys.stderr)
        return 2

    with open(args.text_file, "r", encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        print("KOKORO_ERROR: empty text", file=sys.stderr)
        return 3

    try:
        pipeline = KPipeline(lang_code=args.lang)
        chunks = []
        # Kokoro yields audio per chunk; concatenate into one narration track.
        for _gs, _ps, audio in pipeline(text, voice=args.voice, speed=args.speed):
            if audio is None:
                continue
            arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(arr.astype("float32"))
        if not chunks:
            print("KOKORO_ERROR: no audio produced", file=sys.stderr)
            return 4
        full = np.concatenate(chunks)
        sf.write(args.out, full, 24000)          # Kokoro renders at 24 kHz
        print(f"KOKORO_OK {len(full) / 24000:.2f}s")
        return 0
    except Exception as exc:
        print(f"KOKORO_ERROR: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
