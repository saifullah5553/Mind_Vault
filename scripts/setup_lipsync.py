"""One-command setup for the lip-synced AI presenter (Wav2Lip).

Recreates `tools/Wav2Lip` exactly as this project needs it: clones the repo,
downloads the model weights, and applies the compatibility patches required to
run it on a modern Python/librosa/Windows stack.

Everything here is free and runs on CPU (a GPU just makes it faster).

Usage:
    python -m scripts.setup_lipsync
    python -m scripts.setup_lipsync --check      # report status only

Patches applied (each is needed, and each was a real failure we hit):
  1. librosa >= 0.10 requires keyword args in `librosa.filters.mel(...)`.
  2. `args.face.split('.')[1]` misdetects the file type whenever ANY directory in
     the path contains a dot (e.g. a Windows user named "Saif.Ullah"), which made
     still images be read as videos with fps=inf -> infinite loop -> MemoryError.
  3. Guard against a non-finite/zero fps for the same reason.
  4. Resolve `ffmpeg` via imageio-ffmpeg when it isn't on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from core.config import ROOT_DIR

REPO = "https://github.com/Rudrabha/Wav2Lip.git"
TOOL_DIR = ROOT_DIR / "tools" / "Wav2Lip"

MODELS = [
    ("https://huggingface.co/numz/wav2lip_studio/resolve/main/Wav2lip/wav2lip_gan.pth",
     TOOL_DIR / "checkpoints" / "wav2lip_gan.pth"),
    ("https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth",
     TOOL_DIR / "face_detection" / "detection" / "sfd" / "s3fd.pth"),
]

PIP_DEPS = ["torch", "torchvision", "librosa", "opencv-python", "numba", "imageio-ffmpeg"]

PATCHES: list[tuple[Path, str, str]] = [
    # 1) librosa keyword-args
    (TOOL_DIR / "audio.py",
     "return librosa.filters.mel(hp.sample_rate, hp.n_fft, n_mels=hp.num_mels,\n"
     "                               fmin=hp.fmin, fmax=hp.fmax)",
     "return librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft, n_mels=hp.num_mels,\n"
     "                               fmin=hp.fmin, fmax=hp.fmax)"),
    # 2) robust extension detection (dots in directory names)
    (TOOL_DIR / "inference.py",
     "if os.path.isfile(args.face) and args.face.split('.')[1] in ['jpg', 'png', 'jpeg']:",
     "if os.path.isfile(args.face) and os.path.splitext(args.face)[1].lower() in ['.jpg', '.png', '.jpeg']:"),
    (TOOL_DIR / "inference.py",
     "\telif args.face.split('.')[1] in ['jpg', 'png', 'jpeg']:",
     "\telif os.path.splitext(args.face)[1].lower() in ['.jpg', '.png', '.jpeg']:"),
    # 3) fps guard
    (TOOL_DIR / "inference.py",
     "\tmel_chunks = []\n\tmel_idx_multiplier = 80./fps \n\ti = 0",
     "\tmel_chunks = []\n"
     "\tif not np.isfinite(fps) or fps <= 0:\n"
     "\t\tprint('WARNING: invalid fps %r; falling back to 25.' % (fps,))\n"
     "\t\tfps = 25.\n"
     "\tmel_idx_multiplier = 80./fps\n\ti = 0"),
    # 4) ffmpeg resolution
    (TOOL_DIR / "inference.py",
     "from models import Wav2Lip\nimport platform",
     "from models import Wav2Lip\nimport platform\nimport shutil\n\n\n"
     "def _ffmpeg_exe():\n"
     "\texe = shutil.which('ffmpeg')\n"
     "\tif exe:\n\t\treturn exe\n"
     "\ttry:\n\t\timport imageio_ffmpeg\n\t\treturn imageio_ffmpeg.get_ffmpeg_exe()\n"
     "\texcept Exception:\n\t\treturn 'ffmpeg'"),
    (TOOL_DIR / "inference.py",
     "command = 'ffmpeg -y -i {} -strict -2 {}'.format(args.audio, 'temp/temp.wav')",
     "command = '\"{}\" -y -i {} -strict -2 {}'.format(_ffmpeg_exe(), args.audio, 'temp/temp.wav')"),
    (TOOL_DIR / "inference.py",
     "\tcommand = 'ffmpeg -y -i {} -i {} -strict -2 -q:v 1 {}'.format(args.audio, 'temp/result.avi', args.outfile)\n"
     "\tsubprocess.call(command, shell=platform.system() != 'Windows')",
     "\tcommand = '\"{}\" -y -i \"{}\" -i \"{}\" -strict -2 -q:v 1 \"{}\"'.format(\n"
     "\t\t_ffmpeg_exe(), args.audio, 'temp/result.avi', args.outfile)\n"
     "\tsubprocess.call(command, shell=True)"),
]


def _status() -> dict:
    return {
        "repo": (TOOL_DIR / "inference.py").exists(),
        "gan_model": MODELS[0][1].exists(),
        "face_model": MODELS[1][1].exists(),
        "torch": _importable("torch"),
        "librosa": _importable("librosa"),
        "cv2": _importable("cv2"),
    }


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _clone() -> None:
    if (TOOL_DIR / "inference.py").exists():
        print("  repo already present")
        return
    TOOL_DIR.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    subprocess.run([git, "clone", "--depth", "1", REPO, str(TOOL_DIR)], check=True)
    # The clone's own .git makes it a nested repo; drop it so it's just files.
    shutil.rmtree(TOOL_DIR / ".git", ignore_errors=True)


def _download() -> None:
    import httpx

    for url, dest in MODELS:
        if dest.exists():
            print(f"  {dest.name} already present")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {dest.name} ...")
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        print(f"    {dest.stat().st_size // (1024*1024)} MB")


def _patch() -> None:
    applied = skipped = 0
    for path, old, new in PATCHES:
        if not path.exists():
            print(f"  !! missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        if new in text:
            skipped += 1
            continue
        if old not in text:
            print(f"  !! pattern not found in {path.name} (upstream changed?)")
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        applied += 1
    print(f"  patches applied={applied} already-present={skipped}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Set up Wav2Lip for the AI presenter")
    ap.add_argument("--check", action="store_true", help="report status and exit")
    args = ap.parse_args()

    st = _status()
    if args.check:
        for k, v in st.items():
            print(f"[{'OK ' if v else '-- '}] {k}")
        print("\nReady." if all(st.values()) else "\nRun: python -m scripts.setup_lipsync")
        return

    print("1/4 python deps")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PIP_DEPS], check=False)
    print("2/4 clone Wav2Lip")
    _clone()
    print("3/4 model weights (~500 MB)")
    _download()
    print("4/4 compatibility patches")
    _patch()

    st = _status()
    print("\nStatus:")
    for k, v in st.items():
        print(f"  [{'OK ' if v else '-- '}] {k}")
    print("\nDone. Enable in agents/presenter_agent/config.yaml: lipsync_provider: wav2lip")


if __name__ == "__main__":
    main()
