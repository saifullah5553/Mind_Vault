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

import re
import textwrap
from pathlib import Path

from core.config import get_settings
from core.logging_setup import get_logger
from core.media import credits
from core.media.themes import known_names, pick
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

        # Grade. With a subtitle the frame is muted and darkened at the bottom
        # so text reads; without one the picture keeps its colour (eye-catching
        # imagery is the point) and only gets a light edge vignette.
        img = ImageEnhance.Color(img).enhance(0.82 if subtitle else 1.0)
        img = ImageEnhance.Contrast(img).enhance(1.12 if subtitle else 1.05)

        grad = Image.new("L", (1, height), 0)
        for y in range(height):
            t = y / max(1, height - 1)
            if subtitle:
                v = 30 + 165 * max(0.0, (t - 0.55) / 0.45) ** 1.4
            else:
                v = 70 * max(0.0, (t - 0.80) / 0.20) ** 2     # soft floor for the brand mark
            grad.putpixel((0, y), int(v))
        grad = grad.resize((width, height))
        dark = Image.new("RGB", (width, height), (0, 0, 0))
        img = Image.composite(dark, img, grad.point(lambda v: v))

        # Re-blend so it darkens rather than replaces.
        base = Image.open(src).convert("RGB")
        if base.size != (width, height):
            base = img  # already processed
        if subtitle:
            img = Image.blend(img, img.filter(ImageFilter.SMOOTH), 0.15)

        if subtitle:
            _draw_subtitle(img, scene.text_overlay or scene.narration, width, height)

        d = ImageDraw.Draw(img)
        d.text((30, height - 46), brand, font=_font(max(16, width // 60)), fill=(210, 210, 220))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "JPEG", quality=92, subsampling=0)
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
                    topic: str = "", category: str = "history",
                    subtitles: bool = True, illustrate: str = "") -> list[Scene]:
    """Render one frame per scene. Sets `scene.image_path`. Never raises.

    `subtitles=False` (long-form: captions ship as a caption track) leaves the
    picture clean and keeps its colour instead of darkening it for text.
    """
    cfg = get_settings().images
    brand = get_settings().brand.name
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = cfg.provider.lower()
    width, height = cfg.width, cfg.height

    shown: list[dict] = []
    used: dict[str, int] = {}
    use_stock = provider in ("auto", "stock")

    # One coherent, on-topic image pool for the whole video (see stock.fetch_pool).
    pool: list[dict] = []
    if use_stock and topic:
        try:
            from core.media.stock import fetch_pool, fetch_themed_pool
            # One photo per still, so pictures don't repeat within a video.
            stills = sum(1 for s in scenes if not s.animation_kind and not s.clip_path)
            want = min(max(12, stills), cfg.pool_max)
            if ";" in topic:
                want = cfg.pool_max     # shared between the searches; parts differ in length
            if category == "psychology":
                # Abstract subjects: pick by mood from curated libraries.
                from core.media.themes import THEMES
                per_theme = max(2, -(-want // len(THEMES)))
                pool = fetch_themed_pool(topic, category, per_theme, out_dir)
            if len(pool) < 4:
                pool = fetch_pool(topic, max(4, want), out_dir, category=category)
            if category == "history":
                from core.media.stock import off_story_places
                pool = off_story_places(pool, [s.narration for s in scenes])
        except Exception as exc:
            log.warning("Image pool fetch failed (%s); using cards.", exc)

    from core.media.stock import part_per_line
    by_index = {s.index: s.narration for s in scenes}
    parts = part_per_line([by_index.get(i, "") for i in range(max(by_index, default=-1) + 1)],
                          topic)
    named_cache: dict[str, dict | None] = {}
    known = known_names(" ".join(s.narration for s in scenes))
    done_named: set[int] = set()
    director = {"showcases": [], "labelled": set(), "labels": []}   # see _direct

    def _shows(scene) -> bool:
        return not scene.animation_kind and not scene.clip_path

    # A named person/place/work gets the actual subject, once per video.
    # Only for scenes that will show a still (cards and footage don't).
    if use_stock:
        for scene in scenes:
            if not _shows(scene):
                continue
            out = out_dir / f"scene_{scene.index:03d}.jpg"
            meta = _named_image(scene.narration, named_cache, out_dir, category,
                                width, height, cfg.named_max, known=known)
            if meta and _cinematic_from_photo(Path(meta["path"]), scene, out, width,
                                              height, brand, subtitle=subtitles):
                shown.append(meta)
                scene.source = f"named '{meta.get('named', '')}': {meta.get('title', '')}"
                done_named.add(scene.index)
                _direct(scene, meta, out_dir, director, named=meta.get("named", ""))

    # AI illustrations the script asked for ('ILLUSTRATE: cue = prompt; ...'): the
    # first line containing each cue shows it, tagged on screen (core/media/ai_images.py).
    if illustrate.strip():
        from core.media import ai_images
        made = 0
        for cue, prompt in ai_images.parse(illustrate):
            if made >= ai_images.MAX_PER_VIDEO:
                break
            scene = next((s for s in scenes if _shows(s) and s.index not in done_named
                          and cue.search(s.narration)), None)
            if scene is None:
                log.info("Illustration cue not found in the script: %s", cue.pattern[:60])
                continue
            out = out_dir / f"scene_{scene.index:03d}.jpg"
            meta = ai_images.generate(prompt, out_dir / f"_ai_{scene.index:03d}.jpg")
            if meta and _cinematic_from_photo(Path(meta["path"]), scene, out, width, height,
                                              brand, subtitle=subtitles):
                shown.append(meta)
                scene.source = f"AI illustration: {prompt[:100]}"
                scene.tag = "ILLUSTRATION"
                done_named.add(scene.index)
                made += 1
        if made:
            log.info("AI illustrations: %d", made)

    # Every other line: the pool picture that fits what it says (stock.assign_pictures).
    assigned: dict[int, dict | None] = {}
    if pool and not any("theme" in m for m in pool):
        from core.media.stock import assign_pictures
        rest = [s for s in scenes if s.index not in done_named]
        picks = assign_pictures([s.narration for s in rest],
                                [parts[s.index] if s.index < len(parts) else 0 for s in rest],
                                pool, [_shows(s) for s in rest])
        assigned = {s.index: m for s, m in zip(rest, picks)}

    for scene in scenes:
        out = out_dir / f"scene_{scene.index:03d}.jpg"
        done = scene.index in done_named

        if pool and not done:
            if any("theme" in m for m in pool):
                # Only scenes that will show the still count towards "no repeats".
                # Footage and card scenes get one too, as a fallback, and used to
                # use the pool up: one picture appeared four times in a video.
                meta = pick(scene.narration, pool, used if _shows(scene) else dict(used))
            else:
                meta = assigned.get(scene.index) or pool[scene.index % len(pool)]
            done = _cinematic_from_photo(Path(meta["path"]), scene, out, width, height,
                                         brand, subtitle=subtitles)
            # Every scene gets a still as a fallback; only credit what will show.
            if done and _shows(scene):
                shown.append(meta)
                scene.source = str(meta.get("title", ""))[:120]
                _direct(scene, meta, out_dir, director)

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
    for p in [*out_dir.glob("_pool_*"), *out_dir.glob("_named_*"), *out_dir.glob("_ai_*")]:
        try:
            p.unlink()
        except Exception:
            pass

    if shown:
        credits.add(out_dir, shown, "image")
    log.info("Generated %d scene frame(s) (%d from real photos) in %s",
             len(scenes), len(shown), out_dir)
    return scenes


_SURNAMES = "\0surnames"              # cache entry: surnames of people already looked up


SHOWCASE_MAX = 6          # museum showcases per video
LABEL_MAX = 8             # name captions per video


def _story_countries() -> set[str]:
    try:
        from core.media import maps
        if maps.ensure_data():
            return {n for c in maps._countries() for n in c["names"]}
    except Exception:
        pass
    return set()


def _demonym(word: str) -> bool:
    """'Americans', 'Dutch', 'Japanese': a people, not a name to caption (a photo
    by 'Alexander Gardner (American, born Scotland)' of Japanese envoys got
    'AMERICANS')."""
    try:
        from core.media import maps
        if not maps.ensure_data():
            return False
        bare = re.sub(r"s$", "", word)
        return bool(maps.countries_in(word) or any(p.search(word) or p.search(bare)
                                                   for p, _ in maps.adjective_patterns()))
    except Exception:
        return False


def _direct(scene, meta: dict, out_dir: Path, state: dict, named: str = "") -> None:
    """Choose this photo's scene type from what its line says (core/media/scenes.py):
    a museum showcase when the line names an object or document the photo shows,
    else a name caption the first time a named person or place is seen."""
    import json
    import shutil

    from core.media import scenes
    from core.media.stock import match_words, named_words
    spec = scenes.showcase_for(scene.narration, meta)
    if spec and len(state["showcases"]) < SHOWCASE_MAX \
            and all(abs(scene.index - i) >= 3 for i in state["showcases"]):
        exhibit = out_dir / f"scene_{scene.index:03d}_exhibit.jpg"
        try:
            shutil.copyfile(meta["path"], exhibit)       # the uncropped original
            spec["photo"] = str(exhibit)
            scene.animation_kind = "showcase:" + json.dumps(spec)
            state["showcases"].append(scene.index)
            return
        except OSError as exc:
            log.debug("showcase copy failed (%s)", exc)
    # Name caption: a name the line says that the photo's title also carries.
    if len(state["labels"]) >= LABEL_MAX or any(abs(scene.index - i) < 3 for i in state["labels"]):
        return
    if named:
        name = named
    else:
        # One name, said in the line AND in the photo's own title (a description
        # can mention places the photo doesn't show: 'Althingi.jpg' is in
        # Reykjavik, not Thingvellir). Countries are left to the maps.
        shown = match_words(meta.get("title", ""))
        countries = _story_countries()
        hits = [re.sub(r"['\u2019]s$", "", w) for w in re.findall(r"[\w'\u2019-]+", scene.narration)[1:]
                if w[:1].isupper() and len(w) > 3]
        hits = [w for w in hits if named_words("x " + w) & shown and w not in countries
                and not _demonym(w)]
        name = hits[0] if hits else ""
    key = name.lower()
    if name and key not in state["labelled"]:
        state["labelled"].add(key)
        state["labels"].append(scene.index)
        scene.label = name.upper()


def _named_image(text: str, cache: dict, out_dir: Path, category: str,
                 width: int, height: int, limit: int,
                 known: set[str] | None = None) -> dict | None:
    """Picture of the first not-yet-shown subject this line names, or None."""
    from core.media.stock import fetch_named
    from core.media.themes import named_subjects

    surnames = cache.setdefault(_SURNAMES, set())
    for name in named_subjects(text, known):
        if name in cache or name in surnames:
            continue                      # shown already (or nothing found)
        if len(cache) - 1 >= limit:
            return None
        safe = re.sub(r"[^A-Za-z0-9]+", "_", name)[:40]
        meta = fetch_named(name, out_dir / f"_named_{safe}", category)
        cache[name] = meta
        # "Harlow" later on is this same person, not a search for the town.
        surnames.add(name.split()[-1])
        if meta:
            if (meta.get("width") or 0) < width:
                # Too small to fill the frame sharply: present it on a blurred
                # backdrop of itself rather than upscaling it into mush.
                framed = out_dir / f"_named_{safe}_framed.jpg"
                if _backdrop(Path(meta["path"]), framed, width, height):
                    meta = dict(meta, path=str(framed))
            return meta
    return None


def _backdrop(src: Path, out: Path, width: int, height: int) -> bool:
    """Small image centred, at most 1.5x its own size, over a blurred fill."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        img = Image.open(src).convert("RGB")
        r = max(width / img.width, height / img.height)
        bg = img.resize((round(img.width * r) + 1, round(img.height * r) + 1), Image.BILINEAR)
        bg = bg.crop(((bg.width - width) // 2, (bg.height - height) // 2,
                      (bg.width - width) // 2 + width, (bg.height - height) // 2 + height))
        bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(width / 50))).enhance(0.55)
        s = min(width * 0.86 / img.width, height * 0.86 / img.height, 1.5)
        fg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        bg.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
        bg.save(out, "JPEG", quality=95, subsampling=0)
        return True
    except Exception as exc:
        log.debug("backdrop failed (%s)", exc)
        return False
