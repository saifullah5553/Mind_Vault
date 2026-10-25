"""Word-level transcription of the narration (faster-whisper, CPU).

Why this matters: captions were previously timed from ESTIMATED scene durations,
so they drifted from what is actually said. Transcribing the rendered narration
gives real word timings, which:

  - makes subtitles land exactly on the spoken word,
  - enables karaoke-style caption groups (a strong retention driver on Shorts),
  - and self-corrects whatever the TTS engine actually produced.

Runs on CPU via int8 quantisation. If faster-whisper or the model is missing, the
caller falls back to scene-timed captions, so the pipeline never breaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger

log = get_logger("media.transcribe")


@dataclass
class Word:
    text: str
    start: float
    end: float


@lru_cache(maxsize=2)
def _model(name: str, compute_type: str):
    from faster_whisper import WhisperModel
    log.info("Loading faster-whisper '%s' (%s, CPU) - first run downloads the model.",
             name, compute_type)
    return WhisperModel(name, device="cpu", compute_type=compute_type)


def _load_16k_mono(path: Path):
    """Decode audio to the 16 kHz mono float32 array Whisper expects."""
    try:
        import librosa
        audio, _sr = librosa.load(str(path), sr=16000, mono=True)
        return audio
    except Exception:
        pass
    try:
        import numpy as np
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        audio = data.mean(axis=1)
        if sr != 16000:                      # cheap linear resample fallback
            idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
            audio = np.interp(idx, np.arange(len(audio)), audio).astype("float32")
        return audio
    except Exception as exc:
        log.debug("audio decode failed (%s); letting faster-whisper try the path", exc)
        return None


def transcribe_words(audio_path: str | Path) -> list[Word]:
    """Return word-level timings for the narration. Empty list on any failure."""
    cfg = get_settings().video
    name = getattr(cfg, "caption_model", "base")
    compute = getattr(cfg, "caption_compute", "int8")
    path = Path(audio_path)
    if not path.exists():
        return []
    try:
        model = _model(name, compute)
        # Decode to a 16 kHz mono float32 array ourselves rather than handing
        # faster-whisper a path. Its internal decoder goes through PyAV, whose
        # newer releases dropped the `metadata_errors` argument it passes — this
        # sidesteps that version conflict entirely and avoids pinning `av`.
        audio = _load_16k_mono(path)
        segments, _info = model.transcribe(
            audio if audio is not None else str(path),
            word_timestamps=True, vad_filter=True,
            beam_size=1,                      # greedy: much faster on CPU
        )
        words: list[Word] = []
        for seg in segments:
            for w in (seg.words or []):
                text = (w.word or "").strip()
                if text:
                    words.append(Word(text, float(w.start), float(w.end)))
        log.info("Transcribed %d word(s) from %s", len(words), path.name)
        return words
    except Exception as exc:
        log.warning("Word-level transcription unavailable (%s); "
                    "falling back to scene-timed captions.", str(exc)[:160])
        return []


def group_words(words: list[Word], max_words: int = 5,
                max_gap: float = 0.7, max_dur: float = 3.0) -> list[tuple[float, float, str]]:
    """Group words into short caption cues.

    Short groups (3-5 words) read far better on a phone than full sentences and
    are what high-retention short-form captions look like. A group is also cut
    at a long pause or on sentence-ending punctuation.
    """
    cues: list[tuple[float, float, str]] = []
    buf: list[Word] = []

    def flush():
        if buf:
            cues.append((buf[0].start, buf[-1].end, " ".join(w.text for w in buf)))
            buf.clear()

    for w in words:
        if buf:
            gap = w.start - buf[-1].end
            span = w.end - buf[0].start
            if gap > max_gap or len(buf) >= max_words or span > max_dur:
                flush()
        buf.append(w)
        if w.text.endswith((".", "!", "?")):
            flush()
    flush()
    return cues
