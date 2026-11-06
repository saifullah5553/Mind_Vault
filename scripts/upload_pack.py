"""Build a ready-to-upload folder for manual posting.

For each review bundle it gathers the video, thumbnail and captions, and writes
the title, description and tags as paste-ready text, one folder per platform.

Usage:
    python -m scripts.upload_pack <run_id> [<run_id> ...]

Output: upload_ready/<title>/ (not tracked by git).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from core.config import ROOT_DIR, get_settings


def _link(src: Path, dst: Path) -> None:
    """Hard link where possible: no second copy of a 1 GB video."""
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build(run_id: str, root: Path | None = None) -> Path:
    s = get_settings()
    bundle = ROOT_DIR / s.publishing.review_dir / run_id
    record = json.loads((bundle / "review.json").read_text(encoding="utf-8"))
    metas = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    pub = s.publishing
    allowed = pub.short_platforms if record.get("format") == "short" else pub.long_platforms

    slug = re.sub(r"[^A-Za-z0-9]+", "_", record.get("title") or run_id).strip("_")[:50]
    out = (root or ROOT_DIR / "upload_ready") / f"{record.get('format', 'video')}_{slug}"
    for meta in metas:
        platform = meta["platform"]
        if platform not in allowed:
            continue
        pdir = out / platform
        pdir.mkdir(parents=True, exist_ok=True)
        _link(bundle / "video.mp4", pdir / "video.mp4")
        for name in ("thumbnail.png", "captions.srt"):
            if (bundle / name).exists():
                shutil.copy2(bundle / name, pdir / name)
        tags = " ".join(meta.get("hashtags") or [])
        (pdir / "title.txt").write_text(meta["title"], encoding="utf-8")
        (pdir / "description.txt").write_text(
            f"{meta['description']}\n\n{tags}".strip() + "\n", encoding="utf-8")
        (pdir / "tags.txt").write_text(", ".join(meta.get("tags") or []), encoding="utf-8")
    if (bundle / "credits.txt").exists():
        shutil.copy2(bundle / "credits.txt", out / "credits_full.txt")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build paste-ready upload folders")
    ap.add_argument("run_ids", nargs="+")
    for run_id in ap.parse_args().run_ids:
        print(build(run_id))


if __name__ == "__main__":
    main()
