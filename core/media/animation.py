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
# "%" must end the match itself: with a trailing \b, "42% of" backed off to "42".
_NUM_RE = re.compile(r"\b(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:%|\b)")
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


def _wrap_to_width(draw, text: str, font, max_w: int, spacing: int) -> str:
    """Greedy word wrap on MEASURED widths (character estimates overflow)."""
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=font) <= max_w:
            lines[-1] = trial
        else:
            lines.append(word)
    return "\n".join(lines)


def _fit_text(draw, text: str, font_factory, max_w: int, start: int, min_size: int = 24,
              max_h: int | None = None, spacing: int = 10):
    """Largest font at which the wrapped text fits max_w AND max_h.

    Height used to be ignored, so long text ran off the bottom of the frame or
    out of its box. If it cannot fit even at min_size, the text is cut at a word
    boundary (no ellipsis) rather than drawn off-screen.
    """
    size = start
    while True:
        f = font_factory(size)
        wrapped = _wrap_to_width(draw, text, f, max_w, spacing)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=f, spacing=spacing)
        fits_w = bbox[2] - bbox[0] <= max_w
        fits_h = max_h is None or bbox[3] - bbox[1] <= max_h
        if (fits_w and fits_h) or size <= min_size:
            break
        size = max(min_size, size - 4)
    if max_h is not None:
        lines = wrapped.split("\n")
        while len(lines) > 1 and draw.multiline_textbbox(
                (0, 0), "\n".join(lines), font=f, spacing=spacing)[3] > max_h:
            lines.pop()
        wrapped = "\n".join(lines)
    return f, wrapped


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
    # A quote card needs an actual quoted PHRASE: a stray quote mark made a
    # "quote" card reading just "In ancient Greece".
    q = re.search(r"[\"“]([^\"”]{6,90})[\"”]", t)
    if q and len(q.group(1).split()) >= 2:
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
                              int(w * 0.84), int(w * 0.09), max_h=int(h * 0.62), spacing=12)
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
    is_year = not suffix and raw.isdigit() and len(raw) == 4 and 1000 <= target <= 2100
    label = re.sub(re.escape(raw), "", scene_text).strip(" ,.;:") or scene_text
    label = re.sub(r"\s+(?:in|on|by|from|since|of)$", "", label, flags=re.I)

    if is_year:
        # A year is a date, not a quantity: no thousands separator, no count-up.
        num, num_alpha = raw, _ease(min(1.0, p * 2.2))
    else:
        shown = target * _ease(min(1.0, p * 1.6))
        num = f"{shown:,.0f}{suffix}" if target >= 10 else f"{shown:,.1f}{suffix}"
        num_alpha = 1.0
    nf = _font(int(h * 0.26), True)
    # Size the final number (not the counting one) so the layout doesn't jump.
    final = raw if is_year else (f"{target:,.0f}{suffix}" if target >= 10
                                 else f"{target:,.1f}{suffix}")
    nb = d.textbbox((0, 0), final, font=nf)
    lf, wrapped = _fit_text(d, label, lambda s: _font(s, False),
                            int(w * 0.8), int(w * 0.04), max_h=int(h * 0.16), spacing=8)
    lb = d.multiline_textbbox((0, 0), wrapped, font=lf, spacing=8)
    gap, bar_gap, bar_h = h * 0.05, h * 0.06, 16
    block = (nb[3] - nb[1]) + gap + (lb[3] - lb[1]) + bar_gap + bar_h
    ny = (h - block) / 2 - nb[1]                   # whole block centred vertically
    cur = d.textbbox((0, 0), num, font=nf)
    _alpha_text(img, ((w - (cur[2] - cur[0])) / 2, ny), num, nf, style.accent, num_alpha)
    below = ny + nb[3] + gap                       # label starts under the number
    _alpha_text(img, ((w - (lb[2] - lb[0])) / 2, below), wrapped, lf,
                style.muted, _ease(min(1.0, p * 2)), spacing=8, align="center")

    bw = int(w * 0.62); bx = (w - bw) // 2; by = int(below + (lb[3] - lb[1]) + bar_gap)
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
        r = max(2, int(h * 0.014 * appear))
        col = style.palette[i % len(style.palette)]
        d.ellipse([px - r, y0 - r, px + r, y0 + r], fill=col)
        f = _font(int(w * 0.045), True)
        tb = d.textbbox((0, 0), str(yr), font=f)
        # Year sits clearly ABOVE its dot (it used to be drawn across the line).
        _alpha_text(img, (px - (tb[2] - tb[0]) / 2, y0 - h * 0.05 - tb[3]), str(yr), f,
                    style.ink, appear)
    # What the dates are about, under the line.
    about = re.sub(_YEAR_RE, "", scene_text)
    about = re.sub(r"\s+", " ", re.sub(r"\b(?:from|to|and|between|in)\s+(?=\W|$)", "",
                                       about, flags=re.I)).strip(" ,.;:-")
    if about:
        lf, wrapped = _fit_text(d, about, lambda s: _font(s, False), int(w * 0.76),
                                int(w * 0.036), max_h=int(h * 0.2), spacing=8)
        lb = d.multiline_textbbox((0, 0), wrapped, font=lf, spacing=8)
        _alpha_text(img, ((w - (lb[2] - lb[0])) / 2, y0 + h * 0.07), wrapped, lf,
                    style.muted, _ease(max(0.0, min(1.0, (p - 0.3) * 2.5))), spacing=8,
                    align="center")


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
        f, wrapped = _fit_text(d, part, lambda s: _font(s, False),
                               int(box_w * 0.88), int(w * 0.04),
                               max_h=int(box_h * 0.78), spacing=6)
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
    body = scene_text.strip().strip('"“”')
    f, wrapped = _fit_text(d, body, lambda s: _font(s, False),
                           int(w * 0.74), int(w * 0.06), max_h=int(h * 0.56))
    lines = wrapped.split("\n")
    lh = d.textbbox((0, 0), "Ag", font=f)[3] + 14
    block = len(lines) * lh
    y = max(h * 0.30, (h - block) / 2 + h * 0.05)      # centred, below the mark
    # The quote mark hangs just above-left of the text block, never on top of it.
    block_left = min((w - (d.textbbox((0, 0), ln, font=f)[2])) / 2 for ln in lines)
    qf = _font(max(48, int(min(h * 0.22, y - h * 0.06))), True)
    qb = d.textbbox((0, 0), "“", font=qf)
    _alpha_text(img, (max(w * 0.06, block_left - (qb[2] - qb[0]) * 0.8),
                      y - (qb[3] - qb[1]) * 0.75 - qb[1]), "“", qf,
                style.accent, _ease(min(1.0, p * 3)))
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
    slot = int(h * 0.70 / len(parts))                  # vertical room per bullet
    text_x, text_w = int(w * 0.18), int(w * 0.70)      # stays inside the frame
    fitted = [_fit_text(d, part, lambda s: _font(s, False), text_w, int(w * 0.045),
                        max_h=int(slot * 0.85), spacing=6) for part in parts]
    # One font size for every bullet so the list reads as a set.
    size = min(fo.size for fo, _ in fitted)
    f = _font(size, False)
    rows = [_fit_text(d, part, lambda s: _font(s, False), text_w, size, min_size=size,
                      max_h=int(slot * 0.85), spacing=6)[1] for part in parts]
    top = (h - len(parts) * slot) // 2
    for i, wrapped in enumerate(rows):
        a = _ease(max(0.0, min(1.0, (p - 0.18 * i) * 2.8)))
        if a <= 0:
            continue
        y = top + i * slot + (1 - a) * 26
        col = style.palette[i % len(style.palette)]
        dot = max(12, size // 3)
        cy = y + size * 0.55
        d.ellipse([w * 0.13 - dot / 2, cy - dot / 2, w * 0.13 + dot / 2, cy + dot / 2], fill=col)
        _alpha_text(img, (text_x, y), wrapped, f, style.ink, a, spacing=6, align="left")


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
                           int(w * 0.8), int(w * 0.065), max_h=int(h * 0.5))
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
    frames = max(2, round(max(0.8, duration) * fps))
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
