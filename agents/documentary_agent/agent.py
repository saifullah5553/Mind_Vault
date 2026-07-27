"""Long-form Documentary Agent (8–15 minutes).

Builds a cohesive, chaptered documentary script. Chapters come from one of:
  - `chapters`: explicit themes passed in (e.g. the topics of several related
    SHORT videos you want to combine into one documentary), or
  - related subtopics derived from the taxonomy + already-produced content, or
  - the default documentary arc (Origins -> Turning Point -> ... -> Meaning).

Each chapter is written as flowing narration grounded in the verified facts, then
stitched into intro -> chapters -> conclusion -> CTA. The result is a `Script`
the normal visual/voice/video stages turn into a long video.

This is where "convert multiple related shorts into a documentary" happens: pass
their topics as `chapters` and the agent weaves them into one deeper story.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.database.models import Content
from core.database.session import session_scope
from core.llm.base import LLMMessage
from core.prompts import render
from core.registry import register_agent
from core.schemas import Script
from core.taxonomy import subcategories


@register_agent
class DocumentaryAgent(BaseAgent):
    name = "documentary"
    folder = "documentary_agent"

    def run(self, payload: dict) -> Script:
        topic = payload["topic"]
        category = payload.get("category", "history")
        title = payload.get("title") or topic
        hook = payload.get("hook", "")
        facts = payload.get("facts", [])                 # list[ResearchFact]
        chapters = payload.get("chapters") or self._derive_chapters(topic, category)

        fact_lines = "\n".join(f"- {f.claim}" for f in facts[:12]) or "- (general knowledge)"

        # Intro.
        intro = (f"{hook}\n\n" if hook else "") + (
            f"This is the story of {topic}. To understand it, we have to look past "
            f"the familiar version and follow the threads that actually connect the events, "
            f"the people, and the choices that shaped what came next.")

        # Chapters.
        chapter_blocks: list[str] = []
        for name in chapters:
            body = self._write_chapter(topic, category, name, fact_lines)
            chapter_blocks.append(f"[CHAPTER: {name}]\n{body}")

        # Conclusion.
        conclusion = (
            f"So what does {topic} leave us with? Not just a sequence of events, but a pattern — "
            f"one that still echoes in how we live, decide, and remember. "
            f"That is the real reason this story matters.")
        cta = self.settings.brand.cta

        full = "\n\n".join([f"[INTRODUCTION]\n{intro}", *chapter_blocks,
                            f"[CONCLUSION]\n{conclusion}", f"[CTA]\n{cta}"])
        wc = len(full.split())
        script = Script(
            title=title, hook=hook or intro.split("\n")[0],
            introduction=intro, body="\n\n".join(chapter_blocks),
            ending=conclusion, cta=cta, full_text=full, word_count=wc,
            style="netflix-documentary", structure=f"documentary-{len(chapters)}-chapters",
        )
        self.log.info("Documentary '%s': %d chapters, %d words (~%.1f min)",
                      title, len(chapters), wc, wc / 150.0)
        return script

    # ── chapter planning ────────────────────────────────────────────────────
    def _derive_chapters(self, topic: str, category: str) -> list[str]:
        lo = self.config.get("min_chapters", 4)
        hi = self.config.get("max_chapters", 6)
        # Prefer related, already-produced subtopics so a documentary can grow out
        # of the short-form catalogue; fall back to the default arc.
        related = self._related_produced(category)
        arc = self.config.get("default_arc", ["Origins", "The Turning Point", "What It Means Today"])
        chapters = related[: hi] if len(related) >= lo else arc[: hi]
        return chapters[:hi] if len(chapters) >= lo else (chapters + arc)[:hi]

    def _related_produced(self, category: str) -> list[str]:
        with session_scope() as s:
            topics = [c.topic for c in s.query(Content)
                      .filter(Content.category == category).limit(10).all() if c.topic]
        # De-dup, title-case as chapter names.
        seen, out = set(), []
        for t in topics:
            k = t.lower().strip()
            if k not in seen:
                seen.add(k)
                out.append(t.title())
        return out

    def _write_chapter(self, topic: str, category: str, chapter: str, facts: str) -> str:
        try:
            prompt = render("chapter", topic=topic, category=category, chapter=chapter, facts=facts)
            text = self.llm.generate([LLMMessage("user", prompt)],
                                     max_tokens=self.settings.llm.max_tokens).strip()
            return text or self._fallback_chapter(topic, chapter)
        except Exception as exc:
            self.log.warning("Chapter '%s' generation failed (%s); using fallback.", chapter, exc)
            return self._fallback_chapter(topic, chapter)

    def _fallback_chapter(self, topic: str, chapter: str) -> str:
        return (f"In this part of the story of {topic}, we turn to {chapter.lower()}. "
                f"What looked simple on the surface hid deeper forces at work, and the closer "
                f"we look, the more the familiar account starts to come apart. The details that "
                f"follow reframe everything we thought we understood — and set the stage for what "
                f"comes next.")
