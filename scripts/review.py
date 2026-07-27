"""Manual review CLI — approve or reject produced videos before publishing.

Usage:
    python -m scripts.review list                 # show all pending/approved/rejected
    python -m scripts.review show <run_id>        # print the scorecard + paths
    python -m scripts.review approve <run_id>     # mark approved (eligible to publish)
    python -m scripts.review reject <run_id> [why]

Approved videos are published (privately/unlisted) by:
    python -m scripts.publish_approved
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.database.models import Content, ContentStatus
from core.database.session import session_scope


def _review_root() -> Path:
    return ROOT_DIR / get_settings().publishing.review_dir


def _bundles() -> list[Path]:
    root = _review_root()
    return sorted(root.glob("*/review.json")) if root.exists() else []


def _load(run_id: str) -> tuple[Path, dict]:
    path = _review_root() / run_id / "review.json"
    if not path.exists():
        raise SystemExit(f"No review bundle for run {run_id}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _set_status(run_id: str, status: str, note: str = "") -> None:
    path, rec = _load(run_id)
    rec["status"] = status
    rec["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if note:
        rec["note"] = note
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    cid = rec.get("content_id")
    if cid is not None:
        with session_scope() as s:
            c = s.get(Content, cid)
            if c:
                c.status = {"approved": ContentStatus.APPROVED.value,
                            "rejected": ContentStatus.REJECTED.value}.get(status, c.status)
    print(f"{run_id}: {status}")


def cmd_list(_args) -> None:
    rows = _bundles()
    if not rows:
        print("No review bundles yet. Produce a video first.")
        return
    print(f"\n{'RUN':<14} {'STATUS':<9} {'FMT':<6} {'OVERALL':<8} TITLE")
    print("-" * 78)
    for p in rows:
        r = json.loads(p.read_text(encoding="utf-8"))
        overall = (r.get("scorecard") or {}).get("overall", "-")
        print(f"{r['run_id']:<14} {r['status']:<9} {r.get('format','-'):<6} "
              f"{str(overall):<8} {(r.get('title') or '')[:44]}")
    print()


def cmd_show(args) -> None:
    _, r = _load(args.run_id)
    print(json.dumps(r, indent=2))


def cmd_approve(args) -> None:
    _set_status(args.run_id, "approved")
    print("Approved. Publish (privately) with: python -m scripts.publish_approved")


def cmd_reject(args) -> None:
    _set_status(args.run_id, "rejected", note=" ".join(args.reason) if args.reason else "")


def main() -> None:
    p = argparse.ArgumentParser(description="Review produced videos before publishing")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sp = sub.add_parser("show"); sp.add_argument("run_id"); sp.set_defaults(func=cmd_show)
    sp = sub.add_parser("approve"); sp.add_argument("run_id"); sp.set_defaults(func=cmd_approve)
    sp = sub.add_parser("reject"); sp.add_argument("run_id"); sp.add_argument("reason", nargs="*"); sp.set_defaults(func=cmd_reject)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
