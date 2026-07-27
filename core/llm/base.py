"""LLM provider interface.

DESIGN: A tiny, stable interface (`generate` for text, `generate_json` for
structured output) that every provider implements. Agents depend ONLY on this
interface, so switching from the offline stub to Ollama to a paid API is a
one-line config change and never touches agent code. This is the heart of the
"never hard-code a paid provider" requirement.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMMessage:
    role: str          # system | user | assistant
    content: str


class LLMProvider(ABC):
    """Abstract base every LLM backend implements."""

    name: str = "base"

    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the model's text completion for a chat message list."""

    # Convenience: single-prompt helper.
    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str:
        msgs: list[LLMMessage] = []
        if system:
            msgs.append(LLMMessage("system", system))
        msgs.append(LLMMessage("user", prompt))
        return self.generate(msgs, **kw)

    def generate_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Generate and best-effort parse JSON. Providers with native JSON modes
        can override; the default extracts the first JSON object/array found."""
        raw = self.generate(messages, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(text: str) -> Any:
        """Robustly pull JSON out of a model response (handles ``` fences)."""
        text = text.strip()
        # Strip code fences if present.
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fall back to the first balanced {...} or [...] block.
            match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
        raise ValueError("LLM did not return valid JSON")
