"""Review Agent — the human-in-the-loop gate.

Before anything can be published, this bundles the finished artifacts into a
self-contained review folder (`storage/review/<run_id>/`):

    video.mp4 · thumbnail.png · script.txt · captions.srt · metadata.json · review.json

`review.json` holds status = "pending" plus the full quality scorecard. A human
approves or rejects with `python -m scripts.review`. Only APPROVED bundles are
ever eligible for publishing (and even then, only in private/unlisted mode).

Returns: {"review_dir": path, "status": "pending"}
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.agents.base import BaseAgent
from core.config import ROOT_DIR
from core.database.models import Content, ContentStatus
from core.database.session import session_scope
from core.registry import register_agent
from core.schemas import PipelineContext


@register_agent
class ReviewAgent(BaseAgent):
    name = "review"
    folder = "review_agent"

    def run(self, payload: PipelineContext) -> dict:
        review_root = ROOT_DIR / self.settings.publishing.review_dir
        rdir = review_root / payload.run_id
        rdir.mkdir(parents=True, exist_ok=True)

        # 1) Final video (copied so the bundle is self-contained).
        video_dst = None
        if payload.video and Path(payload.video.video_path).exists():
            src = Path(payload.video.video_path)
            video_dst = rdir / f"video{src.suffix}"
            if self.config.get("copy_video", True):
                shutil.copy2(src, video_dst)
            else:
                video_dst = src

        # 2) Thumbnail.
        thumb = (payload.extra or {}).get("thumbnail")
        thumb_dst = None
        if thumb and Path(thumb).exists():
            thumb_dst = rdir / "thumbnail.png"
            shutil.copy2(thumb, thumb_dst)

        # 3) Captions.
        if payload.video and payload.video.srt_path and Path(payload.video.srt_path).exists():
            shutil.copy2(payload.video.srt_path, rdir / "captions.srt")

        # 4) Script.
        if payload.script:
            (rdir / "script.txt").write_text(
                f"TITLE: {payload.script.title}\n\n{payload.script.full_text}", encoding="utf-8")

        # 5) Metadata (per platform).
        (rdir / "metadata.json").write_text(
            json.dumps([m.model_dump() for m in payload.metadata], indent=2), encoding="utf-8")

        # 6) The review record.
        record = {
            "run_id": payload.run_id,
            "status": "pending",                      # pending | approved | rejected
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": payload.script.title if payload.script else (payload.topic.angle if payload.topic else ""),
            "category": payload.category,
            "format": payload.video_format,
            "quality_passed": payload.quality.passed if payload.quality else None,
            "scorecard": payload.quality.scorecard if payload.quality else {},
            "video": str(video_dst) if video_dst else None,
            "thumbnail": str(thumb_dst) if thumb_dst else None,
            "content_id": payload.content_id,
            "presenter": (payload.extra or {}).get("presenter", {}).get("persona"),
        }
        (rdir / "review.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

        # Mark the content as awaiting review.
        if payload.content_id is not None:
            with session_scope() as s:
                c = s.get(Content, payload.content_id)
                if c and c.status not in (ContentStatus.PUBLISHED.value,):
                    c.status = ContentStatus.IN_REVIEW.value

        self.log.info("Review bundle ready: %s (status=pending)", rdir)
        return {"review_dir": str(rdir), "status": "pending"}
