"""Cut a finished long video into numbered vertical reels and release them through the day.

Usage:
    python -m scripts.make_reels plan <run_id> [--parts N]
        Show where each part starts and ends (sentence breaks), and its text.
    python -m scripts.make_reels render <run_id> --titles content/scripts/<slug>.reels.txt [--parts N]
        Render storage/reels/<run_id>/part_NN.mp4 and sheet.png to review.
    python -m scripts.make_reels publish <run_id> --long-id <video_id> [--live]
        Upload each part PRIVATE to YouTube with a release time (Part 1 after the
        long video goes out), and copy them to upload_ready/ for Facebook/TikTok.
        Without --live it only prints what it would do.

The titles file has one line per part: `HEADLINE | YouTube title`. HEADLINE is the
short text shown at the top of the reel (2-6 words); the YouTube title gets
"(Part n/N)" added.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import ROOT_DIR, get_settings
from core.media import reels

W, H = 1080, 1920
FG_Y = 560                       # the landscape picture sits here, under the headline
FPS = 30
# Release times for reels, in the audience's time zone (publishing.release_timezone).
REEL_TIMES = ["07:00", "09:00", "11:00", "13:00", "16:00", "18:00", "20:00", "22:00"]
_LEAD = timedelta(minutes=45)
_AFTER_LONG = timedelta(hours=1)
_SLOTS = ROOT_DIR / "storage" / "reel_slots.json"
_API = "https://www.googleapis.com/youtube/v3"
# Same caption look as the reviewed Shorts (core/media/video.burn_captions).
_CAPTION_STYLE = ("FontName=Arial,Bold=1,FontSize=13,PrimaryColour=&H00FFFFFF,"
                  "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,"
                  "MarginV=70,MarginL=48,MarginR=48")


def _bundle(run_id: str) -> Path:
    return ROOT_DIR / get_settings().publishing.review_dir / run_id


def _out(run_id: str) -> Path:
    p = ROOT_DIR / "storage" / "reels" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parts(run_id: str, n: int | None) -> list[reels.Part]:
    srt = (_bundle(run_id) / "captions.srt").read_text(encoding="utf-8")
    sents = reels.sentences(reels.parse_srt(srt), get_settings().brand.cta)
    return reels.split(sents, n)


def cmd_plan(args) -> None:
    parts = _parts(args.run_id, args.parts)
    plan = []
    for p in parts:
        print(f"\nPART {p.number}/{p.total}  {p.start:7.1f}s -> {p.end:7.1f}s  ({p.duration:.0f}s)")
        print("  " + p.text)
        plan.append({"part": p.number, "start": p.start, "end": p.end, "text": p.text})
    (_out(args.run_id) / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"\n{len(parts)} parts. Write one line per part, 'HEADLINE | YouTube title', "
          f"in content/scripts/<slug>.reels.txt, then run render.")


def _headline_png(path: Path, number: int, total: int, headline: str) -> None:
    from PIL import Image, ImageDraw

    from core.media.animation import Style, _fit_text, _font
    st = Style()
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # A soft dark band behind the text keeps it readable over any picture.
    for y in range(FG_Y):
        d.line([(0, y), (W, y)], fill=(8, 10, 16, int(150 * min(1.0, (FG_Y - y) / 140))))
    label = f"PART {number}/{total}"
    lf = _font(58, True)
    lb = d.textbbox((0, 0), label, font=lf)
    f, wrapped = _fit_text(d, headline.upper(), lambda s: _font(s, True), 940, 96,
                           min_size=56, max_h=250, spacing=12)
    tb = d.multiline_textbbox((0, 0), wrapped, font=f, spacing=12)
    top = 200
    d.text(((W - (lb[2] - lb[0])) / 2, top), label, font=lf, fill=(*st.accent, 255))
    d.multiline_text(((W - (tb[2] - tb[0])) / 2, top + 90), wrapped, font=f,
                     fill=(*st.ink, 255), spacing=12, align="center",
                     stroke_width=3, stroke_fill=(0, 0, 0, 255))
    img.save(path)


def _card(path: Path) -> None:
    from core.media.animation import render_animated_segment
    b = get_settings().brand
    if not render_animated_segment(b.disclaimer_screen.strip(), "notice", path, (W, H), FPS,
                                   b.disclaimer_seconds_short, brand=""):
        raise SystemExit("could not render the disclaimer card")


def _render_part(src: Path, part: reels.Part, headline: str, card: Path, out: Path) -> None:
    from core.media.video import _COLOUR_TAGS, _crf, _ffmpeg_exe, _normalize_loudness, _preset
    ffmpeg = _ffmpeg_exe()
    work = out.parent / f"_work_{part.number:02d}"
    work.mkdir(exist_ok=True)
    (work / "c.srt").write_text(reels.part_srt(part), encoding="utf-8")
    _headline_png(work / "head.png", part.number, part.total, headline)
    _next_png(work / "next.png", reels.next_step(part.number, part.total))
    d = part.duration
    cta_from = max(0.0, d - reels.NEXT_STEP_SECONDS)
    secs = get_settings().brand.disclaimer_seconds_short
    filt = (
        "[0:v]split[a][b];"
        "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
        f"scale={W}:{H},eq=brightness=-0.18:saturation=0.85[bg];"
        f"[b]scale={W}:-2[fg];[bg][fg]overlay=0:{FG_Y}[v1];[v1][1:v]overlay=0:0[v1h];"
        f"[v1h][4:v]overlay=0:0:enable='gte(t,{cta_from:.3f})'[v2];"
        f"[v2]subtitles=c.srt:force_style='{_CAPTION_STYLE}',"
        f"scale=out_color_matrix=bt709:out_range=tv,fps={FPS},format=yuv420p,setsar=1[vp];"
        f"[2:v]fps={FPS},format=yuv420p,setsar=1[vc];"
        f"[0:a]afade=t=in:d=0.12,afade=t=out:st={max(0.0, d - 0.35):.3f}:d=0.35,"
        "aformat=sample_rates=48000:channel_layouts=stereo[ap];"
        "[3:a]aformat=sample_rates=48000:channel_layouts=stereo[ac];"
        "[vp][ap][vc][ac]concat=n=2:v=1:a=1[vv][a];"
        # concat drops the colour tags; set them so every player shows the same colours.
        "[vv]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[v]")
    raw = work / "raw.mp4"
    cmd = [ffmpeg, "-y", "-ss", f"{part.start:.3f}", "-t", f"{d:.3f}", "-i", str(src.resolve()),
           "-i", str((work / "head.png").resolve()), "-i", str(card.resolve()),
           "-f", "lavfi", "-t", f"{secs}", "-i", "anullsrc=r=48000:cl=stereo",
           "-i", str((work / "next.png").resolve()),
           "-filter_complex", filt, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", _preset(), "-crf", str(_crf()), "-pix_fmt", "yuv420p",
           *_COLOUR_TAGS, "-c:a", "aac", "-b:a", "192k", str(raw.resolve())]
    # The subtitles filter can't take a Windows path, so run beside the .srt.
    r = subprocess.run(cmd, capture_output=True, cwd=str(work))
    if r.returncode != 0:
        raise SystemExit(f"part {part.number} failed: {r.stderr.decode('utf-8', 'replace')[-600:]}")
    if not _normalize_loudness(raw, out):
        shutil.copyfile(raw, out)
    shutil.rmtree(work, ignore_errors=True)


def _next_png(path: Path, text: str) -> None:
    """The call to action shown under the picture over the part's last seconds."""
    from PIL import Image, ImageDraw

    from core.media.animation import Style, _fit_text, _font
    st = Style()
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f, wrapped = _fit_text(d, text, lambda s: _font(s, True), 940, 64,
                           min_size=40, max_h=160, spacing=10)
    tb = d.multiline_textbbox((0, 0), wrapped, font=f, spacing=10)
    # Inside the bottom of the picture, clear of the captions below it.
    top = FG_Y + W * 9 // 16 - 34 - (tb[3] - tb[1]) - 10
    pad = 22
    d.rounded_rectangle([(W - (tb[2] - tb[0])) / 2 - pad, top - pad,
                         (W + (tb[2] - tb[0])) / 2 + pad, top + (tb[3] - tb[1]) + pad + 10],
                        radius=18, fill=(*st.accent, 235))
    d.multiline_text(((W - (tb[2] - tb[0])) / 2 - tb[0], top - tb[1]), wrapped, font=f,
                     fill=(255, 255, 255, 255), spacing=10, align="center")
    img.save(path)


