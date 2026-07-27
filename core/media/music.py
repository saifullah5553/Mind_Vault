"""Background music system — free & copyright-safe.

Two sources, one interface:
  1. User tracks: drop royalty-free .wav/.mp3 files into storage/music/ (and
     optional storage/music/intro, storage/music/outro). Picked deterministically.
  2. Procedural bed: if no user track is present, synthesize a gentle ambient pad
     with numpy — 100% copyright-safe because we generate it — so music works out
     of the box at $0.

`mix_into_video()` (in core.media.video) then lays the bed UNDER the narration
with sidechain ducking (music dips when Aria speaks) and a small intro/outro
volume lift. Nothing here downloads or ships any copyrighted audio.
"""

from __future__ import annotations

import wave
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger

log = get_logger("media.music")

_SR = 44100


def _user_tracks() -> list[Path]:
    mdir = ROOT_DIR / get_settings().video.music_dir
    if not mdir.exists():
        return []
    return sorted([p for p in mdir.glob("*") if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg")
                   and not p.name.startswith("_generated")])


def _procedural_bed(seconds: float, out: Path, seed_text: str = "mind_vault") -> str | None:
    """Synthesize a calm ambient pad (root + fifth + slow tremolo). Stereo WAV."""
    try:
        import numpy as np
    except Exception:
        return None
    dur = max(2.0, seconds)
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    # Deterministic key from the seed so different videos vary a little.
    root = 110.0 * (2 ** ((abs(hash(seed_text)) % 5) / 12.0))  # ~A2 area
    pad = (np.sin(2 * np.pi * root * t)
           + 0.6 * np.sin(2 * np.pi * root * 1.5 * t)      # perfect fifth
           + 0.4 * np.sin(2 * np.pi * root * 2.0 * t))     # octave
    tremolo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.08 * t)   # slow amplitude drift
    # Gentle fade in/out to avoid clicks.
    fade = np.ones(n)
    f = int(_SR * 1.5)
    fade[:f] = np.linspace(0, 1, f)
    fade[-f:] = np.linspace(1, 0, f)
    sig = pad * tremolo * fade
    sig = sig / (np.max(np.abs(sig)) or 1.0) * 0.35        # keep it quiet
    stereo = np.stack([sig, np.roll(sig, 200)], axis=1)     # slight stereo width
    pcm = (stereo * 32767).astype("<i2")
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(_SR)
        wf.writeframes(pcm.tobytes())
    return str(out)


def get_music_bed(seconds: float, seed_text: str = "mind_vault") -> tuple[str | None, str]:
    """Return (path, source) for a background bed. source in {user, procedural, none}."""
    tracks = _user_tracks()
    if tracks:
        pick = tracks[abs(hash(seed_text)) % len(tracks)]
        log.info("Using royalty-free user music: %s", pick.name)
        return str(pick), "user"
    bed = ROOT_DIR / get_settings().video.music_dir / "_generated_bed.wav"
    path = _procedural_bed(seconds, bed, seed_text)
    if path:
        log.info("Using procedural (self-generated) ambient bed.")
        return path, "procedural"
    return None, "none"
