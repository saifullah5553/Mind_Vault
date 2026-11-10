"""Cut a finished long video into numbered vertical reels (Part 1/N, Part 2/N, ...).

The reels reuse the long video's own narration, pictures and music, so they carry
the same checked facts and licences. This module holds the pure logic: reading the
caption timings, finding sentence breaks, and choosing where each part starts and
ends. Rendering and uploading live in scripts/make_reels.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_SENTENCE_END = re.compile(r"[.?!][\"'”’)]*$")

MIN_PARTS, MAX_PARTS = 5, 10
TARGET_SECONDS = 70.0          # a part of about a minute keeps most viewers to the end
MIN_SECONDS, MAX_SECONDS = 30.0, 110.0


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Sentence:
    start: float
    end: float
    text: str
    cues: list[Cue]


@dataclass
class Part:
    number: int
    total: int
    start: float          # cut points in the long video, seconds
    end: float
    sentences: list[Sentence]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


def _secs(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (10 ** len(ms))


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                g = m.groups()
                body = " ".join(x.strip() for x in lines[i + 1:] if x.strip())
                if body:
                    cues.append(Cue(_secs(*g[:4]), _secs(*g[4:]), body))
                break
    return cues


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", text.lower()).strip()


def sentences(cues: list[Cue], cta: str = "") -> list[Sentence]:
    """Join caption cues into sentences, and drop the closing call to action."""
    out: list[Sentence] = []
    cur: list[Cue] = []
    for c in cues:
        cur.append(c)
        if _SENTENCE_END.search(c.text.strip()):
            out.append(Sentence(cur[0].start, cur[-1].end, " ".join(x.text for x in cur), cur))
            cur = []
    if cur:
        out.append(Sentence(cur[0].start, cur[-1].end, " ".join(x.text for x in cur), cur))
    key = _letters(cta)[:30]
    if key:
        for i, s in enumerate(out):
            if _letters(s.text).startswith(key):
                return out[:i]
    return out


def part_count(seconds: float) -> int:
    """5-10 parts of about a minute each."""
    n = round(seconds / TARGET_SECONDS)
    while n < MAX_PARTS and seconds / max(n, 1) > 95:
        n += 1
    return max(MIN_PARTS, min(MAX_PARTS, n))


def split(sents: list[Sentence], parts: int | None = None) -> list[Part]:
    """Split the story into parts at sentence breaks.

    Each part is close to the same length, and a break after a longer pause (a
    paragraph) is preferred, so a part starts where a new thought starts.
    """
    if not sents:
        return []
    total = sents[-1].end - sents[0].start
    n = parts or part_count(total)
    n = max(1, min(n, len(sents)))
    target = total / n
    k = len(sents)
    inf = float("inf")

    def cost(i: int, j: int) -> float:
        dur = sents[j].end - sents[i].start
        if not MIN_SECONDS <= dur <= MAX_SECONDS and n > 1:
            return inf
        c = ((dur - target) / 8.0) ** 2
        if j + 1 < k:                                   # reward a pause at the break
            c -= 2.0 * min(1.5, sents[j + 1].start - sents[j].end)
        return c

    # best[p][j]: the cheapest way to cover sentences 0..j with p parts.
    best = [[inf] * k for _ in range(n + 1)]
    back = [[-1] * k for _ in range(n + 1)]
    for j in range(k):
        best[1][j] = cost(0, j)
    for p in range(2, n + 1):
        for j in range(k):
            for i in range(p - 1, j + 1):
                prev = best[p - 1][i - 1]
                if prev == inf:
                    continue
                c = prev + cost(i, j)
                if c < best[p][j]:
                    best[p][j], back[p][j] = c, i
    if best[n][k - 1] == inf:
        raise ValueError(f"cannot split {total:.0f}s into {n} parts of "
                         f"{MIN_SECONDS:.0f}-{MAX_SECONDS:.0f}s; try another --parts")
    bounds, j = [], k - 1
    for p in range(n, 0, -1):
        i = back[p][j] if p > 1 else 0
        bounds.append((i, j))
        j = i - 1
    bounds.reverse()

    out: list[Part] = []
    for num, (i, j) in enumerate(bounds, 1):
        # Cut inside the pause between sentences, so no audio is heard twice.
        if i == 0:
            start = 0.0
        else:
            gap = sents[i].start - sents[i - 1].end
            start = max(sents[i - 1].end + 0.6 * gap, sents[i].start - 0.12)
        gap = sents[j + 1].start - sents[j].end if j + 1 < k else 1.0
        end = sents[j].end + min(0.45, 0.6 * gap)
        out.append(Part(num, n, round(start, 3), round(end, 3), sents[i:j + 1]))
    return out


def _stamp(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def part_srt(part: Part) -> str:
    """The part's captions, timed from the start of the reel."""
    rows = []
    cues = [c for s in part.sentences for c in s.cues]
    for n, c in enumerate(cues, 1):
        a = max(0.0, c.start - part.start)
        b = min(part.duration, c.end - part.start)
        rows.append(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{c.text}\n")
    return "\n".join(rows)


def read_titles(text: str, parts: int) -> list[tuple[str, str]]:
    """`HEADLINE | YouTube title` per line, one line per part (# lines are notes)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, _, title = line.partition("|")
        head, title = head.strip(), title.strip()
        if not head or not title:
            raise ValueError(f"titles line needs 'HEADLINE | YouTube title': {line!r}")
        rows.append((head, title))
    if len(rows) != parts:
        raise ValueError(f"{len(rows)} title line(s) for {parts} part(s)")
    return rows


def youtube_title(title: str, number: int, total: int) -> str:
    tag = f"(Part {number}/{total})"
    title = re.sub(r"\s*\(?part\s*\d+\s*/\s*\d+\)?\s*$", "", title, flags=re.I).strip()
    return f"{title[:100 - len(tag) - 1].rstrip()} {tag}"


# Seconds at the end of each part that carry the call to action.
NEXT_STEP_SECONDS = 4.0


def next_step(number: int, total: int) -> str:
    """What the reel asks the viewer to do before the disclaimer card."""
    if number < total:
        return f"FOLLOW FOR PART {number + 1}/{total}"
    return "FULL VIDEO: LINK BELOW"
