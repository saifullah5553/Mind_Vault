"""TikTok publisher (Content Posting API, via httpx).

Required env: TIKTOK_ACCESS_TOKEN
Flow: init a FILE_UPLOAD publish -> PUT the video bytes to the returned upload
URL. NOTE: until your TikTok app passes audit, posts are restricted to
SELF_ONLY (private) — we therefore default privacy to private. Nothing runs
unless dry_run is false and the token is present.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from core.errors import ProviderError
from core.publishing.base import PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"


class TikTokPublisher(PlatformPublisher):
    platform = "tiktok"
    required_env = ["TIKTOK_ACCESS_TOKEN"]

    def publish(self, pkg: PublishPackage) -> PublishResult:  # pragma: no cover - needs creds+network
        video = Path(pkg.video_path)
        if not video.exists():
            return PublishResult(platform=self.platform, status="failed", note="video file missing")
        token = os.environ["TIKTOK_ACCESS_TOKEN"]
        size = video.stat().st_size
        caption = f"{pkg.title} {' '.join(pkg.hashtags)}".strip()[:2200]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            init = httpx.post(_INIT, headers=headers, json={
                "post_info": {
                    "title": caption,
                    "privacy_level": "SELF_ONLY" if pkg.privacy == "private" else "PUBLIC_TO_EVERYONE",
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": size,
                    "total_chunk_count": 1,
                },
            }, timeout=60)
            init.raise_for_status()
            data = init.json().get("data", {})
            upload_url = data.get("upload_url")
            publish_id = data.get("publish_id", "")
            if not upload_url:
                return PublishResult(platform=self.platform, status="failed",
                                     note=f"no upload_url in init response: {init.text[:200]}")
            with video.open("rb") as fh:
                httpx.put(upload_url, content=fh.read(),
                          headers={"Content-Type": "video/mp4",
                                   "Content-Range": f"bytes 0-{size-1}/{size}"},
                          timeout=None).raise_for_status()
            self.log.info("TikTok upload submitted (publish_id=%s).", publish_id)
            return PublishResult(platform=self.platform, status="published",
                                 note=f"publish_id={publish_id} (privacy={pkg.privacy})")
        except httpx.HTTPError as exc:
            raise ProviderError(f"TikTok upload failed: {exc}") from exc
