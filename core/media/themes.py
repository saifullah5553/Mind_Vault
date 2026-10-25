"""Visual themes: pick eye-catching imagery by what a beat MEANS, not its words.

Literal keyword search fails for abstract subjects: "motivation" on Wikimedia
returns diagrams of academic models, "solitude" returns vintage cars from a race
called the Solitude Revival. A documentary instead cuts to imagery that carries
the mood: a summit for ambition, a sunrise for hope, a lone figure for doubt.

Each theme has short, title-style subjects searched in curated, high-resolution
libraries (see stock.fetch_themed_pool; Commons matches them against titles).
Each scene is matched to a theme from its narration and gets an unused picture
from that theme.
"""

from __future__ import annotations

import re

# theme -> (narration cue regex, image search queries)
THEMES: dict[str, tuple[str, list[str]]] = {
    "ambition": (r"goal|ambition|achiev|success|striv|effort|drive|determin|persever|"
                 r"climb|purpose|motivat|pursu|passion|win\b",
                 ["summit", "mountaineer", "marathon", "runner"]),
    "hope": (r"hope|change|new\b|begin|future|grow|transform|possib|dream|start|light",
             ["sunrise", "dawn", "sunrise lake"]),
    "mind": (r"mind|think|thought|idea|philosoph|aristotle|plato|socrates|theor|reason|"
             r"brain|psycholog|research|study|scien|concept|understand|believ",
             ["Thinker Rodin", "School Athens", "marble bust", "reading room", "library"]),
    "struggle": (r"doubt|fear|anxi|struggl|fail|lose|lost|alone|stress|pain|dark|quit|"
                 r"stop|hinder|silence|hidden|unconscious|shadow",
                 ["fog forest", "storm", "lone tree", "wilderness"]),
    "people": (r"people|society|social|others|group|together|crowd|culture|community|"
               r"human|everyone|we\b",
               ["crowd", "street market", "festival"]),
    "reward": (r"reward|pleasure|joy|happ|satisf|celebrat|prize|praise|enjoy",
               ["fireworks", "lantern festival", "celebration"]),
    "habit": (r"habit|routine|daily|repeat|practice|work|learn|school|train|skill|"
              r"behavio",
              ["workshop", "craftsman", "classroom", "violinist"]),
    "default": (r"", ["milky way", "mountain panorama", "waves", "forest"]),
}

_CUES = {name: re.compile(cue, re.I) for name, (cue, _) in THEMES.items() if cue}


def theme_of(text: str) -> str:
    """The theme whose cues appear most in `text` ('default' if none)."""
    best, hits = "default", 0
    for name, rx in _CUES.items():
        n = len(rx.findall(text or ""))
        if n > hits:
            best, hits = name, n
    return best


def pick(text: str, pool: list[dict], used: dict[str, int]) -> dict | None:
    """Least-used picture of the scene's theme; any least-used one as fallback.

    Pictures repeat only once every other option is used up, and consecutive
    scenes on the same theme still get different pictures.
    """
    if not pool:
        return None
    theme = theme_of(text)
    same = [m for m in pool if m.get("theme") == theme] or pool
    choice = min(same, key=lambda m: (used.get(m["path"], 0), pool.index(m)))
    if used.get(choice["path"], 0) > 0:
        # Every picture of this theme is used: prefer any unused picture instead.
        fresh = [m for m in pool if used.get(m["path"], 0) == 0]
        if fresh:
            choice = fresh[0]
    used[choice["path"]] = used.get(choice["path"], 0) + 1
    return choice
