"""Viral Hook Engine.

Generates at least 10 hooks per topic, scores each on curiosity / emotion /
shock / novelty / clarity, and selects the strongest. Selected + runner-up hooks
are stored so the Learning Agent can later correlate hook style with retention.
"""

from __future__ import annotations

import re

from core.agents.base import BaseAgent
from core.database.models import Hook as HookRow
from core.database.session import session_scope
from core.llm.base import LLMMessage
from core.prompts import render
from core.registry import register_agent
from core.schemas import Hook


def _clean_line(text: str) -> str:
    """Strip list markers, a leading 'Hook N:' label, and wrapping quotes that
    real LLMs often add — so on-screen hooks read cleanly."""
    s = text.strip().strip("-•*").strip()
    s = re.sub(r"^\s*hook\s*\d*\s*[:.)-]\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*\d+\s*[:.)-]\s*", "", s)          # leading "8:" / "8." / "8)"
    return s.strip().strip('"').strip("'").strip()


@register_agent
class HookEngine(BaseAgent):
    name = "hook"
    folder = "hook_engine"

    def run(self, payload: dict) -> dict:
        topic = payload.get("topic", "the human mind")
        category = payload.get("category", "psychology")

        texts = self._generate(topic, category)
        hooks = [self._score(t) for t in texts]
        hooks.sort(key=lambda h: h.total, reverse=True)
        selected = hooks[0]
        self._persist(hooks, selected)
        self.log.info("Generated %d hooks; best score %.1f", len(hooks), selected.total)
        return {"hooks": hooks, "selected": selected}

    def _generate(self, topic: str, category: str) -> list[str]:
        prompt = render("hooks", topic=topic, category=category)
        raw = self.llm.generate([LLMMessage("user", prompt)])
        lines = [_clean_line(ln) for ln in raw.splitlines() if ln.strip()]
        lines = [ln for ln in lines if len(ln) > 15]
        # Guarantee the minimum count with deterministic fillers.
        while len(lines) < self.config.get("min_hooks", 10):
            lines.append(f"There is something about {topic} almost no one notices.")
        return lines[: max(self.config.get("min_hooks", 10), len(lines))]

    def _score(self, text: str) -> Hook:
        low = text.lower()
        sig = self.config.get("signals", {})

        def dim(name: str, base: int) -> float:
            hits = sum(1 for w in sig.get(name, []) if w in low)
            return float(min(100, base + hits * 12))

        clarity = float(max(40, 100 - abs(len(text.split()) - 12) * 4))  # ~12 words is ideal
        curiosity = dim("curiosity", 60)
        emotion = dim("emotion", 50)
        shock = dim("shock", 48)
        novelty = dim("novelty", 52)

        # DESIGN: a great hook wins on its STRONGEST few axes, not by being
        # uniformly good — so we score the top-3 dimensions (weighted), which
        # both matches how hooks actually work and keeps the 80 gate meaningful.
        dims = sorted([curiosity, emotion, shock, novelty, clarity], reverse=True)[:3]
        tw = [1.2, 1.0, 0.8]
        total = sum(w_ * v for w_, v in zip(tw, dims)) / sum(tw)

        htype = "curiosity" if curiosity >= max(emotion, shock, novelty) else "emotion"
        return Hook(text=text, hook_type=htype, curiosity=curiosity, emotion=emotion,
                    shock=shock, novelty=novelty, clarity=clarity, total=round(total, 1))

    def _persist(self, hooks: list[Hook], selected: Hook) -> None:
        with session_scope() as s:
            for h in hooks:
                s.add(HookRow(
                    text=h.text, hook_type=h.hook_type, curiosity=h.curiosity,
                    emotion=h.emotion, shock=h.shock, novelty=h.novelty,
                    clarity=h.clarity, total_score=h.total, selected=(h.text == selected.text),
                ))
