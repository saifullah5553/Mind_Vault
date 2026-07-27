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

import os
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


class YouTubePublisher(PlatformPublisher):
    platform = "youtube"
    required_env = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]

    def _access_token(self) -> str:
        resp = httpx.post(_TOKEN_URL, data={
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["access_token"]

    def publish(self, pkg: PublishPackage) -> PublishResult:  # pragma: no cover - needs creds+network
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
            # 2) Upload the bytes.
            with video.open("rb") as fh:
                up = httpx.put(session_url, content=fh.read(),
                               headers={"Content-Type": "video/*"}, timeout=None)
            up.raise_for_status()
            video_id = up.json()["id"]
            url = f"https://youtu.be/{video_id}"

            # 3) Custom thumbnail (best-effort).
            if pkg.thumbnail_path and Path(pkg.thumbnail_path).exists():
                try:
                    with open(pkg.thumbnail_path, "rb") as th:
                        httpx.post(_THUMB_URL, params={"videoId": video_id}, headers=headers,
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
            return PublishResult(platform=self.platform, status="published", url=url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube upload failed: {exc}") from exc

    def _upload_caption(self, video_id: str, srt_path: str, token: str) -> None:  # pragma: no cover
        meta = {"snippet": {"videoId": video_id, "language": "en", "name": "English", "isDraft": False}}
        # captions.insert expects multipart (metadata + file); httpx handles it.
        with open(srt_path, "rb") as fh:
            httpx.post(
                _CAPTION_URL, params={"part": "snippet"},
                headers={"Authorization": f"Bearer {token}"},
                files={"metadata": ("meta.json", str(meta), "application/json"),
                       "file": ("captions.srt", fh.read(), "application/octet-stream")},
                timeout=60).raise_for_status()
