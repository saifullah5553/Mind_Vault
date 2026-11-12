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
from core.media.credits import is_restricted
from core.media.credits import is_restricted

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


# Never on a family-friendly educational channel, whatever the topic.
_UNSAFE = re.compile(
    r"\bsex|offend|abuse|\bnude|naked|porn|erotic|fetish|\brap(?:e|ed|es|ist)\b|"
    r"suicid|self-harm|\bgore\b|corpse|tortur|lingerie|bikini|"
    r"stripper|striptease|burlesque|pin[- ]?up|topless|showgirl", re.I)
# Charts, models and slides: Commons answers abstract topics with these, and a
# diagram of an academic model is not a documentary image.
_DIAGRAM = re.compile(
    r"diagram|chart|graph|table|model|theory|triangle|wheel|infographic|flowchart|"
    r"schema|figure|\bfig\.|plot|screenshot|logo|icon|slide|poster|meme|"
    r"letter|lettre|manuscript|document|\bpage\b|\bscan|certificate|map of|"
    r"\.(?:png|svg|gif)$", re.I)
# Fine for history (wars, crimes are history) but off-topic for psychology.
_OFF_TOPIC = {"psychology": re.compile(
    r"murder|terror|bomb|unabomb|weapon|\bguns?\b|nazi|war\b|massacre|execution|"
    # A recognisable person the script doesn't mention reads as the person being
    # discussed: Freud over a line about Thorndike is a factual error on screen.
    r"portrait|freud|\bjung\b|pavlov|skinner|einstein|darwin|\bking\b|\bqueen\b|"
    r"\bhenry\b|\bpresident\b|"
    # Religious art over an unrelated line reads as a statement about faith.
    r"\bsaints?\b|madonna|virgin|christ\b|jesus|coronation|crucifi|\bchurch|cathedral|"
    r"mosque|temple|relig|bible|\bangels?\b|\bgods?\b|goddess|prophet|\bpope\b|marathon", re.I),
    # History: wars are history, but a hell or a biblical Deluge over a line about
    # a real flood reads as a statement about faith (Bosch's "Hell and the Flood").
    "history": re.compile(
    r"\bhell\b|\bsaints?\b|madonna|virgin|christ\b|jesus|crucifi|bible|biblical|"
    r"\bangels?\b|\bgods?\b|goddess|prophet|\bpope\b|deluge|\bnoah\b|genius of|"
    r"^(?:File:)?The Flood\b|"
    # Modern wind farms read as "today" over any period story (it was the 1953
    # flood video's thumbnail).
    r"wind ?turbines?|wind ?farm|windpark|offshore wind|"
    # A road sign showed twice in the Iceland test ("Divers Crossing").
    r"\bsigns?\b|signpost|crossing sign|traffic|"
    # "Viking ship replica" found cruise ships named Viking Sky; "Old Covenant"
    # found Rubens' biblical paintings.
    r"\(ship, (?:19[5-9]\d|20\d\d)\)|cruise|\bferry\b|\bholy\b|trinity|adoration|"
    r"sacrifice of|annunciation|nativity|apostles?\b", re.I)}
