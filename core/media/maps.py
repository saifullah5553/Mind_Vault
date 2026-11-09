"""Animated maps: the country a line is about, and a pin on the place it names.

When the narration names a country or a place for the first time ("Rotterdam is
one of the busiest ports in the world"), that scene can become a map: the camera
eases in from a wider view, the country fills with the brand colour, and a pin
drops on the place with its name. Drawn in code (Pillow), so it is free, sharp at
any resolution, and carries no licence risk.

Data: Natural Earth (public domain), country outlines at 1:50m and populated
places at 1:10m, downloaded once into storage/data/naturalearth (release v5.1.2,
Git blob hashes checked). Landmarks and regions it lacks (Kinderdijk, Zeeland)
live in content/data/places.json.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from core.config import ROOT_DIR
from core.logging_setup import get_logger

log = get_logger("media.maps")

DATA_DIR = ROOT_DIR / "storage" / "data" / "naturalearth"
EXTRA = ROOT_DIR / "content" / "data" / "places.json"
_RELEASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"
_FILES = {
    "ne_50m_admin_0_countries.geojson": "9d99f26dc470fcdbd08b062c813005acbdf73ccb",
    "ne_10m_populated_places_simple.geojson": "4da9c6b27b5cd41d7c930ea9cd0c1f84548b65fb",
}
# Country names that are also everyday words or first names.
_AMBIGUOUS = {"Jordan", "Georgia", "Chad", "Guinea", "Niger"}
# City names that are also words or names; a city must be big to count at all.
_CITY_STOP = {"Victoria", "Florence", "Hamilton", "Mobile", "Reading", "Bath", "Nice",
              "Split", "Male", "Sale", "Orange", "Marathon", "Of", "Mary", "Kingston",
              "Santa", "Concord", "Independence", "Liberty", "Union", "Lincoln"}
_MIN_CITY_POP = 100_000
_DEMONYMS = {"Dutch": "Netherlands"}       # used only to pick a country context


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def ensure_data() -> bool:
    """Download the Natural Earth files once; verify them against pinned hashes."""
    import httpx
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, sha in _FILES.items():
        path = DATA_DIR / name
        if path.exists() and _git_blob_sha(path) == sha:
            continue
        try:
            r = httpx.get(_RELEASE + name, timeout=120, follow_redirects=True)
            r.raise_for_status()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(r.content)
            if _git_blob_sha(tmp) != sha:
                tmp.unlink(missing_ok=True)
                log.warning("Map data %s failed its hash check; maps are off.", name)
                return False
            tmp.replace(path)
        except Exception as exc:
            log.warning("Map data download failed (%s); maps are off.", str(exc)[:120])
            return False
    return True


def _rings(geom: dict) -> list[list[tuple[float, float]]]:
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return []
    return [[(float(x), float(y)) for x, y in poly[0]] for poly in polys]   # outer rings


@lru_cache(maxsize=1)
def _countries() -> tuple[dict, ...]:
    data = json.loads((DATA_DIR / "ne_50m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    out = []
    for f in data["features"]:
        p = f["properties"]
        rings = _rings(f["geometry"])
        if not rings:
            continue
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        names = {p.get("NAME"), p.get("NAME_LONG"), p.get("ADMIN")} - {None, ""}
        out.append({"name": p["NAME"], "names": names, "rings": rings,
                    "bbox": (min(xs), min(ys), max(xs), max(ys))})
    return tuple(out)


@lru_cache(maxsize=1)
def _places() -> tuple[dict, ...]:
    out = []
    try:
        extra = json.loads(EXTRA.read_text(encoding="utf-8"))["places"]
        out += [dict(p, pop=10**9, extra=True) for p in extra]     # curated: always wins
    except Exception as exc:
        log.debug("no extra places (%s)", exc)
    data = json.loads((DATA_DIR / "ne_10m_populated_places_simple.geojson")
                      .read_text(encoding="utf-8"))
    for f in data["features"]:
        p = f["properties"]
        capital = "capital" in str(p.get("featurecla", "")).lower()
        if (p.get("pop_max") or 0) < _MIN_CITY_POP and not capital:
            continue
        if p["name"] in _CITY_STOP or len(p["name"]) < 4:
            continue
        out.append({"name": p["name"], "lat": p["latitude"], "lon": p["longitude"],
                    "country": p["adm0name"], "pop": p.get("pop_max") or 0})
    return tuple(out)


def _country(name: str) -> dict | None:
    for c in _countries():
        if name in c["names"]:
            return c
    return None


def _word(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")


@lru_cache(maxsize=1)
def _country_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    pats = []
    for c in _countries():
        for n in c["names"]:
            if n not in _AMBIGUOUS and len(n) >= 4:
                pats.append((_word(n), c["name"]))
    return tuple(pats)


@lru_cache(maxsize=1)
def _place_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    names = sorted({p["name"] for p in _places()}, key=len, reverse=True)
    return tuple((_word(n), n) for n in names)


def countries_in(text: str) -> list[str]:
    found = [c for pat, c in _country_patterns() if pat.search(text or "")]
    found += [c for d, c in _DEMONYMS.items() if _word(d).search(text or "")]
    return found


def places_in(text: str) -> list[str]:
    hits, taken = [], []
    for pat, name in _place_patterns():                    # longest names first
        for m in pat.finditer(text or ""):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                hits.append((m.start(), name))
                taken.append((m.start(), m.end()))
    return [n for _, n in sorted(hits)]


def _resolve(name: str, context: list[str]) -> dict | None:
    """The place called `name`, preferring one in the story's countries."""
    cands = [p for p in _places() if p["name"] == name]
    if not cands:
        return None
    in_story = [p for p in cands if p["country"] in context]
    if not in_story and not any(p.get("extra") for p in cands):
        return None              # "Paris" in a story about Texas: don't guess
    pool = in_story or cands
    return max(pool, key=lambda p: p["pop"])


