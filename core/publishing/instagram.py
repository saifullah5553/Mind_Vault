"""Instagram Reels publisher (Graph API, via httpx).

Required env: INSTAGRAM_USER_ID, INSTAGRAM_ACCESS_TOKEN
IMPORTANT: Instagram's API does NOT accept a file upload — it requires the video
to be reachable at a PUBLIC URL. So this publisher needs the video hosted first
(set INSTAGRAM_VIDEO_URL to the public URL of the uploaded file, or wire a host
step). Flow: create a REELS media container from the URL -> publish it.
Nothing runs unless dry_run is false and creds are present.
"""

from __future__ import annotations

import os

import httpx

from core.errors import ProviderError
from core.publishing.base import PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_GRAPH = "https://graph.facebook.com/v20.0"


class InstagramPublisher(PlatformPublisher):
    platform = "instagram"
    required_env = ["INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN"]

    def publish(self, pkg: PublishPackage) -> PublishResult:  # pragma: no cover - needs creds+network
        user_id = os.environ["INSTAGRAM_USER_ID"]
        token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
        # IG needs a PUBLIC video URL, not a local file.
        video_url = os.getenv("INSTAGRAM_VIDEO_URL")
        if not video_url:
            return PublishResult(
                platform=self.platform, status="skipped",
                note="Instagram requires a public video URL. Host the mp4 and set "
                     "INSTAGRAM_VIDEO_URL (see docs/PUBLISHING.md).")
        caption = f"{pkg.title}\n\n{' '.join(pkg.hashtags)}".strip()[:2200]
        try:
            create = httpx.post(f"{_GRAPH}/{user_id}/media", data={
                "media_type": "REELS", "video_url": video_url,
                "caption": caption, "access_token": token,
            }, timeout=60)
            create.raise_for_status()
            creation_id = create.json()["id"]
            publish = httpx.post(f"{_GRAPH}/{user_id}/media_publish", data={
                "creation_id": creation_id, "access_token": token,
            }, timeout=60)
            publish.raise_for_status()
            media_id = publish.json().get("id", "")
            self.log.info("Published to Instagram (media_id=%s).", media_id)
            return PublishResult(platform=self.platform, status="published",
                                 note=f"media_id={media_id}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"Instagram upload failed: {exc}") from exc
