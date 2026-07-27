"""Video assembly — free-first and always-produces-a-viewable-artifact.

DESIGN: `auto` picks the best available engine at runtime:
  1. FFmpeg (if on PATH)   -> real .mp4 slideshow with narration audio
  2. MoviePy (if installed) -> real .mp4
  3. Pillow GIF fallback    -> animated .gif from the scene images (ZERO extra
     deps, always works — so a bare machine still gets a real, viewable video
     artifact instead of a crash).

Captions: the per-scene key text is already burned into each scene image by the
image layer, so the output carries on-screen text under every engine.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger
from core.schemas import Scene, VideoResult, VoiceResult

log = get_logger("media.video")


def _ffmpeg_exe() -> str | None:
    """Resolve an ffmpeg binary: system PATH first, else imageio-ffmpeg's bundled
    binary (`pip install imageio-ffmpeg`, free, no system install / no GPU)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _have_ffmpeg() -> bool:
    return _ffmpeg_exe() is not None


def _have_moviepy() -> bool:
    try:
        import moviepy.editor  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _ffmpeg_build(scenes, audio: VoiceResult | None, out_path: Path, res) -> bool:
    imgs = [s for s in scenes if s.image_path]
    if not imgs:
        return False
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    with tempfile.TemporaryDirectory() as td:
        concat = Path(td) / "list.txt"
        lines = []
        for s in imgs:
            lines.append(f"file '{Path(s.image_path).as_posix()}'")
            lines.append(f"duration {max(0.8, s.duration):.3f}")
        lines.append(f"file '{Path(imgs[-1].image_path).as_posix()}'")  # last frame needs repeat
        concat.write_text("\n".join(lines), encoding="utf-8")

        silent = Path(td) / "silent.mp4"
        cmd1 = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                "-vf", f"scale={res[0]}:{res[1]}:force_original_aspect_ratio=decrease,"
                       f"pad={res[0]}:{res[1]}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r", "30", str(silent)]
        subprocess.run(cmd1, check=True, capture_output=True)

        if audio and Path(audio.audio_path).exists():
            cmd2 = [ffmpeg, "-y", "-i", str(silent), "-i", audio.audio_path,
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)]
        else:
            cmd2 = [ffmpeg, "-y", "-i", str(silent), "-c", "copy", str(out_path)]
        subprocess.run(cmd2, check=True, capture_output=True)
    return out_path.exists()


def _moviepy_build(scenes, audio, out_path, res) -> bool:  # pragma: no cover - optional
    try:
        from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
        clips = [ImageClip(s.image_path).set_duration(max(0.8, s.duration))
                 for s in scenes if s.image_path]
        if not clips:
            return False
        video = concatenate_videoclips(clips, method="compose")
        if audio and Path(audio.audio_path).exists():
            video = video.set_audio(AudioFileClip(audio.audio_path))
        video.write_videofile(str(out_path), fps=30, codec="libx264",
                              audio_codec="aac", verbose=False, logger=None)
        return out_path.exists()
    except Exception as exc:
        log.warning("MoviePy build failed (%s).", exc)
        return False


def _gif_fallback(scenes, out_path: Path, res) -> Path:
    """Animated GIF from scene images — pure Pillow, no ffmpeg needed."""
    from PIL import Image

    gif_path = out_path.with_suffix(".gif")
    frames, durations = [], []
    for s in scenes:
        if not s.image_path:
            continue
        img = Image.open(s.image_path).convert("RGB").resize(tuple(res))
        frames.append(img)
        durations.append(int(max(0.8, s.duration) * 1000))
    if not frames:
        # Absolute last resort: a single black frame so a file always exists.
        frames = [Image.new("RGB", tuple(res), (10, 10, 14))]
        durations = [1000]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    return gif_path


def _pip_position(corner: str, w: int, h: int, ow: int, oh: int, margin: int = 40) -> str:
    """ffmpeg overlay x:y expression for a corner (ow/oh = overlay size)."""
    return {
        "bottom-right": f"W-w-{margin}:H-h-{margin}",
        "bottom-left": f"{margin}:H-h-{margin}",
        "top-right": f"W-w-{margin}:{margin}",
        "top-left": f"{margin}:{margin}",
    }.get(corner, f"W-w-{margin}:H-h-{margin}")


def _composite_presenter(base: Path, overlay: str, out: Path, res, scale: float, corner: str) -> bool:
    """Overlay the presenter (still image OR talking clip) as picture-in-picture."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not Path(overlay).exists():
        return False
    pip_w = max(120, int(res[0] * scale))
    is_video = Path(overlay).suffix.lower() in (".mp4", ".mov", ".webm", ".gif")
    pos = _pip_position(corner, res[0], res[1], pip_w, pip_w)
    # Round the presenter into a soft card; keep base audio (the narration).
    fc = (f"[1:v]scale={pip_w}:-1[pp];[0:v][pp]overlay={pos}:shortest=1[v]")
    loop = [] if is_video else ["-loop", "1"]
    cmd = [ffmpeg, "-y", "-i", str(base), *loop, "-i", overlay,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return out.exists()
    except Exception as exc:
        log.warning("Presenter compositing failed (%s); keeping base video.", exc)
        return False


def assemble_video(scenes: list[Scene], audio: VoiceResult | None, out_path: str | Path,
                   video_format: str = "short", presenter_overlay: str | None = None) -> VideoResult:
    """Assemble the final video. Never raises — always returns a VideoResult."""
    cfg = get_settings()
    fmt = cfg.formats.short if video_format == "short" else cfg.formats.long
    res = fmt.resolution
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    engine_pref = cfg.video.engine.lower()

    total = sum(max(0.8, s.duration) for s in scenes) or 1.0
    engine_used = "gif"
    final_path = out

    try:
        if engine_pref in ("auto", "ffmpeg") and _have_ffmpeg() and _ffmpeg_build(scenes, audio, out, res):
            engine_used = "ffmpeg"
        elif engine_pref in ("auto", "moviepy") and _have_moviepy() and _moviepy_build(scenes, audio, out, res):
            engine_used = "moviepy"
        else:
            final_path = _gif_fallback(scenes, out, res)
            engine_used = "gif"
    except Exception as exc:
        log.warning("Primary video engine failed (%s); using GIF fallback.", exc)
        final_path = _gif_fallback(scenes, out, res)
        engine_used = "gif"

    presenter_used = False
    # Composite the AI presenter (PiP) onto ffmpeg-built videos.
    if (presenter_overlay and engine_used == "ffmpeg"
            and cfg.presenter.enabled and cfg.presenter.composite == "pip"):
        composed = out.with_name(out.stem + "_final.mp4")
        pcfg = _presenter_render_cfg()
        if _composite_presenter(final_path, presenter_overlay, composed, res,
                                 pcfg["scale"], pcfg["corner"]):
            final_path = composed
            presenter_used = True

    log.info("Assembled video via %s%s -> %s", engine_used,
             " + presenter PiP" if presenter_used else "", final_path.name)
    return VideoResult(
        video_path=str(final_path),
        duration=round(total, 2),
        resolution=list(res),
        engine=engine_used + ("+presenter" if presenter_used else ""),
        has_captions=cfg.video.captions,
    )


def _presenter_render_cfg() -> dict:
    """Read PiP scale/corner from the presenter agent's own config (best-effort)."""
    import yaml
    from core.config import ROOT_DIR
    path = ROOT_DIR / "agents" / "presenter_agent" / "config.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {"scale": float(data.get("pip_scale", 0.30)), "corner": data.get("pip_corner", "bottom-right")}
    except Exception:
        return {"scale": 0.30, "corner": "bottom-right"}
