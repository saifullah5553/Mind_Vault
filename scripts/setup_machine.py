"""One-command setup for a NEW machine (e.g. moving laptop -> desktop).

After `git clone`, this installs the Python dependencies, downloads the free
Piper voice model, pulls the Ollama model, rebuilds the Wav2Lip lip-sync tool,
initializes the database, and prints a readiness report.

Usage:
    python -m scripts.setup_machine              # everything
    python -m scripts.setup_machine --skip-lipsync   # skip the 500 MB Wav2Lip step
    python -m scripts.setup_machine --check      # report only, change nothing

Prerequisites you must install yourself first (they need admin/installers):
    - Python 3.11+          https://www.python.org/downloads/
    - Git                   https://git-scm.com/downloads
    - Ollama (free LLM)     https://ollama.com
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from core.config import ROOT_DIR, get_settings

# The free, natural female voice used for Aria's narration.
PIPER_VOICE = "en_US-amy-medium"
PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
              "en/en_US/amy/medium/")
VOICE_DIR = ROOT_DIR / "storage" / "voices"

BASE_DEPS = ["-r", str(ROOT_DIR / "requirements.txt")]
EXTRA_DEPS = ["piper-tts", "imageio-ffmpeg"]


def _ok(b: bool) -> str:
    return "OK " if b else "-- "


def _run(cmd: list[str], **kw) -> bool:
    try:
        subprocess.run(cmd, check=True, **kw)
        return True
    except Exception as exc:
        print(f"    ! {exc}")
        return False


def _ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    # Common Windows install location that isn't always on PATH.
    guess = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return str(guess) if guess.exists() else None


def _ollama_ready() -> tuple[bool, list[str]]:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=4)
        r.raise_for_status()
        return True, [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return False, []


def status() -> dict:
    model = get_settings().llm.model
    up, models = _ollama_ready()
    return {
        "python_deps": _importable("fastapi") and _importable("sqlalchemy"),
        "ffmpeg": _importable("imageio_ffmpeg") or bool(shutil.which("ffmpeg")),
        "piper": _importable("piper"),
        "piper_voice": (VOICE_DIR / f"{PIPER_VOICE}.onnx").exists(),
        "ollama_running": up,
        f"ollama_model[{model}]": any(model in m for m in models),
        "lipsync": (ROOT_DIR / "tools" / "Wav2Lip" / "checkpoints" / "wav2lip_gan.pth").exists(),
        "database": (ROOT_DIR / "mind_vault.db").exists(),
        "presenter_portrait": (ROOT_DIR / "storage" / "presenter" / "aria.png").exists(),
    }


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _install_deps() -> None:
    print("1/5 Python dependencies")
    _run([sys.executable, "-m", "pip", "install", "-q", *BASE_DEPS])
    _run([sys.executable, "-m", "pip", "install", "-q", *EXTRA_DEPS])


def _download_voice() -> None:
    print(f"2/5 Piper voice ({PIPER_VOICE}, ~60 MB)")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    import httpx
    for suffix in (".onnx", ".onnx.json"):
        dest = VOICE_DIR / f"{PIPER_VOICE}{suffix}"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"    {dest.name} already present")
            continue
        print(f"    downloading {dest.name} ...")
        try:
            with httpx.stream("GET", PIPER_BASE + f"{PIPER_VOICE}{suffix}",
                              timeout=600, follow_redirects=True) as r:
                r.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            print(f"      {dest.stat().st_size // (1024*1024)} MB")
        except Exception as exc:
            print(f"      ! failed: {exc}")


def _pull_model() -> None:
    model = get_settings().llm.model
    print(f"3/5 Ollama model ({model})")
    exe = _ollama_exe()
    if not exe:
        print("    ! Ollama not found. Install from https://ollama.com, then re-run.")
        return
    up, models = _ollama_ready()
    if not up:
        print("    ! Ollama server not responding. Start Ollama, then re-run.")
        return
    if any(model in m for m in models):
        print("    already pulled")
        return
    print("    pulling (this can take a few minutes) ...")
    _run([exe, "pull", model])


def _setup_lipsync() -> None:
    print("4/5 Lip-sync (Wav2Lip, ~500 MB)")
    _run([sys.executable, "-m", "scripts.setup_lipsync"], cwd=str(ROOT_DIR))


def _init_db() -> None:
    print("5/5 Database")
    _run([sys.executable, "-m", "scripts.init_db"], cwd=str(ROOT_DIR))


def main() -> None:
    ap = argparse.ArgumentParser(description="Set up Mind_Vault on a new machine")
    ap.add_argument("--check", action="store_true", help="report status only")
    ap.add_argument("--skip-lipsync", action="store_true", help="skip the Wav2Lip download")
    args = ap.parse_args()

    if args.check:
        for k, v in status().items():
            print(f"[{_ok(v)}] {k}")
        return

    print(f"\nSetting up {get_settings().brand.name} in {ROOT_DIR}\n")
    _install_deps()
    _download_voice()
    _pull_model()
    if not args.skip_lipsync:
        _setup_lipsync()
    else:
        print("4/5 Lip-sync SKIPPED (run: python -m scripts.setup_lipsync)")
    _init_db()

    print("\n" + "=" * 56)
    print("  Readiness")
    print("=" * 56)
    st = status()
    for k, v in st.items():
        print(f"  [{_ok(v)}] {k}")
    print("\nFull diagnostics : python -m scripts.doctor")
    print("Make a video     : python -m scripts.run_pipeline --category history")
    print("Review queue     : python -m scripts.review list\n")
    if not all(st.values()):
        print("Some items are missing above — see docs/MIGRATION.md.\n")


if __name__ == "__main__":
    main()
