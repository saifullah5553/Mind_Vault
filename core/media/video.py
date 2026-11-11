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
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger
from core.schemas import Scene, VideoResult, VoiceResult

log = get_logger("media.video")


# Every segment carries the same colour tags, or the stream-copied concat takes the
# first segment's and players can show the wrong colours.
_COLOUR_SCALE = "scale=out_color_matrix=bt709:out_range=tv"
_COLOUR_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-color_range", "tv"]
# Platforms turn loud videos down but don't turn quiet ones up.
_LOUDNESS = "I=-14:TP=-1.5:LRA=11"


def _crf() -> int:
    """Encode quality dial (lower = better). Configured in settings.video.crf."""
    return int(getattr(get_settings().video, "crf", 18))


def _preset() -> str:
    return str(getattr(get_settings().video, "preset", "medium"))


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


def _film_look() -> str:
    """One grade for every filmed or photographed scene (not the animated cards),
    so clips from many cameras and century-old prints cut together as one film:
    a gentle contrast curve, slightly muted colour, cool shadows and warm
    highlights, a soft vignette and fine moving grain. Ends with a comma, or is
    empty when settings.video.film_look is off."""
    v = get_settings().video
    if not getattr(v, "film_look", True):
        return ""
    look = ["eq=contrast=1.04:saturation=0.95",
            "colorbalance=rs=-0.015:bs=0.015:rh=0.02:bh=-0.02",
            "vignette=angle=PI/9:eval=init"]
    grain = int(getattr(v, "film_grain", 3))
    if grain > 0:
        look.append(f"noise=c0s={grain}:c0f=t")
    return ",".join(look) + ","


def _clip_segment(ffmpeg: str, scene, dur: float, res, fps: int, part: Path) -> bool:
    """One segment cut from REAL stock footage.

    The clip is looped if shorter than the scene and cover-cropped to the frame
    (no letterboxing).
    """
    w, h = res
    inputs = [ffmpeg, "-y", "-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", scene.clip_path]
    base = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={fps},{_film_look()}{_COLOUR_SCALE},format=yuv420p")
    fc = f"{base}[out]"
    cmd = inputs + ["-filter_complex", fc, "-map", "[out]", "-an",
                    "-r", str(fps), "-c:v", "libx264", "-preset", _preset(),
                    "-crf", str(_crf()), *_COLOUR_TAGS, "-threads", "2", str(part)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return part.exists()
    except Exception as exc:
        log.debug("Footage segment failed (%s).", exc)
        return False


def _kenburns_segment(ffmpeg: str, scene, i: int, dur: float, res, fps: int, part: Path) -> bool:
    """One segment from a still, with a slow Ken Burns move so it feels filmed."""
    """Frames are drawn here and piped to ffmpeg, one per output frame.

    The previous ffmpeg `zoompan` version fed a LOOPED still into zoompan, which
    emits d frames for EVERY input frame: each ~7 s scene came out ~10 minutes
    long (a 12-minute documentary would have taken ~10 hours, and earlier
    videos showed their first still until -shortest cut them). Cropping with a
    float box (Image.EXTENT + bicubic) also gives sub-pixel smooth motion, so no
    2x upscale is needed to hide zoompan's integer jitter.
    """
    from PIL import Image

    w, h = res
    frames = max(2, round(dur * fps))
    # Cover-fit the still to 1.15x the frame: room to move, but the tightest
    # view is still ~1:1 pixels, so the picture stays sharp.
    sw, sh = int(w * 1.15), int(h * 1.15)
    try:
        src = Image.open(scene.image_path).convert("RGB")
        r = max(sw / src.width, sh / src.height)
        src = src.resize((max(sw, round(src.width * r)), max(sh, round(src.height * r))),
                         Image.LANCZOS)
        ox, oy = (src.width - sw) / 2, (src.height - sh) / 2
        src = src.crop((round(ox), round(oy), round(ox) + sw, round(oy) + sh))
    except Exception as exc:
        log.debug("Ken Burns source unreadable (%s).", exc)
        return False

    mode = i % 4
    z0, z1 = {0: (1.0, 1.15), 1: (1.15, 1.0)}.get(mode, (1.08, 1.12))
    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-vf", _film_look() + _COLOUR_SCALE, "-c:v", "libx264",
           "-preset", _preset(), "-crf", str(_crf()), "-pix_fmt", "yuv420p", *_COLOUR_TAGS,
           "-threads", "2", str(part)]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        for f in range(frames):
            t = f / (frames - 1)                  # constant speed reads as "filmed"
            z = z0 + (z1 - z0) * t
            bw, bh = sw / z, sh / z               # visible box in source pixels
            fx, fy = 0.5, 0.5                     # box centre, as a fraction of slack
            if mode == 2:
                fx = 0.15 + 0.7 * t               # drift right
            elif mode == 3:
                fy = 0.15 + 0.7 * t               # drift down
            x0 = (sw - bw) * fx
            y0 = (sh - bh) * fy
            frame = src.transform((w, h), Image.EXTENT, (x0, y0, x0 + bw, y0 + bh),
                                  Image.BICUBIC)
            if getattr(scene, "label", ""):
                from core.media.scenes import draw_lower_third
                draw_lower_third(frame, scene.label, getattr(scene, "label_sub", ""), (w, h),
                                 f / fps, dur)
            if getattr(scene, "tag", ""):
                from core.media.scenes import draw_tag
                draw_tag(frame, scene.tag, (w, h))
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        return proc.wait(timeout=600) == 0 and part.exists()
    except Exception as exc:
        log.debug("Ken Burns segment failed (%s).", exc)
        try:
            proc.kill()
        except Exception:
            pass
        return False


