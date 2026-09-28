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
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.stock_video")

_UA = {"User-Agent": "Mind_Vault/0.1 (https://github.com/saifullah5553/Mind_Vault) python-httpx"}

# Keep downloads sane on a home connection.
MAX_CLIP_MB = 60
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
_SAFE_COLLECTIONS = ("prelinger", "publicmovies", "opensource_movies",
                     "universallibrary", "nasa", "usnationalarchives")


def _is_clearable(meta: dict) -> tuple[bool, str]:
    """True only if the item is provably public domain / CC."""
    fields = " ".join(str(meta.get(k, "")) for k in
                      ("licenseurl", "rights", "possible-copyright-status", "usage"))
    collections = meta.get("collection") or []
    if isinstance(collections, str):
        collections = [collections]
    coll = " ".join(collections).lower()
    if any(c in coll for c in _SAFE_COLLECTIONS):
        return True, (str(meta.get("licenseurl") or "public domain (safe collection)")[:80])
    if _CLEAR_RE.search(fields):
        return True, fields.strip()[:80]
    return False, ""


# ── Internet Archive (public-domain archival film) ──────────────────────────
def _ia_search(query: str, limit: int) -> list[str]:
    import httpx

    # Bias the query itself toward provably-clearable material.
    safe = " OR ".join(f"collection:({c})" for c in _SAFE_COLLECTIONS)
    q = f'({query}) AND mediatype:(movies) AND ({safe})'
    r = httpx.get("https://archive.org/advancedsearch.php",
                  params={"q": q, "fl[]": "identifier", "rows": str(limit),
                          "page": "1", "output": "json", "sort[]": "downloads desc"},
                  headers=_UA, timeout=25)
    r.raise_for_status()
    docs = ((r.json().get("response") or {}).get("docs")) or []
    return [d["identifier"] for d in docs if d.get("identifier")]


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

    best = None
    for f in data.get("files") or []:
        name = f.get("name", "")
        if not name.lower().endswith(_VIDEO_EXT):
            continue
        try:
            size_mb = int(f.get("size", 0)) / (1024 * 1024)
        except (TypeError, ValueError):
            size_mb = 0.0
        # Prefer the smallest usable derivative; size is fine because we only
        # range-read a few seconds of it.
        if best is None or (size_mb and size_mb < best[1]):
            best = (name, size_mb or 1e9)
    if not best:
        return None
    return {
        "url": f"https://archive.org/download/{identifier}/{best[0]}",
        "title": str(meta.get("title") or identifier)[:120],
        "license": lic or "public domain",
        "credit": str(meta.get("creator") or "")[:80],
        "source": "Internet Archive",
        "stream": True,
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


def _pixabay_clips(query: str, limit: int) -> list[dict]:
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    import httpx

    out: list[dict] = []
    try:
        r = httpx.get("https://pixabay.com/api/videos/",
                      params={"key": key, "q": query, "per_page": str(max(3, limit))},
                      headers=_UA, timeout=25)
        r.raise_for_status()
        for v in r.json().get("hits", []):
            vids = v.get("videos") or {}
            pick = vids.get("medium") or vids.get("small") or {}
            if not pick.get("url"):
                continue
            out.append({"url": pick["url"], "title": str(v.get("tags", ""))[:120],
                        "license": "Pixabay (free commercial use)",
                        "credit": v.get("user", ""), "source": "Pixabay"})
    except Exception as exc:
        log.debug("Pixabay search failed: %s", exc)
    return out


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
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
           "-vf", "scale='min(1920,iw)':-2", str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        return dest.exists() and dest.stat().st_size > 20_000
    except Exception as exc:
        log.debug("excerpt failed (%s)", str(exc)[:120])
        return False


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


def fetch_clip_pool(topic: str, count: int, dest_dir: Path,
                    category: str = "history", excerpt_seconds: float = 9.0) -> list[dict]:
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

    hits: list[dict] = []
    seen: set[str] = set()
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
    for i, hit in enumerate(hits):
        dest = dest_dir / f"_clip_{i:03d}.mp4"
        if hit.get("stream"):
            # Stagger the seek so several excerpts from one film differ.
            ok = _excerpt(hit["url"], dest, 45.0 + 37.0 * i, excerpt_seconds)
        else:
            ok = _download(hit["url"], dest)
        if ok:
            pool.append(dict(hit, path=str(dest)))

    if pool:
        log.info("Footage pool for '%s': %d clip(s) from %s", topic[:40], len(pool),
                 ", ".join(sorted({h["source"] for h in pool})))
    else:
        log.info("No clearable stock footage for '%s'; using stills.", topic[:40])
    return pool