# Single pictures that passed the filters but were wrong on screen: a modernist
# painting in the 1953 flood film, and a map lettered in Russian on its thumbnail.
_BLOCKED_TITLES = re.compile(
    r"^(?:File:)?North Sea Edward Wadsworth|^(?:File:)?Nederland 1916 rus\b|"
    # The Iceland film: Stockholm's parliament over the Althing, a living namesake
    # of Ingolfur Arnarson, Norway's present crown prince over King Haakon IV,
    # blank manuscript bindings, and a 1928 building over the 1845 Althing.
    r"Riksdagshuset|Bjorn Thor Arnarson|Crown Prince|AM 113 [ab] fol\. - 001|"
    r"University of Iceland, circa 1928|"
    # Re-render: 20th-century Haakon VII over the 1262 king, blank Íslendingabók
    # pages, a 1918 committee photo over the year 930, modern ships over 874.
    r"Haakon VII|Kong Haakon|Haakon 7\.|Haakon in 20\d\d|slendingab|Sambandslaganefnd|"
    r"Coast Guard ship|from V\w+kin museum|"
    # The Japan film: modern Black Ship Festival parades over 1853, a New York hall
    # and a 1930s Dr Townsend over Townsend Harris, the journalist E. D. Morel over
    # the railway engineer Edmund Morel, a French diplomat over Paul Brunat, a 1778
    # Franco-American treaty, a Polish Iron Age sword, Peking, Osaka plaques.
    r"Black Ship Festival|Townsend Harris Hall|Dr\. Francis Townsend|E\. ?D\.? Morel|"
    r"DuchesneDeBellecourt|Treaty of Amity and Commerce and of Alliance between France|"
    r"Przeworsk|Pekin castle|Chuo Ward,? Osaka|Antigone ?Coaling|Ch\. Etienne|"
    r"Tor Hotel|Gankir|US Army Map Service|^(?:File:)?US Navy \d{6}-N|Grave of Toshimichi|"
    r"^(?:File:)?Tsuba |Minton|"
    # Second Japan render: Dr Francis Townsend again, a surgery photo, a courtesan
    # print, a kabuki actor named Kurofune, a 1922 treaty, a 2024 street.
    r"^(?!.*Harris).*Townsend|Amputation|Oiran|as Kurofune|treaty from 1922|"
    r"^(?:File:)?(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December) 20\d\d, buildings|"
    # Third Japan render: a modern 'Kurofune' train, the New York hall again, a 1930s
    # airfield credited to 'Harris & Ewing' as the Harris Treaty, a modern Yokohama
    # bridge, US Navy volunteers in a cemetery.
    r"Izukyu|Harris Hall|Harris (?:&|&amp;) Ewing|Rivers and bridges in Yokohama|CFAY|NAVSUP", re.I)
MIN_WIDTH = 1600   # below this a 1440p frame is visibly upscaled
# "Sarah Chepchirchir - Paris Half Marathon": a photo titled with a person's name
# shows that person. In the mood pool they'd appear over a line about someone else.
_PERSON_TITLE = re.compile(
    r"^(?:File:)?[A-Z][a-z\u00c0-\u017f]+(?: [A-Z][a-z\u00c0-\u017f]+){1,2}\s+[-\u2013,(]")


def acceptable(hit: dict, category: str = "history") -> bool:
    """Safety + relevance gate on an image's title (pixels are never inspected,
    so this is a filter on what the source says the image is)."""
    title = f"{hit.get('title', '')} {hit.get('tags', '')}"
    if _UNSAFE.search(title) or _DIAGRAM.search(hit.get("title", "")):
        return False
    if is_restricted(hit.get("license")):
        return False
    off = _OFF_TOPIC.get(category)
    if _BLOCKED_TITLES.search(title):
        return False
    if off and off.search(title):
        return False
    # Psychology's mood pool only: a history pool searches named places and people.
    if category == "psychology" and _PERSON_TITLE.match(str(hit.get("title", ""))):
        return False
    w = hit.get("width") or 0
    return not w or w >= MIN_WIDTH


def search_queries(topic: str, category: str) -> list[str]:
    """Queries for a coherent pool. Abstract psychology topics return diagrams
    when searched literally, so they are paired with photographic subjects."""
    kw3, kw2 = keywords_from(topic, 3), keywords_from(topic, 2)
    if category == "psychology":
        return [topic, f"{kw2} person", f"{kw2} portrait", "person thinking window",
                "people city street", "human face emotion", kw3]
    return [topic, kw3, kw2, f"{kw2} historical photograph"]


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
# Hand-reviewed Commons collections: technically excellent, high-resolution and
# visually striking (the "Featured" set is the best few thousand on Commons).
CURATED = ("Featured_pictures_on_Wikimedia_Commons", "Quality_images")


def _commons_search(query: str, limit: int = 3, curated: str | None = None) -> list[dict]:
    import httpx

    within = ""
    if curated:
        # Every word must be in the TITLE: plain search matches any word anywhere,
        # so "The Thinker Rodin" returned a cathedral and a Chinese scroll.
        query = " ".join(f"intitle:{w}" for w in query.split())
        within = f' incategory:"{curated}"'
    params = {
        "action": "query", "format": "json", "generator": "search",
        # JPEG = photographs; PNG/SVG on Commons are mostly diagrams.
        "gsrsearch": f"{query} filetype:bitmap filemime:image/jpeg{within}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": "3840",   # large enough for a 4K frame
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
        if not re.search(r"public domain|cc|pd", lic, re.I) or is_restricted(lic):
            continue
        # What the picture shows, in the uploader's words: used to match each
        # line to the picture that fits it (relevance), not by the safety filters.
        about = " ".join(re.sub(r"<[^>]+>", " ", (meta.get(k) or {}).get("value", ""))
                         for k in ("ImageDescription", "Categories"))
        out.append({
            "url": url,
            "title": (page.get("title") or "").replace("File:", ""),
            "about": re.sub(r"\s+", " ", about.replace("|", " ")).strip()[:400],
            "width": info.get("width") or 0,
            "page": info.get("descriptionurl") or "",
            "license": lic or "see Commons",
            "credit": re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:120],
            "source": "Wikimedia Commons",
        })
    return out