# YouTube's recommended audio: AAC-LC, 48 kHz stereo (mono TTS is upmixed).
_AUDIO_OUT = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def _frame_exact(scenes, fps: int) -> list[float]:
    """Scene durations snapped to frame boundaries on the CUMULATIVE timeline.

    Rounding each scene down on its own lost up to a frame per scene; over 93
    scenes the video ended ~1.5 s before the narration and `-shortest` cut the
    closing line. Snapping cumulative times keeps the total exact.
    """
    out, t, prev = [], 0.0, 0
    for s in scenes:
        t += max(0.8, s.duration)
        edge = round(t * fps)
        out.append(max(1, edge - prev) / fps)
        prev = edge
    return out


def burn_captions(video_path: str, srt_path: str) -> str:
    """Burn the word-timed captions into a Short. Returns the path to use.

    Large, bold, outlined text above the platforms' bottom UI. Falls back to the
    clean video if ffmpeg can't do it, since the SRT still ships alongside.
    """
    ffmpeg = _ffmpeg_exe()
    src, srt = Path(video_path), Path(srt_path)
    out = src.with_name(f"{src.stem}_captioned{src.suffix}")
    style = ("FontName=Arial,Bold=1,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
             "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=70,MarginL=48,MarginR=48")
    # Filter arguments can't hold a Windows path, so run beside the .srt.
    cmd = [ffmpeg, "-y", "-i", str(src.resolve()), "-vf",
           f"subtitles={srt.name}:force_style='{style}'",
           "-c:v", "libx264", "-preset", _preset(), "-crf", str(_crf()),
           "-pix_fmt", "yuv420p", *_COLOUR_TAGS, "-c:a", "copy",
           "-movflags", "+faststart", str(out.resolve())]
    try:
        subprocess.run(cmd, check=True, capture_output=True, cwd=str(srt.parent))
        return str(out)
    except Exception as exc:
        log.warning("Caption burn-in failed (%s); keeping the clean video.", str(exc)[:200])
        return str(src)


def _render_part(job) -> str | None:
    """Render one scene segment. Returns 'anim' | 'clip' | 'still', or None."""
    i, s, part, res, fps, brand, ffmpeg = job
    dur = max(0.8, s.duration)
    # 1) Motion-graphics animation when this beat suits it (a headline, a
    #    number, a date range, a cause->effect chain). Always on-topic and
    #    copyright-free, and covers subjects with no archival footage.
    if s.animation_kind:
        from core.media.animation import render_animated_segment
        if render_animated_segment(s.text_overlay or s.narration, s.animation_kind,
                                   part, res, fps, dur, brand=brand, seed=i):
            return "anim"
    # 2) Real archival footage.
    if s.clip_path and Path(s.clip_path).exists() and _clip_segment(ffmpeg, s, dur, res, fps, part):
        return "clip"
    # 3) Cinematic still with a Ken Burns move.
    if s.image_path and _kenburns_segment(ffmpeg, s, i, dur, res, fps, part):
        return "still"
    return None


