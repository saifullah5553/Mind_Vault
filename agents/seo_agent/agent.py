"""SEO / Metadata Agent.

Generates PER-PLATFORM metadata (title, description, tags, hashtags, category)
tuned to each platform's algorithm — deliberately not the same description
everywhere. Also scores candidate titles and keeps the best.
"""

from __future__ import annotations

import re

from core.agents.base import BaseAgent
from core.llm.base import LLMMessage
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
        keywords = self._keywords(topic, category)

        title = self._best_title(subject, category, base_title)
        description = self._description(topic, category)
        # Append the AI-presenter disclosure (transparency + platform compliance).
        disclosure = (payload.extra or {}).get("presenter", {}).get("disclosure")
        if disclosure:
            description = f"{description}\n\n{disclosure}"
        rules = self.config.get("platform_rules", {})
        base_tags = self.config.get("base_hashtags", [])

        metas: list[PlatformMetadata] = []
        for platform in self.settings.publishing.platforms:
            r = rules.get(platform, {})
            hashtags = self._platform_hashtags(category, base_tags, r.get("hashtags", 3))
            metas.append(PlatformMetadata(
                platform=platform,
                title=self._fit(title, r.get("title_max", 100)),
                description=self._fit(self._platform_desc(description, platform, r), r.get("desc_max", 2000)),
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

    def _platform_desc(self, base: str, platform: str, rules: dict) -> str:
        hint = rules.get("optimize_for", "")
        opener = {
            "youtube": "",
            "tiktok": "Wait for the twist. ",
            "instagram": "Save this for later. ",
            "facebook": "Share this with someone who loves history. ",
        }.get(platform, "")
        return f"{opener}{base}".strip() + (f"\n\n[optimized for: {hint}]" if hint else "")

    def _keywords(self, topic: str, category: str) -> list[str]:
        words = re.findall(r"[A-Za-z]{4,}", topic.lower())
        base = [category, "documentary", "education", "facts", "explained", "story"]
        seen, out = set(), []
        for w in words + base:
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out

    def _platform_hashtags(self, category: str, base: list[str], n: int) -> list[str]:
        tags = base + [f"#{category}facts", "#storytime", "#didyouknow"]
        return tags[:n]

    def _fit(self, text: str, limit: int) -> str:
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