# ── Pexels (optional free key) ──────────────────────────────────────────────
def _pexels_photos(query: str, limit: int = 3) -> list[dict]:
    """Professional stock photos; free for commercial use, attribution optional.
    Used only when PEXELS_API_KEY is set (free account at pexels.com/api)."""
    import os

    import httpx

    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    r = httpx.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                  params={"query": query, "per_page": str(min(limit, 40)),
                          "orientation": "landscape", "size": "large"}, timeout=20)
    r.raise_for_status()
    out = []
    for p in r.json().get("photos", []):
        src = p.get("src") or {}
        url = src.get("original") or src.get("large2x")
        if not url:
            continue
        out.append({
            "url": url, "title": p.get("alt") or query, "width": p.get("width") or 0,
            "page": p.get("url") or "",
            "license": "Pexels License", "credit": p.get("photographer") or "",
            "source": "Pexels",
        })
    return out


def fetch_named(name: str, dest: Path, category: str = "history") -> dict | None:
    """The actual subject a line names ("Aristotle", "Edward Thorndike").

    Title-matched on Commons (every word of the name in the file title), best
    resolution first. Portraits of historical figures are often small, so the
    floor is lower than for mood imagery; callers present small ones on a
    blurred backdrop instead of upscaling them.
    """
    words = name.split()
    # No surname-only fallback: "Edward Thorndike" -> "Thorndike" matched a
    # memorial to George Thorndike Angell. A wrong person is worse than none;
    # the scene then simply gets a mood picture.
    try:
        hits = _commons_search(" ".join(f"intitle:{w}" for w in words), 20)
    except Exception as exc:
        log.debug("named search failed for %r: %s", name, exc)
        return None
    # At the start, in order, allowing a middle initial: "Edward L Deci" is Edward
    # Deci, but "Hull Maintenance Technician Serena Clark" and "Mitch Clark Hull KR"
    # (a rugby player at the club Hull KR) are not Clark Hull.
    whole_name = re.compile(
        r"^(?:(?:portrait|photo|photograph|picture|painting|bust|statue)[\s_]+of[\s_]+|"
        r"(?:dr|prof|professor|sir)\.?[\s_]+)?"
        + r"(?:[\s_]+\w\.?)?[\s_]+".join(map(re.escape, words)) + r"\b", re.I)
    ok = [h for h in hits if (h.get("width") or 0) >= 600 and not is_restricted(h.get("license"))
          and not _UNSAFE.search(h["title"]) and not _DIAGRAM.search(h["title"])
          # A named place gets the same subject checks as the pool: "North Sea"
          # found a 1928 modernist painting, "Nederland" a map in Russian.
          and not _BLOCKED_TITLES.search(h["title"])
          and not (_OFF_TOPIC.get(category) and _OFF_TOPIC[category].search(h["title"]))
          and whole_name.match(h["title"])
          # A lone name is ambiguous ("Thorndike" -> the Thorndike Hotel): it
          # must START the title and the title must describe a likeness.
          and (len(words) > 1 or (h["title"].lower().startswith(words[0].lower())
                                  and _GOOD_SHOT.search(h["title"])))]
    for hit in sorted(ok, key=lambda h: _named_rank(h, name)):
        if _download(hit["url"], dest):
            return dict(hit, path=str(dest), named=name)
    return None


_GOOD_SHOT = re.compile(r"portrait|bust|statue|sculpture|painting|photograph|\bphoto\b", re.I)
_POOR_SHOT = re.compile(r"museum|bag|house|grave|tomb|plaque|signature|book|poetics|"
                        r"edition|cover|stamp|coin|street|building|room|desk|exhibit", re.I)