def _init_worker(settings_dump: dict) -> None:
    """Give a worker process the parent's live settings, not a fresh YAML read
    (runtime overrides such as test fixtures would otherwise be lost)."""
    from core.config import Settings
    live, snap = get_settings(), Settings.model_validate(settings_dump)
    for name in Settings.model_fields:
        setattr(live, name, getattr(snap, name))


def _render_workers(n_jobs: int) -> int:
    import os
    configured = get_settings().video.render_workers
    auto = max(1, (os.cpu_count() or 2) - 2)   # leave headroom for the desktop
    return max(1, min(n_jobs, configured or auto))


def _render_parts(jobs: list) -> list[str | None]:
    """Segments are independent, so render them in parallel across CPU cores.
    Drawing frames is pure-Python Pillow work on one core per segment; at 1440p
    a 12-minute documentary took ~28 min serially on a 12-thread laptop CPU."""
    workers = _render_workers(len(jobs))
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                     initargs=(get_settings().model_dump(),)) as ex:
                return list(ex.map(_render_part, jobs))
        except Exception as exc:  # e.g. a broken pool: finish the job serially
            log.warning("Parallel render failed (%s); rendering serially.", str(exc)[:160])
    return [_render_part(j) for j in jobs]


def _kenburns_build(scenes, audio: VoiceResult | None, out_path: Path, res, fps: int = 30) -> bool:
    """Assemble the video scene-by-scene: REAL FOOTAGE where we have it, a
    Ken Burns still otherwise. Segments are concatenated, then the narration is
    muxed on top."""
    usable = [s for s in scenes if s.clip_path or s.image_path or s.animation_kind]
    ffmpeg = _ffmpeg_exe()
    if not usable or not ffmpeg:
        return False
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        brand = get_settings().brand.name
        jobs = [(i, s.model_copy(update={"duration": d}), tdp / f"p{i:04d}.mp4",
                 res, fps, brand, ffmpeg)
                for i, (s, d) in enumerate(zip(usable, _frame_exact(usable, fps)))]
        kinds = _render_parts(jobs)
        # Concatenate in scene order; a scene that failed every route is dropped.
        parts = [job[2] for job, kind in zip(jobs, kinds) if kind]
        if not parts:
            return False
        log.info("Assembled %d segment(s): %d animated, %d real footage, %d stills.",
                 len(parts), kinds.count("anim"), kinds.count("clip"), kinds.count("still"))

        lst = tdp / "list.txt"
        lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
        silent = tdp / "silent.mp4"
        subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(silent)], check=True, capture_output=True)

        if audio and Path(audio.audio_path).exists():
            cmd2 = [ffmpeg, "-y", "-i", str(silent), "-i", audio.audio_path,
                    "-c:v", "copy", "-af", "apad", *_AUDIO_OUT, "-shortest", str(out_path)]
        else:
            cmd2 = [ffmpeg, "-y", "-i", str(silent), "-c", "copy", str(out_path)]
        subprocess.run(cmd2, check=True, capture_output=True)
    return out_path.exists()


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
                "-r", "30", "-c:v", "libx264", "-preset", _preset(), "-crf", str(_crf()), str(silent)]
        subprocess.run(cmd1, check=True, capture_output=True)

        if audio and Path(audio.audio_path).exists():
            cmd2 = [ffmpeg, "-y", "-i", str(silent), "-i", audio.audio_path,
                    "-c:v", "copy", *_AUDIO_OUT, "-shortest", str(out_path)]
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
           "-c:v", "libx264", "-preset", _preset(), "-crf", str(_crf()), "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-shortest", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return out.exists()
    except Exception as exc:
        log.warning("Presenter compositing failed (%s); keeping base video.", exc)
        return False


