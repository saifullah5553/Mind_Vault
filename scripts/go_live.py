"""Check an uploaded YouTube video, and make it public only if every check passes.

Usage:
    python -m scripts.go_live <video_id> <run_id>            # check only
    python -m scripts.go_live <video_id> <run_id> --public   # check, then publish
"""

from __future__ import annotations

import argparse
import json
import time

import httpx

from core.config import ROOT_DIR, get_settings
from core.publishing.youtube import access_token

_API = "https://www.googleapis.com/youtube/v3"


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify an upload and optionally make it public")
    ap.add_argument("video_id")
    ap.add_argument("run_id")
    ap.add_argument("--public", action="store_true")
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