def plan_maps(narrations: list[str], limit: int = 4, spacing: int = 6) -> dict[int, dict]:
    """Which scenes become maps: the first line naming each place or country.

    At most `limit` maps per video, at least `spacing` scenes apart, never the
    opening scene (the title card). Returns {scene index: map spec}.
    """
    if limit <= 0 or not ensure_data():
        return {}
    counts: dict[str, int] = {}
    for t in narrations:
        for c in countries_in(t):
            counts[c] = counts.get(c, 0) + 1
    context = sorted(counts, key=counts.get, reverse=True)
    if not context:
        return {}
    # Every first mention is a candidate; a pin close to an earlier one
    # (the IJsselmeer is the old Zuiderzee) would show the same map twice.
    shown: set[str] = set()
    pins: list[tuple[float, float]] = []
    cands: list[tuple[int, dict]] = []
    for i, text in enumerate(narrations):
        if i == 0:
            continue
        spec = None
        # The landmark a line is about beats a city it is measured from:
        # "a lake north of Amsterdam called the Beemster" pins the Beemster.
        named = [(_resolve(n, context), pos) for pos, n in enumerate(places_in(text))]
        named = sorted((x for x in named if x[0]), key=lambda x: (not x[0].get("extra"), x[1]))
        for p, _ in named:
            near = any(abs(p["lon"] - a) < 0.35 and abs(p["lat"] - b) < 0.35 for a, b in pins)
            if p["name"] not in shown and not near and _country(p["country"]):
                spec = {"place": p["name"], "lon": round(p["lon"], 4), "lat": round(p["lat"], 4),
                        "country": _country(p["country"])["name"]}
                break
        if spec is None:
            for c in countries_in(text):
                if c not in shown and _country(c):
                    spec = {"place": "", "country": _country(c)["name"]}
                    break
        if spec:
            cands.append((i, spec))
            shown.update({spec["place"], spec["country"]} - {""})
            if spec["place"]:
                pins.append((spec["lon"], spec["lat"]))

    # Spread the maps over the whole story, not the first few minutes.
    plan: dict[int, dict] = {}
    if not cands:
        return plan
    want = min(limit, len(cands))
    picks = sorted({round(j * (len(cands) - 1) / max(1, want - 1)) for j in range(want)})
    last = -spacing
    for j in picks:
        i, spec = cands[j]
        if i - last >= spacing:
            plan[i] = spec
            last = i
    return plan


# ── drawing ──────────────────────────────────────────────────────────────────
def _view(country: dict, res) -> tuple[float, float, float, float]:
    """(centre lon, centre lat, cos(lat), half-width in projected degrees)."""
    x0, y0, x1, y1 = country["bbox"]
    # Overseas parts (Caribbean islands of the Netherlands) would shrink the
    # homeland to a dot: frame the largest ring only.
    big = max(country["rings"], key=lambda r: abs(_area(r)))
    xs, ys = [x for x, _ in big], [y for _, y in big]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    k = math.cos(math.radians(cy))
    w, h = res
    half_w = max((x1 - x0) * k / 2, (y1 - y0) / 2 * w / h) * 1.35
    return cx, cy, k, max(half_w, 0.6)


