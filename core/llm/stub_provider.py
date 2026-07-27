"""Offline, dependency-free LLM provider.

DESIGN: The stub exists so the ENTIRE system runs at $0 with no model download,
no GPU, and no network - critical for CI and for anyone evaluating the project.
It is deterministic and template-driven. It is NOT a fake that returns lorem
ipsum: it reads the structured `TASK:` / `TOPIC:` markers that Mind_Vault agents
put in their prompts and returns coherent, on-topic, well-formed content for
each task. When you configure a real provider (Ollama), you get real prose; the
agent code does not change.
"""

from __future__ import annotations

import hashlib
import re

from core.llm.base import LLMMessage, LLMProvider


def _marker(text: str, key: str, default: str = "") -> str:
    m = re.search(rf"{key}:\s*(.+)", text)
    return m.group(1).strip() if m else default


def _seed_choice(seed: str, options: list[str]) -> str:
    """Deterministic 'random' pick so output is stable across runs/tests."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return options[h % len(options)]


class StubLLM(LLMProvider):
    name = "stub"

    def generate(self, messages: list[LLMMessage], *, temperature=None, max_tokens=None) -> str:
        prompt = "\n".join(m.content for m in messages)
        task = _marker(prompt, "TASK", "prose").lower()
        topic = _marker(prompt, "TOPIC", "the human mind")
        category = _marker(prompt, "CATEGORY", "psychology")

        handler = {
            "hooks": self._hooks,
            "script": self._script,
            "title": self._titles,
            "description": self._description,
            "research": self._research,
            "improve_topic": self._improve_topic,
            "ceo_report": self._ceo_report,
            "chapter": self._chapter,
        }.get(task, self._prose)
        return handler(topic, category, prompt)

    def _chapter(self, topic: str, category: str, prompt: str) -> str:
        chapter = _marker(prompt, "CHAPTER", "the story")
        a = _seed_choice(topic + chapter + "1", [
            f"When we turn to {chapter.lower()}, the story of {topic} stops being simple.",
            f"The chapter of {chapter.lower()} is where {topic} first reveals its depth.",
            f"To understand {chapter.lower()} is to see {topic} in a new light.",
        ])
        b = _seed_choice(topic + chapter + "2", [
            "What looked settled was, in truth, balanced on a knife's edge.",
            "Beneath the surface, forces had been building for a long time.",
            "A single overlooked detail would come to change everything.",
        ])
        c = _seed_choice(topic + chapter + "3", [
            f"The people caught inside {topic} could not yet see where it was leading.",
            f"Each decision narrowed the paths still open to {topic}.",
            f"Slowly, then all at once, {topic} bent toward its turning point.",
        ])
        d = _seed_choice(topic + chapter + "4", [
            "And when the moment finally came, there was no going back.",
            "By the time anyone understood, the shape of the future was already set.",
            "What happened next would be remembered long after the reasons were forgotten.",
        ])
        e = _seed_choice(topic + chapter + "5", [
            "Historians would later argue over exactly when the balance tipped.",
            "The record is incomplete, but the shape of what happened is unmistakable.",
            "Those closest to events left behind only fragments of what they knew.",
        ])
        f = _seed_choice(topic + chapter + "6", [
            f"What makes {topic} so compelling is how ordinary it looked from the inside.",
            f"The people living through {topic} had no map for what was coming.",
            f"Every generation rediscovers {topic} and reads its own fears into it.",
        ])
        return (
            f"{a} {b} {c} For a time, everything seemed to hold — the routines, the certainties, "
            f"the quiet assumption that tomorrow would look like today. But the story of {topic} "
            f"was never that kind of story. Small pressures accumulated in the background, unnoticed "
            f"by almost everyone, until they were impossible to ignore. {e} And yet the deeper we look, "
            f"the clearer it becomes that this was not the work of a single cause, but of many threads "
            f"pulling at once. {f} Ambition and fear, loyalty and betrayal, chance and design — all of "
            f"them left their mark on {chapter.lower()}. To trace them is to watch a familiar story "
            f"become strange again, its edges sharper, its people more human. {d} It is here that "
            f"{chapter.lower()} gives way to what comes next, and the deeper pattern of {topic} begins "
            f"to show itself — a pattern that, once seen, is almost impossible to unsee.")

    # ── task handlers ──────────────────────────────────────────────────────
    def _hooks(self, topic: str, category: str, prompt: str) -> str:
        patterns = [
            f"One overlooked detail changed everything we thought we knew about {topic}.",
            f"Most people get {topic} completely wrong - and it costs them daily.",
            f"For centuries, the truth about {topic} was hidden in plain sight.",
            f"What if everything you believed about {topic} was only half the story?",
            f"There is a reason {topic} still shapes your decisions today.",
            f"Scientists were stunned by what {topic} reveals about the human mind.",
            f"The story of {topic} begins with a single, fateful choice.",
            f"Behind {topic} lies a pattern almost no one notices.",
            f"This is the question about {topic} that experts avoid answering.",
            f"{topic} sounds simple - until you learn what really happened.",
        ]
        return "\n".join(patterns)

    def _titles(self, topic: str, category: str, prompt: str) -> str:
        return "\n".join([
            f"The Secret History of {topic}",
            f"Why {topic} Explains More Than You Think",
            f"{topic}: The Truth Nobody Told You",
            f"The Hidden Psychology Behind {topic}",
            f"What {topic} Reveals About Human Nature",
        ])

    def _description(self, topic: str, category: str, prompt: str) -> str:
        return (
            f"In this Mind_Vault documentary we explore {topic} - the forces, the people, "
            f"and the turning points behind it. A curiosity-driven journey into {category}, "
            f"told like a premium documentary.\n\n"
            f"Chapters: the setup, the conflict, the turning point, and the lesson it leaves us with.\n\n"
            f"Follow for more stories about the human mind and history."
        )

    def _improve_topic(self, topic: str, category: str, prompt: str) -> str:
        template = _seed_choice(topic, [
            "The Secret Reason {t} Still Shapes Us Today",
            "The Hidden Force Behind {t}",
            "What Really Happened With {t} - And Why It Matters",
            "The Untold Story of {t}",
            "How One Moment Changed {t} Forever",
        ])
        return template.format(t=topic)

    def _research(self, topic: str, category: str, prompt: str) -> str:
        # Return structured-ish notes the ResearchAgent can turn into facts.
        return (
            f"- {topic} has a documented history spanning multiple eras.\n"
            f"- Key figures shaped the development and public understanding of {topic}.\n"
            f"- Turning points redefined how {topic} was perceived.\n"
            f"- Modern {category} research continues to reinterpret {topic}.\n"
            f"- Common misconceptions about {topic} persist in popular culture."
        )

    def _script(self, topic: str, category: str, prompt: str) -> str:
        # DESIGN: seed every section from the topic so DIFFERENT topics produce
        # meaningfully different scripts (keeps the originality gate happy across
        # distinct topics), while the SAME topic stays deterministic (so genuine
        # duplicates are still caught). A real LLM removes this templating.
        hook = _seed_choice(topic + "h", [
            f"One overlooked detail changed everything we thought we knew about {topic}.",
            f"For years, the truth about {topic} was hidden in plain sight.",
            f"There is a reason {topic} still shapes the way we live today.",
        ])
        intro = _seed_choice(topic + "i", [
            f"To understand {topic}, you have to forget what you assume you already know.",
            f"The story of {topic} is not the one you were taught - it is stranger, and more human.",
            f"Behind {topic} lies a question that experts have argued over for generations.",
        ])
        conflict = _seed_choice(topic + "c", [
            "But beneath the surface, pressure was building between what people believed and what was true.",
            "Yet a contradiction sat at its heart, and sooner or later it had to break.",
            "What looked like progress was hiding a cost no one had counted.",
        ])
        turn = _seed_choice(topic + "t", [
            "Then came the turning point: a single decision that could not be undone.",
            "And then, almost by accident, everything changed at once.",
            "One moment - one choice - split the story into a before and an after.",
        ])
        lesson = _seed_choice(topic + "l", [
            f"The lesson of {topic} is not really about the past. It is about how easily we mistake the familiar for the understood.",
            f"What {topic} teaches us is uncomfortable: certainty is often just a story we stopped questioning.",
            f"In the end, {topic} is a mirror - and what it reflects is us.",
        ])
        open_b = _seed_choice(topic + "b", [
            f"The early days of {topic} looked ordinary, even forgettable.",
            f"At first, {topic} drew almost no attention at all.",
            f"For a long time, {topic} was treated as settled and obvious.",
        ])
        after = _seed_choice(topic + "a", [
            f"After that, {topic} was never seen the same way again.",
            f"From then on, {topic} carried a meaning no one had expected.",
            f"What came next reshaped {topic} for generations.",
        ])
        bridge = _seed_choice(topic + "w", [
            f"This is where {topic} becomes genuinely surprising.",
            f"Here is what almost everyone misses about {topic}.",
            f"And this is the part of {topic} that changes the whole picture.",
        ])
        return (
            f"[HOOK]\n{hook}\n\n"
            f"[INTRODUCTION]\n{intro} {bridge}\n\n"
            f"[BODY]\n{open_b} {conflict} {turn} {after}\n\n"
            f"[ENDING]\n{lesson}\n\n"
            f"[CTA]\nFollow for more stories about the human mind and history."
        )

    def _ceo_report(self, topic: str, category: str, prompt: str) -> str:
        return (
            "This period, psychology content outperformed history on average retention, "
            "while history drove more shares. Curiosity-led hooks beat statement hooks. "
            "Recommendation: increase relationship-psychology topics, tighten history intros, "
            "and keep shorts under 70 seconds."
        )

    def _prose(self, topic: str, category: str, prompt: str) -> str:
        return (
            f"{topic} sits at the intersection of {category} and human experience. "
            f"It rewards curiosity: the closer you look, the more it reveals about why we think, "
            f"feel, and act the way we do."
        )
