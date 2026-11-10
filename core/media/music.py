"""Background music system — free & copyright-safe.

Two sources, one interface:
  1. User tracks: drop royalty-free .wav/.mp3 files into storage/music/ (and
     optional storage/music/intro, storage/music/outro). Picked deterministically.
  2. Generated score: if no user track is present, synthesize a slow chord
     progression (pads, drone, bells, reverb) with numpy — 100% copyright-safe because we generate it — so music works out
     of the box at $0.

`mix_into_video()` (in core.media.video) then lays the bed UNDER the narration
with sidechain ducking (music dips when Aria speaks) and a small intro/outro
volume lift. Nothing here downloads or ships any copyrighted audio.
"""

from __future__ import annotations

import wave
import zlib
from pathlib import Path

import numpy as np

from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger

log = get_logger("media.music")

_SR = 44100


def _user_tracks(mood: str = "") -> list[Path]:
    """Royalty-free tracks the owner added: storage/music/<category>/ first
    (history, psychology), then storage/music/ itself."""
    mdir = ROOT_DIR / get_settings().video.music_dir
    for folder in ([mdir / mood] if mood else []) + [mdir]:
        if folder.exists():
            found = sorted(p for p in folder.glob("*")
                           if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg")
                           and not p.name.startswith("_generated"))
            if found:
                return found
    return []


SR = _SR
# i - VI - III - VII in a minor key, semitones above the root, voiced low-mid.
PROGRESSIONS = [
    [(0, 3, 7, 12), (-4, 0, 3, 8), (3, 7, 10, 15), (-2, 2, 5, 10)],    # i VI III VII
    [(0, 3, 7, 12), (-2, 2, 5, 10), (-4, 0, 3, 8), (-5, -1, 2, 7)],   # i VII VI v
    [(0, 3, 7, 10), (-4, 0, 3, 7), (-7, -3, 0, 5), (-5, -2, 2, 7)],   # i VI iv v
]


def _note(freq, n, rng):
    """A warm pad voice: three slightly detuned oscillators with soft harmonics."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for det in (-0.0035, 0.0, 0.0035):
        f = freq * (1 + det)
        ph = rng.uniform(0, 2 * np.pi)
        for h, amp in ((1, 1.0), (2, 0.28), (3, 0.12), (4, 0.05)):
            out += amp * np.sin(2 * np.pi * f * h * t + ph * h)
    return out / 3


def _env(n, attack, release):
    e = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    e[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    e[-r:] = np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return e


def _reverb(x, seconds=3.2, mix=0.35, seed=1):
    """Convolution with decaying stereo noise: a large, soft hall."""
    from scipy.signal import fftconvolve
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    decay = np.exp(-np.linspace(0, 7, n))
    out = np.empty_like(x)
    for ch in range(2):
        ir = rng.standard_normal(n) * decay
        ir[: int(0.02 * SR)] *= np.linspace(0, 1, int(0.02 * SR))
        ir /= np.sqrt(np.sum(ir ** 2))
        wet = fftconvolve(x[:, ch], ir)[: len(x)]
        out[:, ch] = (1 - mix) * x[:, ch] + mix * wet
    return out


def score(seconds: float, seed_text: str = "mind_vault", mood: str = "history") -> np.ndarray:
    seed = zlib.crc32(seed_text.encode())
    rng = np.random.default_rng(seed)
    root = 110.0 * 2 ** ((seed % 7 - 3) / 12)          # around A2
    prog = PROGRESSIONS[seed % len(PROGRESSIONS)]
    chord_s = 8.0 if mood == "history" else 6.0
    total = int(seconds * SR) + int(4 * SR)
    mix = np.zeros((total, 2))
    k = 0
    start = 0.0
    while start < seconds + 2:
        chord = prog[k % len(prog)]
        n = int((chord_s + 3.0) * SR)                   # overlap 3 s for a smooth change
        i0 = int(start * SR)
        n = min(n, total - i0)
        if n <= SR:
            break
        env = _env(n, 2.5, 3.0)
        for j, semi in enumerate(chord):
            v = _note(root * 2 ** (semi / 12), n, rng) * env * (0.9 if j else 1.0)
            pan = (j / (len(chord) - 1)) * 0.6 + 0.2    # spread voices across the stereo field
            mix[i0:i0 + n, 0] += v * (1 - pan)
            mix[i0:i0 + n, 1] += v * pan
        # Low drone on the chord's root, an octave down.
        t = np.arange(n) / SR
        drone = 0.55 * np.sin(2 * np.pi * root * 2 ** (chord[0] / 12) / 2 * t) * env
        mix[i0:i0 + n] += drone[:, None] * 0.7
        # Sparse bell notes: chord tones two octaves up, soft and decaying.
        for b in np.arange(1.0, chord_s, 2.0):
            if rng.random() < 0.55:
                semi = chord[rng.integers(len(chord))] + 24
                bn = int(3.5 * SR)
                b0 = i0 + int(b * SR)
                bn = min(bn, total - b0)
                if bn <= 0:
                    continue
                tb = np.arange(bn) / SR
                f = root * 2 ** (semi / 12)
                bell = (np.sin(2 * np.pi * f * tb) + 0.25 * np.sin(2 * np.pi * f * 2.01 * tb)) \
                    * np.exp(-tb * 1.6) * np.minimum(1, tb / 0.01) * 0.35
                pan = rng.uniform(0.25, 0.75)
                mix[b0:b0 + bn, 0] += bell * (1 - pan)
                mix[b0:b0 + bn, 1] += bell * pan
        start += chord_s
        k += 1
    mix = mix[: int(seconds * SR)]
    mix = _reverb(mix, seed=seed)
    # Gentle fade in/out and a fixed loudness (the mixer sets the final level).
    f = int(2.0 * SR)
    mix[:f] *= np.linspace(0, 1, f)[:, None]
    mix[-f:] *= np.linspace(1, 0, f)[:, None]
    rms = np.sqrt(np.mean(mix ** 2)) or 1.0
    mix *= 0.12 / rms                                   # about -18 dBFS RMS
    peak = np.max(np.abs(mix))
    if peak > 0.89:
        mix *= 0.89 / peak
    return mix


def write(path: str, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())



def _procedural_bed(seconds: float, out: Path, seed_text: str = "mind_vault",
                    mood: str = "history") -> str | None:
    """A generated score: a slow minor chord progression on warm detuned pads,
    a low drone, sparse bell notes and a long hall reverb. Copyright-free
    because it is synthesised here; the same seed gives the same music."""
    try:
        x = score(max(2.0, seconds), seed_text, mood)
    except Exception as exc:
        log.warning("Score generation failed (%s).", exc)
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    write(str(out), x)
    return str(out)


def get_music_bed(seconds: float, seed_text: str = "mind_vault",
                  mood: str = "history") -> tuple[str | None, str]:
    """Return (path, source) for a background bed. source in {user, procedural, none}."""
    tracks = _user_tracks(mood)
    if tracks:
        # crc32, not hash(): Python salts hash() per process, so the pick changed per run.
        pick = tracks[zlib.crc32(seed_text.encode()) % len(tracks)]
        log.info("Using royalty-free user music: %s", pick.name)
        return str(pick), "user"
    bed = ROOT_DIR / get_settings().video.music_dir / "_generated_bed.wav"
    path = _procedural_bed(seconds, bed, seed_text, mood)
    if path:
        log.info("Using the generated score (%s).", mood)
        return path, "procedural"
    return None, "none"