def _sheet(files: list[Path], out: Path) -> None:
    """For each part: the opening (headline), the middle and the end card."""
    from PIL import Image

    from core.media.video import _ffmpeg_exe
    ffmpeg = _ffmpeg_exe()
    tw, th = 216, 384
    sheet = Image.new("RGB", (tw * 3 + 40, (th + 10) * len(files) + 10), (20, 20, 24))
    for row, f in enumerate(files):
        dur = _duration(f)
        for col, t in enumerate([0.8, dur * 0.45, dur - 1.5]):
            png = f.with_suffix(f".{col}.png")
            subprocess.run([ffmpeg, "-y", "-ss", f"{t:.2f}", "-i", str(f), "-frames:v", "1",
                            str(png)], capture_output=True)
            if png.exists():
                sheet.paste(Image.open(png).resize((tw, th)), (10 + col * (tw + 10), 10 + row * (th + 10)))
                png.unlink()
    sheet.save(out)


def _duration(f: Path) -> float:
    from core.media.video import _ffmpeg_exe
    r = subprocess.run([_ffmpeg_exe(), "-i", str(f)], capture_output=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr.decode("utf-8", "replace"))
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def cmd_render(args) -> None:
    parts = _parts(args.run_id, args.parts)
    titles = reels.read_titles(Path(args.titles).read_text(encoding="utf-8"), len(parts))
    out = _out(args.run_id)
    for old in out.glob("part_*.mp4"):
        old.unlink()
    src = _bundle(args.run_id) / "video.mp4"
    card = out / "_card.mp4"
    _card(card)
    files, plan = [], []
    for p, (head, title) in zip(parts, titles):
        f = out / f"part_{p.number:02d}.mp4"
        print(f"rendering part {p.number}/{p.total} ({p.duration:.0f}s): {head}")
        _render_part(src, p, head, card, f)
        files.append(f)
        plan.append({"part": p.number, "total": p.total, "start": p.start, "end": p.end,
                     "headline": head, "title": reels.youtube_title(title, p.number, p.total),
                     "seconds": round(_duration(f), 1), "text": p.text, "file": f.name})
    card.unlink(missing_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    _sheet(files, out / "sheet.png")
    for row in plan:
        flag = "" if row["seconds"] <= 180 else "  !! over 3 minutes"
        print(f"  {row['file']}  {row['seconds']:5.1f}s  {row['title']}{flag}")
    print(f"Review {out / 'sheet.png'} and each part before publishing.")


def next_reel_slots(after: datetime, count: int, taken: list[str], tz_name: str,
                    times: list[str] = REEL_TIMES) -> list[datetime]:
    """The next `count` free reel release times after `after` (aware datetimes, UTC)."""
    tz = ZoneInfo(tz_name)
    held = {datetime.fromisoformat(t).astimezone(timezone.utc) for t in taken}
    local = after.astimezone(tz)
    out: list[datetime] = []
    for days in range(0, 60):
        day = (local + timedelta(days=days)).date()
        for hhmm in times:
            h, m = (int(x) for x in hhmm.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(timezone.utc)
            if slot >= after.astimezone(timezone.utc) and slot not in held:
                out.append(slot)
                if len(out) == count:
                    return out
    raise RuntimeError("no free reel slots in the next 60 days")


def _description(long_meta: dict, long_id: str, number: int, total: int) -> str:
    desc = long_meta["description"]
    first, _, rest = desc.partition("\n\n")
    tags = " ".join(dict.fromkeys(["#shorts", *long_meta.get("hashtags", [])]))
    tags = tags.replace("#documentary", "").replace("  ", " ").strip()
    return (f"Part {number} of {total}. {first}\n\n"
            f"Watch the full documentary: https://youtu.be/{long_id}\n\n{rest}\n\n{tags}")


def cmd_publish(args) -> None:
    import httpx

    from core.media import credits
    from core.publishing.youtube import _UPLOAD_URL, _upload_chunks, access_token

    s = get_settings()
    out = _out(args.run_id)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if not all("file" in r for r in plan):
        raise SystemExit("Render the reels first.")
    problem = credits.publish_problem(Path(s.storage_path("images")) / args.run_id)
    if problem:
        raise SystemExit(f"Not publishing: {problem}")
    meta = next(m for m in json.loads((_bundle(args.run_id) / "metadata.json")
                                      .read_text(encoding="utf-8")) if m["platform"] == "youtube")
    for r in plan:
        if r["seconds"] > 180:
            raise SystemExit(f"{r['file']} is over 3 minutes")

    h = {"Authorization": f"Bearer {access_token()}"}
    items = httpx.get(f"{_API}/videos", headers=h, timeout=30,
                      params={"part": "status", "id": args.long_id}).json().get("items", [])
    if not items:
        raise SystemExit(f"long video {args.long_id} not found on the channel")
    st = items[0]["status"]
    now = datetime.now(timezone.utc)
    long_out = (datetime.fromisoformat(st["publishAt"].replace("Z", "+00:00"))
                if st.get("publishAt") else now)
    after = max(now + _LEAD, long_out + _AFTER_LONG)
    taken = json.loads(_SLOTS.read_text(encoding="utf-8")) if _SLOTS.exists() else []
    slots = next_reel_slots(after, len(plan), taken, s.publishing.release_timezone)
    tz, home = ZoneInfo(s.publishing.release_timezone), ZoneInfo(s.publishing.timezone)

    ready = ROOT_DIR / "upload_ready" / f"reels_{args.run_id}"
    ready.mkdir(parents=True, exist_ok=True)
    done_path = out / "published.json"
    done = json.loads(done_path.read_text(encoding="utf-8")) if done_path.exists() else {}
    for r, slot in zip(plan, slots):
        desc = _description(meta, args.long_id, r["part"], r["total"])
        f = out / r["file"]
        shutil.copyfile(f, ready / r["file"])
        (ready / f"{f.stem}.txt").write_text(f"{r['title']}\n\n{desc}\n", encoding="utf-8")
        when = f"{slot.astimezone(tz):%a %d %b %H:%M} ET / {slot.astimezone(home):%H:%M} Dubai"
        if r["file"] in done:
            print(f"  {r['file']} already uploaded: {done[r['file']]['url']}")
            continue
        if not args.live:
            print(f"  [dry] {r['file']} -> {r['title']}  release {when}")
            continue
        body = {"snippet": {"title": r["title"], "description": desc[:4900],
                            "tags": meta.get("tags", [])[:30], "categoryId": "27"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                           "publishAt": slot.strftime("%Y-%m-%dT%H:%M:%SZ")}}
        h = {"Authorization": f"Bearer {access_token()}"}
        init = httpx.post(_UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                          headers={**h, "X-Upload-Content-Length": str(f.stat().st_size),
                                   "X-Upload-Content-Type": "video/*"}, json=body, timeout=60)
        init.raise_for_status()
        vid = _upload_chunks(init.headers["Location"], f)["id"]
        got = httpx.get(f"{_API}/videos", headers=h, timeout=30,
                        params={"part": "status,snippet", "id": vid}).json()["items"][0]
        ok = (got["status"].get("publishAt") and got["snippet"]["title"] == r["title"]
              and "Disclaimer:" in got["snippet"]["description"]
              and not got["status"].get("rejectionReason"))
        done[r["file"]] = {"id": vid, "url": f"https://youtube.com/shorts/{vid}",
                           "release": slot.isoformat(), "checks_ok": bool(ok)}
        taken = sorted({*taken, slot.isoformat()})
        _SLOTS.parent.mkdir(parents=True, exist_ok=True)
        _SLOTS.write_text(json.dumps(taken), encoding="utf-8")
        done_path.write_text(json.dumps(done, indent=2), encoding="utf-8")
        print(f"  [{'OK' if ok else '!!'}] {r['file']} https://youtube.com/shorts/{vid}  release {when}")
    print(f"Facebook/TikTok copies with captions: {ready}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Numbered vertical reels from a long video")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("run_id")
    p.add_argument("--parts", type=int)
    r = sub.add_parser("render")
    r.add_argument("run_id")
    r.add_argument("--titles", required=True)
    r.add_argument("--parts", type=int)
    u = sub.add_parser("publish")
    u.add_argument("run_id")
    u.add_argument("--long-id", required=True)
    u.add_argument("--live", action="store_true", help="upload for real (private, scheduled)")
    args = ap.parse_args(argv)
    {"plan": cmd_plan, "render": cmd_render, "publish": cmd_publish}[args.cmd](args)


if __name__ == "__main__":
    main()
