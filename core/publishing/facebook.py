"""Facebook Page video publisher (Graph API, via httpx).

Required env: FACEBOOK_APP_ID, FACEBOOK_USER_TOKEN, FACEBOOK_PAGE_ID,
FACEBOOK_PAGE_TOKEN.

Flow (Meta Video API): start an upload session on the app, send the file (resuming
from the offset the session reports if the connection drops), then create the
Page video from the upload handle. The file is streamed, never held in memory.

Honours pkg.privacy: anything but "public" is created unpublished. Nothing runs
unless dry_run is false and credentials are present.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from core.errors import ProviderError
from core.publishing.base import GRAPH_VERSION, PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
_GRAPH_VIDEO = f"https://graph-video.facebook.com/{GRAPH_VERSION}"
_RETRIES = 5


def _stream(path: Path, offset: int, block: int = 1 << 20):
    with path.open("rb") as fh:
        fh.seek(offset)
        while chunk := fh.read(block):
            yield chunk


def upload_file(video: Path, app_id: str, user_token: str, sleep=time.sleep) -> str:
    """Resumable upload. Returns the uploaded file handle."""
    size = video.stat().st_size
    start = httpx.post(f"{_GRAPH}/{app_id}/uploads", timeout=60, params={
        "file_name": video.name, "file_length": size, "file_type": "video/mp4",
        "access_token": user_token})
    start.raise_for_status()
    session = f"{_GRAPH}/{start.json()['id']}"
    auth = {"Authorization": f"OAuth {user_token}"}
    offset = 0
    for attempt in range(_RETRIES + 1):
        try:
            r = httpx.post(session, content=_stream(video, offset), timeout=None, headers={
                **auth, "file_offset": str(offset), "Content-Length": str(size - offset)})
            if r.status_code == 200 and "h" in r.json():
                return r.json()["h"]
            if r.status_code < 500:
                raise ProviderError(f"Facebook upload refused: {r.status_code} {r.text[:200]}")
        except httpx.TransportError:
            pass
        if attempt == _RETRIES:
            break
        sleep(min(60, 2 ** (attempt + 1)))
        offset = int(httpx.get(session, headers=auth, timeout=60).json().get("file_offset", 0))
    raise ProviderError("Facebook upload kept failing; giving up")


class FacebookPublisher(PlatformPublisher):
    platform = "facebook"
    required_env = ["FACEBOOK_APP_ID", "FACEBOOK_USER_TOKEN", "FACEBOOK_PAGE_ID",
                    "FACEBOOK_PAGE_TOKEN"]

    def publish(self, pkg: PublishPackage) -> PublishResult:
        video = Path(pkg.video_path)
        if not video.exists():
            return PublishResult(platform=self.platform, status="failed", note="video file missing")
        page_id = os.environ["FACEBOOK_PAGE_ID"]
        desc = f"{pkg.description}\n\n{' '.join(pkg.hashtags)}".strip()
        try:
            handle = upload_file(video, os.environ["FACEBOOK_APP_ID"],
                                 os.environ["FACEBOOK_USER_TOKEN"])
            r = httpx.post(f"{_GRAPH_VIDEO}/{page_id}/videos", timeout=120, data={
                "access_token": os.environ["FACEBOOK_PAGE_TOKEN"],
                "title": pkg.title, "description": desc,
                "fbuploader_video_file_chunk": handle,
                # Never public unless explicitly asked for.
                "published": "true" if pkg.privacy == "public" else "false",
            })
            r.raise_for_status()
            vid = r.json().get("id", "")
            url = f"https://www.facebook.com/{vid}" if vid else ""
            self.log.info("Uploaded to Facebook (%s): %s", pkg.privacy, url)
            return PublishResult(platform=self.platform, status="published", url=url,
                                 external_id=vid, note=f"privacy={pkg.privacy}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"Facebook upload failed: {exc}") from exc
