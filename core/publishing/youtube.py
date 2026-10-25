"""YouTube publisher (YouTube Data API v3, via httpx — no heavy SDK).

Auth: an OAuth2 *refresh token* (obtained once via the consent flow) is exchanged
for a short-lived access token at upload time. Then a resumable upload posts the
video, a custom thumbnail is set, and the SRT caption track is attached.

Required env (set in .env / GitHub Secrets):
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN

Nothing here runs unless publishing.dry_run is false and these are present.
See docs/PUBLISHING.md for how to get the refresh token.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path

import httpx

from core.errors import ProviderError
from core.publishing.base import PlatformPublisher
from core.schemas import PublishPackage, PublishResult

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
_CAPTION_URL = "https://www.googleapis.com/upload/youtube/v3/captions"

# Standard YouTube categoryId: 27 = Education.
_CATEGORY_ID = "27"

# Resumable-upload chunk: must be a multiple of 256 KiB. 8 MiB keeps memory flat
# (a 12-minute 1440p video is hundreds of MB) and limits re-sending on a drop.
_CHUNK = 32 * 256 * 1024
_UPLOAD_RETRIES = 5


def access_token() -> str:
    """Exchange the stored refresh token for a short-lived access token.
    Shared by uploads and live analytics (core/analytics/youtube.py)."""
    resp = httpx.post(_TOKEN_URL, data={
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _upload_chunks(session_url: str, video: Path, sleep=time.sleep) -> dict:
    """Send the file in chunks to a resumable session; resume after errors.

    YouTube answers 308 for each accepted chunk (with the stored byte range in
    `Range`) and 200/201 with the video resource once complete. On a dropped
    connection or a 5xx we ask the session how much it has and continue from
    there, instead of re-sending the whole file.
    """
    size = video.stat().st_size
    offset, failures = 0, 0
    with video.open("rb") as fh:
        while True:
            fh.seek(offset)
            chunk = fh.read(_CHUNK)
            end = offset + len(chunk) - 1
            try:
                r = httpx.put(session_url, content=chunk, timeout=300, headers={
                    "Content-Type": "video/*",
                    "Content-Range": f"bytes {offset}-{end}/{size}"})
            except httpx.TransportError:
                r = None
            if r is not None and r.status_code in (200, 201):
                return r.json()
            if r is not None and r.status_code == 308:
                rng = r.headers.get("Range")          # e.g. "bytes=0-8388607"
                offset = int(rng.split("-")[1]) + 1 if rng else 0
                failures = 0
                continue
            if r is not None and r.status_code < 500:
                r.raise_for_status()                  # 4xx: not retryable
            failures += 1
            if failures > _UPLOAD_RETRIES:
                raise ProviderError("YouTube upload kept failing; giving up")
            sleep(min(60, 2 ** failures))
            # Ask the session what it already holds, then resume from there.
            q = httpx.put(session_url, content=b"", timeout=60,
                          headers={"Content-Range": f"bytes */{size}"})
            if q.status_code in (200, 201):
                return q.json()
            rng = q.headers.get("Range") if q.status_code == 308 else None
            offset = int(rng.split("-")[1]) + 1 if rng else 0


class YouTubePublisher(PlatformPublisher):
    platform = "youtube"
    required_env = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]

    def _access_token(self) -> str:
        return access_token()

    def publish(self, pkg: PublishPackage) -> PublishResult:
        video = Path(pkg.video_path)
        if not video.exists():
            return PublishResult(platform=self.platform, status="failed", note="video file missing")
        try:
            token = self._access_token()
            headers = {"Authorization": f"Bearer {token}"}
            body = {
                "snippet": {
                    "title": pkg.title[:100],
                    "description": pkg.description[:4900],
                    "tags": pkg.tags[:30],
                    "categoryId": _CATEGORY_ID,
                },
                "status": {"privacyStatus": pkg.privacy, "selfDeclaredMadeForKids": False},
            }
            size = video.stat().st_size
            # 1) Start a resumable session.
            init = httpx.post(
                _UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                headers={**headers, "X-Upload-Content-Length": str(size),
                         "X-Upload-Content-Type": "video/*"},
                json=body, timeout=60)
            init.raise_for_status()
            session_url = init.headers["Location"]
            # 2) Upload the bytes in resumable chunks.
            video_id = _upload_chunks(session_url, video)["id"]
            url = f"https://youtu.be/{video_id}"

            # 3) Custom thumbnail (best-effort).
            if pkg.thumbnail_path and Path(pkg.thumbnail_path).exists():
                try:
                    ctype = mimetypes.guess_type(pkg.thumbnail_path)[0] or "image/png"
                    with open(pkg.thumbnail_path, "rb") as th:
                        httpx.post(_THUMB_URL, params={"videoId": video_id},
                                   headers={**headers, "Content-Type": ctype},
                                   content=th.read(),
                                   timeout=60).raise_for_status()
                except Exception as exc:
                    self.log.warning("thumbnail set failed: %s", exc)

            # 4) Captions (best-effort).
            if pkg.srt_path and Path(pkg.srt_path).exists():
                try:
                    self._upload_caption(video_id, pkg.srt_path, token)
                except Exception as exc:
                    self.log.warning("caption upload failed: %s", exc)

            self.log.info("Published to YouTube: %s", url)
            return PublishResult(platform=self.platform, status="published", url=url,
                                 external_id=video_id)
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube upload failed: {exc}") from exc

    def _upload_caption(self, video_id: str, srt_path: str, token: str) -> None:
        meta = {"snippet": {"videoId": video_id, "language": "en", "name": "English", "isDraft": False}}
        # captions.insert expects multipart (metadata + file). The metadata part
        # must be JSON: str(dict) gives Python's single-quoted repr, which the
        # API rejects, so every caption upload would have failed.
        with open(srt_path, "rb") as fh:
            httpx.post(
                _CAPTION_URL, params={"part": "snippet", "uploadType": "multipart"},
                headers={"Authorization": f"Bearer {token}"},
                files={"metadata": ("meta.json", json.dumps(meta), "application/json"),
                       "file": ("captions.srt", fh.read(), "application/octet-stream")},
                timeout=60).raise_for_status()
