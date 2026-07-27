"""Script Writing Agent.

Writes a documentary-style script in the HOOK → INTRODUCTION → BODY → ENDING →
CTA structure, weaving in approved research facts and opening with the selected
hook. Enforces anti-"AI voice" rules by stripping banned phrases. Returns a
structured `Script`.
"""

from __future__ import annotations

import re

from core.agents.base import BaseAgent
from core.llm.base import LLMMessage
from core.prompts import render
from core.registry import register_agent
from core.schemas import Script


@register_agent
class ScriptAgent(BaseAgent):
    name = "script"
    folder = "script_agent"

    def run(self, payload: dict) -> Script:
        topic = payload["topic"]
        category = payload.get("category", "psychology")
        hook = payload.get("hook", "")
        facts = payload.get("facts", [])         # list[ResearchFact]
        title = payload.get("title") or topic
        video_format = payload.get("video_format", "short")

        fact_lines = "\n".join(f"- {f.claim}" for f in facts[:8])
        prompt = render("script", topic=topic, category=category, hook=hook,
                        video_format=video_format, facts=fact_lines)
        raw = self.llm.generate([LLMMessage("user", prompt)], max_tokens=self.settings.llm.max_tokens)
        sections = self._parse_sections(raw)

        # Ensure the chosen hook actually leads the script.
        if hook:
            sections["HOOK"] = hook

        cleaned = {k: self._clean(v) for k, v in sections.items()}
        full = "\n\n".join(v for v in [
            cleaned.get("HOOK", ""), cleaned.get("INTRODUCTION", ""),
            cleaned.get("BODY", ""), cleaned.get("ENDING", ""), cleaned.get("CTA", ""),
        ] if v)

        script = Script(
            title=title,
            hook=cleaned.get("HOOK", hook),
            introduction=cleaned.get("INTRODUCTION", ""),
            body=cleaned.get("BODY", ""),
            ending=cleaned.get("ENDING", ""),
            cta=cleaned.get("CTA", self.settings.brand.cta),
            full_text=full,
            word_count=len(full.split()),
            style=self.config.get("style", "netflix-documentary"),
            structure=self.config.get("structure", "hook-intro-story-lesson"),
        )
        self.log.info("Script written: '%s' (%d words)", script.title, script.word_count)
        return script

    def _parse_sections(self, raw: str) -> dict[str, str]:
        """Split the model output on [SECTION] headers."""
        sections: dict[str, str] = {}
        parts = re.split(r"\[([A-Z]+)\]", raw)
        # parts = ['', 'HOOK', 'text', 'INTRODUCTION', 'text', ...]
        for i in range(1, len(parts) - 1, 2):
            key = parts[i].strip().upper()
            val = parts[i + 1].strip()
            sections[key] = val
        if not sections:  # model didn't use headers — treat whole thing as body
            sections["BODY"] = raw.strip()
        return sections

    def _clean(self, text: str) -> str:
        for phrase in self.config.get("banned_phrases", []):
            text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
