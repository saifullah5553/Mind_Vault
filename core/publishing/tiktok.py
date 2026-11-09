"""TikTok publisher (Content Posting API, via httpx).

Required env: TIKTOK_ACCESS_TOKEN (scope video.publish).

Flow: query the creator's limits -> init a FILE_UPLOAD post -> PUT the file in
order, chunk by chunk. Per TikTok's media transfer guide: chunks are 5-64 MB, the
last may reach 128 MB to absorb trailing bytes, files over 64 MB must be chunked,
and total_chunk_count is video_size / chunk_size rounded down.

NOTE: until your TikTok app passes audit, posts are restricted to SELF_ONLY
(private) and the account must be private. Nothing runs unless dry_run is false
and the token is present.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from core.errors import ProviderError
from core.publishing.base import PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_BASE = "https://open.tiktokapis.com/v2/post/publish"
_SINGLE_MAX = 64 * 1024 * 1024
_CHUNK = 32 * 1024 * 1024
_RETRIES = 3


def plan_chunks(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) for a file of `size` bytes."""
    if size <= _SINGLE_MAX:
        return size, 1
    return _CHUNK, size // _CHUNK


def chunk_ranges(size: int, chunk_size: int, total: int) -> list[tuple[int, int]]:
    """Inclusive byte ranges; the last chunk absorbs the trailing bytes."""
    ranges = [(i * chunk_size, (i + 1) * chunk_size - 1) for i in range(total)]
    ranges[-1] = (ranges[-1][0], size - 1)
    return ranges


def upload_chunks(url: str, video: Path, chunk_size: int, total: int, sleep=time.sleep) -> None:
    size = video.stat().st_size
    with video.open("rb") as fh:
        for first, last in chunk_ranges(size, chunk_size, total):
            fh.seek(first)
            data = fh.read(last - first + 1)
            for attempt in range(_RETRIES + 1):
                r = httpx.put(url, content=data, timeout=300, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {first}-{last}/{size}"})
                if r.status_code in (201, 206):
                    break
                if r.status_code < 500 or attempt == _RETRIES:
                    raise ProviderError(f"TikTok chunk {first}-{last} failed: "
                                        f"{r.status_code} {r.text[:200]}")
                sleep(2 ** (attempt + 1))


class TikTokPublisher(PlatformPublisher):
    platform = "tiktok"
    required_env = ["TIKTOK_ACCESS_TOKEN"]

    def publish(self, pkg: PublishPackage) -> PublishResult:
        video = Path(pkg.video_path)
        if not video.exists():
            return PublishResult(platform=self.platform, status="failed", note="video file missing")
        headers = {"Authorization": f"Bearer {os.environ['TIKTOK_ACCESS_TOKEN']}",
                   "Content-Type": "application/json; charset=UTF-8"}
        size = video.stat().st_size
        # The description carries the licence credits, so it can't be dropped.
        caption = f"{pkg.description}\n\n{' '.join(pkg.hashtags)}".strip()[:2200]
        try:
            info = httpx.post(f"{_BASE}/creator_info/query/", headers=headers, timeout=30)
            info.raise_for_status()
            creator = info.json().get("data", {})
            limit = creator.get("max_video_post_duration_sec") or 0
            if limit and pkg.duration > limit:
                return PublishResult(platform=self.platform, status="failed",
                                     note=f"video is {pkg.duration:.0f}s; this account's limit is {limit}s")
            privacy = "PUBLIC_TO_EVERYONE" if pkg.privacy == "public" else "SELF_ONLY"
            if privacy not in creator.get("privacy_level_options", [privacy]):
                return PublishResult(platform=self.platform, status="failed",
                                     note=f"{privacy} not allowed for this account")
            chunk_size, total = plan_chunks(size)
            init = httpx.post(f"{_BASE}/video/init/", headers=headers, timeout=60, json={
                "post_info": {"title": caption, "privacy_level": privacy,
                              "brand_content_toggle": False, "brand_organic_toggle": False,
                              "is_aigc": True},      # AI narration, disclosed
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": chunk_size, "total_chunk_count": total},
            })
            init.raise_for_status()
            data = init.json().get("data", {})
            upload_url = data.get("upload_url")
            publish_id = data.get("publish_id", "")
            if not upload_url:
                return PublishResult(platform=self.platform, status="failed",
                                     note=f"no upload_url in init response: {init.text[:200]}")
            upload_chunks(upload_url, video, chunk_size, total)
            self.log.info("TikTok upload submitted (publish_id=%s).", publish_id)
            return PublishResult(platform=self.platform, status="published", external_id=publish_id,
                                 note=f"publish_id={publish_id} (privacy={privacy})")
        except httpx.HTTPError as exc:
            raise ProviderError(f"TikTok upload failed: {exc}") from exc
