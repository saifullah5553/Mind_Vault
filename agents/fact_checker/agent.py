"""Fact Checking Agent.

Scores every claim in the dossier and gates it: >=90 approved, 70–90 needs
verification (kept but flagged), <70 rejected. Returns the verdicts plus the
filtered set of usable facts. This is the guard that prevents fabricated history,
fake quotes, and invented statistics from reaching a script.

Scoring inputs (all local, no cost): the researcher's confidence, a license
signal (public-domain / CC sources score higher than 'none'), and a penalty for
claims with no named source. Wire a real claim-verification API later behind the
same interface for stronger guarantees.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.registry import register_agent
from core.schemas import FactVerdict, ResearchDossier, ResearchFact


@register_agent
class FactChecker(BaseAgent):
    name = "fact"
    folder = "fact_checker"

    def run(self, payload: ResearchDossier) -> dict:
        approve_at = self.config.get("approve_at", 90)
        verify_at = self.config.get("verify_at", 70)
        bonuses = self.config.get("license_bonus", {})

        verdicts: list[FactVerdict] = []
        approved: list[ResearchFact] = []
        for fact in payload.facts:
            score = fact.confidence + bonuses.get(fact.license, 0)
            if not fact.source_name or "unverified" in fact.source_name.lower():
                score -= 8
            score = max(0.0, min(100.0, score))

            if score >= approve_at:
                status = "approved"
                approved.append(fact)
            elif score >= verify_at:
                status = "needs_verification"
                approved.append(fact)  # usable but flagged in the dossier
            else:
                status = "rejected"

            verdicts.append(FactVerdict(
                claim=fact.claim, confidence=round(score, 1), status=status,
                note=f"source={fact.source_name or 'none'}, license={fact.license}",
            ))

        avg = round(sum(v.confidence for v in verdicts) / max(1, len(verdicts)), 1)
        min_approved = self.config.get("require_min_approved", 3)
        gate_passed = len(approved) >= min_approved

        self.log.info("Fact check: %d/%d usable, avg conf %.1f, gate=%s",
                      len(approved), len(payload.facts), avg, gate_passed)
        return {
            "verdicts": verdicts,
            "approved_facts": approved,
            "avg_confidence": avg,
            "gate_passed": gate_passed,
        }
