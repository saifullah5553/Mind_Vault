"""Trend Discovery Agent.

Finds topics with high audience potential from FREE sources. Network access is
optional and OFF by default (deterministic, offline-safe). When enabled it pulls
signals from free endpoints (Wikipedia featured, Reddit public JSON, RSS). With
network off it synthesizes plausible trend candidates from the taxonomy plus a
seasonal "this-month-in-history" boost — so the pipeline always has input.

Output: list[TrendItem]  (also written to storage as trend_report.json).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.agents.base import BaseAgent
from core.config import ROOT_DIR
from core.registry import register_agent
from core.schemas import TrendItem
from core.taxonomy import subcategories


@register_agent
class TrendAgent(BaseAgent):
    name = "trend"
    folder = "trend_agent"

    def run(self, payload: dict | None = None) -> list[TrendItem]:
        payload = payload or {}
        category = payload.get("category", "psychology")
        count = int(payload.get("count", self.config.get("candidates_per_run", 12)))

        items: list[TrendItem] = []
        if self.config.get("use_network", False):
            items = self._from_network(category, count)
        if not items:
            items = self._synthesize(category, count)

        items.sort(key=lambda t: t.trend_score, reverse=True)
        items = items[:count]
        self._write_report(items)
        self.log.info("Discovered %d trend candidates for %s", len(items), category)
        return items

    # ── offline synthesis (deterministic) ─────────────────────────────────
    def _synthesize(self, category: str, count: int) -> list[TrendItem]:
        subs = subcategories(category) or ["human nature"]
        month = datetime.now(timezone.utc).strftime("%B")
        items: list[TrendItem] = []
        for i, sub in enumerate(subs * 3):
            if len(items) >= count:
                break
            # Deterministic score from a stable hash of the phrase.
            base = 55 + (hash(sub) % 35)
            seasonal = 8 if (self.config.get("seasonal_boost") and i % 4 == 0) else 0
            score = min(100, base + seasonal)
            items.append(TrendItem(
                topic=sub,
                category=category,
                trend_score=float(score),
                reason=f"Evergreen interest in {sub}; steady search demand"
                       + (f"; seasonal relevance in {month}" if seasonal else ""),
                estimated_interest="high" if score > 80 else "medium",
                recommended_angle=f"Reframe '{sub}' as a curiosity-driven story",
                source="synthesis",
            ))
        return items

    # ── live free sources (opt-in) ─────────────────────────────────────────
    def _from_network(self, category: str, count: int) -> list[TrendItem]:  # pragma: no cover - network
        items: list[TrendItem] = []
        try:
            import httpx

            subs = {"psychology": "psychology", "history": "history"}.get(category, "todayilearned")
            url = self.config["sources"]["reddit_json"].format(sub=subs)
            r = httpx.get(url, headers={"User-Agent": "mind_vault/0.1"}, timeout=15)
            if r.status_code == 200:
                for child in r.json().get("data", {}).get("children", [])[:count]:
                    d = child["data"]
                    ups = d.get("ups", 0)
                    items.append(TrendItem(
                        topic=d.get("title", "")[:180],
                        category=category,
                        trend_score=min(100.0, 40 + ups / 500.0),
                        reason=f"Reddit r/{subs}: {ups} upvotes this week",
                        estimated_interest="high" if ups > 5000 else "medium",
                        recommended_angle="Turn the discussion into a documentary narrative",
                        source="reddit",
                    ))
        except Exception as exc:
            self.log.warning("Network trend fetch failed (%s); will synthesize.", exc)
        return items

    def _write_report(self, items: list[TrendItem]) -> None:
        out = ROOT_DIR / "storage" / "trend_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([i.model_dump() for i in items], indent=2), encoding="utf-8")
