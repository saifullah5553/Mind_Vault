"""Scene types chosen from what each line of the script says.

The director's rules (see agents/video_agent and core/media/images.py):

- An OBJECT the line names (a pot, a coin, a sword), when the line's picture
  shows it, becomes a museum SHOWCASE: the photo on a dark display under a
  spotlight, with a label.
- A DOCUMENT (a book, a law, a treaty, an inscription) gets the same treatment
  with warm desk light: the DOCUMENT showcase.
- Digging, excavation, buried finds and dating become animated soil LAYERS: a
  cross-section built up layer by layer, with the date glowing at its layer.
- The first photo of a named person or place gets a name caption (lower third).

Maps, routes, dates, timelines, figures and quotes are drawn by maps.py and
animation.py. Everything here is drawn with Pillow and numpy, at no cost, from
real licensed photos; labels use only the script's own words.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.scenes")

# Objects a museum would show. Not "ship" (a model or a cruise liner, rarely the
# real thing), "stone" (too vague) or "mask" (read as the pandemic on screen).
OBJECTS = ("pot", "pots", "pottery", "potsherd", "sherd", "vase", "jar", "urn", "bowl", "cup",
           "goblet", "amphora", "coin", "coins", "sword", "swords", "axe", "axes", "helmet",
           "helmets", "shield", "shields", "spear", "dagger", "arrowhead", "bead", "beads",
           "jewel", "jewels", "jewellery", "jewelry", "necklace", "bracelet", "brooch", "ring",
           "rings", "crown", "figurine", "statuette", "seal", "seals", "dice", "toy", "toys",
           "lamp", "tool", "tools", "plough", "loom", "comb", "cloak", "pillar", "pillars",
           "tile", "tiles", "brick", "bricks", "carving", "carvings", "drinking horn", "chess")
DOCUMENTS = ("book", "books", "manuscript", "manuscripts", "letter", "letters", "treaty",
             "charter", "decree", "edict", "inscription", "inscriptions", "tablet", "tablets",
             "scroll", "scrolls", "map", "newspaper", "report", "chronicle", "saga", "sagas",
             "codex", "constitution", "declaration", "proclamation", "petition", "ledger")
_OBJ_RE = re.compile(r"\b(" + "|".join(sorted(OBJECTS, key=len, reverse=True)) + r")(?:e?s)?\b",
                     re.I)
_DOC_RE = re.compile(r"\b(" + "|".join(sorted(DOCUMENTS, key=len, reverse=True)) + r")(?:e?s)?\b",
                     re.I)
_DIG_RE = re.compile(r"\b(?:excavat\w*|archaeolog\w*|unearth\w*|dug up|digging|buried|"
                     r"carbon[- ]dat\w*|radiocarbon|strata|stratum|layers? of (?:soil|earth|ash|"
                     r"rock|clay)|beneath the (?:soil|ground|earth|sand|floor))\b", re.I)
_DATE_RE = re.compile(
    r"\b(?:(?:around|about|c\.|circa)\s+)?(\d{1,3}(?:,\d{3})+|\d{3,4})\s*(BCE|BC|CE|AD)?\b"
    r"(?!\s*(?:years?|people|men|women|km|kilometres|miles|metres|meters|feet|ships|farms|"
    r"soldiers|dead|times))"
    r"|\b(\w+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    r"eighteenth|nineteenth|twentieth)\s+century(\s+(?:BCE|BC|CE|AD))?", re.I)
_LEAD = {"single", "only", "small", "large", "huge", "great", "few", "new", "same", "other",
         "whole", "first", "last", "famous", "the", "a", "an", "his", "her", "their", "its", "of", "and", "with", "this", "that",
         "these", "those", "some", "many", "two", "three", "one", "old", "own", "our", "my",
         "your", "every", "each", "all", "no", "any", "in", "on", "at", "to", "from", "into"}


def date_in(text: str) -> str:
    """The first year or century a line names, as a label ('580 BCE', '13TH CENTURY')."""
    m = _DATE_RE.search(text or "")
    if not m:
        return ""
    if m.group(1):
        year = m.group(1)
        if m.group(2) is None and len(year.replace(",", "")) == 3 and not re.search(
                r"(?:in|around|about|c\.|circa|year)\s+" + re.escape(year), text, re.I):
            return ""                     # "200 people" is not a date
        return f"{year} {m.group(2).upper()}".strip() if m.group(2) else year
    return f"{m.group(3)} century{m.group(4) or ''}".upper()


def _phrase(text: str, word: str) -> str:
    """The object with up to two words before it: 'carved pillars', 'fur cloak'."""
    words = re.findall(r"[\w'-]+", text)
    low = [w.lower() for w in words]
    target = word.lower().split()[0]
    # "brooches" is the plural of the listed "brooch": find the word as it is said.
    at = [k for k, w in enumerate(low) if w == target or (w.startswith(target) and len(w) - len(target) <= 2)]
    if not at:
        return word.upper()
    i = at[0]
    j = i
    while j > 0 and i - j < 2 and low[j - 1] not in _LEAD and not low[j - 1].isdigit():
        j -= 1
    return " ".join(words[j:i + len(word.split())]).upper()


def showcase_for(line: str, picture: dict) -> dict | None:
    """A showcase spec when the line names an object or document AND its picture
    shows it (the same word in the picture's title or description), else None."""
    from core.media.stock import match_words
    shows = match_words(f"{picture.get('title', '')} {picture.get('about', '')} "
                        f"{picture.get('label', '')}")
    for regex, kind in ((_DOC_RE, "document"), (_OBJ_RE, "object")):
        for m in regex.finditer(line or ""):
            if match_words(m.group(1)) & shows:
                label = _proper_name(line, shows) or _phrase(line, m.group(1))
                return {"style": kind, "label": label, "sub": date_in(line)}
    return None


def _proper_name(line: str, shows: set[str]) -> str:
    """A capitalised name in the line that the picture also carries ('Codex Regius')."""
    from core.media.stock import match_words
    for sentence in re.split(r"(?<=[.!?])\s+", line or ""):
        for m in re.finditer(r"(?<!^)(?<![.!?]\s)\b([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,3})",
                             sentence):
            if m.start() == 0:
                continue
            name = m.group(1)
            if len(name) > 3 and match_words(name) and match_words(name) <= (shows | {""}):
                return name.upper()
    return ""


def layers_for(line: str) -> dict | None:
    """Animated soil layers for a line about digging, finds or dating."""
    if not _DIG_RE.search(line or ""):
        return None
    m = _DIG_RE.search(line)
    head = "EXCAVATION" if re.match(r"excavat|unearth|dug|digging|archaeolog", m.group(0), re.I) \
        else "BENEATH THE SURFACE" if re.match(r"beneath|buried", m.group(0), re.I) else "DATING THE LAYERS"
    return {"label": date_in(line) or head, "sub": head if date_in(line) else ""}


# ── drawing ──────────────────────────────────────────────────────────────────
def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


@lru_cache(maxsize=4)
def _stage(res: tuple, warm: bool):
    """The dark display: a falloff from a spotlight above, and a lit plinth."""
    import numpy as np
    from PIL import Image
    w, h = res
    y, x = np.mgrid[0:h, 0:w].astype("float32")
    # Spotlight: an ellipse of light centred a little above the middle.
    d = np.sqrt(((x - w / 2) / (w * 0.42)) ** 2 + ((y - h * 0.42) / (h * 0.62)) ** 2)
    light = np.clip(1.15 - d, 0, 1) ** 1.6
    base = np.array([16, 13, 11] if warm else [10, 12, 17], "float32")
    lit = np.array([92, 72, 50] if warm else [58, 62, 74], "float32")
    img = base + light[..., None] * (lit - base)
    # Plinth: a lighter band low in the frame, brightest at its top edge.
    top = int(h * 0.80)
    band = np.zeros((h, 1), "float32")
    band[top:] = np.linspace(1.0, 0.35, h - top)[:, None]
    img = img + band[..., None] * (np.array([38, 32, 26] if warm else [30, 32, 38], "float32"))
    # Fine noise keeps the gradients from banding.
    rng = np.random.default_rng(7)
    img += rng.normal(0, 1.4, img.shape[:2])[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "RGB")


@lru_cache(maxsize=8)
def _exhibit(path: str, box: tuple):
    """The photo fitted into the display box, with its soft shadow."""
    from PIL import Image, ImageFilter
    src = Image.open(path).convert("RGB")
    bw, bh = box
    r = min(bw / src.width, bh / src.height)
    photo = src.resize((max(2, int(src.width * r)), max(2, int(src.height * r))), Image.LANCZOS)
    pad = int(max(photo.size) * 0.12)
    shadow = Image.new("L", (photo.width + 2 * pad, photo.height + 2 * pad), 0)
    shadow.paste(170, (pad, pad + pad // 3, pad + photo.width, pad + photo.height + pad // 3))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad / 2.5))
    return photo, shadow, pad


def draw_showcase(img, spec: dict, style, res, p: float) -> None:
    """A real photo of an object or a document on a lit museum display."""
    from PIL import Image, ImageDraw

    from core.media.animation import _font
    w, h = res
    warm = spec.get("style") == "document"
    img.paste(_stage((w, h), warm))
    photo, shadow, pad = _exhibit(spec["photo"], (int(w * 0.56), int(h * 0.64)))
    # A slow push-in and a gentle float, so the still feels filmed.
    z = 1.0 + 0.06 * _ease(p)
    pw, ph = int(photo.width * z), int(photo.height * z)
    ph_img = photo.resize((pw, ph), Image.BICUBIC) if z != 1.0 else photo
    cx = w * 0.56
    cy = h * 0.45 + math.sin(p * math.pi) * h * 0.006
    x0, y0 = int(cx - pw / 2), int(cy - ph / 2)
    sh = shadow.resize((int(shadow.width * z), int(shadow.height * z)))
    img.paste((0, 0, 0), (x0 - int(pad * z), y0 - int(pad * z)), sh)
    img.paste(ph_img, (x0, y0))
    d = ImageDraw.Draw(img)
    d.rectangle([x0 - 1, y0 - 1, x0 + pw, y0 + ph], outline=(214, 196, 160) if warm else
                (190, 196, 210), width=max(1, w // 1280))
    # A light sweep crosses the exhibit once.
    t = (p - 0.18) / 0.5
    if 0 < t < 1:
        band = Image.new("L", (pw, ph), 0)
        bd = ImageDraw.Draw(band)
        bx = -pw * 0.4 + t * pw * 1.8
        bd.polygon([(bx, 0), (bx + pw * 0.16, 0), (bx - ph * 0.35 + pw * 0.16, ph),
                    (bx - ph * 0.35, ph)], fill=int(46 * math.sin(t * math.pi)))
        img.paste((255, 244, 220) if warm else (235, 240, 255), (x0, y0), band)
    # The museum label, left of the exhibit.
    a = _ease((p - 0.22) / 0.2)
    if a > 0 and spec.get("label"):
        tf, sf = _font(int(h * 0.046), True), _font(int(h * 0.03), True)
        lx, ly = int(w * 0.06), int(h * 0.62)
        accent = style.palette[3] if warm else style.accent
        bar = tuple(int(c * a + 12 * (1 - a)) for c in accent)
        d.rectangle([lx, ly, lx + int(w * 0.035 * a), ly + max(3, h // 240)], fill=bar)
        ink = tuple(int(c * a + 14 * (1 - a)) for c in style.ink)
        words, lines, cur = spec["label"].split(), [], ""
        for wd in words:                       # wrap within the left margin
            test = f"{cur} {wd}".strip()
            if d.textlength(test, font=tf) > w * 0.21 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = test
        lines.append(cur)
        yy = ly + int(h * 0.022)
        for ln in lines[:3]:
            d.text((lx, yy), ln, font=tf, fill=ink)
            yy += int(h * 0.056)
        if spec.get("sub"):
            muted = tuple(int(c * a + 14 * (1 - a)) for c in style.muted)
            d.text((lx, yy + int(h * 0.006)), spec["sub"], font=sf, fill=muted)


@lru_cache(maxsize=2)
def _strata(res: tuple):
    """Six textured layers of earth, ash and clay with wavy boundaries, drawn once:
    for each layer its pixel mask and its finished colours (the frames only blend)."""
    import numpy as np
    w, h = res
    rng = np.random.default_rng(11)
    colours = [(92, 64, 40), (124, 92, 58), (70, 58, 50), (150, 118, 76), (104, 74, 48),
               (60, 46, 36)]
    n = len(colours)
    top, bottom = int(h * 0.30), h
    span = (bottom - top) / n
    x = np.arange(w, dtype="float32")
    edges = [top + k * span for k in range(n)] + [bottom]
    waves = [np.zeros(w, "float32")] + [
        (math.sin(k) * 8 + np.sin(x / (w / (2 + k)) + k) * span * 0.12
         + np.sin(x / (w / 9.0) + 2 * k) * span * 0.04).astype("float32") for k in range(1, n)] \
        + [np.zeros(w, "float32")]
    tex = rng.normal(0, 1, (h // 4 + 1, w // 4 + 1)).astype("float32")
    tex = np.kron(tex, np.ones((4, 4), "float32"))[:h, :w]
    grain = rng.normal(0, 1, (h, w)).astype("float32")
    y = np.arange(h, dtype="float32")[:, None]
    layers = []
    for k in range(n):
        tp = edges[k] + waves[k][None, :]
        bt = edges[k + 1] + waves[k + 1][None, :]
        mask = (y >= tp) & (y < bt)
        depth = np.clip((y - tp) / np.maximum(1, bt - tp), 0, 1)
        shade = (np.array(colours[k], "float32") + tex[..., None] * 7 + grain[..., None] * 5) \
            * np.sqrt(0.82 + 0.18 * depth)[..., None]
        idx = np.nonzero(mask)
        layers.append((idx, np.clip(shade[idx], 0, 255).astype("float32")))
    return edges, waves, layers


def draw_layers(img, spec: dict, style, res, p: float) -> None:
    """A cross-section of the ground: layers rise into place from the deepest,
    then the date glows at the layer it belongs to."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    from core.media.animation import _font
    w, h = res
    edges, waves, layers = _strata((w, h))
    n = len(layers)
    frame = np.asarray(img.convert("RGB")).copy()
    for k in range(n - 1, -1, -1):           # deepest first
        reveal = _ease((p - (n - 1 - k) * 0.07) / 0.18)
        if reveal <= 0:
            continue
        idx, shade = layers[k]
        if reveal >= 1:
            frame[idx] = shade.astype("uint8")
        else:
            frame[idx] = (frame[idx] * (1 - reveal) + shade * reveal).astype("uint8")
    out = Image.fromarray(frame, "RGB")
    d = ImageDraw.Draw(out)
    # A turf line on the surface once the top layer is in.
    ta = _ease((p - (n - 1) * 0.07) / 0.18)
    if ta > 0:
        pts = [(x, edges[0] + waves[0][x]) for x in range(0, w, max(4, w // 320))] + [(w, edges[0])]
        d.line(pts, fill=tuple(int(c * ta) for c in (58, 84, 44)), width=max(4, h // 90))
    # Depth ruler on the left.
    rx = int(w * 0.07)
    ra = _ease(p / 0.3)
    if ra > 0:
        col = tuple(int(c * ra + 20 * (1 - ra)) for c in style.muted)
        d.line([(rx, edges[0]), (rx, h - h * 0.04)], fill=col, width=max(2, w // 900))
        for k in range(n):
            yy = edges[k]
            d.line([(rx - w * 0.008, yy), (rx + w * 0.008, yy)], fill=col, width=max(2, w // 900))
    # The find: a glowing marker in the fourth layer, with its date.
    ga = _ease((p - 0.55) / 0.2)
    if ga > 0:
        gx, gy = int(w * 0.58), int((edges[3] + edges[4]) / 2 + waves[3][int(w * 0.58)] * 0.5)
        r = int(h * 0.05)
        # The glow is drawn on a small patch, not the whole frame.
        size = 4 * r
        glow = Image.new("L", (size, size), 0)
        ImageDraw.Draw(glow).ellipse([r, r, 3 * r, 3 * r], fill=int(200 * ga))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.8))
        out.paste(style.palette[3], (gx - 2 * r, gy - 2 * r), glow)
        rr = max(6, h // 110)
        d.ellipse([gx - rr, gy - rr, gx + rr, gy + rr], fill=(255, 236, 190))
        tf = _font(int(h * 0.075), True)
        label = spec.get("label", "")
        tw = d.textlength(label, font=tf)
        lx = min(w - tw - w * 0.05, gx + w * 0.04)
        d.line([(gx + rr, gy), (lx - w * 0.01, gy - h * 0.12 + h * 0.03)],
               fill=style.ink, width=max(2, w // 900))
        ink = tuple(int(c * ga + 30 * (1 - ga)) for c in style.ink)
        d.text((lx, gy - h * 0.12 - h * 0.02), label, font=tf, fill=ink,
               stroke_width=max(2, w // 900), stroke_fill=(20, 16, 12))
    if spec.get("sub"):
        sa = _ease((p - 0.1) / 0.2)
        if sa > 0:
            sf = _font(int(h * 0.04), True)
            d.text((int(w * 0.06), int(h * 0.1)), spec["sub"], font=sf,
                   fill=tuple(int(c * sa + 14 * (1 - sa)) for c in style.ink))
    img.paste(out)


def draw_tag(frame, text: str, res) -> None:
    """A small corner tag ('ILLUSTRATION') on an AI picture, for the whole shot."""
    from PIL import ImageDraw

    from core.media.animation import _font
    w, h = res
    f = _font(max(14, int(h * 0.022)), True)
    d = ImageDraw.Draw(frame)
    tw = d.textlength(text, font=f)
    x, y = int(w - tw - w * 0.035), int(h * 0.04)
    pad = int(h * 0.008)
    d.rectangle([x - 2 * pad, y - pad, x + tw + 2 * pad, y + int(h * 0.022) + 2 * pad],
                fill=(12, 14, 20))
    d.text((x, y), text, font=f, fill=(225, 228, 236))


def draw_lower_third(frame, label: str, sub: str, res, t: float, dur: float) -> None:
    """A name caption over a photo: fades in after half a second, out before the cut."""
    from PIL import Image, ImageDraw

    from core.media.animation import Style, _font
    a = min(_ease((t - 0.5) / 0.4), _ease((dur - 0.35 - t) / 0.4))
    if a <= 0 or not label:
        return
    w, h = res
    st = Style()
    tf, sf = _font(int(h * 0.05), True), _font(int(h * 0.03), True)
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    x, y = int(w * 0.06), int(h * 0.78)
    tw = d.textlength(label, font=tf)
    sw = d.textlength(sub, font=sf) if sub else 0
    box_w = int(max(tw, sw) + w * 0.03)
    box_h = int(h * (0.1 if sub else 0.075))
    d.rectangle([x, y, x + box_w, y + box_h], fill=(10, 12, 18, int(170 * a)))
    d.rectangle([x, y, x + max(3, w // 400), y + box_h], fill=(*st.accent, int(255 * a)))
    d.text((x + w * 0.015, y + h * 0.012), label, font=tf, fill=(*st.ink, int(255 * a)))
    if sub:
        d.text((x + w * 0.015, y + h * 0.065), sub, font=sf, fill=(*st.muted, int(255 * a)))
    frame.paste(over, (0, 0), over)


TITLE_IN = 1.0          # the cold open's title fades in here (and the low hit lands)


def film_title(title: str, thumbnail: str = "") -> str:
    """The words for the cold open's title: the title's subject before a colon
    ('Meiji Restoration: How Japan…' -> 'MEIJI RESTORATION'), else the thumbnail
    text, else the title itself, cut to a few words."""
    head = (title or "").split(":", 1)[0].strip()
    if ":" in (title or "") and 1 <= len(head.split()) <= 5:
        return head.upper()
    if thumbnail and len(thumbnail.split()) <= 5:
        return thumbnail.strip().upper()
    return " ".join((title or "").split()[:5]).upper()


def draw_film_title(frame, text: str, res, t: float, dur: float) -> None:
    """The cold open's title over the first shot: spaced capitals with a thin rule,
    fading in after a second and out before the cut, like a film's main title."""
    from PIL import Image, ImageDraw

    from core.media.animation import Style, _font
    end = min(dur - 0.6, TITLE_IN + 5.0)
    a = min(_ease((t - TITLE_IN) / 0.9), _ease((end - t) / 0.8))
    if a <= 0 or not text:
        return
    w, h = res
    st = Style()
    spaced = " ".join(text)                               # letter-spaced, like a title card
    size = int(h * 0.085)
    font = _font(size, True)
    probe = ImageDraw.Draw(frame)
    while probe.textlength(spaced, font=font) > w * 0.86 and size > 20:
        size = int(size * 0.92)
        font = _font(size, True)
    tw = probe.textlength(spaced, font=font)
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    band = int(size * 4.2)
    y = int(h * 0.5 - size * 0.7)
    # A soft shadow band, feathered top and bottom (not a hard grey bar).
    import math
    top = int(y + size * 0.55 - band / 2)
    col = Image.new("L", (1, band))
    for r in range(band):
        col.putpixel((0, r), int(165 * a * math.sin(math.pi * r / max(1, band - 1)) ** 1.2))
    shade = Image.new("RGBA", (w, band), (0, 0, 0, 255))
    shade.putalpha(col.resize((w, band)))
    over.paste(shade, (0, max(0, top)), shade)
    rise = (1 - a) * h * 0.012
    d.text(((w - tw) / 2 + 2, y + rise + 2), spaced, font=font, fill=(0, 0, 0, int(160 * a)))
    d.text(((w - tw) / 2, y + rise), spaced, font=font, fill=(*st.ink, int(255 * a)))
    rw = int(w * 0.12 * a)
    ry = int(y + size * 1.35 + rise)
    d.rectangle([(w - rw) // 2, ry, (w + rw) // 2, ry + max(2, h // 360)],
                fill=(*st.accent, int(255 * a)))
    frame.paste(over, (0, 0), over)


def describe(kind: str) -> str:
    """For the shot list: 'SHOWCASE carved pillars', 'LAYERS 580 BCE'."""
    import json
    for prefix in ("showcase:", "layers:"):
        if kind.startswith(prefix):
            spec = json.loads(kind[len(prefix):])
            return f"{prefix[:-1].upper()} {spec.get('label', '')} {spec.get('sub', '')}".strip() + \
                (f" ({Path(spec['photo']).name})" if spec.get("photo") else "")
    return ""