def _named_rank(hit: dict, name: str) -> tuple:
    """Sort key: a portrait/bust/statue of the subject first, objects last."""
    title = hit.get("title", "")
    score = 0
    score += 3 if _GOOD_SHOT.search(title) else 0
    score -= 3 if _POOR_SHOT.search(title) else 0
    score += 2 if title.lower().startswith(name.split()[0].lower()) else 0
    score += 1 if all(w.lower() in title.lower() for w in name.split()) else 0
    return (-score, -(hit.get("width") or 0))


def fetch_themed_pool(topic: str, category: str, per_theme: int, dest_dir: Path,
                      themes: dict | None = None) -> list[dict]:
    """A pool of eye-catching pictures grouped by visual theme (see themes.py).

    Sources in order of visual quality: Pexels (if a key is set), Commons
    Featured pictures, Commons Quality images, Openverse large photographs.
    Every hit passes the same safety / diagram / HD filter as fetch_pool.
    """
    from core.media.themes import THEMES
    themes = themes or THEMES
    dest_dir.mkdir(parents=True, exist_ok=True)
    sources = [_pexels_photos,
               lambda q, limit: _commons_search(q, limit, CURATED[0]),
               lambda q, limit: _commons_search(q, limit, CURATED[1]),
               _openverse_search]
    seen: set[str] = set()
    pool: list[dict] = []
    for theme, (_cue, queries) in themes.items():
        got = 0
        for q in queries:
            for source in sources:
                if got >= per_theme:
                    break
                try:
                    hits = source(q, per_theme * 2)
                except Exception as exc:
                    log.debug("image source failed for %r: %s", q, exc)
                    continue
                for hit in hits:
                    if got >= per_theme:
                        break
                    title_key = re.sub(r"[^a-z]", "", str(hit.get("title", "")).lower())[:40]
                    if hit["url"] in seen or (title_key and title_key in seen) \
                            or not acceptable(hit, category):
                        continue
                    seen.update({hit["url"], title_key})
                    dest = dest_dir / f"_pool_{len(pool):03d}"
                    if _download(hit["url"], dest):
                        pool.append(dict(hit, path=str(dest), theme=theme))
                        got += 1
    log.info("Themed image pool for '%s': %d picture(s) across %d themes from %s",
             topic[:40], len(pool), len({p["theme"] for p in pool}),
             ", ".join(sorted({p["source"] for p in pool})) or "none")
    return pool


