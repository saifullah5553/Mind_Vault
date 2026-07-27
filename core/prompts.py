"""Prompt-template loader.

DESIGN: Agent prompts live as editable text files in `prompts/templates/`, not
hard-coded in Python. `render(task, **vars)` loads the mapped template and does a
safe placeholder substitution. Every template begins with a `TASK:` marker, which
is what the offline Stub LLM routes on — so the SAME templates work offline and
drive much richer output the moment a real provider (Ollama) is configured.

Editing tone/structure is now a text edit, and a missing template degrades to a
minimal but valid `TASK:`-marked prompt so nothing ever crashes.
"""

from __future__ import annotations

from functools import lru_cache

from core.config import ROOT_DIR
from core.logging_setup import get_logger

log = get_logger("prompts")

_TEMPLATE_DIR = ROOT_DIR / "prompts" / "templates"

# task name -> template filename
PROMPT_FILES: dict[str, str] = {
    "hooks": "hooks.txt",
    "script": "script_documentary.txt",
    "improve_topic": "topic_reframe.txt",
    "title": "title.txt",
    "description": "description.txt",
    "research": "research.txt",
    "chapter": "chapter.txt",
}


@lru_cache(maxsize=64)
def _load(task: str) -> str | None:
    fname = PROMPT_FILES.get(task)
    if not fname:
        return None
    path = _TEMPLATE_DIR / fname
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def render(task: str, **vars: object) -> str:
    """Render the template for `task` with `vars`.

    Uses literal `{key}` -> value replacement (NOT str.format) so stray braces in
    a template (e.g. section markers) never raise. Falls back to a minimal
    TASK:-marked prompt if the template file is absent.
    """
    template = _load(task)
    if template is None:
        lines = [f"TASK: {task}"] + [f"{k.upper()}: {v}" for k, v in vars.items()]
        return "\n".join(lines)

    out = template
    for key, value in vars.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def reload_templates() -> None:
    """Drop the cache so edited templates are picked up (used by the API/tests)."""
    _load.cache_clear()
