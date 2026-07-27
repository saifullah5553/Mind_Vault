"""Environment doctor.

Reports what's installed and, for anything missing, the EXACT command to enable
it — so you know precisely what to do on your machine (or a GPU box) to unlock
real LLM scripts, natural voice, and a photoreal presenter.

Usage:
    python -m scripts.doctor
"""

from __future__ import annotations

import shutil

from core.config import get_settings


def _ok(b: bool) -> str:
    return "OK " if b else "-- "


def _check_ollama():
    from core.llm.ollama_provider import OllamaLLM
    cfg = get_settings().llm
    o = OllamaLLM(model=cfg.model, host_env=cfg.ollama_host_env)
    up = o.is_available()
    models = o.installed_models() if up else []
    has_model = any(cfg.model in m for m in models)
    lines = [f"[{_ok(up)}] Ollama server reachable at {o.host}"]
    if up:
        lines.append(f"[{_ok(has_model)}] configured model '{cfg.model}' present"
                     + (f" (installed: {', '.join(models)})" if models else ""))
        if not has_model:
            lines.append(f"        -> run:  ollama pull {cfg.model}")
    else:
        lines.append("        -> install: https://ollama.com  then:  ollama pull " + cfg.model)
        lines.append("        -> then set llm.provider: ollama in config/settings.yaml")
    return lines


def _check_voice():
    lines = []
    piper_cli = shutil.which("piper") is not None
    try:
        import piper  # type: ignore
        piper_pkg = True
    except Exception:
        piper_pkg = False
    from core.media.tts import _piper_model  # type: ignore
    model = _piper_model()
    lines.append(f"[{_ok(piper_cli or piper_pkg)}] Piper installed (cli={piper_cli}, pkg={piper_pkg})")
    lines.append(f"[{_ok(bool(model))}] Piper voice model found" + (f": {model}" if model else ""))
    if not (piper_cli or piper_pkg):
        lines.append("        -> run:  pip install piper-tts")
    if not model:
        lines.append("        -> download a FEMALE voice (.onnx) into storage/voices/")
        lines.append("           e.g. en_US-amy-medium from huggingface.co/rhasspy/piper-voices")
    try:
        import TTS  # type: ignore  # noqa
        lines.append(f"[{_ok(True)}] Coqui TTS (XTTS) available")
    except Exception:
        lines.append(f"[{_ok(False)}] Coqui TTS not installed (optional)  -> pip install TTS")
    return lines


def _check_gpu():
    lines = []
    try:
        import torch  # type: ignore
        cuda = torch.cuda.is_available()
        name = torch.cuda.get_device_name(0) if cuda else "none"
        vram = (torch.cuda.get_device_properties(0).total_memory // (1024**3)) if cuda else 0
        lines.append(f"[{_ok(cuda)}] CUDA GPU available via torch: {name}"
                     + (f" (~{vram} GB VRAM)" if cuda else ""))
        if cuda and vram < 6:
            lines.append("        !! low VRAM: Stable Diffusion / SadTalker may be slow or OOM.")
            lines.append("           Consider a cloud GPU, or keep the stylized portrait + Piper voice.")
    except Exception:
        lines.append(f"[{_ok(False)}] torch not installed  -> pip install torch  (needed for SD/SadTalker)")
    return lines


def _check_video():
    from core.media.video import _ffmpeg_exe  # type: ignore
    exe = _ffmpeg_exe()
    lines = [f"[{_ok(bool(exe))}] ffmpeg available" + (f": {exe}" if exe else "")]
    if not exe:
        lines.append("        -> run:  pip install imageio-ffmpeg   (free, no system install)")
    return lines


def _check_presenter():
    lines = []
    sad = shutil.which("sadtalker") is not None
    try:
        import diffusers  # type: ignore  # noqa
        diff = True
    except Exception:
        diff = False
    lines.append(f"[{_ok(diff)}] diffusers (Stable Diffusion) installed  " + ("" if diff else "-> pip install diffusers"))
    lines.append(f"[{_ok(sad)}] SadTalker CLI on PATH " + ("" if sad else "(optional; see docs/SETUP_AI.md)"))
    return lines


def _check_publishing():
    from core.publishing import publisher_status
    lines = []
    for name, st in publisher_status().items():
        lines.append(f"[{_ok(st['configured'])}] {name} credentials"
                     + ("" if st["configured"] else f"  -> set: {', '.join(st['missing_env'])}"))
    lines.append(f"        publishing.dry_run = {get_settings().publishing.dry_run}"
                 " (uploads happen only when this is false AND creds present)")
    return lines


def main() -> None:
    s = get_settings()
    print("\n" + "=" * 64)
    print(f"  {s.brand.name} — environment doctor")
    print("=" * 64)
    print(f"LLM provider (config): {s.llm.provider}   model: {s.llm.model}")
    print(f"TTS provider (config): {s.tts.provider}   voice: {s.tts.voice} ({s.tts.gender})")
    print(f"Presenter enabled: {s.presenter.enabled}   avatar: (see presenter_agent/config.yaml)")
    for title, fn in [("LLM / Ollama", _check_ollama), ("Natural voice", _check_voice),
                      ("GPU / CUDA", _check_gpu), ("Video / ffmpeg", _check_video),
                      ("Presenter (photoreal)", _check_presenter),
                      ("Publishing (credentials)", _check_publishing)]:
        print(f"\n-- {title} " + "-" * (60 - len(title)))
        for line in fn():
            print("  " + line)
    print("\nFull setup guide: docs/SETUP_AI.md\n")


if __name__ == "__main__":
    main()
