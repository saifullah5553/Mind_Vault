"""Free HD stock FOOTAGE sourcing — real moving video, no GPU, no API key.

Replacing static stills with real footage is the single biggest quality jump
available to this project: it is what separates "slideshow" from "documentary".

Keyless sources (work out of the box):
  1. Internet Archive — public-domain archival film (Prelinger and friends).
     Ideal for HISTORY: real period footage, genuinely public domain.
  2. Wikimedia Commons — CC/PD video files.

Optional keyed sources (better modern b-roll; free keys, no card):
  3. Pexels Videos   — set PEXELS_API_KEY
  4. Pixabay Videos  — set PIXABAY_API_KEY

Everything returned is public-domain or CC-licensed with commercial use allowed,
and attribution metadata is captured for the video description. Clips are size-
capped so a run never drags down a slow connection.

NOTE on AI video generators (Sora / Runway / Pika / Meta AI): they are
deliberately NOT used here. They have no free API, their free tiers allow only a
handful of clips per day, automating their web UIs violates their terms, and
generated "historical" footage invents inaccurate detail. Real archival footage
is cheaper, faster, legally clean, and more credible for this genre.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from core.logging_setup import get_logger
from core.media.credits import is_restricted

log = get_logger("media.stock_video")

_UA = {"User-Agent": "Mind_Vault/0.1 (https://github.com/saifullah5553/Mind_Vault) python-httpx"}

# Keep downloads sane on a home connection.
MAX_CLIP_MB = 60
# Sources below this height look bad blown up to a 1080p frame, so we skip them
# and let a high-resolution photo or an animated scene take that beat instead.
MIN_SOURCE_HEIGHT = 400


def _min_height() -> int:
    from core.config import get_settings
    return int(getattr(get_settings().video, "min_footage_height", MIN_SOURCE_HEIGHT))
_VIDEO_EXT = (".mp4", ".webm", ".ogv", ".m4v", ".mov")


def _stop_words() -> set[str]:
    from core.media.stock import _STOP
    return _STOP


def search_terms(topic: str, limit: int = 3) -> str:
    """Compact search phrase from a topic string."""
    stop = _stop_words()
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", topic or "")
             if w.lower() not in stop]
    seen: list[str] = []
    for w in words:
        if w.lower() not in [s.lower() for s in seen]:
            seen.append(w)
        if len(seen) >= limit:
            break
    return " ".join(seen)


# ── Licence safety ──────────────────────────────────────────────────────────
# Internet Archive hosts plenty of user uploads that are NOT clearable (TV
# documentaries, films). Using those in a monetised video earns copyright
# strikes, so we accept an item ONLY when its metadata proves it is public
# domain or Creative Commons.
_CLEAR_RE = re.compile(
    r"creativecommons\.org|publicdomain|public[ _-]?domain|cc0|cc[- ]by|"
    r"no known copyright|not in copyright", re.I)
# Collections whose items are public domain by curation. "opensource_movies" is
# NOT here: it is the open community-upload bucket (a 2023 games-conference
# recording came through it as "public domain"). Its items now need an explicit
# PD/CC licence like any other.
_SAFE_COLLECTIONS = ("prelinger", "publicmovies", "universallibrary", "nasa",
                     "usnationalarchives")
# Archival look: modern uploads (talks, streams, screen recordings) don't fit.
_MODERN_RE = re.compile(r"conference|celebration|webinar|zoom|lecture|livestream|"
                        r"podcast|stream|vlog|gameplay|screencast|tutorial|program(?:s)?\b|"
                        r"\b20[0-2]\d\b", re.I)
_LATEST_YEAR = 1990
# Vertical HD barely exists on Pixabay (0-13 clips per subject). Landscape this
# tall, centre-cropped to 9:16, is upscaled at most 1.33x.
_CROP_MIN_HEIGHT = 1440
# Not real scenes: viewers rejected the AI look, and these read as ads, quiz cards
# or slideshows. Named brands and national flags don't belong in the video either.
_NOT_FILMED = re.compile(
    r"ai generated|\b3d\b|cartoon|animation|\bhud\b|green ?screen|chroma|transition|overlay|"
    r"quiz|maze|labyrinth|wallpaper|fifa|coca[- ]cola|\bflags?\b|"
    r"coronavirus|covid|quarantine|\bmasks?\b", re.I)
# Clips that pass every tag check but show something wrong for this channel.
# 132048: kindergarten class in face masks, which dates a story about the 1970s.
_BLOCKED_IDS = {132048}
# Pixabay's CDN answers bursts with empty files, which silently cost a video its
# subject shots (20 of 85 in one render). Wait and try again.
_RETRIES = 3
_RETRY_PAUSE = 4.0
# Trailers advertise someone else's film; a "public domain" tag on one proves little.
_TRAILER_RE = re.compile(r"(?<![a-z])trailers?(?![a-z])", re.I)


def _is_clearable(meta: dict) -> tuple[bool, str]:
    """True only if the item is provably public domain / CC."""
    fields = " ".join(str(meta.get(k, "")) for k in
                      ("licenseurl", "rights", "possible-copyright-status", "usage"))
    collections = meta.get("collection") or []
    if isinstance(collections, str):
        collections = [collections]
    coll = " ".join(collections).lower()
    # Before anything else: a CC link alone says nothing about NC or ND terms,
    # and a curated collection doesn't override the item's own licence.
    if is_restricted(fields) or _TRAILER_RE.search(f"{meta.get('title', '')} {coll}"):
        return False, ""
    if any(c in coll for c in _SAFE_COLLECTIONS):
        return True, (str(meta.get("licenseurl") or "public domain (safe collection)")[:80])
    if _CLEAR_RE.search(fields):
        return True, fields.strip()[:80]
    return False, ""


# ── Internet Archive (public-domain archival film) ──────────────────────────
def _ia_search(query: str, limit: int) -> list[str]:
    import httpx

    # Bias the query itself toward provably-clearable material.
    safe = " OR ".join(f"collection:({c})" for c in (*_SAFE_COLLECTIONS, "opensource_movies"))
    # Title/subject only: matching anywhere in a description pulled in WWII
    # propaganda for "motivation".
    q = f'(title:({query}) OR subject:({query})) AND mediatype:(movies) AND ({safe})'
    r = httpx.get("https://archive.org/advancedsearch.php",
                  params={"q": q, "fl[]": "identifier", "rows": str(limit),
                          "page": "1", "output": "json", "sort[]": "downloads desc"},
                  headers=_UA, timeout=25)
    r.raise_for_status()
    docs = ((r.json().get("response") or {}).get("docs")) or []
    return [d["identifier"] for d in docs if d.get("identifier")]


def _seconds(value) -> float:
    """IA 'length' is seconds ("612.4") or clock time ("10:12"); 0 if unknown."""
    try:
        parts = [float(p) for p in str(value).split(":")]
    except (TypeError, ValueError):
        return 0.0
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def shot_offsets(length: float, shots: int, dur: float) -> list[float]:
    """Start times for `shots` excerpts spread over a film (skips titles/credits).

    Unknown length: staggered guesses within a typical 10-minute short.
    """
    if length and length <= dur * 2:
        # Short stock clip: one shot from (near) the start; it loops if needed.
        return [round(max(0.0, (length - dur) / 2), 1)]
    if length and length > dur * 2:
        lo, hi = length * 0.08, max(length * 0.08, length * 0.88 - dur)
        if shots == 1:
            return [round((lo + hi) / 2, 1)]
        return [round(lo + (hi - lo) * k / (shots - 1), 1) for k in range(shots)]
    return [45.0 + 110.0 * k for k in range(shots)]


def _ia_file(identifier: str) -> dict | None:
    """Return a streamable video URL for a CLEARABLE Internet Archive item.

    We do NOT download the whole film (they run to hundreds of MB); the pool
    step extracts a short excerpt straight from this URL via HTTP range requests.
    """
    import httpx

    r = httpx.get(f"https://archive.org/metadata/{identifier}", headers=_UA, timeout=25)
    r.raise_for_status()
    data = r.json()
    meta = data.get("metadata") or {}
    ok, lic = _is_clearable(meta)
    if not ok:
        return None
    title = str(meta.get("title") or identifier)
    year = re.search(r"\b(1[89]\d\d|20\d\d)\b", str(meta.get("year") or meta.get("date") or ""))
    if _MODERN_RE.search(title) or (year and int(year.group(1)) > _LATEST_YEAR):
        log.debug("%s: modern upload (%s); skipping.", identifier, title[:60])
        return None

    # Pick the HIGHEST-resolution derivative. File size is irrelevant because we
    # only range-read a few seconds; picking the smallest file (as an earlier
    # version did) yielded 320x240 sources that looked terrible upscaled to 1080p.
    best = None      # (name, height, width)
    for f in data.get("files") or []:
        name = f.get("name", "")
        if not name.lower().endswith(_VIDEO_EXT):
            continue
        try:
            fw = int(f.get("width") or 0)
            fh = int(f.get("height") or 0)
        except (TypeError, ValueError):
            fw = fh = 0
        if best is None or fh > best[1]:
            best = (name, fh, fw, _seconds(f.get("length")))
    if not best:
        return None
    # Refuse sources too small to survive upscaling to the output frame.
    if best[1] and best[1] < _min_height():
        log.debug("%s: best derivative only %dp; skipping.", identifier, best[1])
        return None
    return {
        "url": f"https://archive.org/download/{identifier}/{best[0]}",
        "title": str(meta.get("title") or identifier)[:120],
        "license": lic or "public domain",
        "credit": str(meta.get("creator") or "")[:80],
        "source": "Internet Archive",
        "stream": True,
        "height": best[1],
        "width": best[2],
        "length": best[3],
    }


def _ia_clips(query: str, limit: int) -> list[dict]:
    out: list[dict] = []
    try:
        for ident in _ia_search(query, limit * 3):
            if len(out) >= limit:
                break
            try:
                hit = _ia_file(ident)
            except Exception:
                continue
            if hit:
                out.append(hit)
    except Exception as exc:
        log.debug("Internet Archive search failed: %s", exc)
    return out


# ── Wikimedia Commons (CC/PD video) ─────────────────────────────────────────
def _commons_clips(query: str, limit: int) -> list[dict]:
    import httpx

    out: list[dict] = []
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=_UA, timeout=25,
                      params={"action": "query", "format": "json", "generator": "search",
                              "gsrsearch": f"{query} filetype:video", "gsrnamespace": "6",
                              "gsrlimit": str(limit), "prop": "imageinfo",
                              "iiprop": "url|size|extmetadata"})
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url")
            if not url or not url.lower().endswith(_VIDEO_EXT):
                continue
            if (info.get("size") or 0) > MAX_CLIP_MB * 1024 * 1024:
                continue
            em = info.get("extmetadata") or {}
            if is_restricted((em.get("LicenseShortName") or {}).get("value", "")):
                continue
            out.append({
                "url": url,
                "title": (page.get("title") or "").replace("File:", "")[:120],
                "license": (em.get("LicenseShortName") or {}).get("value", "CC")[:80],
                "credit": re.sub(r"<[^>]+>", "", (em.get("Artist") or {}).get("value", ""))[:80],
                "source": "Wikimedia Commons",
            })
    except Exception as exc:
        log.debug("Commons video search failed: %s", exc)
    return out


# ── Optional keyed sources ──────────────────────────────────────────────────
def _pexels_clips(query: str, limit: int) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    import httpx

    out: list[dict] = []
    try:
        r = httpx.get("https://api.pexels.com/videos/search",
                      params={"query": query, "per_page": str(limit), "size": "medium"},
                      headers={**_UA, "Authorization": key}, timeout=25)
        r.raise_for_status()
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", [])
                     if (f.get("height") or 0) >= 720 and f.get("link")]
            if not files:
                continue
            files.sort(key=lambda f: f.get("height", 0))
            out.append({"url": files[0]["link"], "title": (v.get("url") or "Pexels clip")[:120],
                        "license": "Pexels (free commercial use)",
                        "credit": (v.get("user") or {}).get("name", ""), "source": "Pexels"})
    except Exception as exc:
        log.debug("Pexels search failed: %s", exc)
    return out


def _tagged(tags: str, query: str) -> bool:
    """Every search word is a whole tag word ("mother" isn't "motherhood"), and the
    first is among the leading tags: a wasp tagged "pottery" seventh is about wasps.
    """
    def has(word: str, text: str) -> bool:
        return bool(re.search(rf"\b{re.escape(word.removesuffix('s'))}s?\b", text))

    words = query.lower().split()
    leading = ", ".join(tags.split(", ")[:5])
    return has(words[0], leading) and all(has(w, tags) for w in words)


def _pixabay_get(params: dict):
    """The search request, retried through rate limits and dropped connections."""
    import httpx

    for attempt in range(_RETRIES):
        if attempt:
            time.sleep(_RETRY_PAUSE * attempt)
        last = attempt == _RETRIES - 1
        try:
            r = httpx.get("https://pixabay.com/api/videos/", params=params,
                          headers=_UA, timeout=25)
        except httpx.TransportError:
            if last:
                raise
            continue
        if last or (r.status_code != 429 and r.status_code < 500):
            break
    r.raise_for_status()
    return r


def _pixabay_clips(query: str, limit: int, landscape: bool = True,
                   min_height: int = 1080, strict: bool = False) -> list[dict]:
    """HD stock video (free key). Picks the smallest rendition that is at least
    `min_height` tall in the video's orientation; excerpts are range-read, so a
    4K source costs only the seconds actually used.

    Pixabay matches ANY word ("gold medal" finds gold panning, "pottery wheel" a
    Ferris wheel). `strict` keeps only clips tagged with every word.
    """
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    out: list[dict] = []
    try:
        r = _pixabay_get({"key": key, "q": query, "per_page": "100", "video_type": "film",
                          "safesearch": "true"})
        for v in r.json().get("hits", []):
            tags = str(v.get("tags", "")).lower()
            if not acceptable_title(tags) or _NOT_FILMED.search(tags) or v.get("id") in _BLOCKED_IDS:
                continue
            if v.get("type", "film") != "film" or (strict and not _tagged(tags, query)):
                continue
            if float(v.get("duration") or 0) < 8:
                continue                     # shorter than a scene: it would loop
            rends = [x for x in (v.get("videos") or {}).values() if x and x.get("url")]
            # Right orientation only: a vertical clip cover-cropped into a
            # landscape frame loses two thirds of the picture.
            wide = [x for x in rends if x.get("width", 0) > x.get("height", 0)]
            rends = wide if landscape else [x for x in rends if x not in wide]
            short_side = (lambda x: x.get("height", 0)) if landscape else (lambda x: x.get("width", 0))
            good = sorted((x for x in rends if short_side(x) >= min_height), key=short_side)
            if not good and not landscape:
                good = sorted((x for x in wide if x.get("height", 0) >= _CROP_MIN_HEIGHT),
                              key=lambda x: x.get("height", 0))
            if not good:
                continue
            pick = good[0]
            out.append({"url": pick["url"], "title": str(v.get("tags", ""))[:120],
                        "license": "Pixabay Content License (free commercial use)",
                        "credit": v.get("user", ""), "source": "Pixabay",
                        "page": v.get("pageURL", ""), "stream": True, "length": float(v.get("duration") or 0),
                        "width": pick.get("width"), "height": pick.get("height")})
            if len(out) >= limit:
                break
    except Exception as exc:
        # The type only: HTTP errors quote the URL, and the URL holds the API key.
        log.warning("Pixabay search for %r failed: %s", query, type(exc).__name__)
    return out


def acceptable_title(text: str) -> bool:
    """Same safety screen as stills (core.media.stock)."""
    from core.media.stock import _UNSAFE
    return not _UNSAFE.search(text or "")


# ── Fetch (excerpt, not whole file) + pool ──────────────────────────────────
def _excerpt(url: str, dest: Path, start_s: float, dur: float) -> bool:
    """Pull a SHORT excerpt straight from a remote video via ffmpeg.

    `-ss` before `-i` seeks with HTTP range requests, so we transfer only a few
    seconds instead of downloading an entire archival film. Audio is dropped —
    we always narrate over the footage.
    """
    from core.media.video import _ffmpeg_exe
    import subprocess

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-ss", f"{start_s:.1f}", "-i", url, "-t", f"{dur:.1f}",
           # Near-lossless intermediate: it is re-encoded once more in assembly.
           # (Width used to be capped at 1920 and CRF 26, softening 1440p output.)
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
           "-vf", "scale='min(3840,iw)':-2", str(dest)]
    for attempt in range(_RETRIES):
        if attempt:
            time.sleep(_RETRY_PAUSE * attempt)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            if dest.exists() and dest.stat().st_size > 20_000:
                return True
        except Exception as exc:
            log.debug("excerpt failed (%s)", str(exc)[:120])
    dest.unlink(missing_ok=True)
    log.warning("No usable excerpt after %d tries: %s", _RETRIES, url[:90])
    return False


def _keyed_or_flat(clip: Path) -> bool:
    """True if any sampled frame is chroma-key green or one plain colour.

    Tags don't always say so, and a full-screen green frame is the worst thing
    that can reach a viewer.
    """
    import subprocess

    import numpy as np

    from core.media.video import _ffmpeg_exe

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    try:
        raw = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(clip), "-vf",
             "select='not(mod(n\\,60))',scale=64:36", "-frames:v", "3",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=60).stdout
    except Exception:
        return False
    size = 64 * 36 * 3
    if not raw or len(raw) % size:
        return False
    return any(frame_is_unusable(f) for f in
               np.frombuffer(raw, np.uint8).reshape(-1, 64 * 36, 3).astype(int))


def frame_is_unusable(pixels) -> bool:
    """`pixels`: (n, 3) RGB ints. Key green over a quarter of it, or no contrast."""
    r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    keyed = (g > 120) & (g > 2 * r) & (g > 2 * b)
    return bool(keyed.mean() > 0.25 or pixels.mean(axis=1).std() < 6)


def _too_dark(clip: Path, floor: float = 28.0) -> bool:
    """True if the shot is nearly black (a night clip reads as a dropout).

    Samples three frames at thumbnail size; mean luma 0-255 below `floor`.
    """
    from core.media.video import _ffmpeg_exe
    import subprocess

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return False
    try:
        raw = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(clip), "-vf",
             "select='not(mod(n\\,60))',scale=64:36", "-frames:v", "3",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, timeout=60).stdout
    except Exception:
        return False
    if not raw:
        return False
    dark = sum(raw) / len(raw) < floor
    if dark:
        log.debug("Dropping near-black shot %s", clip.name)
        clip.unlink(missing_ok=True)
    return dark


def _download(url: str, dest: Path) -> bool:
    """Plain download for small keyed-provider clips (Pexels/Pixabay)."""
    import httpx

    try:
        with httpx.stream("GET", url, headers=_UA, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            if int(r.headers.get("content-length") or 0) > MAX_CLIP_MB * 1024 * 1024:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes():
                    written += len(chunk)
                    if written > MAX_CLIP_MB * 1024 * 1024:
                        break
                    fh.write(chunk)
        return dest.exists() and dest.stat().st_size > 50_000
    except Exception as exc:
        log.debug("clip download failed (%s)", exc)
        return False


def fetch_subject_clips(wanted: dict[str, int], dest_dir: Path, landscape: bool = True,
                        min_height: int = 1080, excerpt_seconds: float = 12.0) -> dict[str, list[dict]]:
    """Distinct clips for each concrete subject ({"cat": 3} -> three cat shots)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    n = 0
    for subject, count in wanted.items():
        clips: list[dict] = []
        for query in subject.split("|"):
            hits = _pixabay_clips(query, count * 3 + 2, landscape=landscape,
                                  min_height=min_height, strict=True)
            for hit in hits:
                if len(clips) >= count or hit["url"] in seen:
                    continue
                seen.add(hit["url"])
                dest = dest_dir / f"_subject_{n:03d}.mp4"
                n += 1
                start = shot_offsets(hit.get("length") or 0.0, 1, excerpt_seconds)[0]
                if (_excerpt(hit["url"], dest, start, excerpt_seconds)
                        and not _too_dark(dest) and not _keyed_or_flat(dest)):
                    clips.append(dict(hit, path=str(dest), start=start, subject=subject))
        out[subject] = clips
    log.info("Subject footage: %d of %d shot(s) for %d subject(s).",
             sum(len(c) for c in out.values()), sum(wanted.values()), len(out))
    return out


def _themed_hits(count: int, providers, seen: set[str]) -> list[dict]:
    """B-roll by MOOD for abstract topics (see core/media/themes.py): a beat
    about striving gets a climber on a ridge, hope gets a real sunrise."""
    from core.media.themes import THEMES
    per_theme = max(1, -(-count // len(THEMES)))
    hits: list[dict] = []
    for theme, (_cue, queries) in THEMES.items():
        got = 0
        for q in queries:
            for provider in providers:
                if got >= per_theme:
                    break
                try:
                    found = provider(q, per_theme)
                except Exception as exc:
                    log.debug("clip source failed for %r: %s", q, exc)
                    continue
                for hit in found:
                    if got >= per_theme or hit["url"] in seen:
                        continue
                    seen.add(hit["url"])
                    hits.append(dict(hit, theme=theme))
                    got += 1
    return hits


def fetch_clip_pool(topic: str, count: int, dest_dir: Path,
                    category: str = "history", excerpt_seconds: float = 12.0,
                    shots_per_film: int = 1, landscape: bool = True,
                    min_height: int = 1080) -> list[dict]:
    """Build a pool of openly-licensed clips about `topic`.

    One topic-level search (not per-scene) keeps footage visually coherent and
    on-subject, and is far faster than a query per scene. Archive items are
    sampled as short excerpts at staggered offsets so repeated use of one film
    still yields visually different shots.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    terms = [t for t in (topic, search_terms(topic, 3), search_terms(topic, 2)) if t.strip()]

    # History leans on archival film; psychology leans on modern b-roll.
    if category == "history":
        providers = [_ia_clips, _commons_clips, _pexels_clips, _pixabay_clips]
    else:
        providers = [_pexels_clips, _pixabay_clips, _commons_clips, _ia_clips]

    # Archive items match mood words by title alone: that put a 1950s stripper
    # reel and a chimp in a costume into a Short about motivation.
    if category == "psychology":
        providers.remove(_ia_clips)

    from functools import partial
    providers = [partial(_pixabay_clips, landscape=landscape, min_height=min_height)
                 if pr is _pixabay_clips else pr for pr in providers]

    hits: list[dict] = []
    seen: set[str] = set()
    if category == "psychology":
        hits = _themed_hits(count, providers, seen)
        # Mood b-roll found: never pad with keyword-matched archive reels (that
        # is how silent-film title cards and a chimp in a tuxedo got into a
        # psychology documentary).
        if hits:
            terms = []
    for term in terms:
        if len(hits) >= count:
            break
        for provider in providers:
            if len(hits) >= count:
                break
            try:
                for hit in provider(term, count):
                    if hit["url"] in seen:
                        continue
                    seen.add(hit["url"])
                    hits.append(hit)
                    if len(hits) >= count:
                        break
            except Exception as exc:
                log.debug("%s failed: %s", getattr(provider, "__name__", "?"), exc)

    pool: list[dict] = []
    n = 0
    for hit in hits:
        if hit.get("stream"):
            # Several shots per ARCHIVAL film (long, varied reels). A stock clip
            # is one continuous scene: four cuts of the same misty hill read as
            # repetition, so stock gets one shot.
            shots = shots_per_film if hit.get("source") == "Internet Archive" else 1
            for start in shot_offsets(hit.get("length") or 0.0, shots, excerpt_seconds):
                dest = dest_dir / f"_clip_{n:03d}.mp4"
                n += 1
                if (_excerpt(hit["url"], dest, start, excerpt_seconds)
                        and not _too_dark(dest) and not _keyed_or_flat(dest)):
                    pool.append(dict(hit, path=str(dest), start=start))
        else:
            dest = dest_dir / f"_clip_{n:03d}.mp4"
            n += 1
            if _download(hit["url"], dest):
                pool.append(dict(hit, path=str(dest)))
    # Interleave films so consecutive footage scenes come from different films.
    by_film: dict[str, list[dict]] = {}
    for clip in pool:
        by_film.setdefault(clip["url"], []).append(clip)
    rounds = max((len(v) for v in by_film.values()), default=0)
    pool = [v[r] for r in range(rounds) for v in by_film.values() if r < len(v)]

    if pool:
        log.info("Footage pool for '%s': %d shot(s) from %d film(s) via %s", topic[:40],
                 len(pool), len({h["url"] for h in pool}),
                 ", ".join(sorted({h["source"] for h in pool})))
    else:
        log.info("No clearable stock footage for '%s'; using stills.", topic[:40])
    return pool
