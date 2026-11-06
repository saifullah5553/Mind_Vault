"""Subtitle (SRT) generation.

Platforms (YouTube/TikTok/IG/FB) reward accurate captions with reach and
retention. We already know each scene's narration text and its duration, so we
can emit a correctly-timed `.srt` with no extra dependency. If Whisper is later
installed, a word-accurate track can replace this behind the same function.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from core.logging_setup import get_logger
from core.schemas import Scene

log = get_logger("media.captions")


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(scenes: list[Scene], out_path: str | Path) -> str | None:
    """Write an SRT synced to the per-scene narration timings. Returns the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    t = 0.0
    idx = 1
    for scene in scenes:
        dur = max(0.8, scene.duration)
        text = (scene.narration or "").strip()
        if text:
            lines.append(str(idx))
            lines.append(f"{_ts(t)} --> {_ts(t + dur)}")
            lines.append(text)
            lines.append("")
            idx += 1
        t += dur
    if idx == 1:
        return None
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %d caption cues -> %s", idx - 1, out.name)
    return str(out)


def align_to_script(heard: list, script: str) -> list:
    """Word timings from speech recognition, word text from the script.

    Recognition mishears names ("Deci" as "Dessie"), but we know exactly what was
    said. Matched words take the heard timing; words between matches are spread
    evenly across the gap.
    """
    from core.media.transcribe import Word

    tokens = script.split()
    if not tokens or not heard:
        return heard

    def norm(w: str) -> str:
        return re.sub(r"[^a-z0-9]", "", w.lower())

    match = SequenceMatcher(None, [norm(w.text) for w in heard],
                            [norm(t) for t in tokens], autojunk=False)
    timed: dict[int, tuple[float, float]] = {}
    for block in match.get_matching_blocks():
        for k in range(block.size):
            w = heard[block.a + k]
            timed[block.b + k] = (w.start, w.end)
    anchors = sorted(timed)
    if not anchors:
        return heard
    out: list = []
    for i, token in enumerate(tokens):
        if i in timed:
            start, end = timed[i]
        else:
            before = max((a for a in anchors if a < i), default=None)
            after = min((a for a in anchors if a > i), default=None)
            t0 = timed[before][1] if before is not None else heard[0].start
            t1 = timed[after][0] if after is not None else heard[-1].end
            lo = before if before is not None else -1
            hi = after if after is not None else len(tokens)
            step = max(0.0, t1 - t0) / max(1, hi - lo - 1)
            start = t0 + step * (i - lo - 1)
            end = start + step
        out.append(Word(token, start, max(end, start + 0.05)))
    return out


def build_srt_from_audio(audio_path, out_path: str | Path, script: str = "") -> str | None:
    """SRT timed from the ACTUAL narration audio (word-level), not scene estimates.

    With `script`, the caption text is the exact script, not what recognition
    heard. Returns None if transcription is unavailable so the caller can fall back.
    """
    from core.media.transcribe import group_words, transcribe_words

    words = transcribe_words(audio_path)
    if not words:
        return None
    if script:
        words = align_to_script(words, script)
    cues = group_words(words)
    if not cues:
        return None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines += [str(i), f"{_ts(start)} --> {_ts(max(end, start + 0.3))}", text, ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %d word-timed caption cues -> %s", len(cues), out.name)
    return str(out)
