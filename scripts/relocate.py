"""Repair stored absolute paths after the project folder is moved.

The code itself is location-independent (ROOT_DIR is derived from the source
file), but artifacts produced by earlier runs record ABSOLUTE paths:

  - the database        (content.video_path / audio_path / thumbnail_path,
                         thumbnails.path)
  - review bundles      (storage/review/<run>/review.json)
  - pipeline checkpoints(storage/checkpoints/<run>.json)
  - publish manifests   (storage/videos/<run>_publish.json)

After moving the project (e.g. C:\\Users\\...\\AI-Media_Factory -> D:\\Mind_Vault)
those still point at the old drive, so `publish_approved` and `--resume` would
fail to find their files. This rewrites them to the current ROOT_DIR.

Safe to run repeatedly; it only touches paths that do not already live under the
current root.

Usage:
    python -m scripts.relocate --check     # report what would change
    python -m scripts.relocate             # apply
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from core.config import ROOT_DIR
from core.logging_setup import get_logger

log = get_logger("scripts.relocate")

# Matches any absolute path that ends with one of our known project folders,
# e.g. "C:\Users\me\AI-Media_Factory\storage\videos\x.mp4".
_ANCHORS = ("storage", "tools", "config", "prompts", "logs")


def _rewrite(value: str) -> str | None:
    """Return the value rebased onto ROOT_DIR, or None if no change is needed."""
    if not isinstance(value, str) or len(value) < 4:
        return None
    norm = value.replace("/", "\\")
    root = str(ROOT_DIR).replace("/", "\\")
    if norm.lower().startswith(root.lower()):
        return None                      # already correct
    for anchor in _ANCHORS:
        marker = f"\\{anchor}\\"
        idx = norm.lower().find(marker)
        if idx > 0:
            tail = norm[idx + 1:]        # e.g. "storage\videos\x.mp4"
            return str(ROOT_DIR / tail)
    # A bare project-root file such as mind_vault.db
    m = re.match(r"^[A-Za-z]:\\.*\\([^\\]+\.(?:db|sqlite3))$", norm)
    if m:
        return str(ROOT_DIR / m.group(1))
    return None


def _walk_json(obj):
    """Rewrite every string path inside a nested JSON structure. Returns count."""
    changed = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                nv = _rewrite(v)
                if nv:
                    obj[k] = nv
                    changed += 1
            else:
                changed += _walk_json(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                nv = _rewrite(v)
                if nv:
                    obj[i] = nv
                    changed += 1
            else:
                changed += _walk_json(v)
    return changed


def fix_json_files(apply: bool) -> int:
    total = 0
    patterns = [
        ROOT_DIR / "storage" / "review",
        ROOT_DIR / "storage" / "checkpoints",
        ROOT_DIR / "storage" / "videos",
    ]
    for base in patterns:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            n = _walk_json(data)
            if n:
                total += n
                if apply:
                    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                log.info("%s: %d path(s)%s", path.name, n, "" if apply else " (dry run)")
    return total


def fix_database(apply: bool) -> int:
    from core.database.models import Content, Thumbnail
    from core.database.session import session_scope

    total = 0
    with session_scope() as s:
        for row in s.query(Content).all():
            for field in ("video_path", "audio_path", "thumbnail_path"):
                cur = getattr(row, field, None)
                nv = _rewrite(cur) if cur else None
                if nv:
                    total += 1
                    if apply:
                        setattr(row, field, nv)
        for th in s.query(Thumbnail).all():
            nv = _rewrite(th.path) if th.path else None
            if nv:
                total += 1
                if apply:
                    th.path = nv
        if not apply:
            s.rollback()
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair absolute paths after moving the project")
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    args = ap.parse_args()
    apply = not args.check

    print(f"\nProject root: {ROOT_DIR}\n")
    j = fix_json_files(apply)
    d = fix_database(apply)
    verb = "Would fix" if args.check else "Fixed"
    print(f"\n{verb}: {j} path(s) in JSON artifacts, {d} in the database.")
    if args.check and (j or d):
        print("Run without --check to apply.\n")
    elif not (j or d):
        print("Nothing to fix - all stored paths already match this location.\n")


if __name__ == "__main__":
    main()
