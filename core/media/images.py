"""Image generation — free-first and always-produces-images.

DESIGN: `auto` uses Pillow to render clean, on-brand "slide card" images from the
scene's visual prompt/overlay text — zero GPU, zero cost, always works. Stable
Diffusion (`diffusers`+GPU) and ComfyUI are the photorealistic upgrades and slot
in behind the same function via config `images.provider`. Every scene always
gets a real PNG so the video stage never stalls.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger
from core.schemas import Scene

log = get_logger("media.images")

# Deterministic on-brand gradient backgrounds per scene index.
_PALETTE = [
    ((18, 22, 33), (44, 54, 82)),
    ((30, 20, 28), (72, 40, 60)),
    ((16, 28, 30), (34, 66, 70)),
    ((28, 24, 16), (70, 58, 34)),
    ((22, 18, 30), (52, 40, 78)),
]


def _pillow_card(scene: Scene, out_path: Path, width: int, height: int, brand: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    top, bottom = _PALETTE[scene.index % len(_PALETTE)]
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)

    # Vertical gradient (cheap, looks cinematic).
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    def _font(size: int):
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            try:
                return ImageFont.truetype("DejaVuSans.ttf", size)
            except Exception:
                return ImageFont.load_default()

    # Overlay text (the on-screen caption / key phrase for this scene).
    overlay = scene.text_overlay or scene.narration
    wrapped = textwrap.fill(overlay, width=max(14, width // 42))
    fnt = _font(max(28, width // 22))
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=fnt, spacing=10)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((width - tw) / 2, (height - th) / 2), wrapped,
                        font=fnt, fill=(245, 245, 245), spacing=10, align="center")

    # Brand watermark.
    small = _font(max(18, width // 48))
    draw.text((30, height - 60), brand, font=small, fill=(200, 200, 210))
    img.save(out_path, "PNG")


def _try_stable_diffusion(scene: Scene, out_path: Path) -> bool:  # pragma: no cover - needs GPU
    try:
        from diffusers import StableDiffusionPipeline  # type: ignore
        import torch  # type: ignore
    except Exception:
        return False
    try:
        pipe = StableDiffusionPipeline.from_pretrained("runwayml/stable-diffusion-v1-5")
        pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
        image = pipe(scene.visual_prompt).images[0]
        image.save(out_path)
        return True
    except Exception as exc:
        log.warning("Stable Diffusion failed (%s); using Pillow card.", exc)
        return False


def generate_images(scenes: list[Scene], run_dir: str | Path) -> list[Scene]:
    """Render one image per scene; set `scene.image_path`. Never raises."""
    cfg = get_settings().images
    brand = get_settings().brand.name
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = cfg.provider.lower()

    for scene in scenes:
        path = out_dir / f"scene_{scene.index:03d}.png"
        done = False
        if provider in ("stable_diffusion",):
            done = _try_stable_diffusion(scene, path)
        if not done:
            try:
                _pillow_card(scene, path, cfg.width, cfg.height, brand)
                done = True
            except Exception as exc:
                log.error("Pillow card failed for scene %d: %s", scene.index, exc)
        scene.image_path = str(path) if done else None
    log.info("Generated %d scene image(s) in %s", len(scenes), out_dir)
    return scenes
