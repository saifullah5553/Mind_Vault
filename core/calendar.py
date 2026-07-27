"""Content Calendar engine.

Builds a rolling N-day calendar (default 90) that:
- schedules shorts on `publishing.short_days` and long-form on `publishing.long_days`,
- balances categories toward `strategy.category_mix`,
- rotates subcategories so the same angle/topic isn't repeated back-to-back
  (respecting `strategy.avoid_repeat_window`).

The calendar is deterministic given a start date, persisted to
`storage/calendar.json`, and surfaced via the API + dashboard. The CEO consults
it when deciding what to produce next.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger
from core.taxonomy import subcategories

log = get_logger("calendar")

_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _target_sequence(mix: dict[str, float], n: int) -> list[str]:
    """Largest-remainder allocation so category counts match the mix over n slots."""
    raw = {c: w * n for c, w in mix.items()}
    counts = {c: int(v) for c, v in raw.items()}
    while sum(counts.values()) < n:
        # Give the next slot to the category with the largest fractional remainder.
        c = max(mix, key=lambda k: (raw[k] - counts[k], mix[k]))
        counts[c] += 1
    # Interleave categories evenly rather than clumping.
    seq: list[str] = []
    remaining = dict(counts)
    while len(seq) < n:
        c = max(remaining, key=lambda k: remaining[k])
        if remaining[c] <= 0:
            break
        seq.append(c)
        remaining[c] -= 1
        # rotate so we don't always pick the same first
        remaining = {k: remaining[k] for k in list(remaining)[1:] + list(remaining)[:1]}
    return seq[:n]


def build_calendar(start: date | None = None, days: int | None = None) -> list[dict]:
    s = get_settings()
    start = start or date.today()
    days = days or s.strategy.calendar_days
    short_days = {_WEEKDAY[d] for d in s.publishing.short_days if d in _WEEKDAY}
    long_days = {_WEEKDAY[d] for d in s.publishing.long_days if d in _WEEKDAY}

    # Collect the publishing slots (dates that get content).
    slots: list[tuple[date, str]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() in long_days:
            slots.append((d, "long"))
        elif d.weekday() in short_days:
            slots.append((d, "short"))

    categories = _target_sequence(s.strategy.category_mix, len(slots))

    # Rotate subcategories per category, avoiding immediate repeats.
    cursors = {c: 0 for c in s.strategy.category_mix}
    recent: list[str] = []
    window = s.strategy.avoid_repeat_window

    calendar: list[dict] = []
    for (d, fmt), cat in zip(slots, categories):
        subs = subcategories(cat) or [cat]
        # advance cursor until we find a sub not in the recent window
        for _ in range(len(subs)):
            sub = subs[cursors[cat] % len(subs)]
            cursors[cat] += 1
            if sub not in recent:
                break
        recent.append(sub)
        if len(recent) > window:
            recent.pop(0)
        calendar.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%a"),
            "category": cat,
            "subcategory": sub,
            "format": fmt,
        })

    _persist(calendar)
    log.info("Built %d-day calendar: %d slots", days, len(calendar))
    return calendar


def _persist(calendar: list[dict]) -> None:
    out = ROOT_DIR / "storage" / "calendar.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(calendar, indent=2), encoding="utf-8")


def load_calendar() -> list[dict]:
    path = ROOT_DIR / "storage" / "calendar.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return build_calendar()
