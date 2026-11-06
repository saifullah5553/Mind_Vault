"""Load a human-written or human-edited script from a text file.

Format: optional `KEY: value` header lines, then the script with the usual
[INTRODUCTION] / [CHAPTER: Name] / [CONCLUSION] / [CTA] markers.

    TITLE: The title people will see
    DESCRIPTION: The opening of the video description.
    THUMBNAIL: SHORT THUMBNAIL TEXT

    [INTRODUCTION]
    ...
"""

from __future__ import annotations

import re
from pathlib import Path

from core.media.spoken import sentences, spoken_text
from core.schemas import Script

_SECTION = re.compile(r"\[\s*(INTRODUCTION|CHAPTER|CONCLUSION|CTA)\b[^\]]*\]", re.I)


def load(path: str | Path) -> tuple[Script, dict]:
    """Returns the Script and its header fields ({"title", "description", ...})."""
    raw = Path(path).read_text(encoding="utf-8").strip()
    start = _SECTION.search(raw)
    if not start:
        raise ValueError(f"{path}: no [INTRODUCTION]/[CHAPTER] markers found")
    head = {m.group(1).lower(): m.group(2).strip()
            for m in re.finditer(r"^([A-Z_]+):\s*(.+)$", raw[:start.start()], re.M)}
    body = raw[start.start():]

    parts: dict[str, list[str]] = {"introduction": [], "chapter": [], "conclusion": [], "cta": []}
    marks = list(_SECTION.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        kind = m.group(1).lower()
        keep_marker = kind == "chapter"       # chapters stay marked inside `body`
        parts[kind].append(body[m.start() if keep_marker else m.end():end].strip())

    spoken = spoken_text(body)
    lines = sentences(spoken)
    chapters = sum(1 for _ in re.finditer(r"\[\s*CHAPTER", body, re.I))
    script = Script(
        title=head.get("title") or (lines[0][0] if lines else "Untitled"),
        hook=lines[0][0] if lines else "",
        introduction="\n\n".join(parts["introduction"]),
        body="\n\n".join(parts["chapter"]),
        ending="\n\n".join(parts["conclusion"]),
        cta="\n\n".join(parts["cta"]),
        full_text=body,
        word_count=len(spoken.split()),
        style="hand-edited",
        structure=f"documentary-{chapters}-chapters" if chapters else "hook-story-lesson",
    )
    return script, head