def _long_bed(bed: str, seconds: float, work: Path) -> str:
    """A track shorter than the video, repeated with 4-second crossfades instead
    of a hard restart (a 3-minute track plays about three times in 8 minutes)."""
    ffmpeg = _ffmpeg_exe()
    try:
        info = subprocess.run([ffmpeg, "-hide_banner", "-i", bed], capture_output=True).stderr.decode(
            "utf-8", "replace")
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
        length = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    except Exception:
        return bed
    if length >= seconds + 2 or length < 20:
        return bed
    copies = int(math.ceil((seconds + 2) / (length - 4))) + 1
    inputs = [x for _ in range(copies) for x in ("-i", bed)]
    chain, last = [], "[0:a]"
    for k in range(1, copies):
        chain.append(f"{last}[{k}:a]acrossfade=d=4:c1=tri:c2=tri[x{k}]")
        last = f"[x{k}]"
    out = work / "_bed_long.wav"
    try:
        subprocess.run([ffmpeg, "-y", *inputs, "-filter_complex", ";".join(chain), "-map", last,
                        "-t", f"{seconds + 1:.2f}", "-ar", "48000", "-ac", "2", str(out)],
                       check=True, capture_output=True)
        return str(out)
    except Exception as exc:
        log.debug("crossfaded bed failed (%s); looping instead", str(exc)[:120])
        return bed


def _mix_music(base: Path, out: Path, seconds: float, seed: str, mood: str = "history",
               generated: bool = False, audio_only: bool = False) -> str:
    """Lay a background bed UNDER the narration with ducking + intro/outro swell.

    Returns the bed it used ("" on failure). `generated=True` uses the generated
    score whatever the owner added; `audio_only=True` writes just the mixed audio."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return ""
    from core.media.music import get_music_bed
    cfg = get_settings().video
    bed, source = get_music_bed(seconds, seed, mood, generated=generated)
    if not bed or source == "none":
        return ""
    used = bed
    if source == "user":
        bed = _long_bed(bed, seconds, out.parent)
    vol = cfg.music_volume
    io = cfg.music_intro_outro_seconds
    end = max(io, seconds - io)
    # Louder at the intro (t<io) and outro (t>end), quieter in the middle; then
    # sidechain-compress so the music dips whenever the narration is speaking.
    env = (f"volume='if(lt(t,{io}),{vol*2.4}, if(gt(t,{end}),{vol*2.4},{vol}))':eval=frame,"
           # The music ends with the picture instead of being cut off.
           f"afade=t=out:st={max(0.0, seconds - 3):.2f}:d=3")
    # Both inputs go to 48 kHz stereo first: amix adopts the first input's format,
    # so the music bed used to be squashed to Piper's 22 kHz mono.
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    fc = (f"[0:a]{fmt},asplit=2[voice][key];"
          f"[1:a]{fmt},{env}[bed];"
          f"[bed][key]sidechaincompress=threshold=0.04:ratio=8:attack=5:release=320[duck];"
          f"[voice][duck]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]")
    maps = ["-map", "[a]", "-vn"] if audio_only else ["-map", "0:v", "-map", "[a]", "-c:v", "copy"]
    cmd = [ffmpeg, "-y", "-i", str(base), "-stream_loop", "-1", "-i", bed,
           "-filter_complex", fc, *maps, *_AUDIO_OUT, "-shortest", str(out)]
    # (video is stream-copied here, so only the base build + presenter pass encode)
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        log.info("Mixed %s background music (ducked)%s.", source, " for the other platforms"
                 if generated else "")
        return used if out.exists() else ""
    except Exception as exc:
        log.warning("Music mix failed (%s); keeping video without music.", exc)
        return ""


def _normalize_audio(src: Path, out: Path) -> bool:
    """The same two-pass loudness pass as the video, for an audio-only file."""
    ffmpeg = _ffmpeg_exe()
    try:
        probe = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(src), "-af",
                                f"loudnorm={_LOUDNESS}:print_format=json", "-f", "null", "-"],
                               check=True, capture_output=True)
        text = probe.stderr.decode("utf-8", "replace")
        m = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
        subprocess.run([ffmpeg, "-y", "-i", str(src), "-af", _loudness_filter(m), *_AUDIO_OUT,
                        str(out)], check=True, capture_output=True)
        return out.exists()
    except Exception as exc:
        log.warning("Loudness pass (audio) failed (%s).", str(exc)[:160])
        return False


def _loudness_filter(m: dict) -> str:
    """Second loudnorm pass, then a limiter: loudnorm alone let a mix reach a true
    peak of +0.5 dB (it falls back to dynamic mode when the target can't be met)."""
    return (f"loudnorm={_LOUDNESS}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true,"
            # -3 dBFS sample peak leaves room for the AAC encoder's overshoot:
            # -2 dBFS still let one 1953 flood render reach a true peak of 0.0 dB.
            # loudnorm works at 192 kHz; limiting after the return to 48 kHz stops
            # the resampler's overshoot (the generated score's bells reached -0.5 dB).
            "aresample=48000,alimiter=limit=0.708:level=disabled")


def _normalize_loudness(src: Path, out: Path) -> bool:
    """Bring the finished mix to the platforms' level, and put the index up front.

    Two passes: measure, then correct, so the voice keeps its natural dynamics.
    """
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    try:
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af",
             f"loudnorm={_LOUDNESS}:print_format=json", "-f", "null", "-"],
            check=True, capture_output=True)
        text = probe.stderr.decode("utf-8", "replace")
        m = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
        filt = _loudness_filter(m)
        subprocess.run([ffmpeg, "-y", "-i", str(src), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                        "-af", filt, *_AUDIO_OUT, "-movflags", "+faststart", str(out)],
                       check=True, capture_output=True)
        return out.exists()
    except Exception as exc:
        log.warning("Loudness pass failed (%s); keeping the mix as it was.", str(exc)[:200])
        return False


