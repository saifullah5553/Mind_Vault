"""AI illustrations from Cloudflare Workers AI (free daily allowance, $0).

Used only where the script asks for one and no real photo can show the line: a
reconstruction of a scene, a landscape as it was, everyday life in a period.
Never for a real named person, a specific real object or document, or anything
presented as a record; those stay real photos. Every illustration is tagged on
screen ("ILLUSTRATION"), credited as AI, and covered by the disclaimer.

Model: FLUX.2 [klein] 4B (Black Forest Labs, Apache 2.0: commercial use
allowed; the 9B model is non-commercial and is not used). Widescreen 1920x1088,
about 300 of the 10,000 free daily neurons per picture.

Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env. Without them, or
when the day's allowance is spent, it returns None and the line keeps its photo.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger("media.ai_images")

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
LICENSE = "AI illustration (FLUX.2 klein 4B, Apache 2.0)"
SIZE = (1920, 1088)
CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "ai_cache"   # one file per prompt
# Added to every prompt: the look of a documentary still, and what must not appear.
STYLE = ("cinematic documentary film still, natural light, realistic, muted film colours, "
         "historically accurate clothing, buildings and objects for the period, "
         "no text, no letters, no writing, no logos, no watermark, no modern objects, "
         "no fantasy creatures")


def available() -> bool:
    return bool(os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"))


def generate(prompt: str, dest: Path) -> dict | None:
    """One widescreen picture for `prompt`, saved at `dest`. Metadata, or None.

    The token goes only in the Authorization header to api.cloudflare.com and is
    never logged."""
    if not prompt.strip():
        return None
    # Made once, reused by every later plan and render: re-planning a video used
    # to redraw its illustrations each time and spent the free daily allowance.
    import hashlib
    import shutil
    key = hashlib.sha1(f"{MODEL}|{SIZE}|{prompt.strip()}|{STYLE}".encode("utf-8")).hexdigest()[:20]
    cached = CACHE_DIR / f"{key}.jpg"
    if cached.exists() and cached.stat().st_size > 5000:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, dest)
        return _meta(prompt, dest)
    if not available():
        return None
    import httpx
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}"
    form = {"prompt": f"{prompt.strip()}. {STYLE}", "width": str(SIZE[0]), "height": str(SIZE[1])}
    try:
        r = httpx.post(url, files={k: (None, v) for k, v in form.items()}, timeout=120,
                       headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN'].strip()}"})
        if r.status_code != 200:
            # The body explains quota and permission errors; it holds no secret.
            log.warning("Cloudflare illustration failed (%s): %s", r.status_code, r.text[:200])
            return None
        if "json" in r.headers.get("content-type", ""):
            raw = base64.b64decode((r.json().get("result") or {}).get("image") or "")
        else:
            raw = r.content
        if len(raw) < 5000:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)
    except Exception as exc:
        log.warning("Cloudflare illustration failed (%s).", type(exc).__name__)
        return None
    return _meta(prompt, dest)


def _meta(prompt: str, dest: Path) -> dict:
    return {"path": str(dest), "title": f"Illustration: {prompt.strip()[:100]}", "url": "",
            "page": "https://developers.cloudflare.com/workers-ai/models/flux-2-klein-4b/",
            "license": LICENSE, "credit": "AI illustration, FLUX.2 klein 4B on Cloudflare Workers AI",
            "source": "AI illustration", "width": SIZE[0], "ai": True}


MAX_PER_VIDEO = 12


def parse(spec: str) -> list[tuple]:
    """'rode to a crack = wide shot of ...; camped in booths = ...' ->
    [(cue regex, prompt), ...]. The cue is matched case-insensitively, in order."""
    import re
    out = []
    for part in (spec or "").split(";"):
        cue, eq, prompt = part.partition("=")
        if eq and cue.strip() and prompt.strip():
            out.append((re.compile(re.escape(cue.strip()), re.I), prompt.strip()))
    return out
