"""Check an uploaded YouTube video, and make it public only if every check passes.

Usage:
    python -m scripts.go_live <video_id> <run_id>              # check only
    python -m scripts.go_live <video_id> <run_id> --schedule   # check, then release at the next best time
    python -m scripts.go_live <video_id> <run_id> --public     # check, then publish now
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from core.config import ROOT_DIR, get_settings
from core.publishing.youtube import access_token

_API = "https://www.googleapis.com/youtube/v3"
_SLOTS = ROOT_DIR / "storage" / "release_slots.json"
# YouTube needs the video processed and the slot clearly in the future.
_LEAD = timedelta(minutes=45)


def next_release_slot(now: datetime, pub, taken: list[str]) -> datetime:
    """The first release time after `now` + lead time that no video already holds.

    `pub` carries release_timezone / release_weekday / release_weekend ("HH:MM").
    Returns an aware datetime in UTC.
    """
    tz = ZoneInfo(pub.release_timezone)
    local = now.astimezone(tz)
    held = {datetime.fromisoformat(t).astimezone(timezone.utc) for t in taken}
    for days in range(0, 60):
        day = (local + timedelta(days=days)).date()
        hhmm = pub.release_weekend if day.weekday() >= 5 else pub.release_weekday
        h, m = (int(x) for x in hhmm.split(":"))
        slot = datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(timezone.utc)
        if slot >= now.astimezone(timezone.utc) + _LEAD and slot not in held:
            return slot
    raise RuntimeError("no free release slot in the next 60 days")


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify an upload and optionally make it public")
    ap.add_argument("video_id")
    ap.add_argument("run_id")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--public", action="store_true", help="publish now")
    when.add_argument("--schedule", action="store_true", help="release at the next best time")
    args = ap.parse_args()
    h = {"Authorization": f"Bearer {access_token()}"}
    bundle = ROOT_DIR / get_settings().publishing.review_dir / args.run_id
    meta = next(m for m in json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
                if m["platform"] == "youtube")

    for _ in range(40):                       # wait for YouTube to finish processing
        item = httpx.get(f"{_API}/videos", headers=h, timeout=30, params={
            "part": "snippet,status,contentDetails,processingDetails",
            "id": args.video_id}).json()["items"][0]
        if item.get("processingDetails", {}).get("processingStatus") != "processing":
            break
        time.sleep(30)

    s, st, cd = item["snippet"], item["status"], item["contentDetails"]
    caps = httpx.get(f"{_API}/captions", headers=h, timeout=30,
                     params={"part": "snippet", "videoId": args.video_id}).json().get("items", [])
    checks = {
        "upload processed": st.get("uploadStatus") == "processed",
        "not rejected": not st.get("rejectionReason") and not st.get("failureReason"),
        "title matches": s["title"] == meta["title"],
        "description has disclaimer": "Disclaimer:" in s["description"],
        "description has credits link": f"content/credits/{args.run_id}.txt" in s["description"],
        "custom thumbnail": "maxres" in s["thumbnails"] or "sqp=" in s["thumbnails"]["default"]["url"],
        "caption track": any(c["snippet"]["language"] == "en" for c in caps),
        "not made for kids": st.get("madeForKids") is False,
        "HD": cd.get("definition") == "hd",
    }
    for name, ok in checks.items():
        print(f"[{'OK' if ok else '!!'}] {name}")
    print("privacy now:", st["privacyStatus"], "| duration:", cd.get("duration"))

    if args.schedule:
        if not all(checks.values()):
            raise SystemExit("Not scheduling it: a check failed.")
        pub = get_settings().publishing
        taken = json.loads(_SLOTS.read_text(encoding="utf-8")) if _SLOTS.exists() else []
        slot = next_release_slot(datetime.now(timezone.utc), pub, taken)
        stamp = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"id": args.video_id, "status": {
            "privacyStatus": "private", "publishAt": stamp, "selfDeclaredMadeForKids": False,
            "embeddable": True, "license": "youtube", "publicStatsViewable": True}}
        httpx.put(f"{_API}/videos", headers=h, params={"part": "status"}, json=body,
                  timeout=60).raise_for_status()
        now = httpx.get(f"{_API}/videos", headers=h, timeout=30,
                        params={"part": "status", "id": args.video_id}).json()["items"][0]["status"]
        if not now.get("publishAt"):
            raise SystemExit("YouTube did not keep the release time; the video stays private.")
        _SLOTS.parent.mkdir(parents=True, exist_ok=True)
        _SLOTS.write_text(json.dumps(sorted({*taken, slot.isoformat()})), encoding="utf-8")
        tz = ZoneInfo(pub.release_timezone)
        print(f"release at: {slot.astimezone(tz):%a %d %b %H:%M} {pub.release_timezone} "
              f"({slot.astimezone(ZoneInfo(pub.timezone)):%a %d %b %H:%M} {pub.timezone}) "
              f"| YouTube publishAt {now['publishAt']}")

    if args.public:
        if not all(checks.values()):
            raise SystemExit("Not making it public: a check failed.")
        body = {"id": args.video_id, "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False, "embeddable": True,
            "license": "youtube", "publicStatsViewable": True}}
        httpx.put(f"{_API}/videos", headers=h, params={"part": "status"}, json=body,
                  timeout=60).raise_for_status()
        now = httpx.get(f"{_API}/videos", headers=h, timeout=30,
                        params={"part": "status", "id": args.video_id}).json()["items"][0]["status"]
        print("privacy after:", now["privacyStatus"])


if __name__ == "__main__":
    main()
