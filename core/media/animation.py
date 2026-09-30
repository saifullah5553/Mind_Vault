"""Motion-graphics animation engine — Kurzgesagt-style, CPU-only, no GPU.

Why this exists: archival footage does not exist for every topic (there is no
public-domain film of the Maya), and static photos can only carry so much. The
biggest channels in this niche are flat vector motion graphics, not live footage
and not character cartoons. That style is generated entirely in code, so it is
free, always on-topic, infinitely scalable, and carries zero copyright risk.

Deliberately built on Pillow + ffmpeg only — no Manim, no cairo, no LaTeX — so it
runs anywhere the rest of the pipeline already runs.

Scene kinds
-----------
title     big kinetic headline with an accent rule that draws itself
stat      a number counting up behind a filling bar
timeline  a line that draws with date ticks popping in
concept   labelled nodes connected by arrows that draw in sequence
quote     a quotation revealing line by line
bullets   points sliding in one at a time
ambient   drifting abstract shapes behind the caption (generic fallback)

Frames are rendered as JPEG (far faster to encode than PNG) and muxed by ffmpeg.
The static background is computed once per scene and reused for every frame,
which is what keeps this fast enough for long-form.
"""

from __future__ import annotations

import math
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.animation")

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|[1-9][0-9]{0,2}\s?(?:BC|AD|BCE|CE))\b")
_NUM_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?%?)\b")
_CAUSE_RE = re.compile(r"\b(because|therefore|led to|caused|resulted in|which meant)\b", re.I)


@dataclass
class Style:
    """Brand look for the animated scenes."""
    bg_top: tuple = (14, 17, 26)
    bg_bottom: tuple = (32, 38, 58)
    accent: tuple = (139, 123, 240)
    ink: tuple = (245, 246, 250)
    muted: tuple = (150, 158, 178)
    palette: list = field(default_factory=lambda: [
        (139, 123, 240), (240, 118, 128), (96, 190, 180), (226, 170, 84)])


