"""Everything a reviewer needs to judge one finished video, in one place.

Writes storage/review/<run_id>/qa/ (contact sheets, stills, thumbnail preview)
and prints a report: technical checks, licences, scene-by-scene pictures,
search text and the claims a person should check.

Usage:
    python -m scripts.qa_report <run_id>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.media import credits
from core.media.themes import carry_subjects
from core.media.video import _ffmpeg_exe

# Measured targets: platforms play everything near -14 LUFS.
_LOUDNESS_RANGE = (-15.5, -12.5)
_MAX_TRUE_PEAK = -0.5


def _ff(*args: str, timeout: int = 1800) -> str:
    return subprocess.run([_ffmpeg_exe(), "-hide_banner", "-nostats", *args],
                          capture_output=True, timeout=timeout).stderr.decode("utf-8", "replace")


def _loudness(video: Path) -> tuple[float, float]:
    log = _ff("-i", str(video), "-vn", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-")
    summary = log[log.rfind("Summary:"):]
    return (float(re.search(r"I:\s+(-?[\d.]+)", summary)[1]),
            float(re.search(r"Peak:\s+(-?[\d.]+)", summary)[1]))


def _bad_frames(video: Path) -> list[int]:
    """Seconds whose frame is key-green or blank (one frame per second)."""
    import numpy as np

    from core.media.stock_video import frame_is_unusable
    w, h = 64, 36
    raw = subprocess.run([_ffmpeg_exe(), "-v", "error", "-i", str(video), "-vf",
                          f"fps=1,scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=1800).stdout
    # frame_is_unusable takes (pixels, 3) ints: uint8 overflows in its "2 * r" test.
    frames = np.frombuffer(raw, np.uint8).reshape(-1, w * h, 3).astype(int)
    return [i for i, f in enumerate(frames) if frame_is_unusable(f)]


def _sheet(video: Path, times: list[float], size: tuple[int, int], cols: int, out: Path) -> None:
    from PIL import Image
    w, h = size
    rows = (len(times) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 4), rows * (h + 4)))
    tmp = out.with_suffix(".tmp.jpg")
    for i, t in enumerate(times):
        subprocess.run([_ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={w}:{h}", str(tmp)], check=True)
        sheet.paste(Image.open(tmp), ((i % cols) * (w + 4), (i // cols) * (h + 4)))
    tmp.unlink(missing_ok=True)
    sheet.save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Review report for one finished video")
    ap.add_argument("run_id")
    run = ap.parse_args().run_id
    s = get_settings()
    bundle = ROOT_DIR / s.publishing.review_dir / run
    video = bundle / "video.mp4"
    qa = bundle / "qa"
    qa.mkdir(exist_ok=True)
    record = json.loads((bundle / "review.json").read_text(encoding="utf-8"))
    ctx = json.loads((ROOT_DIR / "storage" / "checkpoints" / f"{run}.json").read_text(encoding="utf-8"))
    short = record.get("format") == "short"
    problems: list[str] = []

    # ── technical ──────────────────────────────────────────────────────────
    info = _ff("-i", str(video))
    dur_m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    duration = int(dur_m[1]) * 3600 + int(dur_m[2]) * 60 + float(dur_m[3])
    stream = re.search(r"Video: [^\n]*", info)[0]
    level, peak = _loudness(video)
    bad = _bad_frames(video)
    head = video.read_bytes()[: 8 << 20]
    faststart = head.find(b"moov") != -1 and (head.find(b"mdat") == -1 or head.find(b"moov") < head.find(b"mdat"))
    print(f"== {run}  ({record.get('format')})  {record.get('title')}")
    print(f"length {duration:.1f}s | loudness {level} LUFS, true peak {peak} dB | "
          f"fast-start {faststart} | {video.stat().st_size >> 20} MB")
    print(f"video: {stream[:120]}")
    if duration > s.quality.max_video_seconds:
        problems.append(f"longer than {s.quality.max_video_seconds}s")
    if not _LOUDNESS_RANGE[0] <= level <= _LOUDNESS_RANGE[1] or peak > _MAX_TRUE_PEAK:
        problems.append(f"loudness {level} LUFS / peak {peak}")
    if bad:
        problems.append(f"green or blank frames at {bad[:10]} s")
    if "bt709" not in stream:
        problems.append("colour tags are not bt709")

    # ── pictures ───────────────────────────────────────────────────────────
    if short:
        _sheet(video, [1 + 2.5 * i for i in range(int(duration // 2.5))], (216, 384), 13, qa / "sheet.png")
    else:
        _sheet(video, [4 + 12 * i for i in range(int(duration // 12))], (320, 180), 9, qa / "sheet.png")
    _sheet(video, [max(0.5, duration - 3)], (480, 854) if short else (960, 540), 1, qa / "end.png")
    _sheet(video, [0.5, 2.0, 4.0, 6.0], (216, 384) if short else (480, 270), 4, qa / "opening.png")
    scenes = ctx["scene_plan"]["scenes"]
    stills = [sc for sc in scenes if sc.get("image_path") and not sc.get("clip_path")
              and not sc.get("animation_kind")]
    if stills:
        from PIL import Image
        w, h = (180, 320) if short else (320, 180)
        sheet = Image.new("RGB", (6 * (w + 4), ((len(stills) + 5) // 6) * (h + 4)))
        for i, sc in enumerate(stills):
            sheet.paste(Image.open(sc["image_path"]).convert("RGB").resize((w, h)),
                        ((i % 6) * (w + 4), (i // 6) * (h + 4)))
        sheet.save(qa / "stills.png")
    if (bundle / "thumbnail.png").exists():
        from PIL import Image
        im = Image.open(bundle / "thumbnail.png").convert("RGB")
        im.thumbnail((320, 568) if short else (480, 270))
        im.save(qa / "thumbnail.png")

    # Shot list: every line beside what is on screen, so the director can check
    # that each picture belongs to its line (qa/shotlist.txt, one line per scene).
    print("\n-- scenes (time, length, subject searched, picture, narration)")
    t = 0.0
    shots = []
    for sc, sub in zip(scenes, carry_subjects([sc["narration"] for sc in scenes])):
        kind = sc.get("animation_kind") or ""
        if kind.startswith("map:"):
            spec = json.loads(kind[4:])
            shown = f"MAP {spec.get('place') or ''} {spec.get('country') or ''}".strip()
        elif kind.startswith(("showcase:", "layers:")):
            from core.media.scenes import describe
            shown = describe(kind)
        elif kind:
            shown = f"CARD {kind}"
        else:
            shown = sc.get("source") or Path(sc.get("clip_path") or sc.get("image_path") or "").name
        src = ("ANIM:" + kind[:14]) if kind else Path(sc.get("clip_path") or sc.get("image_path") or "").name
        print(f"{t:6.1f} {sc['duration']:4.1f} {str(sub)[:28]:<28} {src:<18} {sc['narration'][:70]}")
        if sc.get("label"):
            shown += f"  [caption: {sc['label']}]"
        m, sec = divmod(int(t), 60)
        shots.append(f"{m}:{sec:02d}  {sc['narration'].strip()}\n      ON SCREEN: {shown}")
        t += sc["duration"]
    from core.media import shotlist
    text, flagged = shotlist.build(scenes, ctx.get("category", "history"))
    (qa / "shotlist.txt").write_text(text, encoding="utf-8")
    print(f"Shot list: {qa / 'shotlist.txt'}"
          + (f"  ({flagged} line(s) flagged !! for a second look)" if flagged else ""))

    # ── licences ───────────────────────────────────────────────────────────
    folder = Path(s.storage_path("images")) / run
    items = credits.load(folder)
    problem = credits.publish_problem(folder)
    if problem:
        problems.append(problem)
    print(f"\n-- credits: {dict(Counter(i['license'] for i in items))}")
    for i in items:
        if "Pixabay" not in i["license"]:
            print(f"   {i['license']:<18} {i['title'][:70]}")

    # ── search text ────────────────────────────────────────────────────────
    print("\n-- metadata")
    for m in json.loads((bundle / "metadata.json").read_text(encoding="utf-8")):
        desc = m["description"]
        flags = [f for f, ok in (("disclaimer", "Disclaimer:" in desc),
                                 ("credits link", f"content/credits/{run}.txt" in desc)) if not ok]
        if flags:
            problems.append(f"{m['platform']} description lacks {', '.join(flags)}")
        print(f"{m['platform']:<10} title {len(m['title'])} chars | tags {m['tags'][:6]} | {m['hashtags']}")
    yt = next((m for m in json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
               if m["platform"] == "youtube"), None)
    if yt:
        print(f"\nYouTube title: {yt['title']}\nDescription opening: {yt['description'][:300]}")

    claims = bundle / "claims_to_check.txt"
    if claims.exists():
        print("\n-- claims to check\n" + claims.read_text(encoding="utf-8").strip())

    print(f"\nPictures to look at: {qa}")
    print("PROBLEMS: " + ("; ".join(problems) if problems else "none found by the automatic checks"))


if __name__ == "__main__":
    main()
