"""Picture briefs: a detailed master prompt for every line, written from the script.

Broad TOPIC searches filled a pool with whatever came back (space probes, airfields,
other men named Pavlov) and the leftovers landed on abstract lines; each fix needed
another plan and more searches. A brief says exactly what one line must show, so
only that picture is searched for, and only a picture that meets it is used.

`<script>.pictures.yaml`, next to the script, holds a list of briefs:

    - cue: Everyone knows the story        # words from the line (first line that has them)
      kind: photo                          # photo | illustration | hold
      who: Ivan Petrovich Pavlov (1849-1936), Russian physiologist, Nobel Prize 1904;
           a scientist, not a writer, priest or politician
      not: Valentin Pavlov (Soviet prime minister), Vladimir Pavlov, his students alone
      look: older man, full white beard, short white hair, upright
      clothing: white laboratory coat over a dark suit, or a dark three-piece suit
      setting: his laboratory at the Institute of Experimental Medicine, with a dog or apparatus
      mood: serious and focused, watching an experiment or thinking; not a ceremony
      era: 1890-1936                       # years the picture must come from
      framing: medium shot, face clearly visible, room either side for a wide frame
      search: [Pavlov laboratory Wellcome, Ivan Pavlov experiment dog]
      must: [Pavlov]                       # every one must be in the title/description
      any: [Ivan, I. P., laboratory, physiology]   # at least one
      reject: [stamp, coin, banknote, statue, monument]
      label: Ivan Pavlov                   # optional name caption
      pick: "Pavlov experiments with dog Wellcome M0014738.jpg"   # chosen after the plan
      prompt: ...                          # kind: illustration only (never a real person)

A plan (`run_pipeline --plan-only`) writes, for every photo brief, a numbered sheet
of the candidates that passed the checks (storage/images/<run>/briefs/). The
reviewer looks at the pictures against the brief and writes `pick:` (a file title,
or `none` to fall back). Without a pick, the best-ranked candidate is used; when
nothing passes, the line keeps the previous shot (`hold`), never a random picture.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.briefs")

SEARCH_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "cache" / "searches"
SEARCH_CACHE_HOURS = 24
PER_SEARCH = 20            # results asked per search phrase
SHEET_MAX = 8              # candidates shown per brief

# Never the picture a brief means, whatever it names.
_ALWAYS_REJECT = ("postage stamp", "stamp of", "banknote", "coin of", "commemorative coin",
                  "logo", "poster", "signature", "autograph", "map of", "diagram", "chart")
_DESCRIBE = ("look", "clothing", "setting", "mood", "framing")


@dataclass
class Brief:
    cue: str
    kind: str = "photo"
    who: str = ""
    avoid: str = ""
    look: str = ""
    clothing: str = ""
    setting: str = ""
    mood: str = ""
    era: str = ""
    framing: str = ""
    search: list = field(default_factory=list)
    must: list = field(default_factory=list)
    any: list = field(default_factory=list)
    reject: list = field(default_factory=list)
    label: str = ""
    pick: str = ""
    prompt: str = ""

    def years(self) -> tuple[int, int] | None:
        m = re.match(r"\s*(\d{3,4})\s*(?:-|–|to)\s*(\d{3,4})\s*$", str(self.era or ""))
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.match(r"\s*(\d{3,4})\s*$", str(self.era or ""))
        return (int(m.group(1)), int(m.group(1))) if m else None


def load(path: str | Path) -> list[Brief]:
    """The briefs in a pictures file, in order. Bad entries are logged and skipped."""
    import yaml

    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    out: list[Brief] = []
    for i, item in enumerate(data if isinstance(data, list) else []):
        if not isinstance(item, dict) or not str(item.get("cue", "")).strip():
            log.warning("%s: brief %d has no cue; skipped", p.name, i + 1)
            continue
        kw = {k: item[k] for k in Brief.__dataclass_fields__ if k in item and k != "avoid"}
        kw["avoid"] = item.get("not", "")
        for k in ("search", "must", "any", "reject"):
            v = kw.get(k, [])
            kw[k] = [str(x) for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        kw = {k: (v.strip() if isinstance(v, str) else v) for k, v in kw.items()}
        b = Brief(**kw)
        b.kind = (b.kind or "photo").lower()
        if b.kind not in ("photo", "illustration", "hold"):
            log.warning("%s: brief '%s' has unknown kind %r; using hold", p.name, b.cue, b.kind)
            b.kind = "hold"
        out.append(b)
    return out


def pictures_file(script_file: str | Path) -> Path:
    """'content/scripts/pavlov.txt' -> 'content/scripts/pavlov.pictures.yaml'."""
    p = Path(script_file)
    return p.with_name(p.stem + ".pictures.yaml")


def match(briefs: list[Brief], lines: list[str]) -> dict[int, Brief]:
    """{line index: brief}: each brief goes to the first free line containing its cue."""
    out: dict[int, Brief] = {}
    for b in briefs:
        cue = re.compile(re.escape(b.cue), re.I)
        for i, line in enumerate(lines):
            if i not in out and cue.search(line or ""):
                out[i] = b
                break
        else:
            log.warning("Picture brief cue not found in the script: %r", b.cue)
    return out


# ── checks ──────────────────────────────────────────────────────────────────
def _text(hit: dict) -> str:
    return " ".join(str(hit.get(k, "")) for k in ("title", "about", "tags"))


def _has(word: str, text: str) -> bool:
    """A whole word or phrase, case-insensitive, any ending ('physiolog' finds 'physiology')."""
    w = re.escape(word.strip()).replace(r"\ ", r"[\s._-]*")
    return re.search(rf"(?<![\w]){w}", text, re.I) is not None


def _title_years(hit: dict) -> list[int]:
    return [int(y) for y in re.findall(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", str(hit.get("title", "")))]


def check(brief: Brief, hit: dict, category: str = "history") -> str:
    """'' when the picture meets the brief, else the reason it doesn't."""
    from core.media.stock import acceptable

    if not acceptable(hit, category):
        return "blocked or too small"
    text = _text(hit)
    for w in brief.must:
        if not _has(w, text):
            return f"no '{w}'"
    if brief.any and not any(_has(w, text) for w in brief.any):
        return "none of: " + ", ".join(brief.any)
    for w in list(brief.reject) + list(_ALWAYS_REJECT):
        if _has(w, str(hit.get("title", ""))) or (w in brief.reject and _has(w, text)):
            return f"rejected: {w}"
    span = brief.years()
    if span:
        years = _title_years(hit)
        lo, hi = span[0] - 5, span[1] + 5
        if years and not any(lo <= y <= hi for y in years):
            return f"wrong years {years}"
    return ""


