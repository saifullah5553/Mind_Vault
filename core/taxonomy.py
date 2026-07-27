"""Content taxonomy — the seed universe of subcategories the topic engine draws
from. Adding a new content vertical (Mythology, Space, Philosophy...) is a matter
of adding a key here; no agent code changes. This is what makes new categories
expandable-by-configuration, as required.
"""

from __future__ import annotations

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "psychology": {
        "subcategories": [
            "human behavior", "cognitive biases", "relationships", "personality",
            "habits", "decision making", "leadership", "communication",
            "emotional intelligence", "motivation", "fear", "confidence",
            "social psychology",
        ],
    },
    "history": {
        "subcategories": [
            "ancient civilizations", "lost kingdoms", "empires", "famous leaders",
            "historical mysteries", "wars", "discoveries", "inventions",
            "cultural history", "forgotten events",
        ],
    },
    # Future verticals — pre-seeded so expansion is trivial. Not used until the
    # strategy category_mix references them.
    "mythology": {"subcategories": ["creation myths", "gods and monsters", "hero legends"]},
    "science": {"subcategories": ["breakthroughs", "famous experiments", "scientists"]},
    "space": {"subcategories": ["exploration", "cosmic mysteries", "the planets"]},
    "philosophy": {"subcategories": ["big questions", "famous thinkers", "ethics"]},
    "economics": {"subcategories": ["market crashes", "money history", "trade routes"]},
    "technology": {"subcategories": ["inventions", "the internet age", "lost tech"]},
}


def categories() -> list[str]:
    return list(TAXONOMY.keys())


def subcategories(category: str) -> list[str]:
    return TAXONOMY.get(category, {}).get("subcategories", [])
