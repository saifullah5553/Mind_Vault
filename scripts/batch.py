"""Batch content production — generate multiple videos from the 90-day calendar.

Select how many, which categories, which duration, and it produces them (each
lands in the review folder as 'pending', tagged with its scheduled publish date
from the calendar). Nothing publishes here — approval + publish_approved is the
next, deliberate step.

Usage:
    python -m scripts.batch --count 5
    python -m scripts.batch --count 3 --category psychology --format short
    python -m scripts.batch --count 2 --format long
    python -m scripts.batch --count 5 --plan-only        # show the plan, produce nothing
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.calendar import build_calendar
from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger
from core.orchestrator import Orchestrator

log = get_logger("scripts.batch")


def _plan(count: int, category: str | None, video_format: str | None) -> list[dict]:
    slots = build_calendar()
    chosen = []
    for slot in slots:
        if category and category != "both" and slot["category"] != category:
            continue
        if video_format and slot["format"] != video_format:
            continue
        chosen.append(slot)
        if len(chosen) >= count:
            break
    return chosen


def _tag_schedule(run_id: str, scheduled_date: str) -> None:
    rjson = ROOT_DIR / get_settings().publishing.review_dir / run_id / "review.json"
    if rjson.exists():
        rec = json.loads(rjson.read_text(encoding="utf-8"))
        rec["scheduled_date"] = scheduled_date
        rjson.write_text(json.dumps(rec, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-produce videos from the content calendar")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--category", choices=["psychology", "history", "both"], default="both")
    ap.add_argument("--format", dest="video_format", choices=["short", "long"], default=None)
    ap.add_argument("--plan-only", action="store_true", help="print the plan; produce nothing")
    args = ap.parse_args()

    plan = _plan(args.count, args.category, args.video_format)
    print(f"\nPlanned {len(plan)} video(s):")
    for s in plan:
        print(f"  {s['date']} {s['weekday']}  {s['format']:<5} {s['category']:<10} {s['subcategory']}")
    print()
    if args.plan_only or not plan:
        return

    orch = Orchestrator()
    produced = []
    for slot in plan:
        try:
            ctx = orch.produce(category=slot["category"], video_format=slot["format"])
            _tag_schedule(ctx.run_id, slot["date"])
            status = ctx.extra.get("review_status") or ("failed" if ctx.extra.get("failed_stage") else "done")
            produced.append((ctx.run_id, slot["date"], status))
            print(f"  produced {ctx.run_id}  ({slot['category']}/{slot['format']})  -> {status}, publish {slot['date']}")
        except Exception as exc:  # keep going on failure
            log.error("Batch item failed (%s/%s): %s", slot["category"], slot["format"], exc)

    print(f"\nDone. {len(produced)} produced and waiting in the review folder.")
    print("Review:  python -m scripts.review list")
    print("Approve: python -m scripts.review approve <run_id>")
    print("Publish: python -m scripts.publish_approved   (stays private/dry-run)\n")


if __name__ == "__main__":
    main()
