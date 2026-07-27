"""Publish APPROVED videos (privately/unlisted, credential-gated).

Reads approved review bundles, restores each run's full pipeline context from its
checkpoint, marks it approved, and runs the Publishing agent. Publishing still
respects publishing.dry_run and first_privacy (private), so nothing goes public
until you deliberately change those.

Usage:
    python -m scripts.publish_approved            # publish all approved, not-yet-published
    python -m scripts.publish_approved <run_id>   # just one
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.database.models import Content, ContentStatus
from core.database.session import session_scope
from core.logging_setup import get_logger
from core.registry import get_agent, load_all_agents
from core.schemas import PipelineContext

log = get_logger("scripts.publish_approved")


def _review_root() -> Path:
    return ROOT_DIR / get_settings().publishing.review_dir


def _approved(run_id: str | None) -> list[dict]:
    root = _review_root()
    if not root.exists():
        return []
    out = []
    for p in sorted(root.glob("*/review.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") == "approved" and (run_id is None or r["run_id"] == run_id):
            out.append(r)
    return out


def _load_ctx(run_id: str) -> PipelineContext | None:
    cp = ROOT_DIR / "storage" / "checkpoints" / f"{run_id}.json"
    if not cp.exists():
        log.warning("No checkpoint for %s; cannot restore context to publish.", run_id)
        return None
    return PipelineContext(**json.loads(cp.read_text(encoding="utf-8")))


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish approved videos (private)")
    ap.add_argument("run_id", nargs="?", default=None)
    args = ap.parse_args()

    load_all_agents()
    approved = _approved(args.run_id)
    if not approved:
        print("Nothing approved to publish. Approve with: python -m scripts.review approve <run_id>")
        return

    dry = get_settings().publishing.dry_run
    print(f"Publishing {len(approved)} approved video(s). dry_run={dry} (uploads start private).")

    for rec in approved:
        run_id = rec["run_id"]
        ctx = _load_ctx(run_id)
        if ctx is None:
            continue
        ctx.extra["approved"] = True
        results = get_agent("publishing").execute(ctx, run_id=run_id).output or []
        for r in results:
            print(f"  {run_id}  {r.platform:<10} {r.status}  {r.note}")
        # Reflect state.
        published = any(r.status in ("published", "dry_run") for r in results)
        rec["status"] = "published" if published else "approved"
        rec["published_at"] = datetime.now(timezone.utc).isoformat()
        (_review_root() / run_id / "review.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        if published and ctx.content_id:
            with session_scope() as s:
                c = s.get(Content, ctx.content_id)
                if c:
                    c.status = ContentStatus.PUBLISHED.value
                    c.published_date = datetime.now(timezone.utc)


if __name__ == "__main__":
    main()