def _area(ring) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1])) / 2


def draw(img, spec: dict, style, res, p: float) -> None:
    """One frame at progress p (0..1)."""
    import numpy as np
    from PIL import ImageDraw

    from core.media.animation import _ease, _font

    w, h = res
    focus = _country(spec["country"])
    if focus is None:
        return
    cx, cy, k, half = _view(focus, res)
    zoom = _ease(min(1.0, p / 0.45))
    half_now = half * (3.0 - 2.0 * zoom)                # from 3x wider to the country
    scale = (w / 2) / half_now                          # pixels per projected degree

    def to_px(pts) -> list[tuple[float, float]]:
        a = np.asarray(pts, dtype="float64")
        xs = (a[:, 0] - cx) * k * scale + w / 2
        ys = h / 2 - (a[:, 1] - cy) * scale
        return list(zip(xs.tolist(), ys.tolist()))

    d = ImageDraw.Draw(img)
    # Graticule: faint lines every degree (every 5 when zoomed out far).
    step = 1 if half_now < 8 else 5
    grid = tuple(min(255, c + 10) for c in style.bg_top)
    lon_span = half_now / k + step
    for g in range(int(math.floor(cx - lon_span)), int(math.ceil(cx + lon_span)) + 1):
        if g % step == 0:
            x = (g - cx) * k * scale + w / 2
            d.line([(x, 0), (x, h)], fill=grid, width=1)
    lat_span = half_now * h / w + step
    for g in range(int(math.floor(cy - lat_span)), int(math.ceil(cy + lat_span)) + 1):
        if g % step == 0:
            y = h / 2 - (g - cy) * scale
            d.line([(0, y), (w, y)], fill=grid, width=1)

    land, border = (44, 51, 72), (86, 96, 126)
    a = _ease(max(0.0, min(1.0, (p - 0.15) / 0.35)))
    fill = tuple(int(land[i] * (1 - 0.6 * a) + style.accent[i] * 0.6 * a) for i in range(3))
    lon_lim = half_now / k * 1.2
    lat_lim = half_now * h / w * 1.2
    for c in _countries():
        bx0, by0, bx1, by1 = c["bbox"]
        if bx1 < cx - lon_lim or bx0 > cx + lon_lim or by1 < cy - lat_lim or by0 > cy + lat_lim:
            continue
        mine = c is focus
        for ring in c["rings"]:
            if len(ring) < 3:
                continue
            px = to_px(ring)
            d.polygon(px, fill=fill if mine else land,
                      outline=style.accent if mine and a > 0.5 else border,
                      width=max(2, w // 900) if mine else max(1, w // 1400))

    # Pin with pulsing rings.
    if spec.get("place"):
        t = _ease(max(0.0, min(1.0, (p - 0.45) / 0.15)))
        if t > 0:
            (px, py), = to_px([(spec["lon"], spec["lat"])])
            r = max(10, w // 110)
            pin = style.palette[1]
            for n in range(2):
                q = ((p - 0.6) * 2.2 - n * 0.5) % 1.0 if p > 0.6 else 0.0
                rr = r * (1.4 + 3.2 * q)
                if p > 0.6:
                    d.ellipse([px - rr, py - rr, px + rr, py + rr],
                              outline=tuple(int(c * (1 - q) + style.bg_top[i] * q)
                                            for i, c in enumerate(pin)), width=max(2, w // 700))
            rr = r * t
            d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=pin, outline=style.ink,
                      width=max(2, w // 900))

    # Label: the place, big; its country underneath.
    la = _ease(max(0.0, min(1.0, (p - 0.5) / 0.2)))
    if la > 0:
        title = (spec.get("place") or spec["country"]).upper()
        sub = spec["country"].upper() if spec.get("place") else ""
        tf, sf = _font(int(h * 0.075), True), _font(int(h * 0.034), True)
        x, y = int(w * 0.06), int(h * 0.08) + int((1 - la) * 20)
        ink = tuple(int(c * la + style.bg_top[i] * (1 - la)) for i, c in enumerate(style.ink))
        d.text((x, y), title, font=tf, fill=ink, stroke_width=max(2, w // 900),
               stroke_fill=style.bg_top)
        if sub:
            tb = d.textbbox((x, y), title, font=tf)
            muted = tuple(int(c * la + style.bg_top[i] * (1 - la)) for i, c in enumerate(style.muted))
            d.text((x + 4, tb[3] + int(h * 0.02)), sub, font=sf, fill=muted)
