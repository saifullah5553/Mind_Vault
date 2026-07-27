"""Seed demo data so the analytics -> learning -> CEO loop is demonstrable at $0
without waiting for real published performance.

Creates a handful of 'published' Content rows with Topic DNA, then runs the
Analytics, Learning, and CEO agents over them.

Usage:
    python -m scripts.seed_demo
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.database.models import Content, ContentMemory
from core.database.session import init_db, session_scope
from core.logging_setup import get_logger
from core.registry import get_agent, load_all_agents

log = get_logger("scripts.seed_demo")

DEMO = [
    ("psychology", "why we procrastinate", "curiosity", 62.0, 90.0),
    ("history", "the fall of an empire", "emotion", 71.0, 88.0),
    ("psychology", "the fear response", "curiosity", 55.0, 92.0),
    ("history", "a forgotten invention", "curiosity", 68.0, 86.0),
    ("psychology", "how habits form", "shock", 60.0, 89.0),
]


def main() -> None:
    init_db()
    load_all_agents()

    with session_scope() as s:
        for i, (cat, topic, hook_type, dur, qual) in enumerate(DEMO):
            c = Content(topic=topic, category=cat, title=topic.title(),
                        status="published", quality_score=qual, video_format="short",
                        published_date=datetime.now(timezone.utc))
            s.add(c)
            s.flush()
            s.add(ContentMemory(video_id=c.id, topic=topic, hook=f"A hook about {topic}",
                                hook_type=hook_type, duration=dur, script_style="netflix-documentary",
                                story_structure="hook-intro-story-lesson", voice_style="silence"))
    log.info("Seeded %d published videos.", len(DEMO))

    get_agent("analytics").execute({})
    insights = get_agent("learning").execute({}).output
    report = get_agent("ceo").execute({}).output

    print("\n=== Learning insights ===")
    for k, v in insights["insights"].items():
        print(f"  {k}: {v}")
    print("\n=== CEO report ===")
    print(" ", report.summary)
    for a in (report.actions or []):
        print("   -", a)
    print()


if __name__ == "__main__":
    main()
