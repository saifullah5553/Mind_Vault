"""Real imagery sourcing — free, legally clean, no API key.

The single biggest quality problem with generated slideshows is fake-looking
gradient "cards". Real documentaries use real images. This module fetches
genuinely relevant, openly-licensed photographs:

  1. Wikimedia Commons  — public-domain / CC historical photos, paintings, maps.
                          Perfect for HISTORY. No API key, no rate-limit key.
  2. Openverse          — CC-licensed photo search across many providers.
                          Good for PSYCHOLOGY / abstract concepts.

Everything returned is public-domain or CC-licensed (commercial use allowed),
which keeps the copyright-risk score low. Attribution metadata is captured so it
can be surfaced in the video description.

If the network is unavailable or nothing matches, callers fall back to the
locally-generated card so the pipeline never breaks.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.stock")

# Wikimedia's UA policy REJECTS generic agents (403). It requires a descriptive
# agent with a contact URL.
_UA = {"User-Agent": "Mind_Vault/0.1 (https://github.com/saifullah5553/Mind_Vault) python-httpx"}

# Words that add nothing to an image search.
_STOP = {
    "the", "and", "that", "with", "from", "this", "which", "their", "there",
    "would", "could", "about", "into", "than", "them", "were", "been", "have",
    "what", "when", "where", "your", "you", "our", "its", "was", "are", "for",
    "but", "not", "all", "one", "how", "why", "who", "will", "more", "most",
    "story", "reason", "secret", "hidden", "untold", "really", "still",
}


def keywords_from(text: str, limit: int = 4) -> str:
    """Extract a compact, searchable phrase from narration/topic text."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text or "")
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOP or lw in out:
            continue
        out.append(lw)
        if len(out) >= limit:
            break
    return " ".join(out)


# ── Wikimedia Commons ───────────────────────────────────────────────────────
def _commons_search(query: str, limit: int = 3) -> list[dict]:
    import httpx

    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": "6",
        "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "1600",
    }
    r = httpx.get("https://commons.wikimedia.org/w/api.php", params=params,
                  headers=_UA, timeout=20)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out: list[dict] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        # Skip anything not clearly reusable.
        if lic and not re.search(r"public domain|cc|pd", lic, re.I):
            continue
        out.append({
            "url": url,
            "title": (page.get("title") or "").replace("File:", ""),
            "license": lic or "see Commons",
            "credit": re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:120],
            "source": "Wikimedia Commons",
        })
    return out


# ── Openverse ───────────────────────────────────────────────────────────────
def _openverse_search(query: str, limit: int = 3) -> list[dict]:
    import httpx

    r = httpx.get("https://api.openverse.org/v1/images/",
                  params={"q": query, "page_size": str(limit),
                          "license_type": "commercial", "mature": "false"},
                  headers=_UA, timeout=20)
    r.raise_for_status()
    out = []
    for item in r.json().get("results", []):
        url = item.get("url")
        if not url:
            continue
        out.append({
            "url": url,
            "title": item.get("title") or query,
            "license": (item.get("license") or "cc").upper(),
            "credit": item.get("creator") or "",
            "source": item.get("source") or "Openverse",
        })
    return out


def _download(url: str, dest: Path) -> bool:
    import httpx

    try:
        with httpx.stream("GET", url, headers=_UA, timeout=30, follow_redirects=True) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        return dest.exists() and dest.stat().st_size > 5000
    except Exception as exc:
        log.debug("download failed (%s)", exc)
        return False


def fetch_pool(topic: str, count: int, dest_dir: Path, category: str = "history") -> list[dict]:
    """Fetch a COHERENT pool of images about `topic`.

    DESIGN: searching per-scene narration returns visually random results (a Roman
    Empire line can match a Bulgarian mountain). Searching once on the topic and
    distributing the results keeps every frame on-subject and consistent — and is
    far faster (one query, N downloads instead of N queries).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    queries = [topic, keywords_from(topic, 3), keywords_from(topic, 2)]
    providers = ([_commons_search, _openverse_search] if category == "history"
                 else [_openverse_search, _commons_search])

    seen: set[str] = set()
    hits: list[dict] = []
    for q in queries:
        if len(hits) >= count or not q.strip():
            continue
        for provider in providers:
            if len(hits) >= count:
                break
            try:
                for hit in provider(q, limit=count):
                    if hit["url"] in seen:
                        continue
                    seen.add(hit["url"])
                    hits.append(hit)
                    if len(hits) >= count:
                        break
            except Exception as exc:
                log.debug("%s failed for %r: %s", provider.__name__, q[:40], exc)

    pool: list[dict] = []
    for i, hit in enumerate(hits):
        dest = dest_dir / f"_pool_{i:03d}"
        if _download(hit["url"], dest):
            hit = dict(hit, path=str(dest))
            pool.append(hit)
    log.info("Image pool for '%s': %d image(s) from %s", topic[:40], len(pool),
             ", ".join(sorted({h["source"] for h in pool})) or "none")
    return pool


def fetch_image(query: str, dest: Path, category: str = "history") -> dict | None:
    """Find and download ONE openly-licensed image for `query`. Returns metadata."""
    if not query.strip():
        return None
    providers = ([_commons_search, _openverse_search] if category == "history"
                 else [_openverse_search, _commons_search])
    for provider in providers:
        try:
            for hit in provider(query):
                # Normalize to .jpg on disk; Pillow re-encodes later anyway.
                if _download(hit["url"], dest):
                    log.info("Image for '%s' <- %s (%s)", query[:40], hit["source"], hit["license"])
                    return hit
        except Exception as exc:
            log.debug("%s failed for %r: %s", provider.__name__, query[:40], exc)
    return None
