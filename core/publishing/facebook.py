"""Facebook Page video publisher (Graph API, via httpx).

Required env: FACEBOOK_PAGE_ID, FACEBOOK_PAGE_TOKEN
Uploads the video to a Page. For Reels specifically, Meta has a separate
resumable Reels endpoint; this posts a standard Page video (widely supported).
Nothing runs unless dry_run is false and creds are present.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from core.errors import ProviderError
from core.publishing.base import PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_GRAPH = "https://graph-video.facebook.com/v20.0"


class FacebookPublisher(PlatformPublisher):
    platform = "facebook"
    required_env = ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"]

    def publish(self, pkg: PublishPackage) -> PublishResult:  # pragma: no cover - needs creds+network
        video = Path(pkg.video_path)
        if not video.exists():
            return PublishResult(platform=self.platform, status="failed", note="video file missing")
        page_id = os.environ["FACEBOOK_PAGE_ID"]
        token = os.environ["FACEBOOK_PAGE_TOKEN"]
        desc = f"{pkg.title}\n\n{pkg.description}\n\n{' '.join(pkg.hashtags)}".strip()
        try:
            with video.open("rb") as fh:
                r = httpx.post(
                    f"{_GRAPH}/{page_id}/videos",
                    data={"description": desc, "access_token": token},
                    files={"source": (video.name, fh.read(), "video/mp4")},
                    timeout=None)
            r.raise_for_status()
            vid = r.json().get("id", "")
            url = f"https://www.facebook.com/{vid}" if vid else ""
            self.log.info("Published to Facebook: %s", url)
            return PublishResult(platform=self.platform, status="published", url=url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Facebook upload failed: {exc}") from exc
