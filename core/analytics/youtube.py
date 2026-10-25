"""Live YouTube analytics (YouTube Analytics API v2, via httpx — read-only).

Uses the same refresh token as uploads, which must also carry the scope
`https://www.googleapis.com/auth/yt-analytics.readonly` (see docs/PUBLISHING.md).

Only metrics documented at developers.google.com/youtube/analytics/metrics are
requested. Thumbnail impressions/CTR are not among them, so `ctr` stays 0 rather
than being estimated.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from core.errors import ProviderError
from core.publishing.youtube import access_token

_REPORTS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
_TOTALS = ("views", "estimatedMinutesWatched", "averageViewDuration",
           "averageViewPercentage", "likes", "comments", "shares", "subscribersGained")


def _query(token: str, **params) -> dict:
    try:
        r = httpx.get(_REPORTS_URL, headers={"Authorization": f"Bearer {token}"},
                      params={"ids": "channel==MINE", **params}, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        raise ProviderError(f"YouTube Analytics query failed: {exc}") from exc


def _row(report: dict) -> dict:
    """First result row as {metric: value} (a filtered report has one row)."""
    names = [h["name"] for h in report.get("columnHeaders", [])]
    rows = report.get("rows") or []
    return dict(zip(names, rows[0])) if rows else {}


def _deciles(report: dict, n: int = 10) -> list[float]:
    """Audience retention at n even points (percent of viewers still watching)."""
    pts = sorted((float(x), float(y)) for x, y in (report.get("rows") or []))
    if not pts:
        return []
    out = []
    for i in range(n):
        target = i / (n - 1)
        x, y = min(pts, key=lambda p: abs(p[0] - target))
        out.append(round(y * 100, 1))
    return out


def video_report(video_id: str, published: date | None = None,
                 token: str | None = None, deciles: int = 10) -> dict:
    """Lifetime totals + retention curve for one video, mapped to Analytics fields."""
    token = token or access_token()
    start = (published or date.today() - timedelta(days=365)).isoformat()
    end = date.today().isoformat()
    totals = _row(_query(token, startDate=start, endDate=end,
                         metrics=",".join(_TOTALS), filters=f"video=={video_id}"))
    curve = _deciles(_query(token, startDate=start, endDate=end,
                            metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
                            filters=f"video=={video_id}"), deciles)
    views = int(totals.get("views", 0))
    retention = float(totals.get("averageViewPercentage", 0.0))
    return {
        "views": views,
        "ctr": 0.0,                                      # not exposed by the API
        "avg_view_duration": float(totals.get("averageViewDuration", 0.0)),
        "watch_time": round(float(totals.get("estimatedMinutesWatched", 0.0)) / 60, 2),
        "retention": retention,
        "retention_curve": curve,
        "completion_rate": curve[-1] if curve else 0.0,  # still watching at the end
        "likes": int(totals.get("likes", 0)),
        "comments": int(totals.get("comments", 0)),
        "shares": int(totals.get("shares", 0)),
        "subscribers_generated": int(totals.get("subscribersGained", 0)),
    }
