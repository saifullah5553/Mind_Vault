"""Research Agent.

Collects information from FREE sources and produces a `ResearchDossier` of facts,
people, dates, events, and statistics, each with a provenance source and a
confidence score. Network is opt-in; offline it synthesizes structured notes so
the pipeline proceeds. Every source is persisted to the `sources` table with its
license, satisfying the provenance/licensing requirement.

NOTE (honesty): offline confidence is a *heuristic* (does the claim have a named,
appropriately-licensed source?). Real high-confidence verification requires live
sources — enable `use_network` and/or wire additional free APIs. The Fact Checker
consumes these confidences to gate the script.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.agents.base import BaseAgent
from core.database.models import Source
from core.database.session import session_scope
from core.llm.base import LLMMessage
from core.registry import register_agent
from core.schemas import ResearchDossier, ResearchFact, ScoredTopic


@register_agent
class ResearchAgent(BaseAgent):
    name = "research"
    folder = "research_agent"

    def run(self, payload: ScoredTopic) -> ResearchDossier:
        topic = payload.topic
        category = payload.category

        facts = self._network_facts(topic, category) if self.config.get("use_network") else []
        if len(facts) < self.config.get("min_facts", 5):
            facts += self._synthesize_facts(topic, category, need=self.config.get("min_facts", 5) - len(facts))

        dossier = ResearchDossier(
            topic=topic, category=category, facts=facts,
            people=[f.detail for f in facts if f.information_type == "person"][:5],
            events=[f.claim for f in facts if f.information_type == "event"][:5],
            statistics=[f.claim for f in facts if f.information_type == "stat"][:5],
            overall_confidence=round(sum(f.confidence for f in facts) / max(1, len(facts)), 1),
        )
        self._persist_sources(facts)
        self.log.info("Research dossier for '%s': %d facts, conf %.1f",
                      topic, len(facts), dossier.overall_confidence)
        return dossier

    # ── offline synthesis ──────────────────────────────────────────────────
    def _synthesize_facts(self, topic: str, category: str, need: int) -> list[ResearchFact]:
        from core.prompts import render
        prompt = render("research", topic=topic, category=category)
        notes = self.llm.generate([LLMMessage("user", prompt)])
        lines = [ln.strip("-• ").strip() for ln in notes.splitlines() if ln.strip()]
        facts: list[ResearchFact] = []
        for i, line in enumerate(lines):
            if len(facts) >= max(need, 5):
                break
            itype = ["fact", "event", "person", "stat", "date"][i % 5]
            # Offline notes are treated as *general knowledge*: usable but flagged
            # for verification (they land in the 70–90 band, never auto-approved).
            facts.append(ResearchFact(
                claim=line, detail=line, source_name="General knowledge",
                url="", information_type=itype, license="general-knowledge", confidence=85.0,
            ))
        return facts

    # ── free network sources (opt-in) ─────────────────────────────────────
    def _network_facts(self, topic: str, category: str) -> list[ResearchFact]:  # pragma: no cover
        facts: list[ResearchFact] = []
        try:
            import httpx

            q = topic.strip().replace(" ", "_")
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}"
            r = httpx.get(url, headers={"User-Agent": "mind_vault/0.1"}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                extract = data.get("extract", "")
                for sentence in [s.strip() for s in extract.split(". ") if len(s.strip()) > 30][:6]:
                    facts.append(ResearchFact(
                        claim=sentence, detail=sentence,
                        source_name="Wikipedia", url=data.get("content_urls", {}).get("desktop", {}).get("page", url),
                        information_type="fact", license="CC-BY-SA", confidence=88.0,
                    ))
        except Exception as exc:
            self.log.warning("Wikipedia research failed (%s).", exc)
        return facts

    def _persist_sources(self, facts: list[ResearchFact]) -> None:
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            for f in facts:
                if not f.source_name:
                    continue
                s.add(Source(
                    source_name=f.source_name, url=f.url or None, date_used=now,
                    information_type=f.information_type, license=f.license, confidence=f.confidence,
                ))
