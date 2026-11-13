"""The camera: how a still is filmed, the way a documentary director would shoot it.

A still used to be centre-cropped to 16:9 and drifted in one of four fixed ways,
chosen by its position in the list. Here the shot is planned from the picture:

- where the interest is (spectral-residual saliency, Hou & Zhang 2007: numpy only),
  so a push-in ends on the face or the ship, not on the middle of the frame;
- its shape: a wide scroll is panned across, a tall portrait is shown whole over a
  blurred fill (no cut-off heads), anything in between is framed inside the picture;
- coverage: a long shot is cut into a wide and then a close-up on the detail, when
  the picture has the pixels for a sharp close-up;
- moves vary from shot to shot (push in, pull out, drift toward the subject), never
  the same move twice in a row, at documentary speed with soft starts and stops.

Boxes are (x0, y0, x1, y1) in source pixels; every frame is the box resampled to the
output size, so movement is sub-pixel smooth.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ASPECT = 16 / 9
# A close-up needs this many source pixels across (vs the output width) to stay sharp.
CLOSEUP_SHARPNESS = 0.5     # 1280 px across for a 2560 frame: sharp at 1080p viewing
COVERAGE_MIN_SECONDS = 6.0     # shorter shots stay one shot


@dataclass
class Shot:
    frames: int
    start: tuple[float, float, float, float]
    end: tuple[float, float, float, float]
    kind: str                   # "wide", "closeup", "pan", "tilt", "portrait"


# ── where to look ────────────────────────────────────────────────────────────
def interest(img) -> tuple[float, float]:
    """The picture's centre of interest as fractions (0..1) of width and height.

    Spectral residual saliency on a small greyscale copy, weighted toward the
    middle (edges hold frames, borders and museum labels), and for a tall picture
    toward its upper third, where faces are."""
    from PIL import Image
    from scipy.ndimage import gaussian_filter, uniform_filter

    g = img.convert("L")
    scale = 96 / max(g.size)
    g = g.resize((max(8, round(g.width * scale)), max(8, round(g.height * scale))), Image.BILINEAR)
    a = np.asarray(g, dtype=np.float64) / 255.0
    f = np.fft.fft2(a)
    log_amp = np.log(np.abs(f) + 1e-9)
    residual = log_amp - uniform_filter(log_amp, size=3, mode="nearest")
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(f)))) ** 2
    sal = gaussian_filter(sal, sigma=max(1.0, min(a.shape) / 24))
    h, w = sal.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cy = 0.38 if img.height > img.width * 1.05 else 0.5
    prior = np.exp(-(((xs / w - 0.5) / 0.32) ** 2 + ((ys / h - cy) / 0.32) ** 2) / 2)
    sal = sal * prior
    cut = np.quantile(sal, 0.95)
    m = np.where(sal >= cut, sal, 0.0)
    total = m.sum()
    if total <= 0:
        return 0.5, cy
    fx = float((m * xs).sum() / total / max(1, w - 1))
    fy = float((m * ys).sum() / total / max(1, h - 1))
    return min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)


def trim(img, tolerance: float = 10.0, limit: float = 0.12):
    """Cut a scan's plain margins (black frames, white paper edges) so the camera
    films the picture, not its border. At most `limit` of each side is removed."""
    a = np.asarray(img.convert("L").resize((max(8, img.width // 4), max(8, img.height // 4))),
                   dtype=np.float64)
    h, w = a.shape

    def edge(lines, n):
        k = 0
        for line in lines:
            if line.std() > tolerance or k >= n * limit:
                break
            k += 1
        return k

    top = edge(a, h)
    bottom = edge(a[::-1], h)
    left = edge(a.T, w)
    right = edge(a.T[::-1], w)
    if not (top or bottom or left or right):
        return img
    sx, sy = img.width / w, img.height / h
    box = (round(left * sx), round(top * sy), img.width - round(right * sx), img.height - round(bottom * sy))
    return img.crop(box) if box[2] - box[0] > img.width * 0.5 and box[3] - box[1] > img.height * 0.5 else img


# ── framing ──────────────────────────────────────────────────────────────────
def _box(cx: float, cy: float, bw: float, sw: int, sh: int) -> tuple[float, float, float, float]:
    """A 16:9 box of width bw centred on (cx, cy) px, slid inside the picture."""
    bw = min(bw, sw, sh * ASPECT)
    bh = bw / ASPECT
    x0 = min(max(cx - bw / 2, 0.0), sw - bw)
    y0 = min(max(cy - bh / 2, 0.0), sh - bh)
    return (x0, y0, x0 + bw, y0 + bh)


def plan(size: tuple[int, int], focus: tuple[float, float], seconds: float, fps: int,
         out_width: int, index: int) -> list[Shot]:
    """The shots for one still: one or two, filling `seconds` exactly."""
    sw, sh = size
    total = max(2, round(seconds * fps))
    fx, fy = focus[0] * sw, focus[1] * sh
    aspect = sw / sh
    if aspect > 2.1:                                   # a scroll or panorama: pan across it
        bw = sh * ASPECT
        left, right = _box(bw / 2, sh / 2, bw, sw, sh), _box(sw - bw / 2, sh / 2, bw, sw, sh)
        # End on the side the interest is on.
        start, end = (left, right) if fx >= sw / 2 else (right, left)
        return [Shot(total, start, end, "pan")]
    if aspect < 0.95:                                  # a tall portrait: whole, slow push
        return [Shot(total, (0, 0, 1, 1), (0.04, 0.03, 0.96, 0.91), "portrait")]
    if aspect < 1.3:                                   # squarish: tilt toward the interest
        bw = sw
        top, bottom = _box(sw / 2, 0, bw, sw, sh), _box(sw / 2, sh, bw, sw, sh)
        start, end = (top, bottom) if fy > sh / 2 else (bottom, top)
        return [Shot(total, start, end, "tilt")]

    full = min(sw, sh * ASPECT)
    wide_tight = full / 1.12                           # a push of 12%
    move = ("in", "out", "drift")[index % 3]
    wide_start = _box(sw / 2, sh / 2, full, sw, sh)
    wide_end = _box(fx, fy, wide_tight, sw, sh)
    if move == "out":
        wide_start, wide_end = wide_end, wide_start
    elif move == "drift":                              # a lateral move that ends on the subject
        wide_start = _box(sw - fx, fy, wide_tight, sw, sh)

    close_w = full / 1.8
    sharp = close_w >= CLOSEUP_SHARPNESS * out_width
    if seconds >= COVERAGE_MIN_SECONDS and sharp:
        n_wide = round(total * 0.55)
        n_close = total - n_wide
        close_start = _box(fx, fy, close_w, sw, sh)
        close_end = _box(fx, fy, close_w / 1.06, sw, sh)
        return [Shot(n_wide, wide_start, wide_end, "wide"),
                Shot(n_close, close_start, close_end, "closeup")]
    return [Shot(total, wide_start, wide_end, "wide")]


def ease(t: float) -> float:
    """Half linear, half smoothstep: the move never stops dead or lurches."""
    t = min(max(t, 0.0), 1.0)
    return 0.5 * t + 0.5 * t * t * (3 - 2 * t)


def boxes(shot: Shot):
    """The box for each frame of a shot."""
    n = shot.frames
    for f in range(n):
        t = ease(f / max(1, n - 1))
        yield tuple(a + (b - a) * t for a, b in zip(shot.start, shot.end))


# ── drawing ──────────────────────────────────────────────────────────────────
def portrait_frame(src, box_frac, res):
    """A tall picture shown whole over a blurred, darkened fill of itself; box_frac
    zooms the composition slightly (0..1 fractions of the fill)."""
    from PIL import Image, ImageEnhance, ImageFilter
    res = (int(res[0]), int(res[1]))
    w, h = res
    cache = portrait_frame.__dict__.setdefault("_cache", {})
    key = (id(src), res)
    if key not in cache:
        cache.clear()
        r = max(w / src.width, h / src.height)
        bg = src.resize((round(src.width * r) + 2, round(src.height * r) + 2), Image.BILINEAR)
        bg = bg.crop(((bg.width - w) // 2, (bg.height - h) // 2, (bg.width - w) // 2 + w,
                      (bg.height - h) // 2 + h))
        bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(w / 45))).enhance(0.45)
        s = min(w * 0.92 / src.width, h * 0.92 / src.height)
        fg = src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS)
        bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
        cache[key] = bg
    full = cache[key]
    x0, y0, x1, y1 = box_frac
    return full.transform((w, h), Image.EXTENT, (x0 * w, y0 * h, x1 * w, y1 * h), Image.BICUBIC)


def frames(src, seconds: float, fps: int, res, index: int):
    """Every output frame for a still, as (PIL image, shot kind)."""
    from PIL import Image
    res = (int(res[0]), int(res[1]))
    shots = plan(src.size, interest(src), seconds, fps, res[0], index)
    for shot in shots:
        for box in boxes(shot):
            if shot.kind == "portrait":
                yield portrait_frame(src, box, res), shot.kind
            else:
                yield src.transform(res, Image.EXTENT, box, Image.BICUBIC), shot.kind


def describe(src_size, focus, seconds, fps, out_width, index) -> str:
    """For the shot list: 'WIDE push in > CLOSE-UP' etc."""
    shots = plan(src_size, focus, seconds, fps, out_width, index)
    return " > ".join(s.kind.upper() for s in shots)
