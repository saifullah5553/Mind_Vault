"""Visual Planning Agent.

Turns a script into a timed scene breakdown: each scene has narration, a visual
prompt (for the image layer), a duration (derived from word count at narration
pace), an animation, and an on-screen text overlay. Produces a `ScenePlan` that
the image + video layers consume directly.
"""

from __future__ import annotations

import re

from core.agents.base import BaseAgent
from core.media.spoken import CHAPTER_RE, headline, sentences, spoken_text
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

        scenes: list[Scene] = []
        for i, lines in enumerate(self._group(script.full_text, wpm, min_s, max_s)):
            narration = " ".join(lines)
            words = max(1, len(narration.split()))
            dur = min(max_s, max(min_s, round(words / max(1, wpm) * 60.0, 2)))
            scenes.append(Scene(
                index=i,
                narration=narration,
                visual_prompt=f"{style}, {script.title}: {self._visual_hint(narration)}",
                duration=dur,
                animation=anims[i % len(anims)],
                text_overlay=self._overlay(lines[0], first=i == 0),
                sentences=len(lines),
            ))

        plan = ScenePlan(scenes=scenes, total_duration=round(sum(s.duration for s in scenes), 2))
        self.log.info("Visual plan: %d scenes, %.1fs total", len(scenes), plan.total_duration)
        return plan

    def _group(self, text: str, wpm: int, min_s: float, max_s: float) -> list[list[str]]:
        """Group spoken sentences into scenes of a watchable length.

        One picture per short line ("Drawing." "Music.") would flash by; one per
        paragraph would sit too long. Chapter headings always stand alone.
        """
        def seconds(lines: list[str]) -> float:
            return len(" ".join(lines).split()) / max(1, wpm) * 60.0

        groups: list[list[str]] = []
        cur: list[str] = []
        for line, para_end in sentences(spoken_text(text)):
            if CHAPTER_RE.match(line):
                if cur:
                    groups.append(cur)
                    cur = []
                groups.append([line])
                continue
            if cur and seconds(cur + [line]) > max_s:
                groups.append(cur)
                cur = []
            cur.append(line)
            if seconds(cur) >= min_s or para_end:
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        return groups

    def _visual_hint(self, sentence: str) -> str:
        # Keep the most concrete nouns as the image subject.
        words = [w for w in re.findall(r"[A-Za-z]+", sentence) if len(w) > 4]
        return ", ".join(words[:6]) or "abstract concept"

    def _overlay(self, sentence: str, first: bool = False) -> str:
        # A short phrase for the screen. The full sentence is in the captions;
        # cutting it at 8 words with "..." produced fragments on every slide.
        words = sentence.rstrip(".!?").split()
        if any(c.isdigit() for c in sentence) and len(words) <= 12:
            return " ".join(words)      # a figure needs its whole short sentence
        return headline(sentence, max_words=12 if first else 8)
