"""SEO / Metadata Agent.

Generates PER-PLATFORM metadata (title, description, tags, hashtags, category)
tuned to each platform's algorithm — deliberately not the same description
everywhere. Also scores candidate titles and keeps the best.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.agents.base import BaseAgent
from core.llm.base import LLMMessage
from core.media import credits
from core.media.spoken import CHAPTER_RE
from core.prompts import render
from core.registry import register_agent
from core.schemas import PipelineContext, PlatformMetadata


@register_agent
class SEOAgent(BaseAgent):
    name = "seo"
    folder = "seo_agent"

    def run(self, payload: PipelineContext) -> list[PlatformMetadata]:
        # Generate alternates from the RAW subject; the already-curiosity-driven
        # script title (the angle) competes as the strong default so we never
        # reframe an already-reframed title.
        subject = payload.topic.topic if payload.topic else "the human mind"
        topic = payload.topic.angle if payload.topic else subject
        category = payload.category
        base_title = payload.script.title if payload.script else topic
        extra = payload.extra or {}
        # Human-written tags beat anything worked out from the title.
        keywords = [t.strip() for t in str(extra.get("tags") or "").split(",") if t.strip()] \
            or self._keywords(topic, category)
        # A human-written title/description is used as is.
        title = base_title if extra.get("title_locked") else self._best_title(subject, category, base_title)
        description = extra.get("description") or self._description(topic, category)
        # Append the AI-presenter disclosure (transparency + platform compliance).
        disclosure = extra.get("presenter", {}).get("disclosure")
        used = credits.load(Path(self.settings.storage_path("images")) / payload.run_id)
        chapters = self._chapters(payload)
        base = self.settings.publishing.credits_url
        full_url = f"{base}{payload.run_id}.txt" if base and used else ""
        rules = self.config.get("platform_rules", {})

        metas: list[PlatformMetadata] = []
        for platform in self.settings.publishing.platforms:
            r = rules.get(platform, {})
            hashtags = self._platform_hashtags(category, platform, payload.video_format,
                                               r.get("hashtags", 3))
            limit = r.get("desc_max", 2000)
            parts = [self._platform_desc(description, platform)]
            if platform == "youtube" and chapters:
                parts.append(chapters)
            if disclosure:
                parts.append(disclosure)
            notice = (self.settings.brand.disclaimer_description or "").strip()
            if notice:
                parts.append(notice)
            text = "\n\n".join(parts)
            # Credits are a licence requirement, so they get room before anything else.
            block = credits.block(used, limit - min(len(text), limit // 2) - 2, full_url)
            metas.append(PlatformMetadata(
                platform=platform,
                title=self._fit(title, r.get("title_max", 100)),
                description=self._fit(text, limit - len(block) - 2) + (f"\n\n{block}" if block else ""),
                tags=keywords[: r.get("tags", 10)],
                hashtags=hashtags,
                category=category,
            ))
        self.log.info("Generated metadata for %d platforms", len(metas))
        return metas

    # ── helpers ────────────────────────────────────────────────────────────
    def _best_title(self, topic: str, category: str, fallback: str) -> str:
        try:
            raw = self.llm.generate([LLMMessage("user", render("title", topic=topic, category=category))])
            cands = [self._clean_title(c) for c in raw.splitlines() if len(c.strip()) > 8]
        except Exception:
            cands = []
        cands.append(self._clean_title(fallback))
        cands = [c for c in cands if c]
        # Score: curiosity words + ideal length ~55 chars.
        def score(t: str) -> float:
            cur = sum(w in t.lower() for w in ("secret", "why", "hidden", "truth", "reason"))
            return cur * 10 - abs(len(t) - 55) * 0.2
        return max(cands, key=score)

    def _clean_title(self, text: str) -> str:
        """Remove list markers, numbering, and wrapping quotes from a title."""
        s = re.sub(r"^\s*\d+\s*[:.)-]\s*", "", text.strip().strip("-•*").strip())
        return s.strip().strip('"').strip("'").strip()

    def _description(self, topic: str, category: str) -> str:
        try:
            return self.llm.generate([LLMMessage("user", render("description", topic=topic, category=category))])
        except Exception:
            return f"A Mind_Vault documentary about {topic}. {self.settings.brand.cta}"

    def _chapters(self, ctx: PipelineContext) -> str:
        """YouTube chapter list, from the real scene timings.

        YouTube needs the first at 0:00, at least 3 chapters, each 10 s or longer.
        """
        plan = ctx.scene_plan
        if not plan:
            return ""
        marks: list[tuple[float, str]] = [(0.0, "Introduction")]
        t = 0.0
        for scene in plan.scenes:
            m = CHAPTER_RE.match(scene.narration.strip())
            if m:
                marks.append((t, m.group(2)))
            t += scene.duration
        if len(marks) < 3 or any(b[0] - a[0] < 10 for a, b in zip(marks, marks[1:])):
            return ""
        return "\n".join(f"{int(s // 60)}:{int(s % 60):02d} {name}" for s, name in marks)

    def _platform_desc(self, base: str, platform: str) -> str:
        opener = {
            "youtube": "",
            "tiktok": "Wait for the twist. ",
            "instagram": "Save this for later. ",
            "facebook": "Share this with someone who needs to hear it. ",
        }.get(platform, "")
        return f"{opener}{base}".strip()

    def _keywords(self, topic: str, category: str) -> list[str]:
        skip = {"that", "this", "what", "with", "your", "from", "they", "their", "uncovering",
                "hidden", "secret", "truth", "real", "reason"}
        words = [w for w in re.findall(r"[A-Za-z]{4,}", topic.lower()) if w not in skip]
        # What people actually search for comes first; single title words are weak tags.
        base = [category, f"{category} explained", f"{category} documentary", "education"]
        seen, out = set(), []
        for w in base + words:
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out

    def _platform_hashtags(self, category: str, platform: str, video_format: str,
                           n: int) -> list[str]:
        tags = [f"#{category}", "#mindvault"]
        if video_format == "long":
            tags.append("#documentary")
        elif platform == "youtube":
            tags.append("#shorts")
        if platform == "tiktok":
            tags.append("#learnontiktok")
        return (tags + [f"#{category}facts", "#didyouknow", "#storytime"])[:n]

    def _fit(self, text: str, limit: int) -> str:
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
