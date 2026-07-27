"""Topic Generator + Content Opportunity Engine (combined).

Responsibilities
----------------
1. Generate many candidate topics from trends + taxonomy.
2. Score each on virality / curiosity / evergreen / educational / emotional and
   subtract competition — the exact formula from the brief.
3. Run the OPPORTUNITY step: rewrite generic topics ("The History of Rome") into
   curiosity-driven ones ("The Secret Reason Rome Collapsed After 1,000 Years").
4. Enforce duplicate prevention against everything already in the database.
5. Persist scored candidates to the `topics` table and return the best one.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.database.models import Content, Topic
from core.database.session import session_scope
from core.dedup import is_duplicate
from core.errors import DuplicateContentError
from core.llm.base import LLMMessage
from core.registry import register_agent
from core.schemas import ScoredTopic, TrendItem
from core.taxonomy import subcategories

# Words that signal a curiosity-driven (high-CTR) framing already exists.
_CURIOSITY_MARKERS = ("secret", "hidden", "why", "reason", "truth", "untold",
                      "really", "nobody", "what if", "shocking")


@register_agent
class TopicAgent(BaseAgent):
    name = "topic"
    folder = "topic_agent"

    def run(self, payload: dict | None = None) -> ScoredTopic:
        payload = payload or {}
        category = payload.get("category", "psychology")
        trends: list[TrendItem] = payload.get("trends", []) or []

        candidates = self._candidate_phrases(category, trends)
        existing = self._existing_corpus()

        # PERF: reframing calls the LLM, so do a cheap heuristic pre-rank on the
        # raw phrases first and only reframe the top-K. (In stub mode this is all
        # instant; with a real model it turns ~40 LLM calls into ~K.)
        reframe = self.config.get("reframe_generic_topics", True)
        top_k = int(self.config.get("reframe_top_k", 6))
        prelim = sorted(
            candidates,
            key=lambda ps: self._score(ps[0], ps[0], category, ps[1], duplicate=0).total,
            reverse=True,
        )
        chosen = prelim[:top_k] if reframe else prelim

        scored: list[ScoredTopic] = []
        for phrase, sub in chosen:
            angle = self._reframe(phrase) if reframe else phrase
            dup, sim = is_duplicate(angle, existing)
            st = self._score(phrase, angle, category, sub, duplicate=sim)
            if dup:
                st.total -= 100  # push duplicates to the bottom rather than crashing
            scored.append(st)

        scored.sort(key=lambda t: t.total, reverse=True)
        self._persist(scored)

        best = next((t for t in scored if t.total >= self.config.get("min_total_score", 40)), None)
        if best is None:
            raise DuplicateContentError(
                "No sufficiently original, high-scoring topic found this run.")
        self.log.info("Selected topic: %s (score %.1f)", best.angle or best.topic, best.total)
        return best

    # ── candidate generation ───────────────────────────────────────────────
    def _candidate_phrases(self, category: str, trends: list[TrendItem]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        subs = subcategories(category) or ["human nature"]
        for t in trends:
            out.append((t.topic, category))
        # Expand with taxonomy-driven specifics.
        for sub in subs:
            out.append((f"{sub}", sub))
            out.append((f"the psychology of {sub}" if category == "psychology" else f"the story of {sub}", sub))
        # De-dup the candidate list itself.
        seen, uniq = set(), []
        for phrase, sub in out:
            k = phrase.lower().strip()
            if k and k not in seen:
                seen.add(k)
                uniq.append((phrase, sub))
        limit = int(self.config.get("generate_candidates", 40))
        return uniq[:limit]

    # ── the opportunity engine: generic -> curiosity-driven ────────────────
    def _reframe(self, phrase: str) -> str:
        if any(m in phrase.lower() for m in _CURIOSITY_MARKERS):
            return phrase.strip().title()
        try:
            from core.prompts import render
            prompt = render("improve_topic", topic=phrase)
            out = self.llm.generate([LLMMessage("user", prompt)]).strip().splitlines()[0]
            return out.strip().strip('"') or phrase
        except Exception:
            return f"The Secret Reason {phrase.title()} Still Matters"

    # ── scoring ────────────────────────────────────────────────────────────
    def _heur(self, seed: str, lo: int, hi: int) -> float:
        return float(lo + (abs(hash(seed)) % max(1, hi - lo)))

    def _score(self, topic: str, angle: str, category: str, sub: str, duplicate: float) -> ScoredTopic:
        w = self.config.get("weights", {})
        curiosity = 70 + (12 if any(m in angle.lower() for m in _CURIOSITY_MARKERS) else 0) + self._heur(angle, 0, 12)
        virality = self._heur(topic + "v", 40, 90)
        evergreen = 85 if category in ("psychology", "history") else self._heur(topic, 40, 80)
        educational = self._heur(topic + "e", 60, 95)
        emotional = self._heur(angle + "m", 45, 90)
        competition = self._heur(topic + "c", 20, 70)

        total = (
            w.get("virality", 1.0) * virality
            + w.get("curiosity", 1.2) * min(100, curiosity)
            + w.get("evergreen", 1.0) * evergreen
            + w.get("educational", 1.0) * educational
            + w.get("emotional", 0.8) * emotional
            - w.get("competition", 1.0) * competition
        ) / 5.0

        return ScoredTopic(
            topic=topic, category=category, subcategory=sub, angle=angle,
            virality=round(virality, 1), curiosity=round(min(100, curiosity), 1),
            evergreen=round(evergreen, 1), educational=round(educational, 1),
            emotional=round(emotional, 1), competition=round(competition, 1),
            duplicate=round(duplicate * 100, 1), total=round(total, 1),
        )

    # ── persistence / corpus ───────────────────────────────────────────────
    def _existing_corpus(self) -> list[str]:
        # DESIGN: compare only against REAL/committed content — produced Content
        # and topics already USED — NOT the candidate backlog. Otherwise every
        # idea we ever scored would count as "existing" and the pipeline would
        # eventually reject all new topics.
        with session_scope() as s:
            topics = [c.topic for c in s.query(Content.topic).all()]
            topics += [t.angle or t.topic for t in
                       s.query(Topic).filter(Topic.status.in_(("used", "approved"))).all()]
        return [t for t in topics if t]

    def _persist(self, scored: list[ScoredTopic]) -> None:
        with session_scope() as s:
            for st in scored:
                s.add(Topic(
                    topic=st.topic, category=st.category, subcategory=st.subcategory,
                    angle=st.angle, virality_score=st.virality, curiosity_score=st.curiosity,
                    evergreen_score=st.evergreen, educational_score=st.educational,
                    emotional_score=st.emotional, competition_score=st.competition,
                    duplicate_score=st.duplicate, total_score=st.total,
                    status="candidate",
                ))
