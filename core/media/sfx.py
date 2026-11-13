"""Sound design, generated (no samples to license, $0): a soft whoosh on the cut to a
map, number or museum card, and one low hit when the story starts after the title.

Kept well under the voice: the whoosh peaks about 20 dB below speech, the hit about
14 dB below, and nothing plays on ordinary picture cuts (film cuts are silent).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 48000
WHOOSH_GAIN = 0.10
HIT_GAIN = 0.22
# Cards that arrive with a whoosh. The title card gets the hit at its end instead.
_WHOOSH_KINDS = ("map", "stat", "timeline", "showcase", "layers", "quote", "route", "compare")


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def whoosh(seconds: float = 0.8, seed: int = 1) -> np.ndarray:
    """Air rushing past: noise through a band that sweeps up then down, panned
    across the stereo field. Stereo float32, peak 1."""
    from scipy.signal import butter, sosfilt
    n = int(seconds * SR)
    noise = _rng(seed).standard_normal(n)
    out = np.zeros(n)
    blocks = 24
    edges = np.linspace(0, n, blocks + 1, dtype=int)
    for b in range(blocks):
        t = (b + 0.5) / blocks
        centre = 250 * (12 ** (np.sin(np.pi * t)))          # 250 Hz -> 3 kHz -> 250 Hz
        lo, hi = max(40.0, centre / 2), min(SR / 2 - 100, centre * 2)
        sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        seg = slice(max(0, edges[b] - 256), edges[b + 1])
        filt = sosfilt(sos, noise[seg])
        out[edges[b]:edges[b + 1]] = filt[-(edges[b + 1] - edges[b]):]
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 2.2 * (0.6 + 0.4 * t)          # swell, peak late
    out = out * env
    pan = np.clip(t, 0.05, 0.95)                              # left to right
    st = np.stack([out * np.sqrt(1 - pan), out * np.sqrt(pan)], axis=1)
    return (st / (np.abs(st).max() + 1e-9)).astype(np.float32)


def hit(seconds: float = 2.6, seed: int = 2) -> np.ndarray:
    """A low cinematic hit: a falling sub tone, a short noise thump and a dark tail."""
    from scipy.signal import butter, fftconvolve, sosfilt
    n = int(seconds * SR)
    t = np.arange(n) / SR
    freq = 38 + 34 * np.exp(-t * 6)                           # 72 Hz falling to 38 Hz
    sub = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 2.2)
    thump = sosfilt(butter(2, 900, fs=SR, output="sos"), _rng(seed).standard_normal(n))
    thump *= np.exp(-t * 28)
    dry = sub + 0.5 * thump / (np.abs(thump).max() + 1e-9)
    ir_n = int(1.6 * SR)
    ir = _rng(seed + 1).standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR * 3.5)
    ir = sosfilt(butter(2, 1500, fs=SR, output="sos"), ir)
    wet = fftconvolve(dry, ir)[:n]
    wet = wet / (np.abs(wet).max() + 1e-9)
    mono = dry / (np.abs(dry).max() + 1e-9) + 0.35 * wet
    fade = np.ones(n)
    fade[-int(0.3 * SR):] = np.linspace(1, 0, int(0.3 * SR))
    mono *= fade
    st = np.stack([mono, mono], axis=1)
    return (st / (np.abs(st).max() + 1e-9)).astype(np.float32)


def events(kinds: list[str | None], starts: list[float]) -> list[tuple[str, float]]:
    """Where the sounds go: (sound, time in seconds). `kinds` are the scenes'
    animation kinds (None for a photo or clip), `starts` their start times."""
    out: list[tuple[str, float]] = []
    last_whoosh = -99.0
    for k, (kind, start) in enumerate(zip(kinds, starts)):
        name = (kind or "").split(":", 1)[0]
        if k == 1 and (kinds[0] or "").startswith("title"):
            out.append(("hit", start))                        # the story begins
        elif name in _WHOOSH_KINDS and start - last_whoosh >= 12 and k > 0:
            out.append(("whoosh", max(0.0, start - 0.55)))    # peaks on the cut
            last_whoosh = start
    return out


def track(evts: list[tuple[str, float]], seconds: float, path: str | Path) -> str:
    """Write the sound-design track (48 kHz stereo WAV) and return its path."""
    from scipy.io import wavfile
    buf = np.zeros((int(seconds * SR) + SR, 2), dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    for name, at in evts:
        if name not in cache:
            cache[name] = whoosh() * WHOOSH_GAIN if name == "whoosh" else hit() * HIT_GAIN
        s = cache[name]
        i = int(at * SR)
        j = min(len(buf), i + len(s))
        if i < j:
            buf[i:j] += s[: j - i]
    wavfile.write(str(path), SR, (np.clip(buf, -1, 1) * 32767).astype(np.int16))
    return str(path)
