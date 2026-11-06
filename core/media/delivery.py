"""How each line is performed: pace, pitch, emphasis and pauses.

A TTS engine reads every sentence the same way. A narrator does not: a question
lifts at the end, a reveal slows and drops, a dark moment sits lower, a bright
one moves quicker, and the silence after a key line carries as much as the line.
`plan` turns a sentence and its place in the script into that performance, and
`perform` applies the pitch shape to the rendered audio.

Pitch is changed by resampling (with the pace compensated), not by a phase
vocoder, so the voice stays clean at these small amounts. The rules are generic
so unattended scripts get the same treatment.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from core.media.spoken import CHAPTER_RE

_DARK = re.compile(r"\b(fail\w*|worse|lost|lose|fade\w*|wither\w*|starv\w*|anxious|guilt\w*|"
                   r"danger\w*|harm\w*|stopped|broke|went out|quit|lazy|alone|damage|"
                   r"discomfort|hunger\w*|tension|fear\w*|doubt\w*|replaced)\b", re.I)
_BRIGHT = re.compile(r"\b(lov\w+|enjoy\w*|joy\w*|flourish\w*|better|alive|surpris\w*|easy|"
                     r"fire stays|strengthen\w*|faster|grow\w*|good life|hope\w*|gives you)\b", re.I)
_TURN = re.compile(r"^(but|then|and yet|yet|so|however|here is|think about|try this|"
                   r"now|instead)\b", re.I)
_FIGURE = re.compile(r"\b\d|\b(hundred|thousand|million|percent|half)\b", re.I)


@dataclass
class Delivery:
    rate: float = 1.0        # length multiplier: above 1 is slower
    pitch: float = 0.0       # semitones, whole line
    end: float = -0.7        # semitones added over the last third of the line
    gain_db: float = 0.0
    pause_before: float = 0.0
    pause_after: float = 0.32


def plan(sentence: str, *, first: bool = False, last: bool = False,
         para_end: bool = False, prev_short: bool = False) -> Delivery:
    """Choose the delivery for one sentence from what it says and where it sits."""
    s = sentence.strip()
    words = len(s.split())
    d = Delivery()

    if CHAPTER_RE.match(s):                       # a heading: unhurried, set apart
        return Delivery(rate=1.14, pitch=-0.8, end=-1.0, gain_db=0.5,
                        pause_before=0.9, pause_after=0.85)
    if first:                                     # the hook: weighty, lets it land
        d = Delivery(rate=1.1, pitch=-0.6, end=-1.2, gain_db=0.5, pause_after=0.8)

    if _DARK.search(s):
        d.pitch -= 1.2
        d.rate += 0.06
        d.gain_db -= 0.8
    if _BRIGHT.search(s):
        d.pitch += 1.1
        d.rate -= 0.05
        d.gain_db += 0.4
    if _FIGURE.search(s):
        d.rate += 0.03                            # figures need time to register

    if words <= 5:                                # a punch line, or one beat of a list
        d.rate += 0.07
        d.gain_db += 0.5
        d.end = -1.3
        d.pause_after = 0.45 if prev_short else 0.6
    elif words >= 20:
        d.rate -= 0.04                            # long lines keep moving

    if s.endswith("?"):                           # a real question lifts at the end
        d.end = 2.8
        d.pitch += 0.4
        d.pause_after = max(d.pause_after, 0.6)
    if _TURN.match(s):
        d.pause_before = max(d.pause_before, 0.22)

    if para_end:
        d.pause_after = max(d.pause_after, 0.62)
        if not s.endswith("?"):
            d.end = min(d.end, -1.1)
    if last:
        d.rate += 0.04
        d.pause_after = 0.9

    # A little line-to-line variation, so repeated patterns don't sound stamped.
    # Seeded from the text, so a re-render performs the same way.
    wobble = (zlib.crc32(s.encode("utf-8")) % 1000) / 1000 - 0.5
    d.pitch += wobble * 0.5
    d.rate += wobble * 0.03
    return d


def perform(samples, sample_rate: int, d: Delivery):
    """Apply the pitch shape to one line. Returns float32 mono samples.

    Each source sample advances the output at a rate set by the pitch curve, so
    pitch and timing change together; `length_scale_for` pre-compensates the
    timing when the speech is synthesised.
    """
    import numpy as np
    from scipy.signal import resample_poly

    x = np.asarray(samples, dtype="float32")
    if len(x) < 2:
        return x
    n = len(x)
    u = np.linspace(0.0, 1.0, n, dtype="float32")
    curve = d.pitch + d.end * np.clip((u - 0.66) / 0.34, 0.0, 1.0) ** 2
    speed = 2.0 ** (curve / 12.0)                 # source samples per output sample
    t = np.cumsum(1.0 / speed)                    # output time of each source sample
    pos = np.interp(np.arange(int(t[-1])), t, np.arange(n, dtype="float32"))
    up = 4                                        # oversample: clean interpolation
    xu = resample_poly(x, up, 1).astype("float32")
    y = np.interp(pos * up, np.arange(len(xu), dtype="float32"), xu).astype("float32")
    y *= 10.0 ** (d.gain_db / 20.0)
    return y


def length_scale_for(d: Delivery, base: float = 1.0) -> float:
    """Piper's length_scale that yields `d.rate` once pitch resampling is applied."""
    mean_semitones = d.pitch + d.end * 0.11       # mean of the end curve over the line
    return base * d.rate * 2.0 ** (mean_semitones / 12.0)


def trim_silence(samples, sample_rate: int, floor: float = 0.012):
    """Remove the engine's own leading/trailing silence, keeping a soft edge."""
    import numpy as np

    x = np.asarray(samples, dtype="float32")
    loud = np.flatnonzero(np.abs(x) > floor)
    if not len(loud):
        return x
    pad = int(0.02 * sample_rate)
    x = x[max(0, loud[0] - pad): loud[-1] + pad].copy()
    fade = min(int(0.012 * sample_rate), len(x) // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype="float32")
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    return x