def assemble_video(scenes: list[Scene], audio: VoiceResult | None, out_path: str | Path,
                   video_format: str = "short", presenter_overlay: str | None = None,
                   category: str = "history") -> VideoResult:
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
        if (engine_pref in ("auto", "ffmpeg") and _have_ffmpeg()
                and cfg.video.ken_burns and _kenburns_build(scenes, audio, out, res, fmt.fps)):
            engine_used = "ffmpeg-kenburns"
        elif engine_pref in ("auto", "ffmpeg") and _have_ffmpeg() and _ffmpeg_build(scenes, audio, out, res):
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
    if (presenter_overlay and engine_used.startswith("ffmpeg")
            and cfg.presenter.enabled and cfg.presenter.composite == "pip"):
        composed = out.with_name(out.stem + "_final.mp4")
        pcfg = _presenter_render_cfg()
        if _composite_presenter(final_path, presenter_overlay, composed, res,
                                 pcfg["scale"], pcfg["corner"]):
            final_path = _replace(final_path, composed)
            presenter_used = True

    # Background music (ducked under narration) on ffmpeg-built videos.
    music_used = False
    track, alt_audio = None, None
    if engine_used.startswith("ffmpeg") and cfg.video.background_music:
        from core.media.music import _user_tracks
        if _user_tracks(category):
            # The owner's track is licensed for YouTube: the copies for other
            # platforms get the same mix with the generated score instead.
            raw = out.with_name(out.stem + "_alt_raw.m4a")
            alt = out.with_name(out.stem + "_alt_audio.m4a")
            if _mix_music(final_path, raw, total, out.stem, category, generated=True,
                          audio_only=True) and _normalize_audio(raw, alt):
                alt_audio = str(alt)
            raw.unlink(missing_ok=True)
        mixed = final_path.with_name(final_path.stem + "_music.mp4")
        used = _mix_music(final_path, mixed, total, out.stem, category)
        if used:
            final_path = _replace(final_path, mixed)
            music_used = True
            if "_generated" not in Path(used).name:
                track = used
        (out.parent / "_bed_long.wav").unlink(missing_ok=True)

    if engine_used.startswith("ffmpeg"):
        levelled = final_path.with_name(final_path.stem + "_level.mp4")
        if _normalize_loudness(final_path, levelled):
            final_path = _replace(final_path, levelled)

    tags = ("+presenter" if presenter_used else "") + ("+music" if music_used else "")
    log.info("Assembled video via %s%s -> %s", engine_used, tags, final_path.name)
    return VideoResult(
        video_path=str(final_path),
        duration=round(total, 2),
        resolution=list(res),
        engine=engine_used + tags,
        has_captions=cfg.video.captions,
        music_track=track,
        alt_audio_path=alt_audio,
    )


def _replace(old: Path, new: Path) -> Path:
    """Each finishing pass (presenter, music, loudness) writes a new file; the one
    it replaces is an intermediate of this same build, about 1 GB at 1440p. Three
    were kept per video and filled the disk; only the finished file is kept."""
    if new.exists() and new.stat().st_size > 0 and old != new:
        try:
            old.unlink()
        except OSError as exc:
            log.debug("Could not remove intermediate %s (%s).", old.name, exc)
    return new


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
