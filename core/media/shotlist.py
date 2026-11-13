"""The shot list: every line beside what will be on screen, with the picture risks a
director would catch flagged. Used before the render (`run_pipeline --plan-only`,
storage/images/<run_id>/picture_plan.txt) and after it (scripts.qa_report).

The flags come from the faults found by hand in the first weeks' renders:
namesakes (a 1930s Dr Francis Townsend for the consul Townsend Harris, the
journalist E. D. Morel for the engineer Edmund Morel, a hall named after Harris),
a word matched only in the photographer's credit ('Harris & Ewing'), modern photos
over old events, and pictures that share no word at all with their line.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")
_NOW = re.compile(r"\b(?:today|now|still|survives?|surviving|museum|UNESCO|modern|"
                  r"present|restored|rebuilt|ruins?|remains)\b", re.I)
_CREDIT = re.compile(r"\b(?:by|photo(?:graph)?(?:ed)? by|photographer)\b.*$", re.I)
_NAME = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+)+)")
_HONORIFIC = {"commodore", "president", "emperor", "empress", "king", "queen", "sir", "lord",
              "general", "admiral", "captain", "consul", "prince", "princess", "saint", "st",
              "pope", "the", "of", "and", "in", "at", "with"}


def _words(text: str) -> set[str]:
    from core.media.stock import match_words
    return match_words(text or "")


def risks(line: str, title: str, about: str = "", category: str = "history") -> list[str]:
    """What a director should look at twice in this line's picture."""
    out: list[str] = []
    if not title:
        return out
    t_words = _words(title)
    l_words = _words(line)
    plain = _CREDIT.sub("", title)
    shared = l_words & t_words
    if shared and not (l_words & _words(plain)):
        out.append("matches only the photographer's credit")
    elif not shared and not (l_words & _words(about)):
        out.append("shares no word with the line")
    if category == "history" and _YEAR.search(title) and not _NOW.search(line):
        out.append("modern photo over a past event")
    for m in _NAME.finditer(line):
        tokens = [w for w in m.group(1).split() if w.lower() not in _HONORIFIC]
        if len(tokens) < 2:
            continue
        hits = [w for w in tokens if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", title)]
        if hits and len(hits) < len(tokens):
            # One part of a two-part name: is it beside a different name in the title?
            w = hits[0]
            near = re.search(rf"([A-Z][\w.]*\.?)\s+{re.escape(w)}|{re.escape(w)}\s+([A-Z]\w+)", title)
            other = near and (near.group(1) or near.group(2))
            if other and other.lower().strip(".") not in {x.lower() for x in tokens} | _HONORIFIC:
                out.append(f"namesake? '{near.group(0)}' for '{m.group(1)}'")
    return out


def _shown(sc: dict) -> str:
    kind = sc.get("animation_kind") or ""
    if kind.startswith("map:"):
        spec = json.loads(kind[4:])
        return f"MAP {spec.get('place') or ''} {spec.get('country') or ''}".strip()
    if kind.startswith(("showcase:", "layers:")):
        from core.media.scenes import describe
        return describe(kind)
    if kind:
        return f"CARD {kind.split(':', 1)[0]}"
    return sc.get("source") or Path(sc.get("clip_path") or sc.get("image_path") or "").name


def build(scenes: list, category: str = "history") -> tuple[str, int]:
    """(shot list text, number of flagged lines). `scenes` are Scene objects or dicts."""
    rows, flagged, t = [], 0, 0.0
    for s in scenes:
        sc = s if isinstance(s, dict) else s.model_dump()
        shown = _shown(sc)
        if sc.get("label"):
            shown += f"  [caption: {sc['label']}]"
        if sc.get("tag"):
            shown += f"  [{sc['tag']}]"
        flags = [] if (sc.get("animation_kind") or sc.get("tag")) else \
            risks(sc["narration"], sc.get("source") or "", category=category)
        m, sec = divmod(int(t), 60)
        rows.append(f"{m}:{sec:02d}  {sc['narration'].strip()}\n      ON SCREEN: {shown}"
                    + "".join(f"\n      !! {f}" for f in flags))
        flagged += bool(flags)
        t += float(sc.get("duration") or 0)
    head = ("Every line and what is on screen. Check each picture belongs to its line.\n"
            f"Lines marked !! need a second look ({flagged}).\n\n")
    return head + "\n".join(rows) + "\n", flagged


def contact_sheet(scenes: list, out: Path, cols: int = 8, size=(320, 180)) -> Path | None:
    """The planned stills, numbered, for a one-glance check before the render."""
    from PIL import Image, ImageDraw
    items = []
    for s in scenes:
        sc = s if isinstance(s, dict) else s.model_dump()
        if sc.get("animation_kind") or not sc.get("image_path") or sc.get("clip_path"):
            continue
        items.append(sc)
    if not items:
        return None
    w, h = size
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 4), rows * (h + 4)), (20, 20, 20))
    for i, sc in enumerate(items):
        try:
            im = Image.open(sc["image_path"]).convert("RGB").resize(size)
        except Exception:
            continue
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 44, 22), fill=(0, 0, 0))
        d.text((4, 4), str(sc["index"]), fill=(255, 255, 0))
        sheet.paste(im, ((i % cols) * (w + 4), (i // cols) * (h + 4)))
    sheet.save(out, quality=85)
    return out
