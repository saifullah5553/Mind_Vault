"""Publisher factory + readiness reporting."""

from __future__ import annotations

from core.publishing.base import PlatformPublisher
from core.publishing.facebook import FacebookPublisher
from core.publishing.instagram import InstagramPublisher
from core.publishing.tiktok import TikTokPublisher
from core.publishing.youtube import YouTubePublisher

_PUBLISHERS: dict[str, type[PlatformPublisher]] = {
    "youtube": YouTubePublisher,
    "facebook": FacebookPublisher,
    "tiktok": TikTokPublisher,
    "instagram": InstagramPublisher,
}


def get_publisher(platform: str) -> PlatformPublisher | None:
    cls = _PUBLISHERS.get(platform)
    return cls() if cls else None


def publisher_status() -> dict[str, dict]:
    """Report, per platform, whether credentials are configured (for the doctor)."""
    out: dict[str, dict] = {}
    for name, cls in _PUBLISHERS.items():
        p = cls()
        out[name] = {"configured": p.is_configured(), "missing_env": p.missing_env()}
    return out
