"""Attribution for the pictures and footage actually used in a video.

CC BY and CC BY-SA licences require crediting the author, so these credits go
into the published description, not just a file on disk. Only material that
appears on screen is listed. `credits.txt` keeps the full record with source
links; `block` fits what the licences need into a platform's description limit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_NO_ATTRIBUTION = re.compile(r"public domain|\bcc0\b|\bpd\b|pixabay|pexels|no restrictions", re.I)


def _path(out_dir: Path) -> Path:
    return Path(out_dir) / "credits.json"


def reset(out_dir: Path) -> None:
    """Forget earlier renders of this run, so credits match the final cut."""
    for name in ("credits.json", "credits.txt", "footage_credits.txt"):
        (Path(out_dir) / name).unlink(missing_ok=True)


def load(out_dir: Path) -> list[dict]:
    try:
        return json.loads(_path(out_dir).read_text(encoding="utf-8"))
    except Exception:
        return []


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def add(out_dir: Path, items: list[dict], kind: str) -> None:
    """Record items shown on screen. `kind` is "image" or "footage"."""
    merged = load(out_dir)
    seen = {(c["title"], c["source"]) for c in merged}
    for item in items:
        title = re.sub(r"\.(jpe?g|png|tiff?|webp)$", "", _clean(item.get("title")), flags=re.I)
        key = (title, _clean(item.get("source")))
        if key in seen:
            continue
        seen.add(key)
        merged.append({"title": title[:80], "author": _clean(item.get("credit"))[:60],
                       "license": _clean(item.get("license")), "source": key[1],
                       "page": item.get("page") or "", "kind": kind})
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    _path(out_dir).write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    (Path(out_dir) / "credits.txt").write_text(full_text(merged), encoding="utf-8")


def needs_attribution(item: dict) -> bool:
    return not _NO_ATTRIBUTION.search(f"{item.get('license', '')} {item.get('source', '')}")


def _line(item: dict, link: bool) -> str:
    by = f" by {item['author']}" if item.get("author") else ""
    url = f" {item['page']}" if link and item.get("page") else ""
    return f"- {item['title']}{by} ({item['license']}, {item['source']}){url}"


def full_text(items: list[dict]) -> str:
    lines = ["Credits for material used in this video:"]
    lines += [_line(i, link=True) for i in items]
    return "\n".join(lines) + "\n"


def _summary(items: list[dict]) -> str:
    sources = sorted({i["source"] for i in items if not needs_attribution(i)})
    return f"Also includes free-licence material from {', '.join(sources)}." if sources else ""


def block(items: list[dict], budget: int) -> str:
    """Credits text that fits `budget` characters: everything a licence requires,
    with source links if there's room."""
    if not items or budget < 40:
        return ""
    required = [i for i in items if needs_attribution(i)]
    tail = _summary(items)
    for link in (True, False):
        lines = ["Image credits:", *[_line(i, link) for i in required], tail] if required else [tail]
        text = "\n".join(x for x in lines if x)
        if len(text) <= budget:
            return text
    # Still too long: author and licence are what the licences ask for.
    short = [f"{i['author'] or i['title']} ({i['license']})" for i in required]
    return ("Image credits: " + "; ".join(short))[:budget]
