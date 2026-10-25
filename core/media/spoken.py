"""What the narrator actually says, and what goes on screen, from a script.

Scripts carry structure markers ([INTRODUCTION], [CHAPTER: Origins], [CTA]...).
They used to reach the TTS verbatim, so videos opened with the narrator saying
"Introduction, the shocking truth..." and ended "CTA, follow for more...".
Chapter names were glued onto the next sentence ("Chapter. Origins in the
realm of..."). Voice and visual planning both use `spoken_text`, so narration
and scene timing always agree.
"""

from __future__ import annotations

import re

_MARKER = re.compile(r"\[\s*([A-Za-z][A-Za-z _-]*?)\s*(?::\s*([^\]]*))?\]")
_NUMBERS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve"]
CHAPTER_RE = re.compile(r"^Chapter (\w+): (.+?)\.?$")


def spoken_text(full_text: str) -> str:
    """Strip section markers; turn chapter markers into a spoken heading."""
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        tag, name = m.group(1).strip().upper(), (m.group(2) or "").strip().rstrip(".")
        if tag == "CHAPTER" and name:
            count += 1
            n = _NUMBERS[count - 1] if count <= len(_NUMBERS) else str(count)
            return f"\n\nChapter {n}: {name}.\n\n"
        return "\n\n"

    text = _MARKER.sub(repl, full_text or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── on-screen text ──────────────────────────────────────────────────────────
_FILLER = re.compile(
    r"^(?:and|but|so|now|yet|also|then|still|indeed|in fact|of course|"
    r"as we [^,]*,|as we continue [^,]*,|let'?s [^,]*,|this is where|it is|it's)\s+", re.I)
_STOP_END = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "but",
             "that", "which", "who", "with", "by", "is", "are", "was", "were", "be",
             "as", "at", "from", "its", "their", "his", "her", "our", "your", "this"}


def headline(sentence: str, max_words: int = 8) -> str:
    """A short, complete-looking phrase for the screen (never '...'-truncated).

    Prefers a quoted phrase, then the sentence's first clause; drops filler
    openers and never ends on a dangling article or preposition.
    """
    s = (sentence or "").strip()
    m = CHAPTER_RE.match(s)
    if m:
        return f"Chapter {m.group(1)}: {m.group(2)}"
    q = re.search(r"[\"“]([^\"”]{6,90})[\"”]", s)
    if q:
        s = q.group(1)
    for _ in range(3):
        s2 = _FILLER.sub("", s)
        if s2 == s:
            break
        s = s2
    clause = re.split(r"\s*(?:[,;:—–]|\s-\s)\s*", s)[0].strip().rstrip(".!?")
    words = clause.split()
    if len(words) > max_words:
        words = words[:max_words]
    while len(words) > 2 and words[-1].lower().strip(",.") in _STOP_END:
        words.pop()
    out = " ".join(words).strip(" ,.;:")
    return out[:1].upper() + out[1:] if out else ""
