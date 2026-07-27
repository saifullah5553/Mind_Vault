"""Visual Planning Agent.

Turns a script into a timed scene breakdown: each scene has narration, a visual
prompt (for the image layer), a duration (derived from word count at narration
pace), an animation, and an on-screen text overlay. Produces a `ScenePlan` that
the image + video layers consume directly.
"""

from __future__ import annotations

import re

from core.agents.base import BaseAgent
from core.registry import register_agent
from core.schemas import Scene, ScenePlan, Script


@register_agent
class VisualAgent(BaseAgent):
    name = "visual"
    folder = "visual_agent"

    def run(self, payload: dict) -> ScenePlan:
        script: Script = payload["script"]
        wpm = self.settings.tts.words_per_minute
        style = self.config.get("style_prefix", "cinematic documentary still")
        anims = self.config.get("animations", ["slow-zoom"])
        max_s = self.config.get("max_scene_seconds", 6.0)
        min_s = self.config.get("min_scene_seconds", 2.5)

        sentences = self._split(script.full_text)
        scenes: list[Scene] = []
        for i, sentence in enumerate(sentences):
            words = max(1, len(sentence.split()))
            dur = min(max_s, max(min_s, round(words / max(1, wpm) * 60.0, 2)))
            scenes.append(Scene(
                index=i,
                narration=sentence,
                visual_prompt=f"{style}, {script.title}: {self._visual_hint(sentence)}",
                duration=dur,
                animation=anims[i % len(anims)],
                text_overlay=self._overlay(sentence),
            ))

        plan = ScenePlan(scenes=scenes, total_duration=round(sum(s.duration for s in scenes), 2))
        self.log.info("Visual plan: %d scenes, %.1fs total", len(scenes), plan.total_duration)
        return plan

    def _split(self, text: str) -> list[str]:
        # Sentence-ish split, keeping it robust to the section markers.
        text = re.sub(r"\[[A-Z]+\]", " ", text)
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p.strip() for p in parts if len(p.strip()) > 3]

    def _visual_hint(self, sentence: str) -> str:
        # Keep the most concrete nouns as the image subject.
        words = [w for w in re.findall(r"[A-Za-z]+", sentence) if len(w) > 4]
        return ", ".join(words[:6]) or "abstract concept"

    def _overlay(self, sentence: str) -> str:
        # A short on-screen caption (first ~8 words) — burned into the image.
        words = sentence.split()
        return " ".join(words[:8]) + ("…" if len(words) > 8 else "")
