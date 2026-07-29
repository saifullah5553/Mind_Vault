"""Synthetic presenter portrait generation.

Creates a CONSISTENT, fictional presenter face and caches it so the same persona
appears in every video (a real brand asset).

Providers (free-first, pluggable):
- stable_diffusion : photoreal synthetic face from a FIXED seed (needs a GPU +
  `diffusers`+`torch`). The seed makes her look the same every time.
- stylized         : a tasteful CPU portrait card (Pillow, $0, always works).
  Clearly stylized — NOT a claim to be a real photo.

ETHICS: the face is fictional (a person who does not exist). We never take a real
person's likeness as input.
"""

from __future__ import annotations

from pathlib import Path

from core.config import ROOT_DIR
from core.logging_setup import get_logger

log = get_logger("media.avatar")


def _sd_portrait(appearance: str, seed: int, out: Path, size: int = 768) -> bool:  # pragma: no cover - GPU
    try:
        import torch  # type: ignore
        from diffusers import StableDiffusionPipeline  # type: ignore
    except Exception:
        return False
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            # SD on CPU is impractically slow for automation; skip to fallback.
            log.info("No CUDA GPU; skipping Stable Diffusion portrait.")
            return False
        pipe = StableDiffusionPipeline.from_pretrained(
            "runwayml/stable-diffusion-v1-5", torch_dtype=torch.float16).to(device)
        generator = torch.Generator(device=device).manual_seed(seed)
        prompt = (appearance + ", headshot portrait, sharp focus, 85mm, high detail")
        negative = "deformed, extra fingers, watermark, text, cartoon, multiple people"
        image = pipe(prompt, negative_prompt=negative, num_inference_steps=30,
                     guidance_scale=7.0, generator=generator,
                     height=size, width=size).images[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out)
        log.info("Generated photoreal presenter portrait via Stable Diffusion.")
        return True
    except Exception as exc:
        log.warning("Stable Diffusion portrait failed (%s).", exc)
        return False


def _stylized_portrait(name: str, seed: int, out: Path, size: int = 768) -> bool:
    """A clean, professional stylized host avatar (not photoreal, honest)."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        # Deterministic, on-brand palette from the seed.
        hues = [(122, 92, 200), (210, 96, 140), (96, 168, 210), (208, 150, 84)]
        accent = hues[seed % len(hues)]
        bg_top = (24, 26, 38)
        bg_bot = tuple(int(c * 0.5) for c in accent)

        img = Image.new("RGB", (size, size), bg_top)
        d = ImageDraw.Draw(img)
        for y in range(size):
            t = y / (size - 1)
            d.line([(0, y), (size, y)], fill=tuple(int(bg_top[i] + (bg_bot[i] - bg_top[i]) * t) for i in range(3)))

        # Soft circular "portrait" area with a simple, tasteful silhouette.
        cx, cy, r = size // 2, int(size * 0.44), int(size * 0.26)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(238, 232, 240))
        # Stylized shoulders.
        d.ellipse([cx - int(r * 1.7), cy + int(r * 0.7), cx + int(r * 1.7), cy + int(r * 3.0)],
                  fill=(238, 232, 240))
        # Head silhouette (abstract, gender-neutral-but-soft).
        d.ellipse([cx - int(r * 0.62), cy - int(r * 0.5), cx + int(r * 0.62), cy + int(r * 0.75)],
                  fill=accent)

        def font(sz):
            for n in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
                try:
                    return ImageFont.truetype(n, sz)
                except Exception:
                    continue
            return ImageFont.load_default()

        name_f = font(int(size * 0.10))
        role_f = font(int(size * 0.045))
        d.text((cx, int(size * 0.80)), name, font=name_f, fill=(245, 245, 248), anchor="mm")
        d.text((cx, int(size * 0.90)), "AI Presenter", font=role_f, fill=accent, anchor="mm")

        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return True
    except Exception as exc:
        log.warning("Stylized portrait failed (%s).", exc)
        return False


def make_pip_badge(portrait_path: str, out_path: str | Path, size: int = 512,
                   ring: int = 10) -> str | None:
    """Build a circular, transparent-background version of the portrait for use as
    a picture-in-picture badge (reads as a broadcast presenter bug rather than a
    pasted rectangle). Regenerated whenever the source portrait is newer."""
    try:
        from PIL import Image, ImageDraw

        src = Path(portrait_path)
        out = Path(out_path)
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return str(out)

        img = Image.open(src).convert("RGBA")
        # Center-crop to a square, then resize.
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w - side) // 2 + side, (h - side) // 2 + side)).resize((size, size),
                                                                               Image.LANCZOS)
        # Circular alpha mask (supersampled for smooth edges).
        ss = 4
        mask = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * ss, size * ss), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)

        badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        badge.paste(img, (0, 0), mask)

        # Soft white ring for separation against any background.
        draw = ImageDraw.Draw(badge)
        draw.ellipse((ring // 2, ring // 2, size - ring // 2, size - ring // 2),
                     outline=(255, 255, 255, 210), width=ring)

        out.parent.mkdir(parents=True, exist_ok=True)
        badge.save(out, "PNG")
        log.info("Built circular presenter PiP badge -> %s", out.name)
        return str(out)
    except Exception as exc:
        log.warning("PiP badge build failed (%s); using the raw portrait.", exc)
        return None


def get_presenter_portrait(appearance: str, name: str, seed: int, portrait_path: str,
                           provider: str = "auto", force: bool = False) -> str | None:
    """Return a path to the (cached) presenter portrait, generating it if needed.

    NOTE: an operator-supplied portrait at `portrait_path` is always kept as-is —
    we never overwrite it — so a real AI-generated persona image you drop in
    becomes the permanent face of the brand.
    """
    out = ROOT_DIR / portrait_path if not Path(portrait_path).is_absolute() else Path(portrait_path)
    if out.exists() and not force:
        return str(out)

    ok = False
    if provider in ("auto", "stable_diffusion"):
        ok = _sd_portrait(appearance, seed, out)
    if not ok:
        ok = _stylized_portrait(name, seed, out)
    return str(out) if ok else None
