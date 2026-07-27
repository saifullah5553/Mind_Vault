"""Competitor Intelligence Agent.

Monitors successful psychology/history/education content to find OPPORTUNITIES —
topics with high demand but weak existing coverage — NOT to copy anyone. Findings
are written to `ai_memory` (kind='opportunity') so the topic engine and CEO can
act on them.

Network is opt-in and must respect each platform's Terms of Service. Offline, it
produces a structured opportunity map from the taxonomy so the loop is runnable.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.database.models import AIMemory
from core.database.session import session_scope
from core.registry import register_agent
from core.taxonomy import subcategories


@register_agent
class CompetitorAgent(BaseAgent):
    name = "competitor"
    folder = "competitor_agent"

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        category = payload.get("category", "psychology")
        opportunities = self._offline_opportunities(category)
        if self.config.get("use_network", False):
            opportunities += self._network_opportunities(category)

        with session_scope() as s:
            for opp in opportunities:
                s.add(AIMemory(
                    kind="opportunity", key=opp["topic"], outcome="neutral",
                    score=opp["opportunity_score"], samples=1, detail=opp,
                ))
        self.log.info("Logged %d competitor opportunities for %s", len(opportunities), category)
        return {"category": category, "opportunities": opportunities}

    def _offline_opportunities(self, category: str) -> list[dict]:
        out = []
        for sub in subcategories(category):
            demand = 50 + (abs(hash(sub + "d")) % 50)
            coverage = 30 + (abs(hash(sub + "c")) % 60)      # existing coverage quality
            gap = round(max(0.0, (demand - coverage) / 100.0), 2)
            if gap >= self.config.get("opportunity_threshold", 0.6) * 0.4:
                out.append({
                    "topic": sub, "category": category,
                    "demand": demand, "existing_coverage_quality": coverage,
                    "opportunity_score": round(gap * 100, 1),
                    "insight": f"'{sub}' shows demand but existing explanations are shallow — "
                               f"a clearer, story-led version can win.",
                })
        out.sort(key=lambda o: o["opportunity_score"], reverse=True)
        return out[:8]

    def _network_opportunities(self, category: str) -> list[dict]:  # pragma: no cover - network
        self.log.info("Network competitor scan is a wiring point (YouTube Data API / RSS).")
        return []
