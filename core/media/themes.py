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
                 # Specific words: "summit" alone found a cruise ship (Celebrity
                 # Summit) and snow fields, "runner" found racing dogs.
                 ["mountaineer", "marathon", "climber rock"]),
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
               # Not "crowd": Featured "crowd" pictures are historic events
               # (the 1944 Liberation of Paris), off-topic for psychology.
               ["festival", "friends laughing", "city people walking"]),
    "reward": (r"reward|pleasure|joy|happ|satisf|celebrat|prize|praise|enjoy",
               ["fireworks over", "lantern festival", "celebration"]),
    "habit": (r"habit|routine|daily|repeat|practice|work|learn|school|train|skill|"
              r"behavio",
              ["workshop", "craftsman", "classroom", "violinist"]),
    # People absorbed in something, not scenery: this is the fallback for most
    # abstract lines, and a run of skies is where viewers leave.
    "default": (r"", ["pottery wheel", "painter", "piano hands", "surfing", "woodworking"]),
}

_CUES = {name: re.compile(cue, re.I) for name, (cue, _) in THEMES.items() if cue}


# Capitalised words that are just sentence openers, not names worth picturing.
_NOT_NAMES = set("""
a an the this that these those there here it its they them their we our us you your
i he she his her him in on at to for from of by with as but and or so yet not no nor
what when where why how who which whose while if then than though although because
since after before during until once each every some many most more much few all any
both either neither one two three four five six seven eight nine ten first second
third last next chapter introduction conclusion follow consider imagine
perhaps maybe still even just only also however indeed instead meanwhile today
tomorrow yesterday now later soon ultimately finally together yes
monday tuesday wednesday thursday friday saturday sunday january february march april
may june july august september october november december
""".split())
_CAP = re.compile(r"\b[A-Z][a-zA-Z\-]{2,}(?:'s)?")
# Fine inside a name ("New York", "Great Wall") but not a subject on their own.
_LONE_SKIP = {"new", "old", "great", "modern", "ancient", "early", "late", "recent",
              "young", "little", "big", "high", "low", "north", "south", "east", "west"}


# What a line is literally about -> stock video search. A viewer who hears "cats"
# should see a cat; mood pictures only fill the lines with no concrete subject.
SUBJECTS: list[tuple[str, str]] = [
    # Most specific first: the first row that matches wins, so "a researcher put
    # hungry cats in a box" shows cats, not a laboratory.
    (r"\bcats?\b|\blatch\b", "cat"),
    (r"\bdogs?\b", "dog"),
    (r"\bmonkeys?\b|\bapes?\b", "monkey"),
    (r"\bpreschool\w*|\bchild\w*|\bkids?\b|\bdraw\w*|\bmarkers?\b", "child drawing"),
    (r"\bparents?\b|\bdaycare\b|\bpickups?\b", "mother child"),
    (r"\bchess\b", "chess"),
    (r"\bclimb\w*", "rock climbing"),
    (r"\bartists?\b|\bpaint\w*", "painter"),
    (r"\bmusic\w*|\bsing\w*", "playing guitar"),
    (r"\bsports?\b|\bathlet\w*", "soccer goal"),
    (r"\bpuzzles?\b", "puzzle"),
    (r"\bstudents?\b|\buniversity\b|\bclassroom\b", "students classroom"),
    (r"\bmoney\b|\bpaid\b|\bpay\b|\bsalar\w+|\bwages?\b|\bfines?\b|\bprice\b", "money cash"),
    (r"\blikes\b|\bsocial media\b|\bphones?\b|\bonline\b", "smartphone"),
    (r"\bsteps\b|\bwalk\w*", "walking"),
    (r"\bgrades?\b|\bexams?\b", "exam"),
    (r"\bbusiness\w*|\bjobs?\b|\bsales\b|\btargets?\b|\boffice\b", "office work"),
    (r"\bfood\b|\bhungry\b|\bhunger\b|\bmeals?\b", "food"),
    (r"\bthirst\w*", "drinking water"),
    (r"\bmagazines?\b|\bbooks?\b|\breading\b", "reading"),
    (r"\blate\b|\blateness\b|\bdeadlines?\b|\btime\b|\bhours\b|\bminutes\b", "clock"),
    (r"\bfire\b", "campfire"),
    (r"\bmachine\b", "gears machine"),
    # Ideas with no object of their own, shown through someone living them.
    (r"\bflow\b|\beffort felt\b|\bthe doing\b|\bdoing gives\b", "pottery wheel"),
    (r"\bcompetence\b|\bgetting better\b|\bskill\w*|\bprogress\b|\bchallenge\w*|\bpractice\b",
     "skateboard"),
    (r"\brelatedness\b|\bconnected\b|\bdoing this with\b|\btogether\b", "friends laughing"),
    (r"\bbored\b|\blazy\b|\bdull\b", "bored"),
    (r"\banxi\w+|\bstress\w*|\btoo hard\b|\bwithers?\b|\bstarved\b", "stressed"),
    (r"\bloved?\b|\bpassions?\b|\binterest\w*|\benjoy\w*", "playing guitar"),
    (r"\bautonomy\b|\bchose\b|\bchoose\b|\byour own\b|\boutside of you\b", "hiking"),
    (r"\brewards?\b|\bprizes?\b|\bawards?\b|\bpraise\b", "gold medal"),
    (r"\bgoals?\b", "soccer goal"),
    (r"\bscores?\b", "scoreboard"),
    (r"\baudience\b", "applause audience"),
    (r"\bquestions?\b|\bwondered\b", "writing notebook"),
    # Generic last: nearly every study line says "researchers".
    (r"\bexperiment\w*|\blaborator\w*|\bstud(?:y|ies)\b|\bresearchers?\b", "laboratory scientist"),
    (r"\bbrains?\b", "brain"),
    (r"\bancient\b|\bgreeks?\b", "ancient greece ruins"),
]
_SUBJECTS = [(re.compile(rx, re.I), query) for rx, query in SUBJECTS]
# "They got better" is still about the monkeys, for a line or two.
_CARRY_SCENES = 2


def subject_of(text: str) -> str | None:
    """Video search for the most specific subject this line mentions, if any."""
    return next((q for rx, q in _SUBJECTS if rx.search(text or "")), None)


def carry_subjects(lines: list[str]) -> list[str | None]:
    """Each line's subject, or the story's current one if the line names none."""
    out: list[str | None] = []
    current, age = None, 0
    for line in lines:
        found = subject_of(line)
        if found:
            current, age = found, 0
        else:
            age += 1
            if age > _CARRY_SCENES:
                current = None
        out.append(current)
    return out


def named_subjects(text: str) -> list[str]:
    """Proper names a line mentions ("Aristotle", "Edward Thorndike")."""
    names: list[str] = []
    run: list[str] = []
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*|[^\sA-Za-z]", text or "")
    for tok in tokens + ["."]:
        if _CAP.fullmatch(tok) and tok.lower().removesuffix("'s") not in _NOT_NAMES:
            run.append(tok.removesuffix("'s"))
            if tok.endswith("'s"):
                tok = "."            # a possessive ends the name
            else:
                continue
        if run:
            name = " ".join(run)
            lone = len(run) == 1 and run[0].lower() in _LONE_SKIP
            if not lone and name not in names:
                names.append(name)
            run = []
    return names


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