def score(brief: Brief, hit: dict) -> float:
    """How much of the brief's description the picture's own words carry."""
    text = _text(hit)
    words = {w.lower() for k in _DESCRIBE for w in re.findall(r"[A-Za-z]{4,}", getattr(brief, k))}
    words -= {"with", "from", "only", "never", "either", "room", "side", "wide", "frame",
              "clearly", "visible", "shot", "medium", "close", "over", "under", "their", "this"}
    s = sum(1.0 for w in words if _has(w, text))
    s += sum(2.0 for w in brief.any if _has(w, str(hit.get("title", ""))))
    if _title_years(hit):
        s += 0.5
    return s + min(float(hit.get("width") or 0), 6000.0) / 6000.0


# ── searches (cached) ───────────────────────────────────────────────────────
def _cached(source: str, query: str, fetch) -> list[dict]:
    name = hashlib.sha1(f"{source}\0{query}".encode()).hexdigest()
    path = SEARCH_CACHE_DIR / f"{name}.json"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < SEARCH_CACHE_HOURS * 3600:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        hits = fetch(query) or []
    except Exception as exc:
        log.warning("%s search for %r failed: %s", source, query, type(exc).__name__)
        return []
    try:
        SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hits), encoding="utf-8")
    except OSError:
        pass
    return hits


def candidates(brief: Brief, category: str = "history") -> list[dict]:
    """Pictures that meet the brief, best first (Commons, then Openverse)."""
    from core.media import stock

    seen: set[str] = set()
    good: list[tuple[float, int, dict]] = []
    n = 0
    for q in brief.search:
        for source, fetch in (("commons", lambda s: stock._commons_search(s, PER_SEARCH)),
                              ("openverse", lambda s: stock._openverse_search(s, PER_SEARCH))):
            for hit in _cached(source, q, fetch):
                key = str(hit.get("title", "")).lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                if not check(brief, hit, category):
                    n += 1
                    good.append((score(brief, hit), -n, hit))
    good.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [h for _s, _n, h in good]


