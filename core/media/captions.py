"""Subtitle (SRT) generation.

Platforms (YouTube/TikTok/IG/FB) reward accurate captions with reach and
retention. We already know each scene's narration text and its duration, so we
can emit a correctly-timed `.srt` with no extra dependency. If Whisper is later
installed, a word-accurate track can replace this behind the same function.
"""

from __future__ import annotations

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


def build_srt_from_audio(audio_path, out_path: str | Path) -> str | None:
    """SRT timed from the ACTUAL narration audio (word-level), not scene estimates.

    Returns None if transcription is unavailable so the caller can fall back.
    """
    from core.media.transcribe import group_words, transcribe_words

    words = transcribe_words(audio_path)
    if not words:
        return None
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