# ── low-level helpers ───────────────────────────────────────────────────────
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["arialbd.ttf", "seguibl.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _frame_quality() -> int:
    from core.config import get_settings
    return int(getattr(get_settings().video, "frame_quality", 95))


def _enc_crf() -> int:
    from core.config import get_settings
    return int(getattr(get_settings().video, "crf", 18))


def _enc_preset() -> str:
    from core.config import get_settings
    return str(getattr(get_settings().video, "preset", "medium"))


def _ease(t: float) -> float:
    """Smooth in/out easing; motion never starts or stops abruptly."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _background(res, style: Style):
    """Vertical gradient built with numpy (per-line drawing is far too slow)."""
    import numpy as np
    from PIL import Image

    w, h = res
    g = np.linspace(0.0, 1.0, h, dtype="float32")[:, None]
    top = np.array(style.bg_top, dtype="float32")
    bot = np.array(style.bg_bottom, dtype="float32")
    arr = (top * (1 - g) + bot * g)[:, None, :].repeat(w, axis=1)
    return Image.fromarray(arr.astype("uint8"), "RGB")


def _fit_text(draw, text: str, font_factory, max_w: int, start: int, min_size: int = 24):
    """Shrink the font until the text fits the frame width."""
    import textwrap
    size = start
    while size > min_size:
        f = font_factory(size)
        wrapped = textwrap.fill(text, width=max(12, int(max_w / (size * 0.55))))
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=f, spacing=10)
        if bbox[2] - bbox[0] <= max_w:
            return f, wrapped
        size -= 4
    f = font_factory(min_size)
    return f, textwrap.fill(text, width=max(12, int(max_w / (min_size * 0.55))))


def _alpha_text(base, xy, text, font, fill, alpha: float, spacing=10, align="center"):
    """Draw text at a given opacity (for fades) onto an RGB base image."""
    from PIL import Image, ImageDraw
    if alpha <= 0.01:
        return
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.multiline_text(xy, text, font=font, fill=(*fill, int(255 * min(1.0, alpha))),
                     spacing=spacing, align=align)
    merged = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
    base.paste(merged, (0, 0))


# ── scene kind selection ────────────────────────────────────────────────────
def choose_kind(text: str, index: int = 0, is_first: bool = False) -> str | None:
    """Pick an animation kind from the narration, or None to use footage/stills."""
    t = (text or "").strip()
    if not t:
        return None
    if is_first:
        return "title"
    if '"' in t or "“" in t:
        return "quote"
    years = _YEAR_RE.findall(t)
    if len(years) >= 2:
        return "timeline"
    if _NUM_RE.search(t) or years:
        return "stat"
    if _CAUSE_RE.search(t):
        return "concept"
    return None


# ── scene renderers (each draws ONE frame at progress p in [0,1]) ───────────
def _draw_title(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    font, wrapped = _fit_text(d, scene_text, lambda s: _font(s, True),
                              int(w * 0.84), int(w * 0.11))
    bbox = d.multiline_textbbox((0, 0), wrapped, font=font, spacing=12)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    a = _ease(min(1.0, p * 2.2))
    y = (h - th) / 2 - 30 + (1 - a) * 40          # rises slightly as it fades in
    _alpha_text(img, ((w - tw) / 2, y), wrapped, font, style.ink, a, spacing=12)
    rule = _ease(max(0.0, min(1.0, (p - 0.25) * 2.0)))
    if rule > 0:
        rw = int(w * 0.30 * rule)
        ry = int(y + th + 44)
        d.rounded_rectangle([(w - rw) // 2, ry, (w + rw) // 2, ry + 9],
                            radius=5, fill=style.accent)


def _draw_stat(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    m = _NUM_RE.search(scene_text) or _YEAR_RE.search(scene_text)
    raw = m.group(0) if m else "100"
    digits = re.sub(r"[^\d.]", "", raw) or "100"
    suffix = "%" if raw.endswith("%") else ""
    try:
        target = float(digits)
    except ValueError:
        target = 100.0
    shown = target * _ease(min(1.0, p * 1.6))
    label = re.sub(re.escape(raw), "", scene_text).strip(" ,.;:") or scene_text

    num = f"{shown:,.0f}{suffix}" if target >= 10 else f"{shown:,.1f}{suffix}"
    nf = _font(int(w * 0.20), True)
    nb = d.textbbox((0, 0), num, font=nf)
    _alpha_text(img, ((w - (nb[2] - nb[0])) / 2, h * 0.34), num, nf, style.accent, 1.0)

    lf, wrapped = _fit_text(d, label, lambda s: _font(s, False),
                            int(w * 0.8), int(w * 0.055))
    lb = d.multiline_textbbox((0, 0), wrapped, font=lf, spacing=8)
    _alpha_text(img, ((w - (lb[2] - lb[0])) / 2, h * 0.52), wrapped, lf,
                style.muted, _ease(min(1.0, p * 2)), spacing=8)

    bw = int(w * 0.62); bx = (w - bw) // 2; by = int(h * 0.62)
    d.rounded_rectangle([bx, by, bx + bw, by + 16], radius=8, fill=(60, 66, 88))
    d.rounded_rectangle([bx, by, bx + max(1, int(bw * _ease(min(1.0, p * 1.6)))), by + 16],
                        radius=8, fill=style.accent)


def _draw_timeline(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    years = _YEAR_RE.findall(scene_text)[:4] or ["", ""]
    y0 = int(h * 0.48)
    lw = int(w * 0.80); lx = (w - lw) // 2
    drawn = int(lw * _ease(min(1.0, p * 1.4)))
    d.rounded_rectangle([lx, y0 - 3, lx + lw, y0 + 3], radius=3, fill=(70, 78, 100))
    if drawn > 0:
        d.rounded_rectangle([lx, y0 - 3, lx + drawn, y0 + 3], radius=3, fill=style.accent)
    n = max(1, len(years))
    for i, yr in enumerate(years):
        px = lx + int(lw * (i / max(1, n - 1))) if n > 1 else lx + lw // 2
        appear = _ease(max(0.0, min(1.0, (p - 0.15 * i) * 3)))
        if appear <= 0:
            continue
        r = max(2, int(14 * appear))
        col = style.palette[i % len(style.palette)]
        d.ellipse([px - r, y0 - r, px + r, y0 + r], fill=col)
        f = _font(int(w * 0.045), True)
        tb = d.textbbox((0, 0), str(yr), font=f)
        _alpha_text(img, (px - (tb[2] - tb[0]) / 2, y0 - 90), str(yr), f, style.ink, appear)


def _draw_concept(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    parts = [s.strip() for s in _CAUSE_RE.split(scene_text) if s.strip()][:3] or [scene_text]
    parts = [s for s in parts if not _CAUSE_RE.fullmatch(s)] or [scene_text]
    n = len(parts)
    box_w, box_h = int(w * 0.72), int(h * 0.11)
    gap = int(h * 0.06)
    total = n * box_h + (n - 1) * gap
    top = (h - total) // 2
    for i, part in enumerate(parts):
        appear = _ease(max(0.0, min(1.0, (p - 0.22 * i) * 2.6)))
        if appear <= 0:
            continue
        by = top + i * (box_h + gap)
        col = style.palette[i % len(style.palette)]
        d.rounded_rectangle([(w - box_w) // 2, by, (w + box_w) // 2, by + box_h],
                            radius=18, outline=col, width=max(2, int(4 * appear)))
        f, wrapped = _fit_text(d, part[:90], lambda s: _font(s, False),
                               int(box_w * 0.88), int(w * 0.045))
        tb = d.multiline_textbbox((0, 0), wrapped, font=f, spacing=6)
        _alpha_text(img, ((w - (tb[2] - tb[0])) / 2, by + (box_h - (tb[3] - tb[1])) / 2),
                    wrapped, f, style.ink, appear, spacing=6)
        if i < n - 1:
            ar = _ease(max(0.0, min(1.0, (p - 0.22 * i - 0.12) * 3)))
            if ar > 0:
                ax = w // 2; y1 = by + box_h; y2 = y1 + int(gap * ar)
                d.line([ax, y1, ax, y2], fill=style.muted, width=4)
                if ar > 0.85:
                    d.polygon([(ax - 11, y2 - 12), (ax + 11, y2 - 12), (ax, y2)],
                              fill=style.muted)


def _draw_quote(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    qf = _font(int(w * 0.26), True)
    _alpha_text(img, (w * 0.09, h * 0.22), "“", qf, style.accent,
                _ease(min(1.0, p * 3)))
    body = scene_text.strip().strip('"')
    f, wrapped = _fit_text(d, body, lambda s: _font(s, False),
                           int(w * 0.78), int(w * 0.07))
    lines = wrapped.split("\n")
    lh = d.textbbox((0, 0), "Ag", font=f)[3] + 14
    y = h * 0.40
    for i, line in enumerate(lines):
        a = _ease(max(0.0, min(1.0, (p - 0.10 * i) * 3)))
        if a <= 0:
            continue
        tb = d.textbbox((0, 0), line, font=f)
        _alpha_text(img, ((w - (tb[2] - tb[0])) / 2, y + i * lh), line, f, style.ink, a)


def _draw_bullets(img, scene_text, style, res, p):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    parts = [s.strip() for s in re.split(r"[.;]", scene_text) if len(s.strip()) > 3][:4] \
        or [scene_text]
    f = _font(int(w * 0.05), False)
    lh = int(h * 0.09)
    top = (h - len(parts) * lh) // 2
    for i, part in enumerate(parts):
        a = _ease(max(0.0, min(1.0, (p - 0.18 * i) * 2.8)))
        if a <= 0:
            continue
        y = top + i * lh + (1 - a) * 26
        col = style.palette[i % len(style.palette)]
        d.ellipse([w * 0.12, y + 14, w * 0.12 + 16, y + 30], fill=col)
        _alpha_text(img, (w * 0.18, y), part[:80], f, style.ink, a, align="left")


def _draw_ambient(img, scene_text, style, res, p, seed: int = 0):
    from PIL import ImageDraw
    w, h = res
    d = ImageDraw.Draw(img)
    for i in range(5):
        col = style.palette[(i + seed) % len(style.palette)]
        cx = int(w * (0.18 + 0.16 * i) + 40 * math.sin(2 * math.pi * (p + i * 0.2)))
        cy = int(h * (0.25 + 0.12 * ((i * 7 + seed) % 5))
                 + 30 * math.cos(2 * math.pi * (p + i * 0.3)))
        r = int(w * (0.05 + 0.02 * ((i + seed) % 3)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)
    f, wrapped = _fit_text(d, scene_text, lambda s: _font(s, True),
                           int(w * 0.8), int(w * 0.075))
    tb = d.multiline_textbbox((0, 0), wrapped, font=f, spacing=10)
    _alpha_text(img, ((w - (tb[2] - tb[0])) / 2, (h - (tb[3] - tb[1])) / 2),
                wrapped, f, style.ink, _ease(min(1.0, p * 2.5)))


_RENDERERS = {
    "title": _draw_title, "stat": _draw_stat, "timeline": _draw_timeline,
    "concept": _draw_concept, "quote": _draw_quote, "bullets": _draw_bullets,
}


# ── public API ──────────────────────────────────────────────────────────────
def render_animated_segment(text: str, kind: str, out_path: Path, res, fps: int,
                            duration: float, brand: str = "", seed: int = 0,
                            style: Style | None = None) -> bool:
    """Render one animated scene to an mp4 segment. Returns True on success."""
    from PIL import ImageDraw

    from core.media.video import _ffmpeg_exe

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    style = style or Style()
    w, h = res
    frames = max(2, int(max(0.8, duration) * fps))
    renderer = _RENDERERS.get(kind)

    try:
        bg = _background(res, style)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            for i in range(frames):
                p = i / max(1, frames - 1)
                frame = bg.copy()
                if renderer:
                    renderer(frame, text, style, res, p)
                else:
                    _draw_ambient(frame, text, style, res, p, seed=seed)
                if brand:
                    ImageDraw.Draw(frame).text((30, h - 46), brand,
                                               font=_font(max(16, w // 60)),
                                               fill=style.muted)
                frame.save(tdp / f"f{i:05d}.jpg", "JPEG", quality=_frame_quality(), subsampling=0)
            cmd = [ffmpeg, "-y", "-framerate", str(fps), "-i", str(tdp / "f%05d.jpg"),
                   "-r", str(fps), "-c:v", "libx264", "-preset", _enc_preset(),
                   "-crf", str(_enc_crf()), "-pix_fmt", "yuv420p", str(out_path)]
            subprocess.run(cmd, check=True, capture_output=True)
        return out_path.exists()
    except Exception as exc:
        log.warning("Animated segment (%s) failed: %s", kind, str(exc)[:160])
        return False
