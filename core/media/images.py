"""Scene imagery — real documentary photos first, generated card as fallback.

Priority:
  1. `stock`  : a genuinely relevant, openly-licensed photograph (Wikimedia
                Commons / Openverse) composited full-bleed and cinematically
                graded. This is what makes the output look like a documentary
                instead of a slideshow.
  2. `stable_diffusion` : generated art (needs GPU).
  3. `pillow` : a clean typographic card — the always-works fallback.

Captions are rendered as broadcast-style lower-thirds subtitles (not giant
centered text), so frames read as film rather than PowerPoint.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger
from core.schemas import Scene

log = get_logger("media.images")

_PALETTE = [
    ((18, 22, 33), (44, 54, 82)),
    ((30, 20, 28), (72, 40, 60)),
    ((16, 28, 30), (34, 66, 70)),
    ((28, 24, 16), (70, 58, 34)),
    ((22, 18, 30), (52, 40, 78)),
]


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["arialbd.ttf", "seguibl.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_subtitle(img, text: str, width: int, height: int) -> None:
    """Broadcast lower-third subtitle: readable, unobtrusive, film-like."""
    from PIL import Image, ImageDraw

    if not text.strip():
        return
    draw = ImageDraw.Draw(img)
    fnt = _font(max(26, width // 34), bold=True)
    wrapped = textwrap.fill(text, width=max(22, int(width / (width // 34) * 1.7)))

    bbox = draw.multiline_textbbox((0, 0), wrapped, font=fnt, spacing=8)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) / 2
    y = height * 0.80 - th / 2

    # Soft dark scrim behind the text for guaranteed legibility.
    pad = int(width * 0.025)
    scrim = Image.new("RGBA", (int(tw + pad * 2), int(th + pad * 1.4)), (0, 0, 0, 130))
    img.paste(scrim, (int(x - pad), int(y - pad * 0.7)), scrim)

    # Outline + fill.
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        draw.multiline_text((x + dx, y + dy), wrapped, font=fnt, fill=(0, 0, 0),
                            spacing=8, align="center")
    draw.multiline_text((x, y), wrapped, font=fnt, fill=(250, 250, 252),
                        spacing=8, align="center")


def _cinematic_from_photo(src: Path, scene: Scene, out: Path, width: int, height: int,
                          brand: str, subtitle: bool = True) -> bool:
    """Full-bleed cover-crop of a real photo + cinematic grade + subtitle."""
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

        img = Image.open(src).convert("RGB")
        # Cover-crop to the target aspect (no letterboxing, no stretching).
        tr = width / height
        w, h = img.size
        if w / h > tr:
            nw = int(h * tr)
            img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / tr)
            img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        img = img.resize((width, height), Image.LANCZOS)

        # Grade: slight contrast + desaturation for a documentary look.
        img = ImageEnhance.Color(img).enhance(0.82)
        img = ImageEnhance.Contrast(img).enhance(1.12)

        # Vignette + bottom gradient so subtitles always read.
        grad = Image.new("L", (1, height), 0)
        for y in range(height):
            t = y / max(1, height - 1)
            grad.putpixel((0, y), int(30 + 165 * max(0.0, (t - 0.55) / 0.45) ** 1.4))
        grad = grad.resize((width, height))
        dark = Image.new("RGB", (width, height), (0, 0, 0))
        img = Image.composite(dark, img, grad.point(lambda v: v))

        # Re-blend so it darkens rather than replaces.
        base = Image.open(src).convert("RGB")
        if base.size != (width, height):
            base = img  # already processed
        img = Image.blend(img, img.filter(ImageFilter.SMOOTH), 0.15)

        if subtitle:
            _draw_subtitle(img, scene.text_overlay or scene.narration, width, height)

        d = ImageDraw.Draw(img)
        d.text((30, height - 46), brand, font=_font(max(16, width // 60)), fill=(210, 210, 220))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "JPEG", quality=88)
        return True
    except Exception as exc:
        log.warning("Photo composite failed (%s); falling back to card.", exc)
        return False


def _pillow_card(scene: Scene, out_path: Path, width: int, height: int, brand: str) -> None:
    from PIL import Image, ImageDraw

    top, bottom = _PALETTE[scene.index % len(_PALETTE)]
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    _draw_subtitle(img, scene.text_overlay or scene.narration, width, height)
    draw.text((30, height - 46), brand, font=_font(max(16, width // 60)), fill=(200, 200, 210))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88)


def _try_stable_diffusion(scene: Scene, out_path: Path) -> bool:  # pragma: no cover - GPU
    try:
        from diffusers import StableDiffusionPipeline  # type: ignore
        import torch  # type: ignore
    except Exception:
        return False
    try:
        if not torch.cuda.is_available():
            return False
        pipe = StableDiffusionPipeline.from_pretrained("runwayml/stable-diffusion-v1-5").to("cuda")
        pipe(scene.visual_prompt).images[0].save(out_path)
        return True
    except Exception as exc:
        log.warning("Stable Diffusion failed (%s).", exc)
        return False


def generate_images(scenes: list[Scene], run_dir: str | Path,
                    topic: str = "", category: str = "history") -> list[Scene]:
    """Render one frame per scene. Sets `scene.image_path`. Never raises."""
    cfg = get_settings().images
    brand = get_settings().brand.name
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = cfg.provider.lower()
    width, height = cfg.width, cfg.height

    credits: list[dict] = []
    use_stock = provider in ("auto", "stock")

    # One coherent, on-topic image pool for the whole video (see stock.fetch_pool).
    pool: list[dict] = []
    if use_stock and topic:
        try:
            from core.media.stock import fetch_pool
            want = min(len(scenes), int(cfg.style and 12 or 12))
            pool = fetch_pool(topic, max(4, want), out_dir, category=category)
        except Exception as exc:
            log.warning("Image pool fetch failed (%s); using cards.", exc)

    for scene in scenes:
        out = out_dir / f"scene_{scene.index:03d}.jpg"
        done = False

        if pool:
            # Cycle the pool so consecutive scenes differ but stay on-subject.
            meta = pool[scene.index % len(pool)]
            done = _cinematic_from_photo(Path(meta["path"]), scene, out, width, height, brand)
            if done:
                credits.append(meta)

        if not done and provider == "stable_diffusion":
            done = _try_stable_diffusion(scene, out)

        if not done:
            try:
                _pillow_card(scene, out, width, height, brand)
                done = True
            except Exception as exc:
                log.error("Card render failed for scene %d: %s", scene.index, exc)

        scene.image_path = str(out) if done else None

    # Clean the downloaded originals once they've been composited.
    for p in out_dir.glob("_pool_*"):
        try:
            p.unlink()
        except Exception:
            pass

    if credits:
        _write_credits(out_dir, credits)
    log.info("Generated %d scene frame(s) (%d from real photos) in %s",
             len(scenes), len(credits), out_dir)
    return scenes


def _write_credits(out_dir: Path, credits: list[dict]) -> None:
    """Save attribution so it can be appended to the video description."""
    lines = ["Image credits (openly licensed):"]
    seen = set()
    for c in credits:
        key = (c.get("title"), c.get("source"))
        if key in seen:
            continue
        seen.add(key)
        who = f" by {c['credit']}" if c.get("credit") else ""
        lines.append(f"- {c.get('title','')}{who} — {c.get('source','')} ({c.get('license','')})")
    (out_dir / "credits.txt").write_text("\n".join(lines), encoding="utf-8")
