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
        punchy = self._punchy_text(title)

        out_dir = Path(self.settings.storage_path("thumbnails"))
        variants: list[str] = []
        for i, style in enumerate(styles):
            path = out_dir / f"{run_id}_v{i}.png"
            ok = self._render(punchy, path, tuple(size), style)
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
        words = title.split()
        return " ".join(words[: self.config.get("max_words", 6)]).upper()

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
