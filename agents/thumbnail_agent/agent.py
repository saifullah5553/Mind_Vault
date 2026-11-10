"""Thumbnail Testing Engine.

Generates several distinct thumbnail variants per video (free, Pillow — no GPU),
persists each to the `thumbnails` table with its design style for A/B testing,
and selects a default. When real CTR data flows in (Analytics/Learning), the
best-performing styles, colours, and layouts can be favoured automatically.

Returns: {"variants": [paths], "selected": path}
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.agents.base import BaseAgent
from core.database.models import Thumbnail
from core.database.session import session_scope
from core.registry import register_agent


@register_agent
class ThumbnailAgent(BaseAgent):
    name = "thumbnail"
    folder = "thumbnail_agent"

    def run(self, payload: dict) -> dict:
        title = payload.get("title", "The Human Mind")
        run_id = payload.get("run_id", "run")
        content_id = payload.get("content_id")
        video_format = payload.get("video_format", "short")

        size = (self.config.get("short_size", [1080, 1920]) if video_format == "short"
                else self.config.get("long_size", [1280, 720]))
        styles = self.config.get("styles", [])[: self.config.get("variants", 3)]
        punchy = (payload.get("text") or self._punchy_text(title)).upper()
        story = f"{title} {payload.get('text') or ''}"
        photos = self._best_photos(run_id, len(styles), payload.get("stills"),
                                   about=payload.get("about"), story=story)

        out_dir = Path(self.settings.storage_path("thumbnails"))
        variants: list[str] = []
        for i, style in enumerate(styles):
            path = out_dir / f"{run_id}_v{i}.png"
            photo = photos[i] if i < len(photos) else None
            ok = (photo and self._render_photo(punchy, path, tuple(size), style, photo)) \
                or self._render(punchy, path, tuple(size), style)
            if ok:
                variants.append(str(path))

        selected = variants[0] if variants else None
        self._persist(content_id, styles, variants, selected)
        if content_id is not None and selected:
            self._set_content_thumbnail(content_id, selected)

        self.log.info("Thumbnails: %d variant(s) for '%s'", len(variants), title[:40])
        return {"variants": variants, "selected": selected}

    # ── rendering ──────────────────────────────────────────────────────────
    def _punchy_text(self, title: str) -> str:
        # The part before a colon is the headline; never cut mid-phrase.
        words = title.split(":")[0].split()
        return " ".join(words[: self.config.get("max_words", 6)]).upper()

    def _best_photos(self, run_id: str, count: int, only: list[str] | None = None,
                     about: dict | None = None, story: str = "") -> list[Path]:
        """The video's stills that show what the title is about, the most striking
        first: on-story beats colourful (the colour-only pick chose a tulip field
        for the 1953 flood and a farm for the Althing)."""
        try:
            import numpy as np
            from PIL import Image

            scored = []
            folder = Path(self.settings.storage_path("images")) / run_id
            allowed = {Path(p).resolve() for p in only} if only is not None else None
            for path in folder.glob("scene_*.jpg"):
                if allowed is not None and path.resolve() not in allowed:
                    continue
                a = np.asarray(Image.open(path).convert("RGB").resize((160, 90)), dtype="float32")
                rg = a[..., 0] - a[..., 1]
                yb = (a[..., 0] + a[..., 1]) / 2 - a[..., 2]
                colour = float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))
                light = float(a.mean())
                key = tuple(int(c) // 12 for c in a.mean(axis=(0, 1)))   # same photo, same key
                tier = 0
                if about and story:
                    from core.media.stock import relevance
                    text = about.get(str(path)) or about.get(str(path.resolve())) or ""
                    tier = min(3, int(relevance(story, {"title": text})[0] // 2))
                scored.append(((tier, colour * (1.0 if light > 55 else 0.5)), key, path))
            picked, seen = [], set()
            for _score, key, path in sorted(scored, key=lambda s: (-s[0][0], -s[0][1])):
                if key not in seen:
                    seen.add(key)
                    picked.append(path)
                if len(picked) >= count:
                    break
            return picked
        except Exception as exc:
            self.log.debug("No photo for the thumbnail (%s).", exc)
            return []

    def _render_photo(self, text: str, out: Path, size, style: dict, photo: Path) -> bool:
        """Full-bleed photo with a short, complete headline that always fits."""
        try:
            from PIL import Image, ImageDraw, ImageEnhance

            from core.media.animation import _fit_text, _font

            w, h = size
            img = Image.open(photo).convert("RGB")
            r = max(w / img.width, h / img.height)
            img = img.resize((round(img.width * r) + 1, round(img.height * r) + 1), Image.LANCZOS)
            x, y = (img.width - w) // 2, (img.height - h) // 2
            img = img.crop((x, y, x + w, y + h))
            img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.2)).enhance(1.1)

            where = style.get("text", "center")
            draw = ImageDraw.Draw(img)
            font, wrapped = _fit_text(draw, text, lambda s: _font(s, True), int(w * 0.88),
                                      int(h * 0.24), min_size=int(h * 0.07),
                                      max_h=int(h * 0.52), spacing=int(h * 0.02))
            box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=int(h * 0.02))
            tw, th = box[2] - box[0], box[3] - box[1]
            top = {"top": h * 0.08, "bottom": h * 0.9 - th}.get(where, (h - th) / 2)

            # Darken behind the words so they read on any picture.
            shade = Image.new("L", (1, h), 0)
            for row in range(h):
                dist = 0.0 if top - 40 <= row <= top + th + 40 else min(
                    abs(row - (top - 40)), abs(row - (top + th + 40))) / (h * 0.25)
                shade.putpixel((0, row), int(115 * max(0.0, 1.0 - dist)))
            img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, shade.resize((w, h)))

            draw = ImageDraw.Draw(img)
            accent = tuple(style.get("palette", [[0, 0, 0], [255, 214, 10]])[1])
            draw.multiline_text(((w - tw) / 2 - box[0], top - box[1]), wrapped, font=font,
                                fill=(255, 255, 255), spacing=int(h * 0.02), align="center",
                                stroke_width=max(3, h // 140), stroke_fill=(0, 0, 0))
            bar = top + th + h * 0.03
            draw.rectangle([(w - tw * 0.5) / 2, bar, (w + tw * 0.5) / 2, bar + h * 0.012], fill=accent)
            img.save(out, "PNG")
            return True
        except Exception as exc:
            self.log.warning("Photo thumbnail failed (%s).", exc)
            return False

    def _render(self, text: str, out: Path, size, style: dict) -> bool:
        try:
            from PIL import Image, ImageDraw, ImageFont

            w, h = size
            top, accent = style.get("palette", [[10, 12, 20], [232, 74, 74]])
            img = Image.new("RGB", (w, h), tuple(top))
            draw = ImageDraw.Draw(img)

            # Subtle vertical gradient toward black for depth.
            for y in range(h):
                t = y / max(1, h - 1)
                col = tuple(int(c * (1 - 0.5 * t)) for c in top)
                draw.line([(0, y), (w, y)], fill=col)

            def font(sz: int):
                for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
                    try:
                        return ImageFont.truetype(name, sz)
                    except Exception:
                        continue
                return ImageFont.load_default()

            fnt = font(max(48, w // 12))
            wrapped = textwrap.fill(text, width=max(8, w // 90))
            bbox = draw.multiline_textbbox((0, 0), wrapped, font=fnt, spacing=12)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pos = {"top": h * 0.12, "center": (h - th) / 2, "bottom": h * 0.72}.get(
                style.get("text", "center"), (h - th) / 2)

            # Accent bar for contrast/branding.
            draw.rectangle([0, pos - 24, w, pos - 8], fill=tuple(accent))
            # Text shadow then fill for legibility.
            draw.multiline_text(((w - tw) / 2 + 4, pos + 4), wrapped, font=fnt,
                                fill=(0, 0, 0), spacing=12, align="center")
            draw.multiline_text(((w - tw) / 2, pos), wrapped, font=fnt,
                                fill=(245, 245, 245), spacing=12, align="center")
            small = font(max(20, w // 42))
            draw.text((30, h - 60), self.settings.brand.name, font=small, fill=tuple(accent))
            img.save(out, "PNG")
            return True
        except Exception as exc:
            self.log.warning("Thumbnail render failed (%s).", exc)
            return False

    # ── persistence ────────────────────────────────────────────────────────
    def _persist(self, content_id, styles, variants, selected) -> None:
        if content_id is None:
            return
        with session_scope() as s:
            for i, path in enumerate(variants):
                style = styles[i] if i < len(styles) else {}
                s.add(Thumbnail(
                    content_id=content_id, version=f"v{i}", path=path,
                    design_style=style.get("name"), text_style=style.get("text"),
                    selected=(path == selected),
                ))

    def _set_content_thumbnail(self, content_id: int, path: str) -> None:
        from core.database.models import Content
        with session_scope() as s:
            c = s.get(Content, content_id)
            if c:
                c.thumbnail_path = path
