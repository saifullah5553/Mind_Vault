"""Text-to-speech — free-first, natural-voice-capable, always-produces-audio.

Backends behind one function, tried in this order for `provider: auto`:
  1. piper    : FREE, open-source, CPU, genuinely NATURAL neural voice
                (`pip install piper-tts` + a voice model .onnx). Recommended.
  2. coqui    : FREE, open-source XTTS — very natural, heavier (GPU helps).
  3. pyttsx3  : offline OS voice ($0, robotic but real).
  4. silence  : correctly-timed silent WAV (stdlib only) so CI/bare machines
                still get a valid audio file of the right length.

Choosing a specific provider / voice is config (`tts.*`), never a code change.
`tts.gender: female` picks a female voice where the backend supports it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger
from core.schemas import VoiceResult

log = get_logger("media.tts")

_SAMPLE_RATE = 22050


def estimate_duration(text: str, wpm: int) -> float:
    words = max(1, len(text.split()))
    return round(words / max(1, wpm) * 60.0, 2)


def _write_silence(path: Path, seconds: float) -> None:
    """Write a valid silent mono 16-bit WAV of the given length (stdlib only)."""
    n = int(_SAMPLE_RATE * max(0.5, seconds))
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(b"\x00\x00" * n)


def _piper_model() -> str | None:
    """Resolve a Piper voice model path from config/env. A female English voice
    such as `en_US-amy-medium.onnx` or `en_GB-jenny_dioco-medium.onnx` is ideal.
    Download voices from https://huggingface.co/rhasspy/piper-voices (free)."""
    cfg = get_settings().tts
    candidate = os.getenv("PIPER_MODEL") or getattr(cfg, "piper_model", "") or ""
    if candidate:
        p = Path(candidate)
        if not p.is_absolute():
            p = ROOT_DIR / candidate
        return str(p) if p.exists() else None
    # Look for any .onnx voice under storage/voices/.
    vdir = ROOT_DIR / "storage" / "voices"
    if vdir.exists():
        found = sorted(vdir.glob("*.onnx"))
        if found:
            return str(found[0])
    return None


def _try_piper(text: str, path: Path) -> bool:  # pragma: no cover - needs voice model
    model = _piper_model()
    if not model:
        return False
    # Prefer the CLI if present; else the python package.
    try:
        if shutil.which("piper"):
            proc = subprocess.run(["piper", "-m", model, "-f", str(path)],
                                  input=text.encode("utf-8"), capture_output=True)
            if proc.returncode == 0 and path.exists() and path.stat().st_size > 0:
                return True
        from piper import PiperVoice  # type: ignore
        voice = PiperVoice.load(model)
        with wave.open(str(path), "wb") as wf:
            voice.synthesize(text, wf)
        return path.exists() and path.stat().st_size > 0
    except Exception as exc:
        log.warning("Piper TTS failed (%s).", exc)
        return False


def _try_coqui(text: str, path: Path) -> bool:  # pragma: no cover - heavy optional
    try:
        import torch  # type: ignore
        from TTS.api import TTS  # type: ignore
    except Exception:
        return False
    try:
        cfg = get_settings().tts
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # XTTS v2 is multi-speaker + very natural. A female speaker is selected.
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False).to(device)
        speaker = getattr(cfg, "coqui_speaker", "") or "Ana Florence"  # a female preset voice
        tts.tts_to_file(text=text, file_path=str(path), speaker=speaker, language="en")
        return path.exists()
    except Exception as exc:
        log.warning("Coqui XTTS failed (%s); trying a lighter model.", exc)
        try:
            from TTS.api import TTS  # type: ignore
            tts = TTS("tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)  # female LJSpeech
            tts.tts_to_file(text=text, file_path=str(path))
            return path.exists()
        except Exception as exc2:
            log.warning("Coqui fallback failed (%s).", exc2)
            return False


def _try_pyttsx3(text: str, path: Path) -> bool:
    try:
        import pyttsx3  # type: ignore
    except Exception:
        return False
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", get_settings().tts.words_per_minute)
        # Prefer a female system voice when requested.
        if getattr(get_settings().tts, "gender", "female") == "female":
            for v in engine.getProperty("voices"):
                name = (getattr(v, "name", "") or "").lower()
                if any(k in name for k in ("female", "zira", "hazel", "eva", "aria")):
                    engine.setProperty("voice", v.id)
                    break
        engine.save_to_file(text, str(path))
        engine.runAndWait()
        return path.exists() and path.stat().st_size > 0
    except Exception as exc:  # pragma: no cover - platform dependent
        log.warning("pyttsx3 failed (%s); using silent fallback.", exc)
        return False


def synthesize_speech(text: str, out_path: str | Path) -> VoiceResult:
    """Synthesize narration to `out_path` (.wav). Never raises — always returns."""
    cfg = get_settings().tts
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    provider = cfg.provider.lower()
    used = "silence"

    order = {
        "auto": ["piper", "coqui", "pyttsx3"],
        "piper": ["piper"],
        "coqui": ["coqui"],
        "pyttsx3": ["pyttsx3"],
        "silence": [],
    }.get(provider, ["piper", "coqui", "pyttsx3"])

    runners = {"piper": _try_piper, "coqui": _try_coqui, "pyttsx3": _try_pyttsx3}
    for name in order:
        if runners[name](text, out):
            used = name
            break
    else:
        _write_silence(out, estimate_duration(text, cfg.words_per_minute))
        used = "silence"

    # Read back the real duration (WAV only; other formats fall back to estimate).
    try:
        with wave.open(str(out), "r") as wf:
            duration = wf.getnframes() / float(wf.getframerate())
    except Exception:
        duration = estimate_duration(text, cfg.words_per_minute)

    if used == "silence":
        log.info("TTS: no natural voice available -> silent-timed track. "
                 "Install Piper (pip install piper-tts + a voice model) for a natural voice.")
    log.info("TTS via %s -> %s (%.1fs)", used, out.name, duration)
    return VoiceResult(audio_path=str(out), duration=round(duration, 2), provider=used, voice=cfg.voice)
