"""What is working on the channel: every upload's numbers, ranked, as a Markdown report
the daily run reads before it writes the next script.

    .venv\\Scripts\\python -m scripts.analytics_report

Writes storage/analytics/latest.md (and a dated copy plus latest.json). Read-only: it
never changes a video. Public counts (views, likes, comments) come from the YouTube
Data API; retention, watch time, shares and subscribers from the YouTube Analytics API
when it is enabled for the Google Cloud project (otherwise the report says how).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

import core.config  # noqa: F401  (loads .env)
from core.config import ROOT_DIR

_DATA = "https://www.googleapis.com/youtube/v3/"
_REPORTS = "https://youtubeanalytics.googleapis.com/v2/reports"
_TOTALS = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained"
OUT = ROOT_DIR / "storage" / "analytics"
_PART = re.compile(r"\s*\(Part (\d+)/(\d+)\)\s*$")


def _seconds(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return (int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)) if m else 0


def uploads(token: str) -> list[dict]:
    """Every upload on the channel with its public numbers."""
    h = {"Authorization": f"Bearer {token}"}
    ch = httpx.get(_DATA + "channels", headers=h, timeout=60,
                   params={"part": "contentDetails,statistics", "mine": "true"}).json()["items"][0]
    playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        p = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
        if page:
            p["pageToken"] = page
        j = httpx.get(_DATA + "playlistItems", headers=h, params=p, timeout=60).json()
        ids += [i["contentDetails"]["videoId"] for i in j.get("items", [])]
        page = j.get("nextPageToken")
        if not page:
            break
    rows = []
    for i in range(0, len(ids), 50):
        j = httpx.get(_DATA + "videos", headers=h, timeout=60, params={
            "part": "snippet,statistics,status,contentDetails", "id": ",".join(ids[i:i + 50])}).json()
        for it in j.get("items", []):
            st, s, sn = it["status"], it.get("statistics", {}), it["snippet"]
            secs = _seconds(it["contentDetails"]["duration"])
            m = _PART.search(sn["title"])
            rows.append({
                "id": it["id"], "title": sn["title"], "public": st["privacyStatus"] == "public",
                "published": sn.get("publishedAt", ""), "scheduled": st.get("publishAt", ""),
                "seconds": secs, "kind": "short" if secs <= 180 else "long",
                "part": int(m[1]) if m else 0, "parts": int(m[2]) if m else 0,
                "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0))})
    return [r for r in rows if r["public"]], ch.get("statistics", {})


def analytics(token: str, rows: list[dict]) -> str:
    """Add retention and watch numbers; returns "" or why they are missing."""
    h = {"Authorization": f"Bearer {token}"}
    end = datetime.now(timezone.utc).date().isoformat()
    for r in rows:
        start = (r["published"] or "2026-01-01")[:10]
        q = {"ids": "channel==MINE", "startDate": start, "endDate": end,
             "metrics": _TOTALS, "filters": f"video=={r['id']}"}
        resp = httpx.get(_REPORTS, headers=h, params=q, timeout=60)
        if resp.status_code == 403:
            return ("The YouTube Analytics API is switched off for the Google Cloud project, so "
                    "retention and watch time are missing. Enable it at "
                    "https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com")
        if resp.status_code != 200:
            return f"YouTube Analytics answered {resp.status_code}"
        j = resp.json()
        names = [c["name"] for c in j.get("columnHeaders", [])]
        if j.get("rows"):
            r.update(dict(zip(names, j["rows"][0])))
        curve = httpx.get(_REPORTS, headers=h, timeout=60, params={
            **q, "metrics": "audienceWatchRatio", "dimensions": "elapsedVideoTimeRatio"}).json()
        pts = sorted((float(x), float(y)) for x, y in (curve.get("rows") or []))
        if pts:
            r["curve"] = [round(min(pts, key=lambda p: abs(p[0] - t / 10))[1] * 100) for t in range(11)]
    return ""


def _age_hours(r: dict) -> float:
    try:
        t = datetime.fromisoformat(r["published"].replace("Z", "+00:00"))
        return max(1.0, (datetime.now(timezone.utc) - t).total_seconds() / 3600)
    except ValueError:
        return 1.0


def report(rows: list[dict], channel: dict, note: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for r in rows:
        r["per_day"] = round(r["views"] / _age_hours(r) * 24, 1)
        r["like_rate"] = round(100 * r["likes"] / r["views"], 1) if r["views"] else 0.0
    shorts = [r for r in rows if r["kind"] == "short"]
    longs = [r for r in rows if r["kind"] == "long"]
    total = sum(r["views"] for r in rows) or 1
    lines = [f"# Channel analytics — {now}", "",
             f"Channel: {channel.get('viewCount', '?')} views, {channel.get('subscriberCount', '?')} "
             f"subscribers, {len(rows)} public uploads.",
             f"Shorts: {len(shorts)} videos, {sum(r['views'] for r in shorts)} views "
             f"({100 * sum(r['views'] for r in shorts) // total}% of all). "
             f"Long: {len(longs)} videos, {sum(r['views'] for r in longs)} views.", ""]
    if note:
        lines += [f"**Missing data:** {note}", ""]

    def table(title, items, key):
        out = [f"## {title}", "",
               "| views | /day | likes | like % | avg view % | subs | length | title |",
               "|---:|---:|---:|---:|---:|---:|---:|---|"]
        for r in sorted(items, key=key, reverse=True):
            avp = r.get("averageViewPercentage")
            out.append(f"| {r['views']} | {r['per_day']} | {r['likes']} | {r['like_rate']} | "
                       f"{round(avp) if avp is not None else '-'} | {r.get('subscribersGained', '-')} | "
                       f"{r['seconds']}s | {r['title'][:80]} |")
        return out + [""]

    lines += table("Shorts, by views", shorts, lambda r: r["views"])
    lines += table("Long videos, by views", longs, lambda r: r["views"])
    curves = [r for r in rows if r.get("curve")]
    if curves:
        lines += ["## Retention (percent still watching at 0%, 10% … 100% of the video)", ""]
        for r in sorted(curves, key=lambda r: -r["views"])[:12]:
            drop = min(range(1, 11), key=lambda i: r["curve"][i] - r["curve"][i - 1])
            lines.append(f"- {r['title'][:60]}: {r['curve']} — steepest drop before {drop * 10}%")
        lines.append("")
    if len(shorts) >= 6:
        ranked = sorted(shorts, key=lambda r: r["views"], reverse=True)
        third = max(2, len(ranked) // 3)
        lines += ["## Shorts: top third vs bottom third", "",
                  "Top: " + "; ".join(f"\"{_PART.sub('', r['title'])}\" ({r['views']})" for r in ranked[:third]),
                  "", "Bottom: " + "; ".join(f"\"{_PART.sub('', r['title'])}\" ({r['views']})"
                                             for r in ranked[-third:]), ""]
        firsts = [r for r in shorts if r["part"] == 1]
        if firsts:
            avg_first = sum(r["views"] for r in firsts) / len(firsts)
            avg_rest = sum(r["views"] for r in shorts if r["part"] > 1) / max(1, len([r for r in shorts if r["part"] > 1]))
            lines += [f"Part 1 averages {avg_first:.0f} views; later parts {avg_rest:.0f}.", ""]
    lines += ["Read with care: under ~100 views per video, differences are mostly chance. "
              "Act on patterns that repeat across several videos, not on one result.", ""]
    return "\n".join(lines)


def main() -> None:
    from core.publishing.youtube import access_token
    token = access_token()
    rows, channel = uploads(token)
    note = analytics(token, rows)
    OUT.mkdir(parents=True, exist_ok=True)
    text = report(rows, channel, note)
    stamp = datetime.now().strftime("%Y-%m-%d")
    (OUT / "latest.md").write_text(text, encoding="utf-8")
    (OUT / f"report_{stamp}.md").write_text(text, encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