def chosen(brief: Brief, found: list[dict]) -> dict | None:
    """The reviewer's pick (by title), else the best candidate; None means fall back."""
    if brief.pick.strip().lower() == "none":
        return None
    if brief.pick.strip():
        want = brief.pick.strip().lower().replace("file:", "")
        for h in found:
            if str(h.get("title", "")).lower().replace("file:", "") == want:
                return h
        log.warning("Picked picture not found for '%s': %s; using the best candidate",
                    brief.cue, brief.pick)
    return found[0] if found else None


def thumb_url(hit: dict, width: int = 330) -> str:
    """A small copy for the review sheet (Commons thumbnails can be any width)."""
    url = str(hit.get("url", ""))
    m = re.search(r"/(\d+)px-", url)
    return url[:m.start(1)] + str(width) + url[m.end(1):] if m and "/thumb/" in url else url


def sheet(brief: Brief, found: list[dict], line: str, out: Path) -> Path | None:
    """A numbered contact sheet of the candidates, with the brief at the top."""
    import io

    import httpx
    from PIL import Image, ImageDraw

    from core.media.images import _font
    from core.media.stock import _UA

    cols, tw, th = 4, 330, 240
    shown = found[:SHEET_MAX]
    rows = max(1, -(-len(shown) // cols))
    head = 150
    img = Image.new("RGB", (cols * tw, head + rows * (th + 46)), (18, 18, 24))
    d = ImageDraw.Draw(img)
    f, small = _font(17, True), _font(14)
    d.text((10, 8), f"LINE: {line[:120]}", font=f, fill=(245, 246, 250))
    need = " | ".join(x for x in (brief.who, brief.setting, brief.clothing, brief.mood) if x)
    for k, chunk in enumerate([need[i:i + 150] for i in range(0, min(len(need), 600), 150)]):
        d.text((10, 36 + k * 22), chunk, font=small, fill=(170, 178, 198))
    if not shown:
        d.text((10, head + 20), "NO PICTURE MEETS THIS BRIEF -> falls back (hold)", font=f,
               fill=(240, 118, 128))
    for k, hit in enumerate(shown):
        x, y = (k % cols) * tw, head + (k // cols) * (th + 46)
        try:
            r = httpx.get(thumb_url(hit), headers=_UA, timeout=20, follow_redirects=True)
            r.raise_for_status()
            t = Image.open(io.BytesIO(r.content)).convert("RGB")
            t.thumbnail((tw - 8, th - 8))
            img.paste(t, (x + 4, y + 4))
        except Exception:
            d.rectangle([x + 4, y + 4, x + tw - 4, y + th - 4], outline=(90, 90, 110))
        d.text((x + 8, y + 6), str(k + 1), font=f, fill=(226, 170, 84))
        d.text((x + 6, y + th + 2), str(hit.get("title", ""))[:44], font=small, fill=(220, 220, 230))
        d.text((x + 6, y + th + 22), str(hit.get("title", ""))[44:88], font=small, fill=(150, 158, 178))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=85)
    return out


def report(rows: list[tuple[int, str, Brief, list[dict]]]) -> str:
    """The text beside the sheets: every brief, its candidates (numbered as on
    the sheet) and what will be used."""
    lines = ["Picture briefs: candidates that met each brief, best first.",
             "Look at briefs/NN.jpg, then write `pick: <title>` (or `pick: none`) in the",
             "pictures file for any line where #1 is not right.", ""]
    for idx, line, b, found in rows:
        lines.append(f"[{idx:03d}] {line[:110]}")
        lines.append(f"      brief: {b.kind}  cue '{b.cue}'" + (f"  pick: {b.pick}" if b.pick else ""))
        if b.kind == "photo":
            if not found:
                lines.append("      NO CANDIDATE -> hold the previous shot")
            for k, h in enumerate(found[:SHEET_MAX]):
                lines.append(f"      {k + 1}. {str(h.get('title', ''))[:100]}")
        lines.append("")
    return "\n".join(lines)