# ── Openverse ───────────────────────────────────────────────────────────────
def _openverse_search(query: str, limit: int = 3) -> list[dict]:
    import httpx

    r = httpx.get("https://api.openverse.org/v1/images/",
                  params={"q": query, "page_size": str(min(limit, 20)),
                          # commercial + modification: we crop and grade, so
                          # no-derivatives licences are out.
                          "license_type": "commercial,modification", "mature": "false",
                          "category": "photograph", "size": "large"},
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
            "tags": " ".join(tg.get("name", "") for tg in (item.get("tags") or [])[:12]),
            "page": item.get("foreign_landing_url") or "",
            "width": item.get("width") or 0,
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


def topic_parts(topic: str) -> list[tuple[str, re.Pattern | None]]:
    """'flood 1953 @ flood|storm; Kinderdijk @ windmill' -> [(query, cue), ...].

    A TOPIC with ';' names several picture searches; the words after '@' are the
    lines each one belongs to. A plain TOPIC is one search with no cue.
    """
    parts = []
    for raw in (topic or "").split(";"):
        query, _, cues = raw.partition("@")
        if query.strip():
            cue = re.compile(r"\b(?:" + cues.strip() + ")", re.I) if cues.strip() else None
            parts.append((query.strip(), cue))
    return parts or [(topic or "", None)]


def part_per_line(lines: list[str], topic: str) -> list[int]:
    """The TOPIC part each line belongs to: the last part whose cue this line (or
    an earlier one) mentions, so a story told in order shows each subject in turn."""
    parts = topic_parts(topic)
    out, current = [], 0
    for line in lines:
        hits = [i for i, (_, cue) in enumerate(parts) if cue and cue.search(line or "")]
        if hits and current not in hits:
            # "the families sailed from Norway" matches the settlers' cue and the
            # later Norway chapter's: the story moves on to the nearest part ahead.
            ahead = [i for i in hits if i > current]
            current = min(ahead) if ahead else max(hits)
        out.append(current)
    return out


# ── matching each line to its picture ───────────────────────────────────────
# Within a TOPIC part the pictures used to be handed out in search order, so a
# line about the Law Rock could get a snowy town from the same search. Each line
# now gets the free picture whose title, description and search words share the
# most words with it, and a picture that shows a place or person the line NAMES
# is claimed by that line first.
_FOLD = str.maketrans({"þ": "th", "Þ": "Th", "ð": "d", "Ð": "D", "æ": "ae", "Æ": "Ae",
                       "ø": "o", "Ø": "O", "ß": "ss"})
_WEAK = {"file", "jpg", "jpeg", "photo", "photograph", "image", "picture", "view",
         "panorama", "category", "categories", "commons", "wikimedia", "taken", "uploaded",
         "own", "work", "camera", "nikon", "canon", "dsc", "img", "also", "very", "just",
         "only", "then", "they", "these", "those", "over", "after", "before", "under",
         "every", "each", "some", "many", "much", "made", "make", "like", "even", "came",
         "come", "went", "said", "says", "first", "last", "year", "years", "time", "had",
         "has", "his", "her", "him", "she", "here", "now", "out", "off", "can", "may"}
STRONG_MATCH = 4.0       # a named subject in the title, or two title words


def _fold(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", (text or "").translate(_FOLD))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _stem(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def match_words(text: str) -> set[str]:
    """Content words of a line or a picture's title, accents folded, plurals cut."""
    words = re.findall(r"[a-z]{3,}|\d{3,4}", _fold(text).replace("'s", ""))
    return {_stem(w) for w in words if w not in _STOP and w not in _WEAK}


def named_words(text: str) -> set[str]:
    """Names in a line: capitalised words that don't start a sentence."""
    out: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for w in re.findall(r"[\w'-]+", sentence)[1:]:
            if w[:1].isupper() and len(w) > 2:
                out |= match_words(w)
    return out


# A picture whose title names a person shows that person: over a line about
# someone else it is a wrong person on screen (King Inge over Thorgeir).
_PERSON_PICTURE = re.compile(
    r"\b(?:king|queen|prince|princess|saint|bishop|jarl|earl|president|emperor|empress|"
    r"pope|chieftain|portrait|bust of|statue of|coronation|royalty|royals)\b", re.I)


def _common(a: set[str], b: set[str]) -> set[str]:
    """Words of `a` found in `b`, a long word also matching its longer or shorter
    form (Althing / Althingi, Thingvellir / Thingvallavatn is not: 6+ letters)."""
    out = a & b
    for w in a - out:
        if len(w) >= 6 and any(len(x) >= 6 and (x.startswith(w) or w.startswith(x)) for x in b):
            out.add(w)
    return out


def relevance(line: str, hit: dict) -> tuple[float, bool]:
    """How well a picture fits a line, and whether it shows something the line names.

    Title words count most, then the uploader's description, then the words the
    TOPIC gave its search ("Lögberg Thingvellir = Law Rock": pictures of the
    Lögberg fit lines about the Law Rock). A picture of a person the line does
    not name scores below zero, so it is used only when nothing else is left.
    """
    words = match_words(line)
    if not words:
        return 0.0, False
    title = match_words(hit.get("title", ""))
    about = match_words(f"{hit.get('about', '')} {hit.get('tags', '')}") - title
    label = match_words(hit.get("label", "")) - title - about
    query = match_words(hit.get("query", "")) - title - about - label
    names = _common(named_words(line), title | about | label)
    score = (2 * len(_common(words, title)) + len(_common(words, about))
             + 1.5 * len(_common(words, label)) + 0.5 * len(_common(words, query))
             + 2 * len(names))
    if _PERSON_PICTURE.search(hit.get("title", "")) and not (named_words(line) & title):
        score -= 100
    return score, bool(names)


def off_story_places(pool: list[dict], lines: list[str]) -> list[dict]:
    """The pool without pictures of places in countries the story never names.

    Uses the map data (core/media/maps.py): countries, their adjectives
    (Australia -> Australian) and cities of 100,000+ people. Without the data
    the pool is returned as it is."""
    try:
        from core.media import maps
        if not maps.ensure_data():
            return pool
        story = set()
        for line in lines:
            story.update(maps.countries_in(line))
            for name in maps.places_in(line):
                story.update(p["country"] for p in maps._places() if p["name"] == name)
        if not story:
            return pool
        adjectives = maps.adjective_patterns()
        keep = []
        for hit in pool:
            title = str(hit.get("title", ""))
            where = set(maps.countries_in(title))
            where.update(c for pat, c in adjectives if pat.search(title))
            # A city says where the photo was taken: one in a country outside the
            # story drops it even if the title also names a story country
            # ("Danish Royalty Tours Minneapolis").
            abroad = False
            for name in maps.places_in(title):
                cands = {p["country"] for p in maps._places() if p["name"] == name}
                if cands and not cands & story:
                    abroad = True
            if abroad or (where and not where & story):
                log.info("Off-story place dropped: %s", title[:80])
                continue
            keep.append(hit)
        return keep
    except Exception as exc:
        log.debug("place filter skipped (%s)", exc)
        return pool


def assign_pictures(lines: list[str], parts: list[int], pool: list[dict],
                    shows: list[bool]) -> list[dict | None]:
    """One pool picture per line.

    Lines that show their still each get a different picture where the pool
    allows: first the strong matches (a picture of the place the line names),
    then, in story order, the best-fitting free picture of the line's own TOPIC
    part, then the free picture of the nearest part. Lines that don't show
    their still (footage, cards) get a fallback that doesn't use a picture up.
    """
    if not pool:
        return [None] * len(lines)
    has_parts = any("part" in m for m in pool)
    part_of = (lambda m: m.get("part", 0)) if has_parts else (lambda m: 0)
    want = [(parts[i] if i < len(parts) else 0) if has_parts else 0 for i in range(len(lines))]
    scores = [[relevance(line, m) for m in pool] for line in lines]
    out: list[dict | None] = [None] * len(lines)
    used = [0] * len(pool)

    # 1) Strong matches claim their picture, best first. Across parts only when
    #    the picture shows what the line names.
    strong = sorted(((scores[i][j][0], -i, i, j) for i in range(len(lines)) if shows[i]
                     for j in range(len(pool))
                     if scores[i][j][0] >= STRONG_MATCH
                     and (part_of(pool[j]) == want[i] or scores[i][j][1])), reverse=True)
    for _s, _neg, i, j in strong:
        if out[i] is None and not used[j]:
            out[i], used[j] = pool[j], 1

    # 2) The rest in story order.
    for i in range(len(lines)):
        if not shows[i] or out[i] is not None:
            continue
        free = [j for j in range(len(pool)) if not used[j]]
        if free:
            def rank(j):
                sc, same = scores[i][j][0], part_of(pool[j]) == want[i]
                # Own part first; then any picture that fits the line; then the
                # nearest part. A picture of an unnamed person comes last.
                return (sc < 0, 0 if same else 1 if sc >= 2 else 2,
                        0 if same or sc >= 2 else abs(part_of(pool[j]) - want[i]), -sc, j)
            j = min(free, key=rank)
        else:      # pool spent: repeat the least-used fitting picture of this part
            j = min(range(len(pool)), key=lambda j: (part_of(pool[j]) != want[i], used[j],
                                                     -scores[i][j][0], j))
        out[i] = pool[j]
        used[j] += 1

    # 3) Fallback stills behind footage and cards: never use a picture up.
    for i in range(len(lines)):
        if not shows[i]:
            j = min(range(len(pool)), key=lambda j: (part_of(pool[j]) != want[i], used[j],
                                                     -scores[i][j][0], j))
            out[i] = pool[j]
    return out


def fetch_pool(topic: str, count: int, dest_dir: Path, category: str = "history") -> list[dict]:
    """Fetch a COHERENT pool of images about `topic`.

    DESIGN: searching per-scene narration returns visually random results (a Roman
    Empire line can match a Bulgarian mountain). Searching once on the topic and
    distributing the results keeps every frame on-subject and consistent — and is
    far faster (one query, N downloads instead of N queries).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    parts = topic_parts(topic)
    providers = ([_commons_search, _openverse_search] if category == "history"
                 else [_openverse_search, _commons_search])
    # Each query is asked once per provider: the top-up pass used to ask again,
    # and a 7-part TOPIC took 28 minutes instead of 5.
    answers: dict[tuple[str, str], list[dict]] = {}

    def _once(provider):
        def ask(q: str, limit: int = 3) -> list[dict]:
            key = (provider.__name__, q)
            if key not in answers:
                answers[key] = provider(q, limit=50)
            return answers[key][:limit]
        ask.__name__ = provider.__name__
        return ask
    providers = [_once(pr) for pr in providers]

    seen: set[str] = set()
    hits: list[dict] = []
    share = -(-count // len(parts))
    for part, (query, _) in enumerate(parts):
        # 'a + b + c' gives one part several searches, so a narrow subject
        # still fills its share of photos instead of repeating a few. Each
        # search gets an equal slice first (eight postcards of one Bergen hall
        # filled a whole part), then the part is topped up in order.
        # 'Lögberg = Law Rock' labels a search's pictures with the words its
        # lines use (see relevance).
        alts = [a.partition("=") for a in query.split("+") if a.strip()]
        slice_ = -(-share // max(1, len(alts)))
        found: list[dict] = []
        for search, _eq, label in alts:
            qs = list(dict.fromkeys(search_queries(search.strip(), category)))
            got = _pool_hits(qs, min(slice_, share - len(found)), providers, category, seen)
            found += [dict(h, label=label.strip()) for h in got]
        for search, _eq, label in alts:
            if len(found) >= share:
                break
            qs = list(dict.fromkeys(search_queries(search.strip(), category)))
            got = _pool_hits(qs, share - len(found), providers, category, seen)
            found += [dict(h, label=label.strip()) for h in got]
        hits += [dict(h, part=part) for h in found] if len(parts) > 1 else found

    pool: list[dict] = []
    looks: list[int] = []
    for i, hit in enumerate(hits):
        dest = dest_dir / f"_pool_{i:03d}"
        if _download(hit["url"], dest):
            # Museums hold several prints of one engraving under different
            # titles: compare the pictures themselves, and keep one.
            look = _look(dest)
            if look is not None and any(_near(look, other) for other in looks):
                dest.unlink(missing_ok=True)
                continue
            if _too_dark(dest):
                dest.unlink(missing_ok=True)       # a near-black interior showed as a blank
                continue
            if look is not None:
                looks.append(look)
            hit = dict(hit, path=str(dest))
            pool.append(hit)
    log.info("Image pool for '%s': %d image(s) from %s", topic[:40], len(pool),
             ", ".join(sorted({h["source"] for h in pool})) or "none")
    return pool


def _look(path: Path) -> int | None:
    """A 64-bit difference hash: near-identical pictures get near-identical hashes."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            px = list(im.convert("L").resize((9, 8)).getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (px[row * 9 + col] < px[row * 9 + col + 1])
        return bits
    except Exception:
        return None


def _too_dark(path: Path) -> bool:
    """Near-black or flat pictures read as a blank frame on screen."""
    try:
        from PIL import Image, ImageStat
        with Image.open(path) as im:
            st = ImageStat.Stat(im.convert("L").resize((64, 36)))
        return st.mean[0] < 40 or st.stddev[0] < 14
    except Exception:
        return False


def _near(a: int, b: int, limit: int = 10) -> bool:
    return bin(a ^ b).count("1") <= limit


def _series_key(title: str) -> str:
    """The same key for every picture of a numbered series: 'Thingvellir-63a-Lögberg'
    and 'Thingvellir-63b-Lögberg' were four near-identical shots in a row."""
    t = re.sub(r"\d+[a-z]?\b", "", _fold(str(title)))
    return re.sub(r"[^a-z]", "", t)[:40]


def _pool_hits(queries: list[str], count: int, providers, category: str,
               seen: set[str]) -> list[dict]:
    hits: list[dict] = []
    for q in queries:
        if len(hits) >= count or not q.strip():
            continue
        for provider in providers:
            if len(hits) >= count:
                break
            try:
                # Ask for more than needed: many results fail the licence,
                # size or subject checks.
                for hit in provider(q, limit=min(50, count * 3)):
                    title_key = _series_key(hit.get("title", ""))
                    if hit["url"] in seen or (title_key and title_key in seen) \
                            or not acceptable(hit, category):
                        continue
                    seen.update({hit["url"], title_key})
                    hits.append(dict(hit, query=q))
                    if len(hits) >= count:
                        break
            except Exception as exc:
                log.debug("%s failed for %r: %s", provider.__name__, q[:40], exc)
    return hits


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
